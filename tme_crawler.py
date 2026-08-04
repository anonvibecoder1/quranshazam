import os
import re
import urllib.request
import html
import time
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
import config
from core.db import Database
from core.recognizer import AudioRecognizer
from core.audio import extract_pcm_from_file

# Regex patterns for Quran Surah metadata extraction in Arabic captions
SURAH_PATTERN = re.compile(r'(?:سورة|سوره)\s+([^\n\-\|,:]+)', re.UNICODE)
AYAH_PATTERN = re.compile(r'(?:الآيات|الايات|الآية|الآيه|آية|ايه)?\s*\(?(\d+[\s\-\,\:]*\d*)\)?', re.UNICODE)
TYPE_PATTERNS = {
    "حفلة": ["حفلة", "خارجية", "محفل", "مسجد"],
    "مجود": ["مجود", "المجود", "إستوديو"],
    "مرتل": ["مرتل", "المرتل", "المصحف المرتل"]
}

def parse_caption_metadata(caption: str) -> Dict[str, str]:
    """
    Extracts Surah Name, Ayah Range, and Recitation Type from Arabic captions.
    """
    surah_match = SURAH_PATTERN.search(caption)
    surah_name = surah_match.group(1).strip() if surah_match else ""

    ayah_match = AYAH_PATTERN.search(caption)
    ayah_range = ayah_match.group(1).strip() if ayah_match else ""

    recitation_type = "مجود"  # Default for Minshawi
    for type_name, keywords in TYPE_PATTERNS.items():
        if any(kw in caption for kw in keywords):
            recitation_type = type_name
            break

    return {
        "surah_name": surah_name,
        "ayah_range": ayah_range,
        "recitation_type": recitation_type
    }

