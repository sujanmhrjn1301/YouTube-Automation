"""
Stage 7: Supabase Database and Cloud Storage Service.
Uploads processed Shorts to Supabase Storage and records pipeline metadata in Supabase DB.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from supabase import create_client, Client

from src.config import settings
from src.console import (
    log_stage,
    log_info,
    log_success,
    log_warning,
    log_error,
)
from src.models import VideoMetadata, ViralClip


class DatabaseService:
    """Manages Supabase Storage uploads, local SQLite persistence, and Supabase DB logging."""

    def __init__(self) -> None:
        self.url = settings.SUPABASE_URL
        self.key = settings.SUPABASE_SERVICE_ROLE_KEY
        self.bucket_name = settings.SUPABASE_SHORTS_BUCKET
        self.local_db_path = settings.OUTPUT_DIR / "shorts.db"
        self.json_history_path = settings.OUTPUT_DIR / "shorts_metadata.json"
        self.client: Optional[Client] = None
        self._init_local_db()
        self._init_client()

    def _init_local_db(self) -> None:
        """Initialize local SQLite database table if missing."""
        try:
            conn = sqlite3.connect(self.local_db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shorts_metadata (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_url TEXT NOT NULL,
                    source_video_id TEXT,
                    source_title TEXT,
                    hook_title TEXT,
                    description TEXT,
                    tags TEXT,
                    viral_reasoning TEXT,
                    hook_score INTEGER,
                    start_time REAL,
                    end_time REAL,
                    duration REAL,
                    storage_url TEXT,
                    local_path TEXT,
                    youtube_id TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            log_warning("DATABASE", f"Local SQLite init error: {e}")

    def _init_client(self) -> None:
        """Initialize Supabase client if credentials exist."""
        if self.url and self.key:
            try:
                self.client = create_client(self.url, self.key)
            except Exception as e:
                log_warning("DATABASE", f"Failed to connect to Supabase: {e}")
        else:
            log_warning("DATABASE", "SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not configured in .env.")

    def upload_to_storage(self, file_path: str, remote_filename: Optional[str] = None) -> Optional[str]:
        """
        Upload final video file to Supabase Storage bucket.
        Returns public URL if available.
        """
        if not self.client:
            log_warning("DATABASE", "Supabase client not initialized. Skipping storage upload.")
            return None

        path_obj = Path(file_path)
        if not path_obj.exists():
            log_error("DATABASE", f"File not found for storage upload: {file_path}")
            return None

        if not remote_filename:
            remote_filename = f"shorts/{path_obj.name}"

        log_info("DATABASE", f"Uploading {path_obj.name} to Supabase bucket '{self.bucket_name}'...")

        try:
            with open(path_obj, "rb") as f:
                file_bytes = f.read()

            # Upload or overwrite file in bucket
            self.client.storage.from_(self.bucket_name).upload(
                path=remote_filename,
                file=file_bytes,
                file_options={"content-type": "video/mp4", "upsert": "true"},
            )

            public_url = self.client.storage.from_(self.bucket_name).get_public_url(remote_filename)
            log_success("DATABASE", f"File uploaded to Supabase Storage: {public_url}")
            return public_url
        except Exception as e:
            log_warning("DATABASE", f"Supabase storage upload error: {e}")
            return None

    def save_clip_record(
        self,
        source_url: str,
        video_meta: VideoMetadata,
        clip: ViralClip,
        storage_url: Optional[str] = None,
        local_path: Optional[str] = None,
        youtube_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Record generated Short and viral metrics into local SQLite and Supabase table.
        """
        now_iso = datetime.utcnow().isoformat()
        tags_str = ", ".join(clip.tags)

        # 1. Local SQLite storage (always succeeds out-of-the-box)
        local_rec_id = None
        try:
            conn = sqlite3.connect(self.local_db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO shorts_metadata (
                    source_url, source_video_id, source_title, hook_title,
                    description, tags, viral_reasoning, hook_score,
                    start_time, end_time, duration, storage_url, local_path,
                    youtube_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                source_url,
                video_meta.video_id,
                video_meta.title,
                clip.hook_title,
                clip.description,
                tags_str,
                clip.viral_reasoning,
                clip.hook_score,
                clip.start_time,
                clip.end_time,
                round(clip.end_time - clip.start_time, 2),
                storage_url or "",
                local_path or "",
                youtube_id or "",
                now_iso,
            ))
            conn.commit()
            local_rec_id = cursor.lastrowid
            conn.close()
            log_success("DATABASE", f"Saved clip to local SQLite database (ID: {local_rec_id})")
        except Exception as e:
            log_warning("DATABASE", f"Failed to save to local SQLite: {e}")

        # 2. Append to JSON history file
        try:
            history: List[Dict[str, Any]] = []
            if self.json_history_path.exists():
                try:
                    with open(self.json_history_path, "r", encoding="utf-8") as f:
                        history = json.load(f)
                except Exception:
                    history = []

            history.append({
                "id": local_rec_id,
                "source_url": source_url,
                "source_video_id": video_meta.video_id,
                "source_title": video_meta.title,
                "hook_title": clip.hook_title,
                "description": clip.description,
                "tags": clip.tags,
                "viral_reasoning": clip.viral_reasoning,
                "hook_score": clip.hook_score,
                "start_time": clip.start_time,
                "end_time": clip.end_time,
                "duration": round(clip.end_time - clip.start_time, 2),
                "storage_url": storage_url,
                "local_path": local_path,
                "youtube_id": youtube_id,
                "created_at": now_iso,
            })

            with open(self.json_history_path, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2)
        except Exception:
            pass

        # 3. Supabase Cloud Sync (if connected and table exists)
        if not self.client:
            return str(local_rec_id) if local_rec_id else "saved"

        record_data: Dict[str, Any] = {
            "source_url": source_url,
            "source_video_id": video_meta.video_id,
            "source_title": video_meta.title,
            "hook_title": clip.hook_title,
            "description": clip.description,
            "tags": clip.tags,
            "viral_reasoning": clip.viral_reasoning,
            "hook_score": clip.hook_score,
            "start_time": clip.start_time,
            "end_time": clip.end_time,
            "duration": round(clip.end_time - clip.start_time, 2),
            "storage_url": storage_url,
            "youtube_id": youtube_id,
            "created_at": now_iso,
        }

        table_name = "shorts_metadata"
        log_info("DATABASE", f"Syncing viral clip metadata to Supabase table '{table_name}'...")

        try:
            res = self.client.table(table_name).insert(record_data).execute()
            if res.data and len(res.data) > 0:
                rec_id = str(res.data[0].get("id", local_rec_id))
                log_success("DATABASE", f"Synced to Supabase DB (ID: {rec_id})")
                return rec_id
        except Exception as e:
            log_warning("DATABASE", f"Supabase DB sync note: {e}")

        return str(local_rec_id) if local_rec_id else "saved"
