import os
import re
import tempfile
import yt_dlp
from typing import Optional, Tuple
from core.audio import extract_pcm_from_file
import numpy as np

URL_REGEX = re.compile(r'https?://[^\s]+')

def extract_url_from_text(text: str) -> Optional[str]:
    """Finds the first HTTP/HTTPS URL in a given text message."""
    match = URL_REGEX.search(text)
    return match.group(0) if match else None

def download_audio_from_url(url: str) -> Tuple[str, str]:
    """
    Uses yt-dlp to extract and download audio from social media URLs
    (Instagram, TikTok, Facebook, YouTube, Twitter, direct links).
    Returns:
        (downloaded_file_path, title_or_meta)
    """
    tmp_dir = tempfile.mkdtemp(prefix="quranshazam_media_")
    output_template = os.path.join(tmp_dir, "media_%(id)s.%(ext)s")

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Media Stream') if info else 'Media Stream'
    except Exception as e:
        # Fallback for direct audio download (e.g. .mp3, .m4a, .wav)
        import urllib.request
        title = os.path.basename(url.split("?")[0]) or "Downloaded Audio"
        download_target = os.path.join(tmp_dir, "media_direct.mp3")
        try:
            req = urllib.request.Request(url, headers={'User-Agent': ydl_opts['user_agent']})
            with urllib.request.urlopen(req) as resp, open(download_target, 'wb') as out_file:
                out_file.write(resp.read())
        except Exception:
            raise RuntimeError(f"Could not extract or download audio from URL: {url}. Details: {str(e)}")

    # Locate downloaded file
    file_path = None
    for file in os.listdir(tmp_dir):
        if file.endswith(('.mp3', '.m4a', '.wav', '.ogg')) or file.startswith('media_'):
            file_path = os.path.join(tmp_dir, file)
            break
    
    if not file_path or not os.path.exists(file_path):
        raise FileNotFoundError(f"Failed to extract audio from URL: {url}")

    return file_path, title

def process_media_url(url: str) -> Tuple[np.ndarray, float, str]:
    """
    Downloads media URL and extracts mono PCM float32 samples.
    Returns:
        (samples: np.ndarray, duration_seconds: float, title: str)
    """
    file_path, title = download_audio_from_url(url)
    try:
        samples, duration = extract_pcm_from_file(file_path)
        return samples, duration, title
    finally:
        # Cleanup
        if os.path.exists(file_path):
            os.remove(file_path)
            try:
                os.rmdir(os.path.dirname(file_path))
            except Exception:
                pass
