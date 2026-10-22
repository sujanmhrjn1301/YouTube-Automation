"""
Standalone single-item uploader for Shorts Studio Dashboard.
Uploads a specific Short by its database ID to YouTube (@eijishorts),
marks it as uploaded in Supabase and SQLite, and prints clean progress.

Usage:
    python dashboard/upload_single.py --id <short_id>
"""

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Optional

# Fix Windows console encoding if needed
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import settings
from src.console import (
    print_banner,
    log_stage,
    log_info,
    log_success,
    log_warning,
    log_error,
    console,
)
from src.models import ViralClip
from src.services.database import DatabaseService
from src.services.youtube_uploader import YouTubeUploaderService


def upload_single_short(short_id: int, publish_at: Optional[str] = None) -> bool:
    print_banner()
    schedule_text = f" (Scheduled: {publish_at})" if publish_at else ""
    log_stage(6, "Targeted Uploader", f"Publishing Short #{short_id} to YouTube{schedule_text}")

    db_service = DatabaseService()
    uploader = YouTubeUploaderService()

    # 1. Check daily YouTube upload progress (allow beyond 6, baseline target is 6)
    quota = db_service.get_daily_quota_status()
    uploads_today = quota.get("uploads_today", 0)
    if uploads_today >= 6:
        log_info(
            "UPLOADER",
            f"Daily baseline reached ({uploads_today}/6+ uploads completed today). Proceeding with upload...",
        )
    else:
        log_info(
            "UPLOADER",
            f"Daily upload progress: {uploads_today}/6 uploads completed today.",
        )

    # 2. Query target record: Supabase-First, Local Fallback
    item = None
    if db_service.client:
        try:
            res = db_service.client.table("shorts_metadata").select("*").eq("id", short_id).execute()
            if res.data and len(res.data) > 0:
                item = res.data[0]
                log_info("UPLOADER", f"☁️ [SUPABASE] Found Short #{short_id} in Supabase cloud database")
        except Exception as e:
            log_warning("UPLOADER", f"Supabase query note: {e}")

    if not item:
        conn = db_service._get_connection()
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM shorts_metadata WHERE id = ?", (short_id,)).fetchone()
        conn.close()
        if row:
            item = dict(row)
            log_info("UPLOADER", f"💾 [LOCAL DB] Found Short #{short_id} in local database")

    if not item:
        log_error("UPLOADER", f"Short #{short_id} not found in Supabase or local database.")
        return False

    source_vid = item.get("source_video_id") or "video"
    part_num = item.get("part_number") or 1
    total_parts = item.get("total_parts") or 1
    title = item.get("hook_title") or f"Short Part {part_num}"
    part_str = f"Part {part_num}/{total_parts}" if total_parts > 1 else "Short"

    log_info("UPLOADER", f"Preparing: [bold yellow]{part_str}[/bold yellow] - [bold white]{title}[/bold white]")

    # 3. Locate or download video file (Cloud-First from Supabase, Local Fallback)
    video_file_path = None
    storage_url = item.get("storage_url")

    # PRIMARY: Cloud Storage (Supabase)
    if storage_url and not storage_url.startswith("https://example.com") and "#" not in storage_url:
        target_dest = str(settings.OUTPUT_DIR / f"cloud_{source_vid}_part{part_num}.mp4")
        log_info("UPLOADER", f"☁️ [CLOUD-FIRST] Fetching video from Supabase Storage: {storage_url}")
        video_file_path = db_service.download_from_storage(storage_url, target_dest)

    # FALLBACK: Local Disk
    if not video_file_path or not Path(video_file_path).exists() or Path(video_file_path).stat().st_size <= 1024:
        loc_path = item.get("local_path")
        if loc_path and Path(loc_path).exists() and Path(loc_path).stat().st_size > 1024:
            video_file_path = str(loc_path)
            log_info("UPLOADER", f"💾 [LOCAL FALLBACK] Using local disk file: {video_file_path}")
        else:
            import re
            clean_title = re.sub(r'[^a-zA-Z0-9]', '', title.lower().replace("shorts", ""))
            for f in settings.OUTPUT_DIR.glob("*.mp4"):
                f_name_lower = f.name.lower()
                f_stem_clean = re.sub(r'[^a-zA-Z0-9]', '', f.stem.lower())
                if (source_vid and source_vid.lower() in f_name_lower and f"part{part_num}" in f_name_lower) or \
                   (clean_title and len(clean_title) >= 10 and clean_title[:15] in f_stem_clean):
                    video_file_path = str(f)
                    log_info("UPLOADER", f"💾 [LOCAL FALLBACK] Found matching video file in output: {video_file_path}")
                    break

    if not video_file_path or not Path(video_file_path).exists():
        log_error("UPLOADER", f"No video file found on cloud storage or local disk for Short #{short_id}.")
        return False

    # 4. Construct ViralClip object
    raw_tags = item.get("tags") or []
    if isinstance(raw_tags, str):
        tags_list = [t.strip() for t in raw_tags.split(",") if t.strip()]
    elif isinstance(raw_tags, list):
        tags_list = raw_tags
    else:
        tags_list = ["Shorts", "Viral"]

    clip_obj = ViralClip(
        start_time=float(item.get("start_time") or 0.0),
        end_time=float(item.get("end_time") or 50.0),
        hook_title=title,
        hook_score=float(item.get("hook_score") or 90.0),
        viral_reasoning=item.get("viral_reasoning") or "Direct dashboard single upload",
        description=item.get("description") or f"{title} #Shorts",
        tags=tags_list,
    )

    # 5. Check duplicate upload
    existing_yt_id = db_service.check_existing_upload(
        source_video_id=source_vid,
        start_time=clip_obj.start_time,
        end_time=clip_obj.end_time,
        title=clip_obj.hook_title,
    )
    if existing_yt_id:
        log_warning("UPLOADER", f"⏭️ Duplicate detected! Already uploaded to YouTube: {existing_yt_id}")
        db_service.mark_short_uploaded(short_id, source_vid, part_num, existing_yt_id)
        if db_service.client:
            try:
                from datetime import datetime, timezone
                db_service.client.table("shorts_metadata").update({
                    "is_confirmed_uploaded": True,
                    "confirmed_at": datetime.now(timezone.utc).isoformat(),
                    "youtube_id": existing_yt_id
                }).eq("id", short_id).execute()
            except Exception:
                pass
        log_success("UPLOADER", f"[OK] Marked existing Short #{short_id} as uploaded: https://www.youtube.com/shorts/{existing_yt_id}")
        return True

    # 6. Perform Upload
    schedule_note = f" (Scheduled: {publish_at})" if publish_at else ""
    log_info("UPLOADER", f"Uploading to YouTube channel: {settings.YOUTUBE_TARGET_HANDLE}{schedule_note}...")
    yt_id = uploader.upload_short(video_path=video_file_path, clip=clip_obj, publish_at=publish_at)

    if yt_id:
        yt_url = f"https://www.youtube.com/shorts/{yt_id}"
        db_service.mark_short_uploaded(short_id, source_vid, part_num, yt_id, scheduled_at=publish_at)
        if db_service.client:
            try:
                from datetime import datetime, timezone
                update_payload = {
                    "is_confirmed_uploaded": True,
                    "confirmed_at": datetime.now(timezone.utc).isoformat(),
                    "youtube_id": yt_id
                }
                if publish_at:
                    try:
                        db_service.client.table("shorts_metadata").update({**update_payload, "scheduled_publish_at": publish_at}).eq("id", short_id).execute()
                    except Exception:
                        db_service.client.table("shorts_metadata").update(update_payload).eq("id", short_id).execute()
                else:
                    db_service.client.table("shorts_metadata").update(update_payload).eq("id", short_id).execute()
            except Exception:
                pass
        db_service.record_quota_usage(units=1600, is_upload=True)
        if publish_at:
            log_success("UPLOADER", f"[OK] Successfully scheduled Short #{short_id} on YouTube! Scheduled for release: {publish_at}")
        else:
            log_success("UPLOADER", f"[OK] Successfully published Short #{short_id} -> {yt_url}")
        return True
    else:
        log_error("UPLOADER", f"[X] Upload failed for Short #{short_id}.")
        return False


def main():
    parser = argparse.ArgumentParser(description="Upload single Short by ID")
    parser.add_argument("--id", type=int, required=True, help="Database ID of the short to upload")
    parser.add_argument("--publish-at", type=str, default=None, help="Scheduled release date/time in ISO-8601 format")
    args = parser.parse_args()

    success = upload_single_short(args.id, publish_at=args.publish_at)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
