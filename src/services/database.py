"""
Stage 7: Supabase Database and Cloud Storage Service.
Uploads processed Shorts to Supabase Storage and records pipeline metadata in Supabase DB.
"""

import json
import re
import sqlite3
import urllib.parse
from datetime import datetime, timezone
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
        self.livestream_bucket_name = settings.SUPABASE_LIVESTREAM_SHORTS_BUCKET
        self.local_db_path = settings.OUTPUT_DIR / "shorts.db"
        self.json_history_path = settings.OUTPUT_DIR / "shorts_metadata.json"
        self.client: Optional[Client] = None
        self._init_local_db()
        self._init_client()

    def _get_connection(self) -> sqlite3.Connection:
        """Get SQLite connection configured for concurrent multi-terminal safe access."""
        conn = sqlite3.connect(self.local_db_path, timeout=60.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=60000;")
        except Exception:
            pass
        return conn

    def _init_local_db(self) -> None:
        """Initialize local SQLite database tables and schema migrations."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 1. Main shorts metadata table
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

            # Add part and confirmation columns if missing (idempotent migrations)
            cursor.execute("PRAGMA table_info(shorts_metadata)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            if "part_number" not in existing_cols:
                cursor.execute("ALTER TABLE shorts_metadata ADD COLUMN part_number INTEGER DEFAULT 1")
            if "total_parts" not in existing_cols:
                cursor.execute("ALTER TABLE shorts_metadata ADD COLUMN total_parts INTEGER DEFAULT 1")
            if "is_confirmed_uploaded" not in existing_cols:
                cursor.execute("ALTER TABLE shorts_metadata ADD COLUMN is_confirmed_uploaded INTEGER DEFAULT 0")
            if "confirmed_at" not in existing_cols:
                cursor.execute("ALTER TABLE shorts_metadata ADD COLUMN confirmed_at TEXT")

            # 2. Multi-part series linking table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS video_series (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_video_id TEXT NOT NULL,
                    source_title TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    part_number INTEGER NOT NULL,
                    total_parts INTEGER NOT NULL,
                    short_title TEXT NOT NULL,
                    duration REAL NOT NULL,
                    youtube_id TEXT,
                    youtube_url TEXT,
                    is_confirmed INTEGER DEFAULT 0,
                    confirmed_at TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            # 3. YouTube API daily quota tracking table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS youtube_quota (
                    date TEXT PRIMARY KEY,
                    units_used INTEGER DEFAULT 0,
                    uploads_count INTEGER DEFAULT 0,
                    last_updated TEXT
                )
            """)

            conn.commit()
            conn.close()
        except Exception as e:
            log_warning("DATABASE", f"Local SQLite init error: {e}")

    def check_existing_upload(
        self,
        source_video_id: str,
        start_time: float,
        end_time: float,
        title: Optional[str] = None,
    ) -> Optional[str]:
        """
        Check if this exact clip or title was already uploaded to YouTube.
        Checks both local SQLite database and Supabase DB table.
        Returns the existing YouTube video ID if found, else None.
        """
        # 1. Local SQLite database check
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Check timestamp overlap (< 2.0s tolerance) on the same source video
            cursor.execute("""
                SELECT youtube_id, hook_title FROM shorts_metadata
                WHERE source_video_id = ?
                  AND ABS(start_time - ?) < 2.0
                  AND ABS(end_time - ?) < 2.0
                  AND youtube_id IS NOT NULL AND youtube_id != ''
                ORDER BY id DESC LIMIT 1
            """, (source_video_id, start_time, end_time))
            row = cursor.fetchone()
            if row and row[0]:
                conn.close()
                return str(row[0]).strip()

            # Check title match if provided
            if title:
                # Strip #shorts for comparison
                norm_title = title.replace("#Shorts", "").replace("#shorts", "").strip().lower()
                cursor.execute("""
                    SELECT youtube_id, hook_title FROM shorts_metadata
                    WHERE youtube_id IS NOT NULL AND youtube_id != ''
                    ORDER BY id DESC
                """)
                for y_id, h_title in cursor.fetchall():
                    if h_title:
                        existing_norm = h_title.replace("#Shorts", "").replace("#shorts", "").strip().lower()
                        if existing_norm == norm_title:
                            conn.close()
                            return str(y_id).strip()

            conn.close()
        except Exception as e:
            log_warning("DATABASE", f"Local duplicate check error: {e}")

        # 2. Supabase Cloud DB check (if connected)
        if self.client:
            try:
                res = self.client.table("shorts_metadata") \
                    .select("youtube_id, hook_title, start_time, end_time") \
                    .eq("source_video_id", source_video_id) \
                    .neq("youtube_id", "") \
                    .execute()
                if res.data:
                    for item in res.data:
                        yt_id = item.get("youtube_id")
                        if not yt_id:
                            continue
                        st = float(item.get("start_time", 0.0))
                        et = float(item.get("end_time", 0.0))
                        if abs(st - start_time) < 2.0 and abs(et - end_time) < 2.0:
                            return str(yt_id).strip()

                        if title:
                            h_title = item.get("hook_title", "")
                            norm_t1 = title.replace("#Shorts", "").replace("#shorts", "").strip().lower()
                            norm_t2 = h_title.replace("#Shorts", "").replace("#shorts", "").strip().lower()
                            if norm_t1 == norm_t2:
                                return str(yt_id).strip()
            except Exception as e:
                log_warning("DATABASE", f"Supabase duplicate check note: {e}")

        return None

    def _init_client(self) -> None:
        """Initialize Supabase client if credentials exist."""
        if self.url and self.key:
            try:
                self.client = create_client(self.url, self.key)
            except Exception as e:
                log_warning("DATABASE", f"Failed to connect to Supabase: {e}")
        else:
            log_warning("DATABASE", "SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not configured in .env.")

    def ensure_bucket_exists(self, bucket_name: str, public: bool = True) -> bool:
        """
        Verify that the given storage bucket exists in Supabase.
        Auto-creates it with public access if it is missing.
        """
        if not self.client:
            return False
        try:
            buckets = self.client.storage.list_buckets()
            names = [b.name for b in buckets]
            if bucket_name not in names:
                log_info("DATABASE", f"Creating missing Supabase Storage bucket: '{bucket_name}' (public={public})...")
                self.client.storage.create_bucket(bucket_name, options={"public": public})
                log_success("DATABASE", f"Successfully created Supabase bucket: '{bucket_name}'")
            return True
        except Exception as e:
            log_warning("DATABASE", f"Supabase bucket check note for '{bucket_name}': {e}")
            return False

    def upload_livestream_agent_short(
        self,
        file_path: str,
        remote_filename: Optional[str] = None,
    ) -> Optional[str]:
        """
        Exclusively uploads Shorts generated by the Autonomous Livestream Monitoring Agent
        to the dedicated SUPABASE_LIVESTREAM_SHORTS_BUCKET ('livestream-shorts').
        GUARANTEED ISOLATION: Never combines or writes into 'youtube-shorts' or 'reels'.
        """
        target_bucket = self.livestream_bucket_name
        self.ensure_bucket_exists(target_bucket, public=True)
        return self.upload_to_storage(
            file_path=file_path,
            remote_filename=remote_filename,
            is_livestream=True,
            bucket_name=target_bucket,
        )

    def upload_to_storage(
        self,
        file_path: str,
        remote_filename: Optional[str] = None,
        is_livestream: bool = False,
        bucket_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Upload final video file to Supabase Storage bucket.
        Organizes files into shorts/standard/ or shorts/livestreams/ folders.
        Supports explicit bucket targeting for guaranteed isolation.
        Returns public URL if available.
        """
        if not self.client:
            log_warning("DATABASE", "Supabase client not initialized. Skipping storage upload.")
            return None

        path_obj = Path(file_path)
        if not path_obj.exists():
            log_error("DATABASE", f"File not found for storage upload: {file_path}")
            return None

        target_bucket = bucket_name or self.bucket_name

        if not remote_filename:
            folder = "shorts/livestreams" if is_livestream else "shorts/standard"
            stem = path_obj.stem.replace("[", "").replace("]", "").replace(" ", "_")
            safe_stem = re.sub(r'[^a-zA-Z0-9_-]', '_', stem)
            safe_stem = re.sub(r'_+', '_', safe_stem).strip('_')
            remote_filename = f"{folder}/{safe_stem or 'short'}.mp4"
        else:
            parts = remote_filename.split("/")
            safe_parts = []
            for p in parts:
                p_clean = re.sub(r'[^a-zA-Z0-9_.-]', '_', p)
                p_clean = re.sub(r'_+', '_', p_clean).strip('_')
                safe_parts.append(p_clean)
            remote_filename = "/".join(safe_parts)

        log_info("DATABASE", f"Uploading {path_obj.name} to Supabase bucket '{target_bucket}/{remote_filename}'...")

        try:
            with open(path_obj, "rb") as f:
                file_bytes = f.read()

            # Upload or overwrite file in targeted bucket
            self.client.storage.from_(target_bucket).upload(
                path=remote_filename,
                file=file_bytes,
                file_options={"content-type": "video/mp4", "upsert": "true"},
            )

            public_url = self.client.storage.from_(target_bucket).get_public_url(remote_filename)
            log_success("DATABASE", f"File uploaded to Supabase Storage [{target_bucket}]: {public_url}")
            return public_url
        except Exception as e:
            log_warning("DATABASE", f"Supabase storage upload error in bucket '{target_bucket}': {e}")
            return None

    def save_clip_record(
        self,
        source_url: str,
        video_meta: VideoMetadata,
        clip: ViralClip,
        storage_url: Optional[str] = None,
        local_path: Optional[str] = None,
        youtube_id: Optional[str] = None,
        part_number: int = 1,
        total_parts: int = 1,
        is_confirmed: bool = False,
    ) -> Optional[str]:
        """
        Record generated Short and viral metrics into local SQLite, video_series, and Supabase table.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        tags_str = ", ".join(clip.tags)
        confirmed_at = now_iso if is_confirmed else ""

        # 1. Local SQLite storage (always succeeds out-of-the-box)
        local_rec_id = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO shorts_metadata (
                    source_url, source_video_id, source_title, hook_title,
                    description, tags, viral_reasoning, hook_score,
                    start_time, end_time, duration, storage_url, local_path,
                    youtube_id, created_at, part_number, total_parts,
                    is_confirmed_uploaded, confirmed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                part_number,
                total_parts,
                1 if is_confirmed else 0,
                confirmed_at,
            ))
            conn.commit()
            local_rec_id = cursor.lastrowid
            conn.close()
            log_success("DATABASE", f"Saved clip to local SQLite database (ID: {local_rec_id})")
        except Exception as e:
            log_warning("DATABASE", f"Failed to save to local SQLite: {e}")

        # Also register in the video_series linking table
        self.record_series_part(
            source_video_id=video_meta.video_id,
            source_title=video_meta.title,
            source_url=source_url,
            part_number=part_number,
            total_parts=total_parts,
            short_title=clip.hook_title,
            duration=clip.total_duration if hasattr(clip, "total_duration") else (clip.end_time - clip.start_time),
            youtube_id=youtube_id,
            is_confirmed=is_confirmed,
        )

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
                "part_number": part_number,
                "total_parts": total_parts,
                "is_confirmed_uploaded": is_confirmed,
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
            "part_number": part_number,
            "total_parts": total_parts,
            "is_confirmed_uploaded": is_confirmed,
            "confirmed_at": confirmed_at if confirmed_at else None,
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

    # ─────────────────────────────────────────────────────────────
    # MULTI-PART SERIES & CONFIRMATION METHODS
    # ─────────────────────────────────────────────────────────────
    def record_series_part(
        self,
        source_video_id: str,
        source_title: str,
        source_url: str,
        part_number: int,
        total_parts: int,
        short_title: str,
        duration: float,
        youtube_id: Optional[str] = None,
        is_confirmed: bool = False,
    ) -> int:
        """Record or update a part in the video_series linking table."""
        now_iso = datetime.now(timezone.utc).isoformat()
        yt_url = f"https://www.youtube.com/shorts/{youtube_id}" if youtube_id else ""
        confirmed_at = now_iso if is_confirmed else ""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            # Check if part already exists
            cursor.execute(
                "SELECT id FROM video_series WHERE source_video_id = ? AND part_number = ?",
                (source_video_id, part_number)
            )
            existing = cursor.fetchone()
            if existing:
                cursor.execute("""
                    UPDATE video_series
                    SET short_title = ?, duration = ?, youtube_id = ?, youtube_url = ?,
                        is_confirmed = ?, confirmed_at = CASE WHEN ? != '' THEN ? ELSE confirmed_at END
                    WHERE id = ?
                """, (short_title, round(duration, 2), youtube_id or "", yt_url, 1 if is_confirmed else 0, confirmed_at, confirmed_at, existing[0]))
                rec_id = existing[0]
            else:
                cursor.execute("""
                    INSERT INTO video_series (
                        source_video_id, source_title, source_url, part_number,
                        total_parts, short_title, duration, youtube_id,
                        youtube_url, is_confirmed, confirmed_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    source_video_id, source_title, source_url, part_number,
                    total_parts, short_title, round(duration, 2), youtube_id or "",
                    yt_url, 1 if is_confirmed else 0, confirmed_at, now_iso
                ))
                rec_id = cursor.lastrowid
            conn.commit()
            conn.close()

            # Supabase cloud sync for video_series
            if self.client:
                try:
                    self.client.table("video_series").upsert({
                        "source_video_id": source_video_id,
                        "source_title": source_title,
                        "source_url": source_url,
                        "part_number": part_number,
                        "total_parts": total_parts,
                        "short_title": short_title,
                        "duration": round(duration, 2),
                        "youtube_id": youtube_id or "",
                        "youtube_url": yt_url,
                        "is_confirmed": is_confirmed,
                        "confirmed_at": confirmed_at if confirmed_at else None,
                        "created_at": now_iso,
                    }, on_conflict="source_video_id,part_number").execute()
                except Exception:
                    pass

            return rec_id
        except Exception as e:
            log_warning("DATABASE", f"Failed to record video series part: {e}")
            return 0

    def mark_part_confirmed(self, source_video_id: str, part_number: int, youtube_id: str) -> None:
        """Mark a video part as fully confirmed uploaded after YouTube API verification."""
        now_iso = datetime.now(timezone.utc).isoformat()
        yt_url = f"https://www.youtube.com/shorts/{youtube_id}"
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE video_series
                SET is_confirmed = 1, confirmed_at = ?, youtube_id = ?, youtube_url = ?
                WHERE source_video_id = ? AND part_number = ?
            """, (now_iso, youtube_id, yt_url, source_video_id, part_number))
            cursor.execute("""
                UPDATE shorts_metadata
                SET is_confirmed_uploaded = 1, confirmed_at = ?
                WHERE source_video_id = ? AND youtube_id = ?
            """, (now_iso, source_video_id, youtube_id))
            conn.commit()
            conn.close()
            log_success("DATABASE", f"Marked Part #{part_number} as confirmed uploaded in series database.")

            # Update Supabase cloud DB as well
            if self.client:
                try:
                    self.client.table("video_series").update({
                        "is_confirmed": True,
                        "confirmed_at": now_iso,
                        "youtube_id": youtube_id,
                        "youtube_url": yt_url,
                    }).eq("source_video_id", source_video_id).eq("part_number", part_number).execute()

                    self.client.table("shorts_metadata").update({
                        "is_confirmed_uploaded": True,
                        "confirmed_at": now_iso,
                    }).eq("source_video_id", source_video_id).eq("youtube_id", youtube_id).execute()
                except Exception:
                    pass

        except Exception as e:
            log_warning("DATABASE", f"Failed to mark part confirmed: {e}")

    def get_series_summary(self, source_video_id: str) -> List[Dict[str, Any]]:
        """Retrieve all parts and confirmation status for a source video."""
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT part_number, total_parts, short_title, duration, youtube_id, youtube_url, is_confirmed, confirmed_at
                FROM video_series
                WHERE source_video_id = ?
                ORDER BY part_number ASC
            """, (source_video_id,))
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            log_warning("DATABASE", f"Failed to get series summary: {e}")
            return []

    # ─────────────────────────────────────────────────────────────
    # YOUTUBE API QUOTA TRACKING METHODS
    # ─────────────────────────────────────────────────────────────
    def get_daily_quota_status(self) -> Dict[str, Any]:
        """
        Check daily YouTube API quota consumption.
        Free tier default is 10,000 units/day (resets daily at midnight PST).
        """
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT units_used, uploads_count FROM youtube_quota WHERE date = ?", (today_str,))
            row = cursor.fetchone()
            conn.close()
            units_used = row[0] if row else 0
            uploads_today = row[1] if row else 0
        except Exception:
            units_used = 0
            uploads_today = 0

        max_daily_units = 10000
        cost_per_upload = 1600
        remaining = max(0, max_daily_units - units_used)
        can_upload = (units_used + cost_per_upload) <= max_daily_units

        return {
            "date": today_str,
            "units_used": units_used,
            "remaining_units": remaining,
            "uploads_today": uploads_today,
            "can_upload": can_upload,
            "max_daily_units": max_daily_units,
        }

    def record_quota_usage(self, units: int = 1600, is_upload: bool = True) -> None:
        """Record API quota consumption for today in SQLite."""
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            upload_inc = 1 if is_upload else 0
            cursor.execute("""
                INSERT INTO youtube_quota (date, units_used, uploads_count, last_updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    units_used = units_used + excluded.units_used,
                    uploads_count = uploads_count + excluded.uploads_count,
                    last_updated = excluded.last_updated
            """, (today_str, units, upload_inc, now_iso))
            conn.commit()
            conn.close()
        except Exception as e:
            log_warning("DATABASE", f"Failed to record quota usage: {e}")

    # ─────────────────────────────────────────────────────────────
    # STANDALONE QUEUED / PENDING UPLOADS
    # ─────────────────────────────────────────────────────────────
    def get_pending_shorts(self, limit: Optional[int] = 50) -> List[Dict[str, Any]]:
        """
        Query for Shorts that have been rendered and saved but not yet uploaded to YouTube.
        Merges local SQLite records (with accurate local_path) with Supabase cloud records.
        Prioritizes items that have an existing file ready on disk or valid storage URL.
        """
        from pathlib import Path
        import re

        pending_list: List[Dict[str, Any]] = []
        seen_keys = set()
        local_map: Dict[tuple, Dict[str, Any]] = {}

        # 1. Fetch from local SQLite first (primary source for local file paths)
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, source_url, source_video_id, source_title, hook_title,
                       description, tags, viral_reasoning, hook_score,
                       start_time, end_time, duration, storage_url, local_path,
                       youtube_id, created_at, part_number, total_parts,
                       is_confirmed_uploaded, confirmed_at
                FROM shorts_metadata
                WHERE (is_confirmed_uploaded = 0 OR is_confirmed_uploaded IS NULL)
                  AND (youtube_id IS NULL OR youtube_id = '')
                ORDER BY id ASC
            """)
            for row in cursor.fetchall():
                d = dict(row)
                k = (d.get("source_video_id"), d.get("part_number", 1))
                local_map[k] = d
            conn.close()
        except Exception as e:
            log_warning("DATABASE", f"SQLite pending query note: {e}")

        # 2. Supabase check
        if self.client:
            try:
                res = self.client.table("shorts_metadata")\
                    .select("*")\
                    .or_("is_confirmed_uploaded.eq.false,is_confirmed_uploaded.is.null,youtube_id.is.null,youtube_id.eq.''")\
                    .order("id", desc=False)\
                    .limit(limit or 50)\
                    .execute()
                if res.data:
                    for r in res.data:
                        k = (r.get("source_video_id"), r.get("part_number", 1))
                        # Enrich with local_path from local SQLite
                        if (not r.get("local_path") or not Path(str(r.get("local_path"))).exists()) and k in local_map:
                            r["local_path"] = local_map[k].get("local_path")
                        seen_keys.add(k)
                        pending_list.append(r)
            except Exception as e:
                log_warning("DATABASE", f"Supabase pending query note: {e}")

        # 3. Add any items from SQLite not yet present
        for k, d in local_map.items():
            if k not in seen_keys:
                seen_keys.add(k)
                pending_list.append(d)

        # 4. Resolve local file existence (fallback search in output directory)
        for item in pending_list:
            lp = item.get("local_path")
            if not lp or not Path(lp).exists():
                title = item.get("hook_title", "")
                src_vid = item.get("source_video_id", "")
                part_num = item.get("part_number", 1)
                clean_title = re.sub(r'[^a-zA-Z0-9]', '', title.lower().replace("shorts", ""))
                for f in settings.OUTPUT_DIR.glob("*.mp4"):
                    f_name_lower = f.name.lower()
                    f_stem_clean = re.sub(r'[^a-zA-Z0-9]', '', f.stem.lower())
                    if (src_vid and src_vid.lower() in f_name_lower and f"part{part_num}" in f_name_lower) or \
                       (clean_title and len(clean_title) >= 10 and clean_title[:15] in f_stem_clean):
                        item["local_path"] = str(f)
                        break

        # 5. Sort: items available in Cloud Storage come FIRST, then local files, sorted chronologically (FIFO)
        def file_readiness(item: Dict[str, Any]) -> int:
            surl = item.get("storage_url")
            if surl and not surl.startswith("https://example.com") and "#" not in surl:
                return 0  # CLOUD FIRST: Available in Supabase cloud storage
            lp = item.get("local_path")
            if lp and Path(lp).exists() and Path(lp).stat().st_size > 1024:
                return 1  # LOCAL FALLBACK: Available on local disk
            return 2  # Missing / invalid

        pending_list.sort(key=lambda x: (file_readiness(x), int(x.get("id") or 0)))

        return pending_list[:limit] if limit else pending_list

    def download_from_storage(self, remote_path_or_url: str, target_local_path: str) -> Optional[str]:
        """
        Download a Short video file from Supabase Storage bucket to local disk.
        Cloud-first operation: fetches master video from Supabase Storage.
        If file already exists locally, returns the local path immediately.
        """
        from pathlib import Path
        t_path = Path(target_local_path)
        if t_path.exists() and t_path.is_file() and t_path.stat().st_size > 1024:
            return str(t_path)

        t_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.client:
            log_warning("DATABASE", "Supabase client not initialized to download from storage.")
            return None

        # Extract bucket relative path from URL if needed
        clean_path = remote_path_or_url
        if f"/{self.bucket_name}/" in clean_path:
            clean_path = clean_path.split(f"/{self.bucket_name}/", 1)[1].split("?")[0]
        clean_path = urllib.parse.unquote(clean_path)

        log_info("DATABASE", f"Downloading Short from Supabase Storage: {clean_path} -> {target_local_path}")
        try:
            file_bytes = self.client.storage.from_(self.bucket_name).download(clean_path)
            with open(t_path, "wb") as f:
                f.write(file_bytes)
            log_success("DATABASE", f"Successfully downloaded Short to: {target_local_path}")
            return str(t_path)
        except Exception as e:
            log_warning("DATABASE", f"Supabase storage download failed ({e}). Attempting public HTTP download...")
            try:
                import urllib.request
                urllib.request.urlretrieve(remote_path_or_url, str(t_path))
                if t_path.exists() and t_path.stat().st_size > 1024:
                    return str(t_path)
            except Exception as e2:
                log_error("DATABASE", f"Failed to download video file: {e2}")

        return None

    def mark_short_uploaded(
        self,
        record_id: Any,
        source_video_id: str,
        part_number: int,
        youtube_id: str,
    ) -> None:
        """Mark Short as uploaded across local SQLite, video_series, and Supabase."""
        now_iso = datetime.now(timezone.utc).isoformat()
        # 1. Update SQLite
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE shorts_metadata
                SET youtube_id = ?, is_confirmed_uploaded = 1, confirmed_at = ?
                WHERE id = ? OR (source_video_id = ? AND part_number = ?)
            """, (youtube_id, now_iso, record_id, source_video_id, part_number))
            conn.commit()
            conn.close()
        except Exception as e:
            log_warning("DATABASE", f"SQLite mark uploaded note: {e}")

        # 2. Update video_series table
        self.mark_part_confirmed(source_video_id, part_number, youtube_id)

        # 3. Update Supabase table
        if self.client:
            try:
                self.client.table("shorts_metadata").update({
                    "youtube_id": youtube_id,
                    "is_confirmed_uploaded": True,
                    "confirmed_at": now_iso,
                }).eq("source_video_id", source_video_id).eq("part_number", part_number).execute()
            except Exception as e:
                log_warning("DATABASE", f"Supabase mark uploaded note: {e}")

