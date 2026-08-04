import numpy as np
from scipy.ndimage import maximum_filter
import scipy.signal
from typing import List, Tuple
import config

def generate_spectrogram(samples: np.ndarray, sample_rate: int = config.SAMPLE_RATE, 
                         fft_size: int = config.FFT_WINDOW_SIZE, hop_size: int = config.HOP_SIZE) -> Tuple[np.ndarray, float]:
    """
    Computes STFT magnitude spectrogram in logarithmic scale using fast scipy routines.
    Returns:
        (spectrogram 2D array [freq_bins, time_frames], time_step_seconds)
    """
    if len(samples) < fft_size:
        samples = np.pad(samples, (0, fft_size - len(samples)))

    noverlap = fft_size - hop_size
    _, _, Sxx = scipy.signal.spectrogram(samples, fs=sample_rate, nperseg=fft_size, noverlap=noverlap, mode='magnitude')
    # Scale magnitude by 1000.0 so constellation peaks comfortably exceed MIN_AMP threshold (1.0)
    log_spectrogram = np.log1p(Sxx * 1000.0)
    time_step = hop_size / float(sample_rate)
    return log_spectrogram, time_step

def get_landmark_peaks(log_spectrogram: np.ndarray, min_amp: float = config.MIN_AMP, 
                       neighborhood_size: int = config.NEIGHBORHOOD_SIZE) -> List[Tuple[int, int]]:
    """
    Extracts 2D local maximum peaks (constellation map) from spectrogram.
    Returns list of (freq_bin, time_frame) tuples.
    """
    # Define neighborhood footprint for maximum filter
    struct = np.ones((neighborhood_size, neighborhood_size), dtype=bool)
    local_max = maximum_filter(log_spectrogram, footprint=struct) == log_spectrogram
    
    # Thresholding for background noise
    amp_mask = log_spectrogram >= min_amp
    detected_peaks = local_max & amp_mask
    
    # Get peak coordinates (freq_idx, time_idx)
    freqs, times = np.where(detected_peaks)
    
    peaks = list(zip(freqs, times))
    # Sort peaks chronologically by time frame
    peaks.sort(key=lambda p: p[1])
    return peaks

def generate_hashes(peaks: List[Tuple[int, int]], time_step: float, fanout: int = config.DEFAULT_FANOUT) -> List[Tuple[int, float]]:
    """
    Pairs constellation peaks into Shazam landmark hashes.
    Each hash combines:
      - freq1 (10 bits)
      - freq2 (10 bits)
      - delta_t quantized (10 bits)
    Total 30 bits integer hash.
    
    Returns:
        List of (hash_30bit: int, time_offset_seconds: float)
    """
    hashes = []
    num_peaks = len(peaks)
    
    min_delta_frames = int(config.MIN_TIME_DELTA / time_step)
    max_delta_frames = int(config.MAX_TIME_DELTA / time_step)

    for i in range(num_peaks):
        f1, t1 = peaks[i]
        
        # Look ahead for target peaks in fanout window
        target_count = 0
        for j in range(i + 1, num_peaks):
            f2, t2 = peaks[j]
            delta_t = t2 - t1
            
            if delta_t < min_delta_frames:
                continue
            if delta_t > max_delta_frames:
                break
                
            # Quantize values into 10 bits each (0 to 1023)
            f1_q = min(int(f1), 1023)
            f2_q = min(int(f2), 1023)
            dt_q = min(int(delta_t), 1023)
            
            # Combine into 30-bit integer hash
            hash_val = (f1_q << 20) | (f2_q << 10) | dt_q
            t1_seconds = round(t1 * time_step, 3)
            
            hashes.append((hash_val, t1_seconds))
            
            target_count += 1
            if target_count >= fanout:
                break

    return hashes

def fingerprint_audio(samples: np.ndarray, sample_rate: int = config.SAMPLE_RATE) -> List[Tuple[int, float]]:
    """
    High level helper: converts raw PCM audio into Shazam landmark hashes.
    """
    spec, time_step = generate_spectrogram(samples, sample_rate)
    peaks = get_landmark_peaks(spec)
    hashes = generate_hashes(peaks, time_step)
    return hashes
