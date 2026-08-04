import argparse
import sys
import os
import uvicorn

import config
from core.db import Database
from core.recognizer import AudioRecognizer
from core.media import process_media_url, extract_url_from_text
from crawler.tme_crawler import TelegramChannelCrawler

def main():
    parser = argparse.ArgumentParser(description="Quran Shazam CLI & Management Tool")
    subparsers = parser.add_subparsers(dest="command", help="Subcommand to execute")

    # Command: stats
    parser_stats = subparsers.add_parser("stats", help="Display database catalog and fingerprint statistics")

    # Command: crawl
    parser_crawl = subparsers.add_parser("crawl", help="Crawl Telegram channel and index recitations")
    parser_crawl.add_argument("--channel", default="AlminshawiEncyclopedia", help="Telegram channel slug or URL (default: AlminshawiEncyclopedia)")
    parser_crawl.add_argument("--reciter", default=config.DEFAULT_RECITER_SLUG, help="Reciter slug (default: minshawi)")
    parser_crawl.add_argument("--max", type=int, default=20, help="Max posts to crawl (default: 20)")
    parser_crawl.add_argument("--order", choices=["latest", "oldest"], default="latest", help="Crawl order: latest (newest first) or oldest (default: latest)")

    # Command: index-file
    parser_index = subparsers.add_parser("index-file", help="Index a local audio file into catalog")
    parser_index.add_argument("--file", required=True, help="Path to audio file")
    parser_index.add_argument("--title", required=True, help="Recitation Title")
    parser_index.add_argument("--surah", default="", help="Surah name")
    parser_index.add_argument("--ayah", default="", help="Ayah range")
    parser_index.add_argument("--type", default="مجود", help="Recitation type (حفلة / مجود / مرتل)")
    parser_index.add_argument("--reciter", default=config.DEFAULT_RECITER_SLUG, help="Reciter slug")
    parser_index.add_argument("--url", default="", help="Telegram post URL")

    # Command: index-folder
    parser_folder = subparsers.add_parser("index-folder", help="Batch index a folder of audio files into catalog")
    parser_folder.add_argument("--folder", required=True, help="Path to directory containing audio files")
    parser_folder.add_argument("--reciter", default=config.DEFAULT_RECITER_SLUG, help="Reciter slug")

    # Command: index-url
    parser_url = subparsers.add_parser("index-url", help="Index a track directly from a Telegram post URL or media link")
    parser_url.add_argument("--url", required=True, help="Telegram post URL or audio stream link")
    parser_url.add_argument("--reciter", default=config.DEFAULT_RECITER_SLUG, help="Reciter slug")

    # Command: search
    parser_search = subparsers.add_parser("search", help="Search/Identify an audio clip or social media URL")
    parser_search.add_argument("--file", help="Path to audio/video query file")
    parser_search.add_argument("--url", help="Social media URL (TikTok/IG/FB/YT)")
    parser_search.add_argument("--reciter", help="Filter search by reciter slug")

    # Command: run-api
    parser_api = subparsers.add_parser("run-api", help="Start FastAPI REST Web Server")
    parser_api.add_argument("--host", default="0.0.0.0", help="Host address (default: 0.0.0.0)")
    parser_api.add_argument("--port", type=int, default=8000, help="Port number (default: 8000)")

    # Command: run-bot
    parser_bot = subparsers.add_parser("run-bot", help="Start Telegram Bot")

    args = parser.parse_args()

    if not args.command or args.command == "stats":
        db = Database()
        stats = db.get_stats()
        print("=== Quran Shazam Database Stats ===")
        print(f"Reciters:     {stats['reciters']}")
        print(f"Tracks:       {stats['tracks']}")
        print(f"Fingerprints: {stats['fingerprints']:,}")
        return

    if args.command == "crawl":
        print(f"Crawling Telegram channel: {args.channel} (Reciter: {args.reciter}, Order: {args.order})...")
        crawler = TelegramChannelCrawler(channel_slug=args.channel, reciter_slug=args.reciter)
        count = crawler.crawl_and_index(max_posts=args.max, order=args.order)
        print(f"Successfully indexed {count} recitations into catalog.")

    elif args.command == "index-file":
        crawler = TelegramChannelCrawler(reciter_slug=args.reciter)
        track_id = crawler.ingest_audio_file(
            file_path=args.file,
            title=args.title,
            surah_name=args.surah,
            ayah_range=args.ayah,
            recitation_type=args.type,
            telegram_post_url=args.url
        )
        print(f"Successfully indexed track #{track_id} '{args.title}'")

    elif args.command == "index-folder":
        crawler = TelegramChannelCrawler(reciter_slug=args.reciter)
        count = crawler.ingest_folder(folder_path=args.folder)
        print(f"Successfully indexed {count} audio files from folder '{args.folder}' into catalog.")

    elif args.command == "index-url":
        crawler = TelegramChannelCrawler(reciter_slug=args.reciter)
        track_id = crawler.ingest_post_url(post_url=args.url)
        if track_id:
            print(f"Successfully indexed track #{track_id} from URL '{args.url}'")
        else:
            print(f"Failed to index track from URL '{args.url}'")

    elif args.command == "search":
        recognizer = AudioRecognizer()
        if args.file:
            print(f"Searching query file: {args.file}...")
            matches = recognizer.match_file(args.file, reciter_slug=args.reciter)
        elif args.url:
            print(f"Downloading and searching social URL: {args.url}...")
            samples, duration, title = process_media_url(args.url)
            matches = recognizer.match_pcm(samples, reciter_slug=args.reciter)
        else:
            print("Error: Must specify either --file or --url")
            sys.exit(1)

        if not matches:
            print("No matching Quranic recitation found.")
        else:
            top = matches[0]
            print("\n✨ Match Found! ✨")
            print(f"Title:        {top['title']}")
            print(f"Surah:        {top['surah_name']} ({top['ayah_range']})")
            print(f"Reciter:      {top['reciter_name']}")
            print(f"Type:         {top['recitation_type']}")
            print(f"Timestamp:    {top['timestamp_formatted']} (second {top['timestamp_seconds']})")
            print(f"Confidence:   {top['confidence']}% (Score: {top['score']})")
            print(f"Telegram URL: {top['telegram_post_url']}")

    elif args.command == "run-api":
        print(f"Launching Quran Shazam Web API on http://{args.host}:{args.port}...")
        uvicorn.run("api.app:app", host=args.host, port=args.port, reload=True)

    elif args.command == "run-bot":
        from bot.telegram_bot import main as run_telegram_bot
        run_telegram_bot()

if __name__ == "__main__":
    main()
