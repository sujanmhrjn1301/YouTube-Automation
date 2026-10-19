"""
Stage 1: Video and Audio Ingestion Service using yt-dlp and FFmpeg.
Downloads highest quality video (up to 1080p) and extracts 16kHz mono WAV audio.
"""

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional
import yt_dlp

from src.config import settings
from src.console import (
    log_stage,
    log_info,
    log_warning,
    log_success,
    log_error,
    log_table,
    create_download_progress_bar,
    console,
)
from src.models import VideoMetadata


class IngestionService:
    """Service to handle video downloading and audio extraction with enterprise anti-bot bypass."""

    def __init__(self, cookies_from_browser: Optional[str] = None) -> None:
        self.download_dir = settings.DOWNLOADS_DIR
        self.audio_dir = settings.AUDIO_DIR
        self.ffmpeg_path = settings.FFMPEG_PATH
        self.cookies_from_browser = cookies_from_browser or os.getenv("YOUTUBE_COOKIES_BROWSER")
        self.cookie_file = self._resolve_cookie_file()

    def _resolve_cookie_file(self) -> Optional[str]:
        """
        Locate or auto-generate persistent Netscape cookies to permanently solve IP/bot verification.
        Checks for existing cookies.txt, then auto-extracts from local browsers via rookiepy.
        """
        # 1. Check existing cookie files
        for candidate in [settings.OUTPUT_DIR / "cookies.txt", settings.BASE_DIR / "cookies.txt"]:
            if candidate.exists() and candidate.stat().st_size > 50:
                return str(candidate)

        # 2. Auto-extract from available local browsers
        try:
            import rookiepy
            browsers = [
                ("firefox", rookiepy.firefox),
                ("edge", rookiepy.edge),
                ("brave", rookiepy.brave),
                ("chrome", rookiepy.chrome),
            ]
            for browser_name, fn in browsers:
                try:
                    cookies = fn([".youtube.com", "youtube.com", ".google.com"])
                    if cookies and len(cookies) > 5:
                        target_file = settings.OUTPUT_DIR / "cookies.txt"
                        with open(target_file, "w", encoding="utf-8") as f:
                            f.write("# Netscape HTTP Cookie File\n")
                            for ck in cookies:
                                domain = ck.get("domain", "")
                                flag = "TRUE" if domain.startswith(".") else "FALSE"
                                path = ck.get("path", "/")
                                secure = "TRUE" if ck.get("secure") else "FALSE"
                                expires = str(int(ck.get("expires", 0) or 0))
                                name = ck.get("name", "")
                                value = ck.get("value", "")
                                f.write(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
                        log_success("INGESTION", f"Auto-discovered and saved persistent cookies from {browser_name.capitalize()}")
                        return str(target_file)
                except Exception:
                    continue
        except Exception:
            pass

        return None

    def _build_ydl_base_opts(self) -> Dict[str, Any]:
        """Construct robust yt-dlp options using Android player client to permanently bypass bot challenges."""
        ffmpeg_dir = os.path.dirname(self.ffmpeg_path) if os.path.exists(self.ffmpeg_path) else self.ffmpeg_path
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "ffmpeg_location": ffmpeg_dir,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android"]
                }
            },
        }

        # Only use cookies if explicitly requested by user (desktop cookies break mobile client)
        if self.cookies_from_browser:
            opts["cookiesfrombrowser"] = (self.cookies_from_browser,)

        # Support optional proxy from .env
        proxy = os.getenv("YOUTUBE_PROXY")
        if proxy:
            opts["proxy"] = proxy

        return opts

    def ingest(self, video_url: str) -> VideoMetadata:
        """
        Download YouTube video and extract 16kHz mono audio.
        Returns VideoMetadata containing paths and metrics.
        """
        log_stage(1, "Video & Audio Ingestion", "yt-dlp & 16kHz Mono Extraction")
        log_info("INGESTION", f"Querying metadata from: {video_url}")

        # Step 1: Query info with anti-bot mobile player clients
        info_opts = self._build_ydl_base_opts()
        info_opts["extract_flat"] = False

        info = None
        try:
            with yt_dlp.YoutubeDL(info_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
        except Exception as e:
            err_str = str(e)
            if "Sign in" in err_str or "bot" in err_str or "429" in err_str:
                log_warning("INGESTION", "YouTube bot challenge encountered. Retrying with mobile player client...")
                info_opts["extractor_args"] = {"youtube": {"player_client": ["android", "ios"]}}
                try:
                    with yt_dlp.YoutubeDL(info_opts) as ydl:
                        info = ydl.extract_info(video_url, download=False)
                except Exception as retry_err:
                    log_error("INGESTION", f"Failed to fetch video info after retry: {retry_err}")
                    raise
            else:
                log_error("INGESTION", f"Failed to fetch video info: {e}")
                raise

        video_id: str = info.get("id", "video")
        title: str = info.get("title", "Unknown Title")
        author: str = info.get("uploader", info.get("channel", "Unknown Channel"))
        duration: float = float(info.get("duration") or 0.0)
        view_count: int = info.get("view_count", 0)
        is_live: bool = bool(info.get("is_live") or info.get("live_status") == "is_live")
        was_live: bool = bool(info.get("was_live") or info.get("live_status") == "was_live")

        if is_live:
            log_error(
                "INGESTION",
                f"⛔ ACTIVE LIVESTREAM DETECTED: '{title}' is currently broadcasting live!\n"
                f"   Peak detection and jump-cut synthesis require a completed broadcast or VOD.\n"
                f"   Please wait until the livestream concludes before clipping.",
            )
            raise RuntimeError(f"Cannot process ongoing livestream '{title}'. Please wait until the stream finishes broadcasting.")

        if duration <= 0.0:
            log_error("INGESTION", f"Invalid video duration ({duration}s) for video: '{title}'.")
            raise ValueError(f"Video '{title}' has zero or unknown duration.")

        log_table("Source Video Metadata", {
            "Video ID": video_id,
            "Title": title,
            "Author / Channel": author,
            "Duration": f"{duration // 60:.0f}m {duration % 60:.0f}s ({duration:.1f}s)",
            "Views": f"{view_count:,}",
        })

        # Step 2: Download video with rich progress bar (reuse if already downloaded)
        video_filename = f"{video_id}.mp4"
        video_path = self.download_dir / video_filename
        outtmpl = str(self.download_dir / f"{video_id}.%(ext)s")

        if video_path.exists() and video_path.stat().st_size > 1024 * 1024:
            filesize_mb = video_path.stat().st_size / (1024 * 1024)
            log_success("INGESTION", f"Using existing downloaded video: {video_path} ({filesize_mb:.2f} MB)")
        else:
            progress = create_download_progress_bar()
            task_id = progress.add_task("Downloading Video", total=None)

            def ydl_hook(d: Dict[str, Any]) -> None:
                status = d.get("status")
                if status == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate")
                    downloaded = d.get("downloaded_bytes", 0)

                    if total and progress.tasks[task_id].total != total:
                        progress.update(task_id, total=total)

                    progress.update(
                        task_id,
                        completed=downloaded,
                        description=f"[bold cyan]Downloading: {d.get('filename', '')[:25]}...",
                    )
                elif status == "finished":
                    progress.update(task_id, description="[bold green]Download finished!")

            ydl_opts = self._build_ydl_base_opts()
            ydl_opts.update({
                "format": "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]/best[height<=1080]/best/18",
                "outtmpl": outtmpl,
                "merge_output_format": "mp4",
                "progress_hooks": [ydl_hook],
            })

            with progress:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])

            if not video_path.exists():
                # In case extension merged as mkv or other
                possible_files = list(self.download_dir.glob(f"{video_id}.*"))
                if possible_files:
                    video_path = possible_files[0]
                else:
                    raise FileNotFoundError(f"Downloaded video file not found for ID: {video_id}")

            filesize_mb = video_path.stat().st_size / (1024 * 1024)
            log_success("INGESTION", f"Video saved to: {video_path} ({filesize_mb:.2f} MB)")

        # Step 3: Extract lightweight 16kHz mono audio for transcription (reuse if cached)
        audio_filename = f"{video_id}_16khz.wav"
        audio_path = self.audio_dir / audio_filename

        if audio_path.exists() and audio_path.stat().st_size > 1024 * 1024:
            audio_size_mb = audio_path.stat().st_size / (1024 * 1024)
            log_success("INGESTION", f"Using existing 16kHz audio: {audio_path} ({audio_size_mb:.2f} MB)")
        else:
            log_info("INGESTION", f"Extracting 16kHz mono WAV audio using FFmpeg: {self.ffmpeg_path}")
            ffmpeg_cmd = [
                self.ffmpeg_path,
                "-y",
                "-i", str(video_path),
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                str(audio_path),
            ]

            result = subprocess.run(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                log_error("INGESTION", f"FFmpeg audio extraction error: {result.stderr}")
                raise RuntimeError(f"FFmpeg failed with code {result.returncode}")

            audio_size_mb = audio_path.stat().st_size / (1024 * 1024)
            log_success("INGESTION", f"Audio track ready: {audio_path} ({audio_size_mb:.2f} MB)")

        return VideoMetadata(
            video_id=video_id,
            title=title,
            duration=duration,
            author=author,
            resolution="1080p",
            video_path=str(video_path),
            audio_path=str(audio_path),
            filesize_mb=filesize_mb,
            was_live=was_live,
        )
