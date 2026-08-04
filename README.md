# Quran Shazam (موسوعة شازام القرآن الكريم)

A Shazam-like recognition and timestamp-alignment engine for Quranic recitations.

Given an audio recording, voice note, video clip, or social media link (**Instagram Reels**, **TikTok**, **Facebook**, **YouTube Shorts**), **Quran Shazam** identifies:
- 👤 **The Reciter** (e.g. Al-Minshawi, Abdulbasit, etc.)
- 📖 **The Surah & Ayah range**
- 🎙️ **Recitation Type** (Hafala / Mujawwad / Murattal)
- ⏱️ **Exact Timestamp offset** (e.g. `04:12` into the track)
- 🔗 **Direct Telegram Link** to the full recitation post.

---

## 🌟 Key Features

1. **Acoustic Landmark Fingerprinting**: Custom peak-constellation algorithm optimized for vocal recitations.
2. **Exact Timestamp Identification**: Calculates time offset alignment histogram to pinpoint the exact minute and second where the query clip appears.
3. **Multi-Platform Link Ingestion**: Built-in `yt-dlp` integration to automatically fetch audio from TikTok, Instagram, Facebook, YouTube, or direct links.
4. **Telegram Bot**: Full Arabic/English Telegram bot interface for voice messages, audio/video uploads, and links.
5. **FastAPI Web REST Backend**: Decoupled backend with REST API endpoints ready for web frontends.
6. **Extensible Catalog**: Supports indexing any reciter encyclopedia or Telegram channel (`t.me/MinshawiEncyclopedia`, `t.me/...`).

---

## 🚀 Quick Start

### 1. Environment Setup

```bash
# Activate virtual environment
source venv/bin/bin/activate # or ./venv/bin/python
```

### 2. Crawl and Index Telegram Channel (`https://t.me/MinshawiEncyclopedia`)

To fetch and index recitations from the Minshawi Telegram channel into the local database:

```bash
./venv/bin/python cli.py crawl --channel MinshawiEncyclopedia --reciter minshawi --max 20
```

To view database statistics:

```bash
./venv/bin/python cli.py stats
```

---

## 🎧 Search & Identify Recitation Clips

### Via CLI:

Query a local audio/video clip:
```bash
./venv/bin/python cli.py search --file test_clip.mp3
```

Query a TikTok or Instagram link:
```bash
./venv/bin/python cli.py search --url "https://www.instagram.com/reel/Cxxxxxx/"
```

---

## 🤖 Running Telegram Bot

Set your `@BotFather` token and run the bot:

```bash
export TELEGRAM_BOT_TOKEN="your_bot_father_token_here"
./venv/bin/python cli.py run-bot
```

Features in Telegram:
- Send a Voice Note or Audio file
- Send a Video clip or Video Note
- Paste a TikTok, Instagram Reels, or Facebook Video link
- Receive Surah, Ayah range, reciter, timestamp, and Telegram post link!

---

## 🌐 Running Web REST API

To launch the FastAPI Web Server (for web app frontends):

```bash
./venv/bin/python cli.py run-api --host 0.0.0.0 --port 8000
```

Interactive API documentation will be available at:
`http://localhost:8000/docs`

### Key API Endpoints:

- `POST /api/v1/identify`: Upload audio file or form URL to identify recitation and get timestamp.
- `POST /api/v1/identify/url`: JSON body `{ "url": "..." }` to identify social media link.
- `GET /api/v1/stats`: Catalog statistics.
- `GET /api/v1/reciters`: List registered reciters.
- `GET /api/v1/tracks`: List indexed track catalog.
- `POST /api/v1/ingest/channel`: Trigger Telegram channel crawler.

---

## 📁 Project Architecture

```
quranshazam/
├── config.py             # System & audio fingerprint configurations
├── cli.py                # Command Line Interface & Management
├── requirements.txt      # Python dependencies
├── core/
│   ├── audio.py          # FFmpeg audio extractor & PCM normalizer
│   ├── fingerprint.py    # Shazam landmark constellation algorithm
│   ├── db.py             # SQLite catalog & fingerprint index manager
│   ├── recognizer.py     # Timestamp offset voting & matching engine
│   └── media.py          # yt-dlp social media link extractor
├── crawler/
│   └── tme_crawler.py    # Telegram channel crawler & metadata parser
├── api/
│   └── app.py            # FastAPI REST Web server
└── bot/
    └── telegram_bot.py   # Telegram Bot handler
```
