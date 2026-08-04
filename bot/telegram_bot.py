import logging
import os
import tempfile
import asyncio
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode
from telegram.error import BadRequest

from core.db import Database
from core.recognizer import AudioRecognizer
from core.audio import extract_pcm_from_file
from core.fingerprint import fingerprint_audio
from core.media import process_media_url, extract_url_from_text
from crawler.tme_crawler import parse_caption_metadata
import config

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("QuranShazamBot")

db = Database()
recognizer = AudioRecognizer(db)

# In-memory storage for pending user media messages
pending_messages = {}

async def update_progress(status_msg, stage_name: str, percent: int, description: str):
    """Updates the Telegram status message with an animated progress bar and detailed stage description."""
    bar_length = 8
    filled = int(bar_length * (percent / 100))
    bar = "🟩" * filled + "⬜" * (bar_length - filled)

    text = (
        f"🎧 **جاري معالجة التلاوة (Processing Recitation)**\n\n"
        f"[{bar}] `{percent}%`\n"
        f"📌 **المرحلة**: {stage_name}\n"
        f"💬 _{description}_"
    )
    try:
        await status_msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass

def format_match_message(match: dict) -> str:
    """Formats Quran Shazam match response in Markdown."""
    title = match.get("title", "Recitation Match")
    surah = match.get("surah_name", "")
    ayah = match.get("ayah_range", "")
    reciter = match.get("reciter_name", config.DEFAULT_RECITER_NAME)
    rec_type = match.get("recitation_type", "")
    timestamp = match.get("timestamp_formatted", "00:00")
    confidence = match.get("confidence", 0.0)
    tg_url = match.get("telegram_post_url", "")

    header = f"✨ **تم التعرف على التلاوة! | Recitation Identified!** ✨"

    body_ar = (
        f"📖 **السورة**: {surah or title}\n"
        f"🔢 **الآيات**: {ayah if ayah else 'غير محدد'}\n"
        f"👤 **القارئ**: {reciter}\n"
        f"🎙️ **نوع التلاوة**: {rec_type or 'مجود'}\n"
        f"⏱️ **التوقيت الدقيق في التلاوة**: `{timestamp}`\n"
        f"🎯 **نسبة التطابق**: `{confidence}%`"
    )

    links = ""
    if tg_url:
        links = f"\n\n🔗 **رابط التلاوة الكاملة على تليجرام**:\n[اضغط هنا للاستماع للمقطع الكامل]({tg_url})"

    return f"{header}\n\n{body_ar}{links}"

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🕌 **أهلاً بك في بوت شازام القرآن الكريم (Quran Shazam)** 🕌\n\n"
        "أرسل أو حوّل أي **تلاوة** من التليجرام، وسأعرض لك خيارين:\n"
        "1. 🔍 **التعرف على التلاوة والتوقيت**: لمعرفة اسم السورة والآيات والتوقيت.\n"
        "2. 📥 **إضافة للموسوعة (Index)**: لحفظ التلاوة وبصمتها في قاعدة البيانات.\n\n"
        "كما يمكنك إرسال روابط من Instagram Reels / TikTok / Facebook!"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_command(update, context)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = db.get_stats()
    msg = (
        f"📊 **إحصائيات الموسوعة (Quran Shazam Stats)**:\n"
        f"• عدد القراء: `{stats['reciters']}`\n"
        f"• عدد التلاوات المحفوظة: `{stats['tracks']}`\n"
        f"• عدد البصمات الصوتية: `{stats['fingerprints']:,}`"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def handle_audio_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    msg_id = message.message_id
    chat_id = message.chat_id

    # Save message in pending
    pending_messages[(chat_id, msg_id)] = message

    # Offer interactive choices
    keyboard = [
        [
            InlineKeyboardButton("🔍 التعرف على التلاوة (Recognize)", callback_data=f"rec_{msg_id}"),
            InlineKeyboardButton("📥 إضافة للموسوعة (Index)", callback_data=f"idx_{msg_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    caption = message.caption or message.text or ""
    title_preview = caption.split("\n")[0][:40] if caption else "مقطع تلاوة"

    await message.reply_text(
        f"🎧 **تم استلام التلاوة**: `{title_preview}`\n\nاختر الإجراء المطلوب:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def process_action(query, action: str, message: Update.message):
    status_msg = await query.message.edit_text("📥 **جاري بدء المعالجة...**", parse_mode=ParseMode.MARKDOWN)

    # Check media object
    media_obj = message.voice or message.audio or message.video or message.video_note or message.document
    file_ext = "mp3"
    if message.voice:
        file_ext = "ogg"
    elif message.video or message.video_note:
        file_ext = "mp4"

    if not media_obj:
        await status_msg.edit_text("❌ لم يتم التعرف على الملف الصوتي.")
        return

    # Check for forwarded channel link
    forward_url = None
    origin = getattr(message, "forward_origin", None)
    if origin and getattr(origin, "type", "") == "channel":
        chat = getattr(origin, "chat", None)
        f_msg_id = getattr(origin, "message_id", None)
        if chat and getattr(chat, "username", None) and f_msg_id:
            forward_url = f"https://t.me/{chat.username}/{f_msg_id}"

    if not forward_url:
        chat = getattr(message, "forward_from_chat", None)
        f_msg_id = getattr(message, "forward_from_message_id", None)
        if chat and getattr(chat, "username", None) and f_msg_id:
            forward_url = f"https://t.me/{chat.username}/{f_msg_id}"

    tmp_path = None
    try:
        # Step 1: Download Media
        await update_progress(status_msg, "تنزيل الملف الصوتي", 20, "جاري تنزيل الصوت...")

        with tempfile.NamedTemporaryFile(suffix=f".{file_ext}", delete=False) as tmp:
            tmp_path = tmp.name

        samples = None
        duration = 0.0

        try:
            telegram_file = await media_obj.get_file()
            await telegram_file.download_to_drive(tmp_path)
            await update_progress(status_msg, "معالجة الصوت", 40, "جاري تحويل وتصفية نبرة الصوت (FFmpeg)...")
            samples, duration = await asyncio.to_thread(extract_pcm_from_file, tmp_path)
        except BadRequest as e:
            if "File is too big" in str(e):
                if forward_url:
                    await update_progress(status_msg, "تحميل عبر الرابط", 30, f"حجم الملف كبير، جاري التحميل المباشر من:\n`{forward_url}`...")
                    samples, duration, title = await asyncio.to_thread(process_media_url, forward_url)
                else:
                    await status_msg.edit_text("⚠️ **الملف كبير جداً** (يتجاوز 20MB حد تليجرام البوتات). أرسل مقطعاً أقصر أو رابطاً.")
                    return
            else:
                raise e

        if samples is None or len(samples) == 0:
            await status_msg.edit_text("❌ تعذر استخراج الصوت من الملف.")
            return

        if action == "recognize":
            # RECOGNITION WORKFLOW
            await update_progress(status_msg, "تحليل ومطابقة البصمة", 75, "جاري البحث في قاعدة البيانات وتحديد التوقيت...")
            matches = await asyncio.to_thread(recognizer.match_pcm, samples)

            if matches:
                await update_progress(status_msg, "تمت المطابقة بنجاح", 100, "تم تحديد التلاوة والتوقيت!")
                await asyncio.sleep(0.3)
                response_text = format_match_message(matches[0])
                await status_msg.edit_text(response_text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=False)
            else:
                await status_msg.edit_text("❓ عذراً، لم أتمكن من إيجاد مطابقة لهذه التلاوة في الموسوعة الحالية.")

        elif action == "index":
            # INDEXING / INGESTION WORKFLOW
            await update_progress(status_msg, "فهرسة وتوليد البصمات", 70, "جاري استخراج كافة البصمات الصوتية وحفظ التلاوة بالموسوعة...")

            caption = message.caption or message.text or ""
            file_name = getattr(media_obj, "file_name", "") or "تلاوة قرآنية"
            title = caption.split("\n")[0] if caption else file_name

            # Parse Arabic metadata
            meta = parse_caption_metadata(caption)
            surah_name = meta.get("surah_name", "")
            ayah_range = meta.get("ayah_range", "")
            recitation_type = meta.get("recitation_type", "مجود")

            # 1. Add track
            track_id = db.add_track(
                reciter_slug=config.DEFAULT_RECITER_SLUG,
                title=title,
                surah_name=surah_name,
                ayah_range=ayah_range,
                recitation_type=recitation_type,
                telegram_post_url=forward_url or "",
                duration=duration
            )

            # 2. Extract full hashes
            hashes = await asyncio.to_thread(fingerprint_audio, samples)
            db.store_fingerprints(track_id, hashes)

            stats = db.get_stats()

            await update_progress(status_msg, "تم الحفظ بالموسوعة", 100, "تمت الفهرسة وتوليد البصمات بنجاح!")
            await asyncio.sleep(0.3)

            msg_done = (
                f"✅ **تمت إضافة التلاوة بنجاح إلى الموسوعة!**\n\n"
                f"📖 **العنوان**: `{title}`\n"
                f"🔢 **الآيات**: `{ayah_range if ayah_range else 'غير محدد'}`\n"
                f"⏱️ **المدة**: `{int(duration // 60):02d}:{int(duration % 60):02d}`\n"
                f"⚡ **عدد البصمات الصوتية**: `{len(hashes):,}`\n"
                f"🔗 **الرابط**: {forward_url or 'تليجرام'}\n\n"
                f"📊 **إجمالي التلاوات في الموسوعة**: `{stats['tracks']}`"
            )
            await status_msg.edit_text(msg_done, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=False)

    except Exception as e:
        logger.error(f"Error processing action {action}: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ حدث خطأ أثناء المعالجة: `{str(e)}`", parse_mode=ParseMode.MARKDOWN)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = query.message.chat_id

    if data.startswith("rec_"):
        orig_msg_id = int(data.replace("rec_", ""))
        message = pending_messages.get((chat_id, orig_msg_id)) or query.message.reply_to_message or query.message
        await process_action(query, "recognize", message)

    elif data.startswith("idx_"):
        orig_msg_id = int(data.replace("idx_", ""))
        message = pending_messages.get((chat_id, orig_msg_id)) or query.message.reply_to_message or query.message
        await process_action(query, "index", message)

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    url = extract_url_from_text(text)

    if not url:
        await update.message.reply_text("💡 يرجى إرسال مقطع صوتي/فيديو أو رابط من (Instagram/TikTok/Facebook/YouTube).")
        return

    status_msg = await update.message.reply_text("🌐 **جاري معالجة الرابط...**", parse_mode=ParseMode.MARKDOWN)

    try:
        await update_progress(status_msg, "تنزيل المقطع من الرابط", 30, f"جاري تحميل الصوت من الرابط...")
        samples, duration, title = await asyncio.to_thread(process_media_url, url)

        await update_progress(status_msg, "تحليل ومطابقة البصمة الصوتية", 75, "جاري استخراج بصمات الطيف الصوتي وتحديد التوقيت...")
        matches = await asyncio.to_thread(recognizer.match_pcm, samples)

        if matches:
            await update_progress(status_msg, "تمت المطابقة بنجاح", 100, "تم العثور على التلاوة وتحديد التوقيت!")
            await asyncio.sleep(0.3)
            response_text = format_match_message(matches[0])
            await status_msg.edit_text(response_text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=False)
        else:
            await status_msg.edit_text("❓ لم أتمكن من العثور على مطابقة لهذه التلاوة في موسوعة التسجيلات.")
    except Exception as e:
        logger.error(f"Error processing URL {url}: {e}")
        await status_msg.edit_text(f"❌ تعذر تحميل المقطع من الرابط: `{str(e)}`", parse_mode=ParseMode.MARKDOWN)

def create_telegram_application(token: str = config.TELEGRAM_BOT_TOKEN) -> Application:
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is missing.")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))

    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.VIDEO | filters.VIDEO_NOTE | filters.Document.ALL, handle_audio_message))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text_message))
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    return app

def main():
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN environment variable not set.")
        return

    print("Starting Quran Shazam Telegram Bot...")
    app = create_telegram_application(token)
    app.run_polling()

if __name__ == "__main__":
    main()
