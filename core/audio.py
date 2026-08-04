import os
import subprocess
import numpy as np
import tempfile
from pathlib import Path
from typing import Tuple, Optional
import config

def extract_pcm_from_file(file_path: str, sample_rate: int = config.SAMPLE_RATE) -> Tuple[np.ndarray, float]:
    """
    Extracts mono PCM audio (float32 array) from any video/audio/voice file using FFmpeg.
    Returns:
        (audio_samples: np.ndarray, duration_seconds: float)
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio/Video file not found: {file_path}")

    # FFmpeg command to decode to s16le raw mono PCM audio
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-loglevel", "error",
        "-i", file_path,
        "-ac", "1",               # Mono
        "-ar", str(sample_rate),   # Target sample rate
        "-f", "s16le",             # Signed 16-bit little-endian raw PCM
        "-acodec", "pcm_s16le",
        "pipe:1"
    ]

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        raw_audio, stderr = process.communicate()
        if process.returncode != 0 and len(raw_audio) == 0:
            raise RuntimeError(f"FFmpeg failed: {stderr.decode('utf-8', errors='ignore')}")

        # Convert int16 raw buffer to float32 normalized in [-1.0, 1.0]
        samples = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0
        duration = len(samples) / float(sample_rate)
        return samples, duration
    except Exception as e:
        raise RuntimeError(f"Error processing audio file {file_path}: {e}")

def extract_pcm_from_bytes(audio_bytes: bytes, file_extension: str = "mp3", sample_rate: int = config.SAMPLE_RATE) -> Tuple[np.ndarray, float]:
    """
    Extracts PCM audio from in-memory audio/video bytes.
    """
    with tempfile.NamedTemporaryFile(suffix=f".{file_extension}", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        return extract_pcm_from_file(tmp_path, sample_rate)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
