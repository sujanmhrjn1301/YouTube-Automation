"""
Standalone Queued Uploader Script.
Runs autonomously: Finds the next stored Short that has not been uploaded yet,
uploads it to YouTube (@eijishorts), confirms the upload, and marks it in Supabase/database.

Usage:
    python upload_pending.py
"""

import sys

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from pathlib import Path
from rich.table import Table

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


def main() -> None:
    print_banner()
    log_stage(6, "Autonomous Pending Uploader", "Selecting next unuploaded Short from Supabase / database")

    db_service = DatabaseService()
    uploader = YouTubeUploaderService()

    # 1. Check daily YouTube API quota
    quota = db_service.get_daily_quota_status()
    if not quota["can_upload"]:
        log_warning(
            "UPLOADER",
            f"⛔ YouTube Upload Quota Limit Reached ({quota['units_used']}/{quota['max_daily_units']} units used today).\n"
            f"   Cannot upload right now to avoid API lockout. Resets at midnight PST.",
        )
        return

    # 2. Query pending Shorts
    pending = db_service.get_pending_shorts(limit=50)
    if not pending:
        console.print("\n[bold green]🎉 No pending Shorts to upload![/bold green] All stored Shorts are already live on YouTube.\n")
        return

    uploaded_one = False
    for item in pending:
        part_num = item.get("part_number", 1)
        total_parts = item.get("total_parts", 1)
        source_vid = item.get("source_video_id", "video")
        title = item.get("hook_title", f"Short Part {part_num}")
        part_str = f"Part {part_num}/{total_parts}" if total_parts > 1 else "Short"

        log_info("UPLOADER", f"Inspecting: [bold yellow]{part_str}[/bold yellow] - [bold white]{title}[/bold white]")

        # 3. Locate or download video file (Cloud-First, Local Fallback)
        video_file_path = None
        storage_url = item.get("storage_url")

        # PRIMARY: Cloud Storage (Supabase)
        if storage_url and not storage_url.startswith("https://example.com") and "#" not in storage_url:
            target_dest = str(settings.OUTPUT_DIR / f"cloud_{source_vid}_part{part_num}.mp4")
            log_info("UPLOADER", f"☁️ [CLOUD-FIRST] Fetching video from Supabase Storage: {storage_url}")
            video_file_path = db_service.download_from_storage(storage_url, target_dest)

        # FALLBACK: Local Disk (if cloud download unavailable or storage_url not present)
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
            log_warning("UPLOADER", f"No video file found on cloud storage or local disk for: {title}. Checking next...")
            continue

        # 4. Construct ViralClip object
        raw_tags = item.get("tags", [])
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
            viral_reasoning=item.get("viral_reasoning") or "Autonomous queue upload",
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
            db_service.mark_short_uploaded(item.get("id"), source_vid, part_num, existing_yt_id)
            console.print(f"[bold yellow]Video is already live on YouTube:[/bold yellow] https://www.youtube.com/shorts/{existing_yt_id}\n")
            continue

        # 6. Perform Upload
        log_info("UPLOADER", f"Uploading to YouTube channel: {settings.YOUTUBE_TARGET_HANDLE}...")
        yt_id = uploader.upload_short(video_path=video_file_path, clip=clip_obj)

        if yt_id:
            yt_url = f"https://www.youtube.com/shorts/{yt_id}"
            db_service.mark_short_uploaded(item.get("id"), source_vid, part_num, yt_id)

            # 7. Rich Summary Table
            pub_table = Table(title="🚀 Upload Completed Successfully", style="bold green", header_style="bold magenta")
            pub_table.add_column("Part", style="bold yellow", justify="center")
            pub_table.add_column("Title", style="bold white")
            pub_table.add_column("Status", justify="center")
            pub_table.add_column("YouTube Link", style="bold underline blue")

            pub_table.add_row(
                part_str,
                title,
                "[bold green]✅ Confirmed Uploaded[/bold green]",
                yt_url,
            )

            console.print()
            console.print(pub_table)
            console.print()
            uploaded_one = True
            break
        else:
            log_error("UPLOADER", f"Upload failed for {title}. Checking next...")

    if not uploaded_one:
        console.print("\n[bold yellow]No valid pending video files ready for upload at this time.[/bold yellow]\n")


if __name__ == "__main__":
    main()
