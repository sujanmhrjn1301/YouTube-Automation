"""
Main CLI Application and Pipeline Orchestrator.
Automates extraction, reframing, subtitling, and uploading of viral segments from YouTube videos.
"""

import sys
import time

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from typing import Optional
import click

from src.config import settings
from src.console import (
    print_banner,
    log_stage,
    log_info,
    log_success,
    log_warning,
    log_error,
    log_table,
    console,
)
from src.models import (
    CropMode,
    LLMProvider,
    PipelineRunResult,
    ViralClip,
    WhisperModelSize,
)
from pathlib import Path
from src.services.database import DatabaseService
from src.services.ingestion import IngestionService
from src.services.peak_detector import PeakDetectorService
from src.services.subtitler import SubtitlerService
from src.services.transcription import TranscriptionService
from src.services.video_processor import VideoProcessorService
from src.services.viral_detector import ViralDetectorService
from src.services.youtube_uploader import YouTubeUploaderService
from src.utils import generate_short_filename, slice_transcription


@click.command(help="Automate extraction, reframing, subtitling, and uploading of viral YouTube Shorts.")
@click.option(
    "--url",
    default=None,
    type=str,
    help="YouTube source video URL.",
)
@click.option(
    "--doctor",
    is_flag=True,
    default=False,
    help="Run system and API dependency health check.",
)
@click.option(
    "--model-size",
    default="base",
    type=click.Choice(["tiny", "base", "small", "medium", "large-v3"], case_sensitive=False),
    show_default=True,
    help="Whisper model size for transcription.",
)
@click.option(
    "--llm-provider",
    default="openrouter",
    type=click.Choice(["openrouter", "openai", "gemini"], case_sensitive=False),
    show_default=True,
    help="LLM provider for viral moment detection.",
)
@click.option(
    "--llm-model",
    default=None,
    type=str,
    help="Specific model to request from provider (e.g. 'openai/gpt-4o-mini', 'meta-llama/llama-3.3-70b-instruct').",
)
@click.option(
    "--crop-mode",
    default="blurred_background",
    type=click.Choice(["face_tracking", "blurred_background", "center_crop"], case_sensitive=False),
    show_default=True,
    help="Reframing strategy for vertical 9:16 Shorts.",
)
@click.option(
    "--cookies-from-browser",
    default=None,
    type=click.Choice(["chrome", "firefox", "edge", "brave", "opera", "safari"], case_sensitive=False),
    help="Browser to import YouTube cookies from to bypass bot checks (e.g. 'firefox', 'chrome').",
)
@click.option(
    "--auto-upload",
    is_flag=True,
    default=False,
    help="Trigger YouTube OAuth upload immediately (default: save locally for review).",
)
@click.option(
    "--auth-youtube",
    is_flag=True,
    default=False,
    help="Authorize and link YouTube account via OAuth without processing a video.",
)
@click.option(
    "--stream-mode",
    is_flag=True,
    default=False,
    help="Livestream mode: Uses Audio Energy peak detection & multi-clip batch extraction.",
)
@click.option(
    "--clips-count",
    default=3,
    type=int,
    show_default=True,
    help="Number of viral Shorts / peak parts to extract.",
)
@click.option(
    "--cleanup-raw/--no-cleanup-raw",
    default=True,
    show_default=True,
    help="Automatically delete raw downloaded video & audio once all Shorts are published/saved.",
)
@click.option(
    "--keep-raw",
    is_flag=True,
    default=False,
    help="Keep raw downloaded video & audio on disk (overrides default auto-cleanup).",
)
@click.option(
    "--clean-cache",
    is_flag=True,
    default=False,
    help="Purge cached raw videos, intermediate audio, and clips to free disk space.",
)
@click.option(
    "--upload-pending",
    is_flag=True,
    default=False,
    help="Automatically pick the next unuploaded Short from Supabase/storage and upload it to YouTube.",
)
@click.option(
    "--upload-all-pending",
    is_flag=True,
    default=False,
    help="Upload all pending unuploaded Shorts sequentially, respecting daily API quota limits.",
)
@click.option(
    "--upload-all-parts",
    is_flag=True,
    default=False,
    help="When used with --auto-upload, uploads all generated series parts at once (default: upload only Part 1).",
)
@click.option(
    "--captions/--no-captions",
    default=True,
    show_default=True,
    help="Burn animated word-by-word karaoke captions onto the Short (pass --no-captions to disable).",
)
@click.option(
    "--no-subtitles",
    is_flag=True,
    default=False,
    help="Alias for --no-captions: skip burning subtitles onto the video.",
)
@click.option(
    "--single-clip",
    is_flag=True,
    default=False,
    help="Extract peak moments as single continuous uninterrupted clips without multi-cut jump-cuts.",
)
@click.option(
    "--bleep-profanity / --no-bleep-profanity",
    default=True,
    help="Automatically detect English swear words and censor with standard 1000Hz bleeps.",
)
def run_pipeline(
    url: Optional[str],
    doctor: bool,
    model_size: str,
    llm_provider: str,
    llm_model: Optional[str],
    crop_mode: str,
    cookies_from_browser: Optional[str],
    auto_upload: bool,
    auth_youtube: bool,
    stream_mode: bool,
    clips_count: int,
    cleanup_raw: bool,
    keep_raw: bool,
    clean_cache: bool,
    upload_pending: bool,
    upload_all_pending: bool,
    upload_all_parts: bool,
    captions: bool,
    no_subtitles: bool,
    single_clip: bool,
    bleep_profanity: bool,
) -> None:
    """Run full automated YouTube Shorts pipeline end-to-end."""
    if doctor:
        from src.doctor import run_system_doctor
        run_system_doctor()
        return

    if clean_cache:
        from src.utils import clean_cache as do_clean_cache
        from rich.table import Table
        res = do_clean_cache()
        table = Table(title="🧹 Cache & Disk Cleanup Summary", style="bold green")
        table.add_column("Category", style="bold white")
        table.add_column("Files Removed", justify="center")
        table.add_column("Space Freed", justify="right", style="bold cyan")
        for cat, data in res["categories"].items():
            table.add_row(cat, str(data["files"]), f"{data['mb']:.1f} MB")
        console.print()
        console.print(table)
        console.print(f"\n[bold green]✨ Cleanup Complete![/bold green] Total Space Freed: [bold cyan]{res['mb_freed']:.1f} MB[/bold cyan] ({res['gb_freed']:.2f} GB)")
        console.print("[dim white]Note: Final rendered Shorts and database records in output/ were preserved.[/dim white]\n")
        return

    if auth_youtube:
        uploader = YouTubeUploaderService()
        uploader.test_connection()
        return

    if upload_pending or upload_all_pending:
        from rich.table import Table

        print_banner()
        log_stage(6, "Pending Shorts Auto-Uploader", "Selecting unuploaded video from Supabase / database")

        db_service = DatabaseService()
        uploader = YouTubeUploaderService()

        # Check quota first
        quota = db_service.get_daily_quota_status()
        if not quota["can_upload"]:
            log_warning(
                "ORCHESTRATOR",
                f"⛔ YouTube Upload Quota Limit Reached ({quota['units_used']}/{quota['max_daily_units']} units used today).\n"
                f"   Cannot upload pending Shorts right now. Try again tomorrow after midnight PST.",
            )
            return

        # Fetch pending Shorts
        limit = 10 if upload_all_pending else 1
        pending = db_service.get_pending_shorts(limit=limit)

        if not pending:
            console.print("\n[bold green]🎉 No pending Shorts to upload![/bold green] All Shorts in Supabase & local DB are already uploaded to YouTube.\n")
            return

        log_info("ORCHESTRATOR", f"Found {len(pending)} pending Short(s) queued for upload.")

        uploaded_records = []
        for idx, item in enumerate(pending):
            # Check quota before each item
            curr_quota = db_service.get_daily_quota_status()
            if not curr_quota["can_upload"]:
                log_warning("ORCHESTRATOR", "Daily YouTube upload quota reached. Halting remaining pending uploads.")
                break

            part_num = item.get("part_number", 1)
            total_parts = item.get("total_parts", 1)
            source_vid = item.get("source_video_id", "video")
            title = item.get("hook_title", f"Short Part {part_num}")
            part_str = f"Part {part_num}/{total_parts}" if total_parts > 1 else "Short"

            log_info("ORCHESTRATOR", f"\n[bold cyan]Uploading [{idx+1}/{len(pending)}]: {part_str} - {title}[/bold cyan]")

            # Resolve video file path (Cloud-First, Local Fallback)
            video_file_path = None
            storage_url = item.get("storage_url")

            # PRIMARY: Cloud Storage (Supabase)
            if storage_url and not storage_url.startswith("https://example.com") and "#" not in storage_url:
                target_dest = str(settings.OUTPUT_DIR / f"cloud_{source_vid}_part{part_num}.mp4")
                log_info("ORCHESTRATOR", f"☁️ [CLOUD-FIRST] Fetching video from Supabase Storage: {storage_url}")
                video_file_path = db_service.download_from_storage(storage_url, target_dest)

            # FALLBACK: Local Disk (if cloud download unavailable)
            if not video_file_path or not Path(video_file_path).exists() or Path(video_file_path).stat().st_size <= 1024:
                loc_path = item.get("local_path")
                if loc_path and Path(loc_path).exists() and Path(loc_path).stat().st_size > 1024:
                    video_file_path = str(loc_path)
                    log_info("ORCHESTRATOR", f"💾 [LOCAL FALLBACK] Using existing local video file: {video_file_path}")
                else:
                    import re
                    clean_title = re.sub(r'[^a-zA-Z0-9]', '', title.lower().replace("shorts", ""))
                    for f in settings.OUTPUT_DIR.glob("*.mp4"):
                        f_name_lower = f.name.lower()
                        f_stem_clean = re.sub(r'[^a-zA-Z0-9]', '', f.stem.lower())
                        if (source_vid and source_vid.lower() in f_name_lower and f"part{part_num}" in f_name_lower) or \
                           (clean_title and len(clean_title) >= 10 and clean_title[:15] in f_stem_clean):
                            video_file_path = str(f)
                            log_info("ORCHESTRATOR", f"💾 [LOCAL FALLBACK] Found matching video file in output: {video_file_path}")
                            break

            if not video_file_path or not Path(video_file_path).exists():
                log_error("ORCHESTRATOR", f"Could not find video file on cloud storage or local disk for {title}. Skipping.")
                continue

            # Parse tags
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
                viral_reasoning=item.get("viral_reasoning") or "Pending upload",
                description=item.get("description") or f"{title} #Shorts",
                tags=tags_list,
            )

            # Avoid duplicates
            existing_yt_id = db_service.check_existing_upload(
                source_video_id=source_vid,
                start_time=clip_obj.start_time,
                end_time=clip_obj.end_time,
                title=clip_obj.hook_title,
            )
            if existing_yt_id:
                log_warning("ORCHESTRATOR", f"⏭️ Duplicate detected! Already uploaded to YouTube: {existing_yt_id}")
                db_service.mark_short_uploaded(item.get("id"), source_vid, part_num, existing_yt_id)
                uploaded_records.append({
                    "part": part_str,
                    "title": title,
                    "status": "⏭️ Duplicate (Live)",
                    "youtube": f"https://www.youtube.com/shorts/{existing_yt_id}",
                })
                continue

            # Perform YouTube upload
            yt_id = uploader.upload_short(video_path=video_file_path, clip=clip_obj)
            if yt_id:
                yt_url = f"https://www.youtube.com/shorts/{yt_id}"
                db_service.mark_short_uploaded(item.get("id"), source_vid, part_num, yt_id)
                uploaded_records.append({
                    "part": part_str,
                    "title": title,
                    "status": "[bold green]✅ Confirmed Uploaded[/bold green]",
                    "youtube": yt_url,
                })
                log_success("ORCHESTRATOR", f"Successfully published {part_str} -> {yt_url}")
            else:
                uploaded_records.append({
                    "part": part_str,
                    "title": title,
                    "status": "[bold red]❌ Failed[/bold red]",
                    "youtube": "N/A",
                })

            if not upload_all_pending:
                break

        # Summary Table
        pub_table = Table(title="🚀 Standalone Upload Summary", style="bold cyan", header_style="bold magenta")
        pub_table.add_column("Part", style="bold yellow", justify="center")
        pub_table.add_column("Title", style="bold white")
        pub_table.add_column("Status", justify="center")
        pub_table.add_column("YouTube Link", style="bold underline blue")

        for r in uploaded_records:
            pub_table.add_row(r["part"], r["title"], r["status"], r["youtube"])

        console.print()
        console.print(pub_table)
        console.print()
        return

    if not url:
        console.print("[bold red]Error:[/bold red] Missing required option '--url'.")
        console.print("Run [bold cyan]python cli.py --help[/bold cyan] for usage or [bold cyan]python cli.py --doctor[/bold cyan] for health check.")
        sys.exit(1)

    # ─────────────────────────────────────────────────────────────
    # Automatic 14-Day Rolling Cache Cleanup (Background Garbage Collection)
    # ─────────────────────────────────────────────────────────────
    from src.utils import auto_cleanup_expired_cache
    auto_clean_res = auto_cleanup_expired_cache(max_age_days=14)
    if auto_clean_res["files_removed"] > 0:
        log_info(
            "ORCHESTRATOR",
            f"🧹 [14-DAY AUTO CLEANUP] Automatically purged {auto_clean_res['files_removed']} expired cache files (>14 days old). Freed {auto_clean_res['mb_freed']:.1f} MB!",
        )

    print_banner()

    start_total_time = time.time()
    effective_model = llm_model or (settings.OPENROUTER_MODEL if llm_provider == "openrouter" else "default")

    # Display configuration table
    log_table("Active Pipeline Configuration", {
        "Source URL": url,
        "Whisper Model": model_size.lower(),
        "LLM Provider": f"{llm_provider.upper()} ({effective_model})",
        "Crop Strategy": crop_mode.lower(),
        "Auto-Upload": "ENABLED" if auto_upload else "DISABLED (Save Locally)",
        "FFmpeg Executable": settings.FFMPEG_PATH,
        "Supabase Storage": settings.SUPABASE_SHORTS_BUCKET,
    })

    result = PipelineRunResult(success=False, source_url=url)

    try:
        # ─────────────────────────────────────────────────────────────
        # STAGE 1: Video & Audio Ingestion
        # ─────────────────────────────────────────────────────────────
        ingestion_service = IngestionService(cookies_from_browser=cookies_from_browser)
        video_meta = ingestion_service.ingest(url)
        result.video_metadata = video_meta

        # ─────────────────────────────────────────────────────────────
        # STAGE 2: Multi-Part Peak Detection & Targeted Extraction
        # ─────────────────────────────────────────────────────────────
        # Accurately distinguish Livestreams from Standard edited videos:
        # 1. User passed --stream-mode
        # 2. YouTube metadata explicitly says it was a live broadcast (was_live = True)
        # 3. Very long unedited archive (duration >= 2 hours / 7200s)
        is_stream_video = bool(stream_mode or getattr(video_meta, "was_live", False) or video_meta.duration >= 7200.0)

        effective_clips_count = clips_count if clips_count > 0 else 3
        if video_meta.duration < 90.0:
            effective_clips_count = 1
        elif video_meta.duration < 180.0:
            effective_clips_count = min(2, effective_clips_count)

        peak_window_dur = 150.0 if is_stream_video else 120.0
        log_stage(2, "Peak Detection & Multi-Part Extraction", f"Waveform Energy Scanning (Target: {effective_clips_count} Peak Parts)")
        peak_detector = PeakDetectorService()
        peaks = peak_detector.find_top_peak_windows(
            Path(video_meta.audio_path),
            video_meta.duration,
            window_duration=peak_window_dur,
            top_k=effective_clips_count,
        )

        total_parts = len(peaks)
        log_info("ORCHESTRATOR", f"Extracted {total_parts} chronological peak moments for multi-part Short series.")

        transcription_service = TranscriptionService(model_size=model_size.lower())
        viral_detector = ViralDetectorService(provider=llm_provider.lower(), model=llm_model)
        video_processor = VideoProcessorService(crop_mode=crop_mode.lower())
        subtitler = SubtitlerService()
        db_service = DatabaseService()
        uploader = YouTubeUploaderService() if auto_upload else None

        series_results = []
        uploaded_in_this_run = 0

        for idx, (p_start, p_end, p_score) in enumerate(peaks):
            part_num = idx + 1
            part_label = f"Part {part_num}/{total_parts}" if total_parts > 1 else "Short"
            console.print(f"\n[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]")
            log_info("ORCHESTRATOR", f"Processing {part_label} [{p_start:.1f}s -> {p_end:.1f}s] (Peak Score: {p_score})")

            # Fast targeted transcription of only this candidate window
            window_transcript = transcription_service.transcribe_window(
                audio_path=video_meta.audio_path,
                start_time=p_start,
                end_time=p_end,
                video_id=video_meta.video_id,
            )
            if not window_transcript.segments:
                log_warning("ORCHESTRATOR", f"No dialogue detected in {part_label}. Skipping...")
                continue

            allow_cuts = not (is_stream_video or single_clip)
            viral_clip = viral_detector.detect_viral_moment(
                window_transcript,
                allow_multi_cut=allow_cuts,
                allow_extended_duration=is_stream_video,
            )

            # Auto-label title with [Part X] if multi-part series
            if total_parts > 1:
                clean_t = viral_clip.hook_title.replace("#Shorts", "").replace("#shorts", "").strip()
                if f"part {part_num}" not in clean_t.lower() and f"part-{part_num}" not in clean_t.lower():
                    clean_t = f"{clean_t} [Part {part_num}]"
                viral_clip.hook_title = f"{clean_t} #Shorts"

            descriptive_filename = generate_short_filename(
                title=viral_clip.hook_title,
                video_id=video_meta.video_id,
                duration=viral_clip.total_duration,
                clip_index=part_num,
                is_livestream=is_stream_video,
            )

            from src.services.profanity_filter import ProfanityFilterService
            profanity_service = ProfanityFilterService()
            bleep_intervals = []
            if bleep_profanity:
                bleep_intervals = profanity_service.find_profanity_intervals(
                    window_transcript,
                    viral_clip.start_time,
                    viral_clip.end_time,
                )
                if bleep_intervals:
                    words_found = [b[2] for b in bleep_intervals]
                    log_info(
                        "ORCHESTRATOR",
                        f"🤫 [PROFANITY CENSORED] Detected {len(bleep_intervals)} swear word(s) ({', '.join(words_found)}). Applying TV/YouTube 1000Hz censor bleeps...",
                    )

            cropped_path = video_processor.process_clip(
                input_video_path=video_meta.video_path,
                clip=viral_clip,
                video_id=f"{video_meta.video_id}_part{part_num}",
                bleep_intervals=bleep_intervals,
            )

            # Determine whether captions should be burned
            effective_captions = captions and not no_subtitles
            if (is_stream_video or not captions or no_subtitles) and "--captions" not in sys.argv:
                # Streams and long VODs default to clean video without captions
                effective_captions = False

            if not effective_captions:
                log_info("ORCHESTRATOR", f"⏩ [CLEAN STREAM] Skipping subtitle burn for {part_label} (single continuous clean clip).")
                import shutil
                final_video_path = str(settings.OUTPUT_DIR / descriptive_filename)
                shutil.copy2(cropped_path, final_video_path)
                subtitled_path = final_video_path
            else:
                subtitled_path = subtitler.burn_subtitles(
                    video_path=cropped_path,
                    transcription=window_transcript,
                    clip=viral_clip,
                    video_id=f"{video_meta.video_id}_part{part_num}",
                    output_filename=descriptive_filename,
                )

            yt_id = None
            yt_url = None
            is_confirmed = False
            status_text = "💾 Saved Locally"

            if auto_upload:
                if uploaded_in_this_run >= 1 and not upload_all_parts:
                    log_info(
                        "ORCHESTRATOR",
                        f"💾 [SAVED TO QUEUE] {part_label} saved to Supabase & disk for scheduled upload.\n"
                        f"    (Only Part 1 is auto-uploaded now to protect your channel from spam).",
                    )
                    status_text = "💾 Saved (Pending Queue)"
                else:
                    existing_yt_id = db_service.check_existing_upload(
                        source_video_id=video_meta.video_id,
                        start_time=viral_clip.start_time,
                        end_time=viral_clip.end_time,
                        title=viral_clip.hook_title,
                    )
                    if existing_yt_id:
                        log_warning(
                            "ORCHESTRATOR",
                            f"⏭️  [DUPLICATE AVOIDED] {part_label} was already uploaded to YouTube!\n"
                            f"    YouTube ID: {existing_yt_id}\n"
                            f"    URL: https://www.youtube.com/shorts/{existing_yt_id}\n"
                            f"    Skipping upload to avoid duplicate content on your channel.",
                        )
                        yt_id = existing_yt_id
                        yt_url = f"https://www.youtube.com/shorts/{yt_id}"
                        status_text = "⏭️ Duplicate (Live)"
                        is_confirmed = True
                        uploaded_in_this_run += 1
                    elif uploader:
                        yt_id = uploader.upload_short(video_path=subtitled_path, clip=viral_clip)
                        if yt_id:
                            yt_url = f"https://www.youtube.com/shorts/{yt_id}"
                            status_text = "✅ Confirmed Uploaded"
                            is_confirmed = True
                            uploaded_in_this_run += 1
                            db_service.mark_part_confirmed(video_meta.video_id, part_num, yt_id)
                        else:
                            status_text = "⚠️ Upload Skipped / Failed"

            st_url = None
            if db_service.client:
                st_url = db_service.upload_to_storage(subtitled_path, is_livestream=is_stream_video)

            db_service.save_clip_record(
                source_url=url,
                video_meta=video_meta,
                clip=viral_clip,
                storage_url=st_url,
                local_path=subtitled_path,
                youtube_id=yt_id,
                part_number=part_num,
                total_parts=total_parts,
                is_confirmed=is_confirmed,
            )

            series_results.append({
                "part": f"Part {part_num}/{total_parts}" if total_parts > 1 else "Short #1",
                "title": viral_clip.hook_title,
                "duration": f"{viral_clip.total_duration:.1f}s",
                "status": status_text,
                "file": descriptive_filename,
                "youtube": yt_url or "Saved locally",
                "supabase": st_url or "Local only",
            })

        total_elapsed = time.time() - start_total_time
        result.success = True

        # Render rich multi-part series tracking table
        from rich.table import Table
        series_table = Table(
            title=f"🎬 Multi-Part Series Tracking Table: {video_meta.title[:65]}",
            style="bold cyan",
            header_style="bold magenta",
        )
        series_table.add_column("Part", style="bold yellow", justify="center")
        series_table.add_column("Short Hook Title", style="bold white")
        series_table.add_column("Duration", justify="center", style="dim white")
        series_table.add_column("Upload Status", justify="center")
        series_table.add_column("YouTube Shorts Link", style="bold underline blue")

        for s in series_results:
            status_style = "[bold green]✅ Confirmed Uploaded[/bold green]" if "Confirmed" in s["status"] else (
                "[bold yellow]⏭️ Duplicate (Live)[/bold yellow]" if "Duplicate" in s["status"] else f"[dim]{s['status']}[/dim]"
            )
            series_table.add_row(
                s["part"],
                s["title"],
                s["duration"],
                status_style,
                s["youtube"],
            )

        console.print()
        console.print(series_table)
        console.print()

        summary_dict = {
            "Total Pipeline Runtime": f"{total_elapsed:.2f} seconds",
            "Extracted Shorts": f"{len(series_results)} Parts",
            "Video Title": video_meta.title,
            "Video ID": video_meta.video_id,
        }
        for i, s in enumerate(series_results):
            summary_dict[f"Part {i + 1}"] = f"{s['title']} ({s['duration']})\nStatus: {s['status']}\nURL: {s['youtube']}"
        log_table("🎉 Multi-Part Series Execution Completed Successfully", summary_dict)

        # Auto-clean heavy raw source video and audio unless --keep-raw is set
        if cleanup_raw and not keep_raw:
            from src.utils import cleanup_raw_source
            mb_freed = cleanup_raw_source(video_meta.video_path, video_meta.audio_path)
            if mb_freed > 0:
                log_success("ORCHESTRATOR", f"🧹 [AUTO CLEANUP] Cleaned up heavy raw source files. Freed {mb_freed:.1f} MB disk space!")

    except Exception as exc:
        log_error("PIPELINE_ERROR", f"Pipeline execution failed: {exc}")
        result.error_message = str(exc)
        sys.exit(1)


if __name__ == "__main__":
    run_pipeline()