class TelegramChannelCrawler:
    def __init__(self, channel_slug: str = "AlminshawiEncyclopedia", reciter_slug: str = config.DEFAULT_RECITER_SLUG, db: Optional[Database] = None):
        self.channel_slug = channel_slug.replace("https://t.me/", "").replace("s/", "").replace("@", "").strip("/")
        self.reciter_slug = reciter_slug
        self.db = db or Database()
        self.recognizer = AudioRecognizer(self.db)

    def ingest_audio_file(self, file_path: str, title: str, surah_name: str = "", ayah_range: str = "",
                          recitation_type: str = "", telegram_post_url: str = "") -> int:
        """
        Extracts PCM audio from a local file, registers the track, computes landmark fingerprints,
        and stores everything into SQLite database.
        """
        print(f"Indexing track: {title} ({file_path})...")
        track_id = self.recognizer.index_track(
            file_path=file_path,
            title=title,
            reciter_slug=self.reciter_slug,
            surah_name=surah_name,
            ayah_range=ayah_range,
            recitation_type=recitation_type,
            telegram_post_url=telegram_post_url
        )
        print(f"Successfully indexed track #{track_id}: {title}")
        return track_id

    def ingest_post_url(self, post_url: str) -> int:
        """
        Ingests a track from a Telegram post URL using Telethon MTProto engine.
        """
        match = re.search(r't\.me/([^/]+)/(\d+)', post_url)
        if match:
            channel_username, message_id = match.group(1), int(match.group(2))
            return self.ingest_telegram_post(channel_username, message_id)

        from core.media import download_audio_from_url
        print(f"Downloading and extracting metadata from URL: {post_url}...")

        downloaded_path, title = download_audio_from_url(post_url)
        meta = parse_caption_metadata(title)
        
        if meta["surah_name"]:
            title = meta["surah_name"]
        if meta["ayah_range"]:
            title += f" ({meta['ayah_range']})"

        file_id = os.path.basename(downloaded_path)
        save_path = os.path.join(config.AUDIO_STORE_DIR, f"post_url_{file_id}")
        
        if os.path.exists(downloaded_path):
            os.replace(downloaded_path, save_path)

        track_id = self.ingest_audio_file(
            file_path=save_path,
            title=title,
            surah_name=meta["surah_name"],
            ayah_range=meta["ayah_range"],
            recitation_type=meta["recitation_type"],
            telegram_post_url=post_url
        )
        return track_id

    def ingest_telegram_post(self, channel_username: str, message_id: int) -> int:
        """
        Downloads and indexes a specific Telegram post by message ID using Telethon MTProto.
        """
        async def _ingest():
            from telethon import TelegramClient
            API_ID = 2040
            API_HASH = "b18441a12607e10979b050123651490e"
            token = config.TELEGRAM_BOT_TOKEN

            client = TelegramClient("telethon_single_ingest", API_ID, API_HASH)
            await client.start(bot_token=token)

            message = await client.get_messages(channel_username, ids=message_id)
            if not message or not message.media:
                await client.disconnect()
                raise ValueError(f"No media found in post #{message_id} on @{channel_username}")

            post_url = f"https://t.me/{channel_username}/{message_id}"
            caption = message.text or ""
            file_name = getattr(message.file, "name", "") or f"post_{message_id}.mp3"
            meta = parse_caption_metadata(caption or file_name)
            
            title = meta["surah_name"] or caption.split("\n")[0][:60] or file_name
            if meta["ayah_range"]:
                title += f" ({meta['ayah_range']})"

            tmp_path = str(config.TEMP_DIR / f"mtproto_post_{message_id}.mp3")

            try:
                print(f"📥 MTProto downloading post #{message_id} ({getattr(message.file, 'size', 0)/1024/1024:.2f} MB)...")
                await client.download_media(message, file=tmp_path)
                track_id = self.ingest_audio_file(
                    file_path=tmp_path,
                    title=title,
                    surah_name=meta["surah_name"],
                    ayah_range=meta["ayah_range"],
                    recitation_type=meta["recitation_type"],
                    telegram_post_url=post_url
                )
                return track_id
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                await client.disconnect()

        return asyncio.run(_ingest())

    def ingest_folder(self, folder_path: str) -> int:
        """
        Indexes all audio files in a directory into the database catalog.
        """
        if not os.path.exists(folder_path):
            raise FileNotFoundError(f"Folder not found: {folder_path}")

        count = 0
        audio_extensions = {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac"}
        
        for root, _, files in os.walk(folder_path):
            for file in sorted(files):
                ext = os.path.splitext(file)[1].lower()
                if ext in audio_extensions:
                    full_path = os.path.join(root, file)
                    raw_name = os.path.splitext(file)[0]
                    meta = parse_caption_metadata(raw_name)
                    surah_name = meta["surah_name"] or raw_name
                    
                    try:
                        self.ingest_audio_file(
                            file_path=full_path,
                            title=surah_name,
                            surah_name=meta["surah_name"],
                            ayah_range=meta["ayah_range"],
                            recitation_type=meta["recitation_type"]
                        )
                        count += 1
                    except Exception as e:
                        print(f"Error indexing file {file}: {e}")

        return count

    async def crawl_channel_mtproto(self, max_posts: int = 500) -> int:
        """
        Crawls full Telegram channel over MTProto using Telethon.
        Downloads full-size audio files without any size limits, extracts metadata, 
        generates constellation fingerprints, and stores them in SQLite DB.
        """
        from telethon import TelegramClient

        API_ID = 2040
        API_HASH = "b18441a12607e10979b050123651490e"
        token = config.TELEGRAM_BOT_TOKEN
        channel_username = self.channel_slug

        client = TelegramClient("telethon_crawler_session", API_ID, API_HASH)
        await client.start(bot_token=token)

        indexed_count = 0
        print(f"🚀 Starting high-speed MTProto crawl on @{channel_username} (max_posts={max_posts})...")

        async for message in client.iter_messages(channel_username, limit=max_posts):
            if not message.media:
                continue

            post_url = f"https://t.me/{channel_username}/{message.id}"
            
            # Skip if already indexed
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM tracks WHERE telegram_post_url = ?", (post_url,))
                if cursor.fetchone():
                    print(f"⏩ Post #{message.id} already indexed, skipping.")
                    continue

            caption = message.text or ""
            file_name = getattr(message.file, "name", "") or f"post_{message.id}.mp3"
            meta = parse_caption_metadata(caption or file_name)
            
            title = meta["surah_name"] or caption.split("\n")[0][:60] or file_name
            if meta["ayah_range"]:
                title += f" ({meta['ayah_range']})"

            tmp_path = str(config.TEMP_DIR / f"mtproto_post_{message.id}.mp3")
            size_mb = (getattr(message.file, "size", 0) or 0) / (1024 * 1024)

            try:
                print(f"📥 Downloading post #{message.id} ({size_mb:.2f} MB)...")
                await client.download_media(message, file=tmp_path)

                if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                    track_id = self.ingest_audio_file(
                        file_path=tmp_path,
                        title=title,
                        surah_name=meta["surah_name"],
                        ayah_range=meta["ayah_range"],
                        recitation_type=meta["recitation_type"],
                        telegram_post_url=post_url
                    )
                    indexed_count += 1
                    print(f"✅ Successfully indexed post #{message.id} (Track #{track_id})!")
            except Exception as e:
                print(f"❌ Error indexing post #{message.id}: {e}")
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        await client.disconnect()
        return indexed_count

    def crawl_and_index(self, max_posts: int = 50, order: str = "latest") -> int:
        """
        Synchronous entry point for crawling channel posts.
        Uses MTProto engine for unlimited large file downloading and indexing.
        """
        return asyncio.run(self.crawl_channel_mtproto(max_posts=max_posts))
