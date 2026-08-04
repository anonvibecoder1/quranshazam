from collections import defaultdict
import math
from typing import Dict, Any, List, Optional, Tuple
import numpy as np

from core.db import Database
from core.fingerprint import fingerprint_audio
from core.audio import extract_pcm_from_file, extract_pcm_from_bytes
import config

class AudioRecognizer:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()

    def index_audio_file(self, file_path: str, track_id: int) -> int:
        """
        Processes an audio file, generates fingerprints, and stores them in the database for track_id.
        Returns number of fingerprints stored.
        """
        samples, duration = extract_pcm_from_file(file_path)
        hashes = fingerprint_audio(samples)
        self.db.store_fingerprints(track_id, hashes)
        return len(hashes)

    def match_pcm(self, samples: np.ndarray, reciter_slug: Optional[str] = None, max_query_duration: float = 45.0) -> List[Dict[str, Any]]:
        """
        Matches raw PCM sample array against database tracks.
        Trims query clip to max_query_duration (45s) for instant sub-second recognition.
        Returns ranked list of match results.
        """
        if len(samples) == 0:
            return []

        # Trim query audio clip to 45 seconds for sub-second fingerprinting
        max_samples = int(max_query_duration * config.SAMPLE_RATE)
        if len(samples) > max_samples:
            samples = samples[:max_samples]

        # Generate query hashes: list of (hash_val, query_offset_sec)
        query_hashes = fingerprint_audio(samples)
        if not query_hashes:
            return []

        # Extract hash values for DB lookup
        hash_to_query_offsets = defaultdict(list)
        for h_val, q_offset in query_hashes:
            hash_to_query_offsets[h_val].append(q_offset)

        all_query_hash_vals = list(hash_to_query_offsets.keys())
        
        # Query DB for matching hashes
        db_matches = self.db.query_fingerprints(all_query_hash_vals)
        if not db_matches:
            return []

        # Vote per track using time-difference histogram
        # track_id -> dict of binned_offset -> count
        track_votes = defaultdict(lambda: defaultdict(int))
        track_offset_samples = defaultdict(lambda: defaultdict(list))

        BIN_SIZE = 0.5  # 0.5 second histogram resolution for time offset alignment

        for h_val, track_id, db_offset in db_matches:
            for q_offset in hash_to_query_offsets[h_val]:
                diff = db_offset - q_offset
                binned_diff = round(diff / BIN_SIZE) * BIN_SIZE
                track_votes[track_id][binned_diff] += 1
                track_offset_samples[track_id][binned_diff].append(diff)

        # Process results per track
        results = []
        for track_id, binned_histogram in track_votes.items():
            track_info = self.db.get_track(track_id)
            if not track_info:
                continue

            # If filtering by reciter
            if reciter_slug and track_info.get("reciter_slug") != reciter_slug:
                continue

            # Find peak offset bin
            best_bin, peak_score = max(binned_histogram.items(), key=lambda x: x[1])
            
            # Refine precise timestamp (average of offsets in best bin)
            exact_offset = float(np.mean(track_offset_samples[track_id][best_bin]))
            exact_offset = max(0.0, exact_offset)

            # Total matches across all bins for this track
            total_track_matches = sum(binned_histogram.values())
            
            # Confidence score calculation
            confidence = float(peak_score) / float(len(query_hashes)) * 100.0

            # Format timestamp string (MM:SS or HH:MM:SS)
            seconds = int(exact_offset)
            mins, secs = divmod(seconds, 60)
            hours, mins = divmod(mins, 60)
            if hours > 0:
                timestamp_str = f"{hours:02d}:{mins:02d}:{secs:02d}"
            else:
                timestamp_str = f"{mins:02d}:{secs:02d}"

            results.append({
                "track_id": track_id,
                "title": track_info["title"],
                "surah_name": track_info.get("surah_name", ""),
                "ayah_range": track_info.get("ayah_range", ""),
                "recitation_type": track_info.get("recitation_type", ""),
                "reciter_name": track_info.get("reciter_name", ""),
                "reciter_slug": track_info.get("reciter_slug", ""),
                "telegram_post_url": track_info.get("telegram_post_url", ""),
                "timestamp_seconds": round(exact_offset, 2),
                "timestamp_formatted": timestamp_str,
                "score": peak_score,
                "total_matches": total_track_matches,
                "confidence": round(confidence, 2)
            })

        # Sort results by score (peak vote count) descending
        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    def match_file(self, file_path: str, reciter_slug: Optional[str] = None) -> List[Dict[str, Any]]:
        samples, duration = extract_pcm_from_file(file_path)
        return self.match_pcm(samples, reciter_slug)

    def match_bytes(self, audio_bytes: bytes, file_extension: str = "mp3", reciter_slug: Optional[str] = None) -> List[Dict[str, Any]]:
        samples, duration = extract_pcm_from_bytes(audio_bytes, file_extension)
        return self.match_pcm(samples, reciter_slug)
