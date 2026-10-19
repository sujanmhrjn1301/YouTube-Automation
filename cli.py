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
    WhisperModelSize,
)
from src.services.database import DatabaseService
from src.services.ingestion import IngestionService
from src.services.subtitler import SubtitlerService
from src.services.transcription import TranscriptionService
from src.services.video_processor import VideoProcessorService
from src.services.viral_detector import ViralDetectorService
from src.services.youtube_uploader import YouTubeUploaderService


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
) -> None:
    """Run full automated YouTube Shorts pipeline end-to-end."""
    if doctor:
        from src.doctor import run_system_doctor
        run_system_doctor()
        return

    if auth_youtube:
        uploader = YouTubeUploaderService()
        uploader.test_connection()
        return

    if not url:
        console.print("[bold red]Error:[/bold red] Missing required option '--url'.")
        console.print("Run [bold cyan]python cli.py --help[/bold cyan] for usage or [bold cyan]python cli.py --doctor[/bold cyan] for health check.")
        sys.exit(1)

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
        # STAGE 2: Word-Level Transcription
        # ─────────────────────────────────────────────────────────────
        transcription_service = TranscriptionService(model_size=model_size.lower())
        transcription = transcription_service.transcribe(video_meta.audio_path, video_id=video_meta.video_id)

        if not transcription.segments:
            raise RuntimeError("Transcription returned 0 segments. Cannot analyze video.")

        # ─────────────────────────────────────────────────────────────
        # STAGE 3: Viral Moment Detection & Metadata Generation
        # ─────────────────────────────────────────────────────────────
        viral_detector = ViralDetectorService(provider=llm_provider.lower(), model=llm_model)
        viral_clip = viral_detector.detect_viral_moment(transcription)
        result.selected_clip = viral_clip

        # ─────────────────────────────────────────────────────────────
        # STAGE 4: Reframing & Video Processing (9:16 Crop)
        # ─────────────────────────────────────────────────────────────
        video_processor = VideoProcessorService(crop_mode=crop_mode.lower())
        cropped_path = video_processor.process_clip(
            input_video_path=video_meta.video_path,
            clip=viral_clip,
            video_id=video_meta.video_id,
        )
        result.cropped_video_path = cropped_path

        # ─────────────────────────────────────────────────────────────
        # STAGE 5: Subtitling & Karaoke Captions
        # ─────────────────────────────────────────────────────────────
        subtitler = SubtitlerService()
        subtitled_path = subtitler.burn_subtitles(
            video_path=cropped_path,
            transcription=transcription,
            clip=viral_clip,
            video_id=video_meta.video_id,
        )
        result.subtitled_video_path = subtitled_path

        # ─────────────────────────────────────────────────────────────
        # STAGE 6: YouTube OAuth Upload (Optional / Configured)
        # ─────────────────────────────────────────────────────────────
        if auto_upload:
            uploader = YouTubeUploaderService()
            youtube_id = uploader.upload_short(
                video_path=subtitled_path,
                clip=viral_clip,
                privacy_status="public",
            )
            if youtube_id:
                result.youtube_video_id = youtube_id
                result.youtube_video_url = f"https://www.youtube.com/shorts/{youtube_id}"
        else:
            log_info(
                "ORCHESTRATOR",
                f"Auto-upload flag not set. Short is saved locally for review: {subtitled_path}",
            )

        # ─────────────────────────────────────────────────────────────
        # STAGE 7: Storage & Metadata Persistence
        # ─────────────────────────────────────────────────────────────
        log_stage(7, "Storage & Metadata Persistence", "Local SQLite & Supabase Sync")
        db_service = DatabaseService()
        storage_url = None
        if db_service.client:
            storage_url = db_service.upload_to_storage(subtitled_path)
            result.supabase_storage_url = storage_url

        record_id = db_service.save_clip_record(
            source_url=url,
            video_meta=video_meta,
            clip=viral_clip,
            storage_url=storage_url,
            local_path=subtitled_path,
            youtube_id=result.youtube_video_id,
        )
        result.supabase_record_id = record_id

        result.success = True
        total_elapsed = time.time() - start_total_time

        # Render Final Success Table
        log_table("🎉 Pipeline Execution Completed Successfully", {
            "Total Pipeline Runtime": f"{total_elapsed:.2f} seconds",
            "Rendered Video Path": str(result.subtitled_video_path),
            "YouTube Shorts URL": result.youtube_video_url or "Not uploaded (Local review)",
            "Supabase Storage URL": result.supabase_storage_url or "Local only",
            "Supabase Record ID": result.supabase_record_id or "N/A",
        })

    except Exception as exc:
        log_error("PIPELINE_ERROR", f"Pipeline execution failed: {exc}")
        result.error_message = str(exc)
        sys.exit(1)


if __name__ == "__main__":
    run_pipeline()
