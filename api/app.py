from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import tempfile
import os

from core.db import Database
from core.recognizer import AudioRecognizer
from core.media import process_media_url, extract_url_from_text
from crawler.tme_crawler import TelegramChannelCrawler
import config

app = FastAPI(
    title="Quran Shazam API",
    description="Shazam-like Recitation Audio Recognition & Timestamp Alignment Engine",
    version="1.0.0"
)

# CORS middleware for web frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = Database()
recognizer = AudioRecognizer(db)

class URLIdentifyRequest(BaseModel):
    url: str
    reciter_slug: Optional[str] = None

class IngestUrlRequest(BaseModel):
    channel_url: str = config.DEFAULT_CHANNEL_URL
    max_posts: int = 20
    reciter_slug: str = config.DEFAULT_RECITER_SLUG

@app.get("/")
def read_root():
    return {
        "service": "Quran Shazam API",
        "status": "online",
        "docs": "/docs",
        "default_reciter": config.DEFAULT_RECITER_SLUG
    }

@app.get("/api/v1/stats")
def get_stats():
    return db.get_stats()

@app.get("/api/v1/reciters")
def list_reciters():
    return db.list_reciters()

@app.get("/api/v1/tracks")
def list_tracks(reciter_slug: Optional[str] = None):
    with db.get_connection() as conn:
        cursor = conn.cursor()
        if reciter_slug:
            reciter = db.get_reciter(reciter_slug)
            if not reciter:
                return []
            cursor.execute("SELECT * FROM tracks WHERE reciter_id = ? ORDER BY id DESC", (reciter["id"],))
        else:
            cursor.execute("SELECT * FROM tracks ORDER BY id DESC")
        return [dict(r) for r in cursor.fetchall()]

@app.post("/api/v1/identify")
async def identify_audio(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    reciter_slug: Optional[str] = Form(None)
):
    """
    Identifies recitation clip from uploaded audio/video file OR social media URL (IG/TikTok/FB/YT).
    Returns matched track info, exact timestamp, and confidence score.
    """
    if file:
        file_bytes = await file.read()
        ext = file.filename.split(".")[-1] if file.filename and "." in file.filename else "mp3"
        try:
            matches = recognizer.match_bytes(file_bytes, file_extension=ext, reciter_slug=reciter_slug)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Audio processing error: {str(e)}")
    elif url or (file is None and url is None):
        if not url:
            raise HTTPException(status_code=400, detail="Must provide either an audio/video file or a URL.")
        extracted_url = extract_url_from_text(url) or url
        try:
            samples, duration, title = process_media_url(extracted_url)
            matches = recognizer.match_pcm(samples, reciter_slug=reciter_slug)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to process media URL: {str(e)}")
    else:
        raise HTTPException(status_code=400, detail="Invalid request payload.")

    if not matches:
        return {
            "matched": False,
            "message": "No matching Quranic recitation found.",
            "results": []
        }

    best_match = matches[0]
    return {
        "matched": True,
        "best_match": best_match,
        "results": matches[:5]
    }

@app.post("/api/v1/identify/url")
def identify_by_url(body: URLIdentifyRequest):
    """JSON endpoint for identifying social media link (TikTok/IG/FB/YT/direct link)."""
    extracted_url = extract_url_from_text(body.url) or body.url
    try:
        samples, duration, title = process_media_url(extracted_url)
        matches = recognizer.match_pcm(samples, reciter_slug=body.reciter_slug)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Media URL processing error: {str(e)}")

    if not matches:
        return {
            "matched": False,
            "message": "No matching recitation found.",
            "results": []
        }

    return {
        "matched": True,
        "best_match": matches[0],
        "results": matches[:5]
    }

@app.post("/api/v1/ingest/channel")
def ingest_telegram_channel(body: IngestUrlRequest, background_tasks: BackgroundTasks):
    """
    Crawls and indexes recitations from Telegram Channel.
    """
    crawler = TelegramChannelCrawler(channel_slug=body.channel_url, reciter_slug=body.reciter_slug, db=db)
    count = crawler.crawl_and_index(max_posts=body.max_posts)
    return {
        "status": "success",
        "indexed_tracks": count,
        "channel": body.channel_url
    }
