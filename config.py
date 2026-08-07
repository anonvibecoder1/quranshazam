import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

AUDIO_STORE_DIR = DATA_DIR / "audio_store"
AUDIO_STORE_DIR.mkdir(exist_ok=True)

TEMP_DIR = DATA_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

DB_PATH = os.getenv("QURAN_SHAZAM_DB", str(DATA_DIR / "quranshazam.db"))

# Audio Processing Settings
SAMPLE_RATE = 11025  # Mono 11.025 kHz suitable for vocal speech/recitation matching
FFT_WINDOW_SIZE = 4096
HOP_SIZE = 1024
DEFAULT_FANOUT = 15

# Landmark Peak Detection Settings
MIN_AMP = 1.0  # Minimum logarithmic spectrogram amplitude threshold
NEIGHBORHOOD_SIZE = 10  # Minimum distance between peaks in time/frequency grid

# Shazam Pair Hashing Settings
MIN_TIME_DELTA = 0.5  # seconds
MAX_TIME_DELTA = 5.0  # seconds
FREQ_BITS = 10        # quantization bits for frequency (0..1023)

# Telegram Bot Config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8776235491:AAF1o4qO0ByJrnrDGp7QihZUp4bOFqgYb-w")
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")

# Default Reciter Settings
DEFAULT_RECITER_SLUG = "minshawi"
DEFAULT_RECITER_NAME = "Mohamed Siddiq El-Minshawi (محمد صديق المنشاوي)"
DEFAULT_CHANNEL_URL = "https://t.me/s/AlminshawiEncyclopedia"
