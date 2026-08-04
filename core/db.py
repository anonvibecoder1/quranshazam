import sqlite3
import os
from typing import List, Tuple, Dict, Any, Optional
import config

class Database:
    def __init__(self, db_path: str = config.DB_PATH):
        self.db_path = db_path
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Reciters table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reciters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Tracks table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tracks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reciter_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    surah_name TEXT,
                    ayah_range TEXT,
                    recitation_type TEXT,
                    telegram_post_url TEXT,
                    audio_file_path TEXT,
                    duration REAL DEFAULT 0.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (reciter_id) REFERENCES reciters(id) ON DELETE CASCADE
                )
            """)
            # Fingerprints table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS fingerprints (
                    hash INTEGER NOT NULL,
                    track_id INTEGER NOT NULL,
                    offset REAL NOT NULL,
                    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
                )
            """)
            # Indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_fingerprints_hash ON fingerprints(hash)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_reciter ON tracks(reciter_id)")
            
            # Ensure default reciter exists
            cursor.execute("""
                INSERT INTO reciters (slug, name, description)
                VALUES (?, ?, ?)
                ON CONFLICT(slug) DO NOTHING
            """, (config.DEFAULT_RECITER_SLUG, config.DEFAULT_RECITER_NAME, "المنشاوي - موسوعة التسجيلات الكاملة"))
            conn.commit()

    def add_reciter(self, slug: str, name: str, description: str = "") -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO reciters (slug, name, description) VALUES (?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET name=excluded.name, description=excluded.description
            """, (slug, name, description))
            conn.commit()
            cursor.execute("SELECT id FROM reciters WHERE slug = ?", (slug,))
            return cursor.fetchone()["id"]

    def get_reciter(self, slug_or_id: Any) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if isinstance(slug_or_id, int) or (isinstance(slug_or_id, str) and slug_or_id.isdigit()):
                cursor.execute("SELECT * FROM reciters WHERE id = ?", (int(slug_or_id),))
            else:
                cursor.execute("SELECT * FROM reciters WHERE slug = ?", (str(slug_or_id),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_reciters(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM reciters ORDER BY id ASC")
            return [dict(r) for r in cursor.fetchall()]

    def add_track(self, reciter_slug: str, title: str, surah_name: str = "", ayah_range: str = "",
                  recitation_type: str = "", telegram_post_url: str = "", audio_file_path: str = "", duration: float = 0.0) -> int:
        reciter = self.get_reciter(reciter_slug)
        reciter_id = reciter["id"] if reciter else self.add_reciter(reciter_slug, reciter_slug)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Check if track already exists by telegram_post_url or title
            if telegram_post_url:
                cursor.execute("SELECT id FROM tracks WHERE telegram_post_url = ?", (telegram_post_url,))
                existing = cursor.fetchone()
                if existing:
                    return existing["id"]

            cursor.execute("""
                INSERT INTO tracks (reciter_id, title, surah_name, ayah_range, recitation_type, telegram_post_url, audio_file_path, duration)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (reciter_id, title, surah_name, ayah_range, recitation_type, telegram_post_url, audio_file_path, duration))
            conn.commit()
            return cursor.lastrowid

    def delete_track(self, track_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
            conn.commit()

    def get_track(self, track_id: int) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT t.*, r.slug as reciter_slug, r.name as reciter_name
                FROM tracks t
                JOIN reciters r ON t.reciter_id = r.id
                WHERE t.id = ?
            """, (track_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def store_fingerprints(self, track_id: int, hashes: List[Tuple[int, float]]):
        if not hashes:
            return
        records = [(h_val, track_id, round(offset, 3)) for h_val, offset in hashes]
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("INSERT INTO fingerprints (hash, track_id, offset) VALUES (?, ?, ?)", records)
            conn.commit()

    def query_fingerprints(self, hashes: List[int]) -> List[Tuple[int, int, float]]:
        """
        Batch query hash matches.
        Returns list of tuples: (hash, track_id, offset_seconds)
        """
        if not hashes:
            return []

        unique_hashes = list(set(hashes))
        results = []
        CHUNK_SIZE = 500

        with self.get_connection() as conn:
            cursor = conn.cursor()
            for i in range(0, len(unique_hashes), CHUNK_SIZE):
                chunk = unique_hashes[i:i + CHUNK_SIZE]
                placeholders = ",".join(["?"] * len(chunk))
                cursor.execute(f"SELECT hash, track_id, offset FROM fingerprints WHERE hash IN ({placeholders})", chunk)
                results.extend([(r["hash"], r["track_id"], r["offset"]) for r in cursor.fetchall()])

        return results

    def get_stats(self) -> Dict[str, int]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            reciter_count = cursor.execute("SELECT COUNT(*) FROM reciters").fetchone()[0]
            track_count = cursor.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
            fingerprint_count = cursor.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[0]
            return {
                "reciters": reciter_count,
                "tracks": track_count,
                "fingerprints": fingerprint_count
            }
