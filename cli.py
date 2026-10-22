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
    help="Post-livestream mode: Uses Audio Energy peak detection & multi-clip batch extraction for stream VODs.",
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
    default=False,
    show_default=True,
    help="Burn animated word-by-word karaoke captions onto the Short (default: False, pass --captions to enable).",
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
    help="Extract peak moments as single continuous uninterrupted clips (default behavior).",
)
@click.option(
    "--multi-cut",
    is_flag=True,
    default=False,
    help="Enable experimental multi-cut jump-cuts to skip lulls (default: single continuous clip).",
)
@click.option(
    "--bleep-profanity / --no-bleep-profanity",
    default=True,
    help="Automatically detect English swear words and censor with standard 1000Hz bleeps.",
)
@click.option(
    "--monitor-stream",
    is_flag=True,
    default=False,
    help="Launch autonomous live stream monitoring agent to continuously monitor live broadcast and clip into isolated bucket.",
)
@click.option(
    "--prompt",
    default="",
    type=str,
    help="Custom scene directives or timestamps to pin (e.g. 'anchor at 14:20; find loud screams').",
)
@click.option(
    "--search-engine",
    default="both",
    type=click.Choice(["both", "hybrid", "twelvelabs"], case_sensitive=False),
    help="AI scene search engine: 'both' (Ensemble), 'hybrid' (Option 1), 'twelvelabs' (Option 2).",
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
    multi_cut: bool,
    bleep_profanity: bool,
    monitor_stream: bool,
    prompt: str = "",
    search_engine: str = "both",
) -> None:
    """Run full automated YouTube Shorts pipeline end-to-end."""
    if monitor_stream:
        if not url:
            console.print("[bold red]Error:[/bold red] Missing required option '--url' for live stream monitoring.")
            sys.exit(1)
        from src.services.stream_monitor import StreamMonitorAgent
        agent = StreamMonitorAgent(
            target_url=url,
            chunk_duration=150,
            crop_mode=crop_mode.lower(),
            bleep_profanity=bleep_profanity,
            auto_upload=auto_upload,
            llm_provider=llm_provider.lower(),
            llm_model=llm_model,
            whisper_model=model_size.lower(),
        )
        agent.run_autonomous_monitor()
        return

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
        from upload_pending import run_pending_upload
        run_pending_upload(upload_all=upload_all_pending)
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
        # Accurately distinguish Post-Livestreams (stream VODs) from Standard edited videos:
        # 1. User passed --stream-mode
        # 2. YouTube metadata explicitly says it was a live broadcast (was_live = True)
        # 3. Very long unedited archive (duration >= 2 hours / 7200s)
        is_post_livestream = bool(stream_mode or getattr(video_meta, "was_live", False) or video_meta.duration >= 7200.0)

        effective_clips_count = clips_count if clips_count > 0 else 3
        if video_meta.duration < 90.0:
            effective_clips_count = 1
        elif video_meta.duration < 180.0:
            effective_clips_count = min(2, effective_clips_count)

        peak_window_dur = 150.0 if is_post_livestream else 120.0
        log_stage(2, "Peak Detection & Multi-Part Extraction", f"Waveform Energy Scanning (Target: {effective_clips_count} Peak Parts)")
        peak_detector = PeakDetectorService()
        peaks = peak_detector.find_top_peak_windows(
            Path(video_meta.audio_path),
            video_meta.duration,
            window_duration=peak_window_dur,
            top_k=effective_clips_count,
        )

        if prompt and prompt.strip():
            try:
                from src.services.scene_search import SceneSearchService
                searcher = SceneSearchService()
                custom_scenes = searcher.find_scenes(
                    prompt=prompt.strip(),
                    search_engine=search_engine,
                    video_url_or_path=url or str(video_meta.video_path),
                    total_duration=video_meta.duration,
                    top_k=effective_clips_count,
                )
                if custom_scenes:
                    log_info("ORCHESTRATOR", f"Integrating {len(custom_scenes)} custom directives/pinned scenes into Short candidates.")
                    for cs in custom_scenes:
                        peaks.insert(0, (cs["start"], cs["end"], cs.get("confidence", 1.0)))
            except Exception as e:
                log_warning("ORCHESTRATOR", f"Scene search error: {e}")

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
            part_label = f"Part {part_num}/{total_parts}" if total_parts > 1 else f"Short #{part_num}"
            console.print(f"\n[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]")
            log_info("ORCHESTRATOR", f"Processing {part_label} [{p_start:.1f}s -> {p_end:.1f}s] (Peak Score: {p_score})")
            log_stage(4, f"Clipping Video {part_num}/{total_parts}", f"Processing {part_label} ({idx}/{total_parts} videos done)")

            # Fast targeted transcription of only this candidate window
            window_transcript = transcription_service.transcribe_window(
                audio_path=video_meta.audio_path,
                start_time=p_start,
                end_time=p_end,
                video_id=video_meta.video_id,
            )
            if not window_transcript.segments:
                log_warning("ORCHESTRATOR", f"No dialogue detected in {part_label}. Skipping...")
                log_info("ORCHESTRATOR", f"Progress: {part_num}/{total_parts} videos done ({part_label} skipped)")
                continue

            allow_cuts = bool(multi_cut and not is_post_livestream and not single_clip)
            viral_clip = viral_detector.detect_viral_moment(
                window_transcript,
                allow_multi_cut=allow_cuts,
                allow_extended_duration=is_post_livestream,
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
                is_livestream=is_post_livestream,
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
            if (is_post_livestream or not captions or no_subtitles) and "--captions" not in sys.argv:
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
                st_url = db_service.upload_to_storage(subtitled_path, is_post_livestream=is_post_livestream)

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
            log_success("ORCHESTRATOR", f"✅ Progress: {part_num}/{total_parts} videos done ({part_label} complete)")

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
