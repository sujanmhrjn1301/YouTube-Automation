"""
Autonomous Livestream Monitoring and Real-Time Clipping Agent.
Continuously monitors active YouTube livestreams, captures rolling live buffers,
processes peak viral moments into 9:16 Shorts with karaoke captions, and uploads
directly to a strictly dedicated Supabase bucket ('livestream-shorts').
"""

import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import yt_dlp

from src.config import settings
from src.console import (
    log_stage,
    log_info,
    log_success,
    log_warning,
    log_error,
    log_table,
    console,
)
from src.models import VideoMetadata, CropMode
from src.services.database import DatabaseService
from src.services.peak_detector import PeakDetectorService
from src.services.profanity_filter import ProfanityFilterService
from src.services.subtitler import SubtitlerService
from src.services.transcription import TranscriptionService
from src.services.video_processor import VideoProcessorService
from src.services.viral_detector import ViralDetectorService
from src.services.youtube_uploader import YouTubeUploaderService
from src.utils import generate_short_filename


class StreamMonitorAgent:
    """
    Autonomous agent that continuously monitors live broadcasts,
    captures fresh rolling buffers, and produces broadcast-ready Shorts
    saved exclusively into the dedicated 'livestream-shorts' bucket.
    """

    def __init__(
        self,
        target_url: str,
        chunk_duration: int = 150,
        poll_interval: int = 45,
        crop_mode: str = "blurred_background",
        bleep_profanity: bool = True,
        auto_upload: bool = False,
        max_clips: int = 0,
        llm_provider: str = "openrouter",
        llm_model: Optional[str] = None,
        whisper_model: str = "base",
        enable_captions: bool = False,
    ) -> None:
        self.target_url = target_url
        self.chunk_duration = max(60, chunk_duration)
        self.poll_interval = max(15, poll_interval)
        self.crop_mode = crop_mode.lower()
        self.bleep_profanity = bleep_profanity
        self.auto_upload = auto_upload
        self.max_clips = max_clips
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self.whisper_model = whisper_model
        self.enable_captions = enable_captions

        self.agent_dir = settings.LIVESTREAM_AGENT_DIR
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.agent_dir / "agent_state.json"

        # Initialize sub-services
        self.db_service = DatabaseService()
        self.peak_detector = PeakDetectorService()
        self.transcription_service = TranscriptionService(model_size=self.whisper_model)
        self.viral_detector = ViralDetectorService(provider=self.llm_provider, model=self.llm_model)
        self.video_processor = VideoProcessorService(crop_mode=self.crop_mode)
        self.subtitler = SubtitlerService()
        self.profanity_service = ProfanityFilterService()
        self.uploader = YouTubeUploaderService() if self.auto_upload else None

        # Verify dedicated bucket on initialization
        if self.db_service.client:
            self.db_service.ensure_bucket_exists(settings.SUPABASE_LIVESTREAM_SHORTS_BUCKET, public=True)

    def _build_ydl_opts(self) -> Dict[str, Any]:
        """Construct robust yt-dlp extractor options with mobile client anti-bot bypass."""
        ffmpeg_dir = os.path.dirname(settings.FFMPEG_PATH) if os.path.exists(settings.FFMPEG_PATH) else settings.FFMPEG_PATH
        return {
            "quiet": True,
            "no_warnings": True,
            "ffmpeg_location": ffmpeg_dir,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android"]
                }
            },
        }

    def check_stream_status(self) -> Optional[Dict[str, Any]]:
        """
        Check whether the target channel or stream is currently broadcasting live.
        Returns live stream metadata and HLS manifest URL if live, else None.
        """
        norm_url = self.target_url.strip()
        if not norm_url.endswith("/live") and ("youtube.com/@" in norm_url or "youtube.com/c/" in norm_url):
            norm_url = f"{norm_url.rstrip('/')}/live"

        ydl_opts = self._build_ydl_opts()
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(norm_url, download=False)
                if not info:
                    return None

                is_live = bool(info.get("is_live") or info.get("live_status") == "is_live")
                if not is_live:
                    return None

                formats = info.get("formats", [])
                m3u8_formats = [
                    f for f in formats
                    if "m3u8" in f.get("url", "") or f.get("protocol") == "m3u8_native"
                ]

                manifest_url = None
                if m3u8_formats:
                    # Pick highest resolution manifest (usually last in list)
                    manifest_url = m3u8_formats[-1].get("url")
                elif info.get("url"):
                    manifest_url = info.get("url")

                if not manifest_url:
                    return None

                return {
                    "video_id": info.get("id", "live_stream"),
                    "title": info.get("title", "Live Broadcast"),
                    "author": info.get("uploader", info.get("channel", "Live Channel")),
                    "manifest_url": manifest_url,
                    "resolution": m3u8_formats[-1].get("resolution", "1080p") if m3u8_formats else "1080p",
                    "live_url": f"https://www.youtube.com/watch?v={info.get('id')}",
                }
        except Exception as e:
            err_msg = str(e)
            if "ended" in err_msg.lower():
                log_error("STREAM_MONITOR", "This YouTube live event has ended. A completed stream video will not broadcast live again.")
                log_info("STREAM_MONITOR", f"💡 To extract Shorts from this completed video/VOD, run:\n   python cli.py --url {self.target_url} --crop-mode {self.crop_mode}")
                log_info("STREAM_MONITOR", "💡 To monitor an ongoing/upcoming stream, pass a channel live link:\n   python monitor_stream.py --url https://www.youtube.com/@ChannelName/live")
                return {"is_ended": True}
            if "not a live stream" in err_msg.lower() or "offline" in err_msg.lower():
                return None
            log_warning("STREAM_MONITOR", f"Status check note: {err_msg[:90]}")
            return None

    def capture_live_chunk(self, manifest_url: str, video_id: str, duration: int) -> Optional[Path]:
        """
        Capture a rolling chunk from the live HLS stream using FFmpeg copy mode.
        Executes in seconds with zero re-encoding loss.
        """
        chunk_file = self.agent_dir / f"{video_id}_chunk_{int(time.time())}.mp4"
        cmd = [
            settings.FFMPEG_PATH,
            "-y",
            "-i", manifest_url,
            "-t", str(duration),
            "-c", "copy",
            "-movflags", "+faststart",
            str(chunk_file),
        ]

        log_info("STREAM_MONITOR", f"Capturing {duration}s rolling buffer from live stream...")
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

        if proc.returncode != 0 or not chunk_file.exists() or chunk_file.stat().st_size < 100 * 1024:
            log_warning("STREAM_MONITOR", f"Buffer capture failed or empty: {proc.stderr.decode('utf-8', errors='ignore')[:150]}")
            if chunk_file.exists():
                try:
                    chunk_file.unlink()
                except Exception:
                    pass
            return None

        size_mb = chunk_file.stat().st_size / (1024 * 1024)
        log_success("STREAM_MONITOR", f"Captured {duration}s live buffer ({size_mb:.2f} MB)")
        return chunk_file

    def extract_chunk_audio(self, chunk_path: Path) -> Optional[Path]:
        """Extract 16kHz mono WAV audio from chunk for Whisper and peak detection."""
        audio_file = chunk_path.with_suffix(".wav")
        cmd = [
            settings.FFMPEG_PATH,
            "-y",
            "-i", str(chunk_path),
            "-vn",
            "-ar", "16000",
            "-ac", "1",
            "-c:a", "pcm_s16le",
            str(audio_file),
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if proc.returncode != 0 or not audio_file.exists():
            return None
        return audio_file

    def process_live_chunk(
        self,
        chunk_path: Path,
        stream_meta: Dict[str, Any],
        clip_index: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Process rolling live chunk end-to-end:
        Transcribe -> Sentence-Snapped Viral Clip -> Reframing -> Karaoke Captions -> Isolated Supabase Upload.
        """
        log_stage(3, "Live Buffer Processing", f"Analyzing Stream Segment #{clip_index}")

        # 1. Extract 16kHz WAV
        wav_path = self.extract_chunk_audio(chunk_path)
        if not wav_path:
            log_error("STREAM_MONITOR", "Failed to extract 16kHz audio from buffer.")
            return None

        try:
            # 2. Transcribe buffer
            transcription = self.transcription_service.transcribe(str(wav_path), video_id=f"live_{chunk_path.stem}")
            if not transcription.segments or transcription.total_words < 5:
                log_info("STREAM_MONITOR", "No active speech or dialogue in this buffer. Skipping...")
                return None

            # 3. Detect viral moment with clean sentence boundaries and up to 120s extension
            viral_clip = self.viral_detector.detect_viral_moment(
                transcription,
                allow_multi_cut=False,          # Single continuous narrative (no abrupt cuts)
                allow_extended_duration=True,   # Up to 120s if climax needs it
            )

            # Auto-label title with Part/Segment tag
            clean_t = viral_clip.hook_title.replace("#Shorts", "").replace("#shorts", "").strip()
            viral_clip.hook_title = f"{clean_t} [Live #{clip_index}] #Shorts"

            descriptive_filename = generate_short_filename(
                title=viral_clip.hook_title,
                video_id=stream_meta["video_id"],
                duration=viral_clip.total_duration,
                clip_index=clip_index,
                is_livestream=True,
            )

            # 4. English profanity detection and bleeping
            bleep_intervals = []
            if self.bleep_profanity:
                bleep_intervals = self.profanity_service.find_profanity_intervals(
                    transcription,
                    viral_clip.start_time,
                    viral_clip.end_time,
                )
                if bleep_intervals:
                    words = [b[2] for b in bleep_intervals]
                    log_info("STREAM_MONITOR", f"🤫 Censored {len(bleep_intervals)} swear word(s) ({', '.join(words)})")

            # 5. 9:16 Vertical reframing
            cropped_path = self.video_processor.process_clip(
                input_video_path=str(chunk_path),
                clip=viral_clip,
                video_id=f"live_{stream_meta['video_id']}_{clip_index}",
                bleep_intervals=bleep_intervals if self.bleep_profanity else None,
            )

            # 6. Burn karaoke subtitles (if enabled, default: clean clip)
            subtitled_path = cropped_path
            if self.enable_captions:
                try:
                    subtitled_path = self.subtitler.burn_subtitles(
                        video_path=cropped_path,
                        transcription=transcription,
                        clip=viral_clip,
                        video_id=f"live_{stream_meta['video_id']}_{clip_index}",
                        output_filename=descriptive_filename,
                    )
                except Exception as e:
                    log_error("STREAM_MONITOR", f"Subtitle burn encountered an issue ({e}), using cropped 9:16 video.")
                    subtitled_path = cropped_path
            else:
                log_info("STREAM_MONITOR", f"⏩ [CLEAN CLIP] Skipping captions burn for live Short #{clip_index}.")

            # 7. EXCLUSIVE UPLOAD TO DEDICATED SUPABASE BUCKET ('livestream-shorts')
            st_url = None
            if self.db_service.client:
                st_url = self.db_service.upload_livestream_agent_short(subtitled_path)

            # Optional YouTube publish
            yt_id = None
            yt_url = None
            if self.auto_upload and self.uploader:
                yt_id = self.uploader.upload_short(video_path=subtitled_path, clip=viral_clip)
                if yt_id:
                    yt_url = f"https://www.youtube.com/shorts/{yt_id}"

            # Save metadata
            mock_meta = VideoMetadata(
                video_id=stream_meta.get("video_id", "live_stream"),
                title=stream_meta.get("title", "Live Stream"),
                author=stream_meta.get("author", "Live Streamer"),
                duration=float(viral_clip.total_duration),
                resolution="1080x1920",
                filesize_mb=round(Path(subtitled_path).stat().st_size / (1024 * 1024), 2) if Path(subtitled_path).exists() else 0.0,
                video_path=str(chunk_path),
                audio_path=str(wav_path),
                was_live=True,
            )

            rec_id = self.db_service.save_clip_record(
                source_url=stream_meta.get("live_url", ""),
                video_meta=mock_meta,
                clip=viral_clip,
                storage_url=st_url,
                local_path=str(subtitled_path),
                youtube_id=yt_id,
                part_number=clip_index,
                total_parts=clip_index,
                is_confirmed=bool(yt_id),
            )
            log_success("STREAM_MONITOR", f"Live clip registered in Pending Uploads & Highlights DB (ID: {rec_id})")

            return {
                "clip_index": clip_index,
                "title": viral_clip.hook_title,
                "duration": f"{viral_clip.total_duration:.1f}s",
                "storage_url": st_url or "Local only",
                "storage_bucket": settings.SUPABASE_LIVESTREAM_SHORTS_BUCKET,
                "youtube_url": yt_url or "Uploaded to Supabase Cloud",
                "file": Path(subtitled_path).name,
            }

        finally:
            # Auto-cleanup temporary raw chunk files immediately to protect disk
            try:
                if wav_path and wav_path.exists():
                    wav_path.unlink()
                if chunk_path and chunk_path.exists():
                    chunk_path.unlink()
            except Exception:
                pass

    def run_autonomous_monitor(self) -> None:
        """
        Main execution loop for continuous autonomous livestream monitoring.
        Polls target channel/stream, captures buffers, and clips Shorts into isolated bucket.
        """
        console.print("\n[bold cyan]╔══════════════════════════════════════════════════════════════════════════╗[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]   [bold magenta]AUTONOMOUS LIVESTREAM MONITORING & REAL-TIME CLIPPING AGENT[/bold magenta]            [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]║[/bold cyan]   [dim white]Live HLS Ingestion • Sentence-Snapped Shorts • Isolated Cloud Bucket[/dim white]   [bold cyan]║[/bold cyan]")
        console.print("[bold cyan]╚══════════════════════════════════════════════════════════════════════════╝[/bold cyan]\n")

        log_table("Agent Configuration", {
            "Target URL / Channel": self.target_url,
            "Rolling Buffer Duration": f"{self.chunk_duration} seconds",
            "Liveness Poll Interval": f"{self.poll_interval} seconds",
            "Supabase Isolated Bucket": f"[bold green]{settings.SUPABASE_LIVESTREAM_SHORTS_BUCKET}[/bold green]",
            "Profanity Bleep Filter": "ENABLED (1000Hz Censor Bleeps)" if self.bleep_profanity else "DISABLED",
            "Auto YouTube Upload": "ENABLED" if self.auto_upload else f"DISABLED (Supabase [{settings.SUPABASE_LIVESTREAM_SHORTS_BUCKET}])",
            "Crop Mode": self.crop_mode.upper(),
        })

        clips_generated = 0
        buffers_captured = 0
        cycle = 0
        chunk_queue: queue.Queue = queue.Queue(maxsize=3)
        stop_event = threading.Event()

        def _processing_worker():
            nonlocal clips_generated
            while not stop_event.is_set():
                try:
                    item = chunk_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                if item is None:
                    break

                chunk_path, stream_meta, clip_idx = item
                try:
                    log_info("STREAM_MONITOR", f"⚡ [ASYNC PROCESSOR] Processing buffer #{clip_idx} while stream watcher monitors the next moments...")
                    result = self.process_live_chunk(
                        chunk_path=chunk_path,
                        stream_meta=stream_meta,
                        clip_index=clip_idx,
                    )

                    if result:
                        clips_generated += 1
                        log_table("✨ Live Short Created & Uploaded", {
                            "Short Title": result["title"],
                            "Duration": result["duration"],
                            "Supabase Storage Bucket": f"[bold green]{result['storage_bucket']}[/bold green]",
                            "Cloud URL": result["storage_url"],
                            "YouTube Status": result["youtube_url"],
                            "Total Live Shorts Generated": str(clips_generated),
                        })
                except Exception as exc:
                    log_error("STREAM_MONITOR", f"Error in background chunk processing: {exc}")
                finally:
                    chunk_queue.task_done()

        worker_thread = threading.Thread(target=_processing_worker, daemon=True, name="LiveShortsProcessor")
        worker_thread.start()

        try:
            while True:
                cycle += 1
                log_info("STREAM_MONITOR", f"[Cycle #{cycle}] Checking if stream is LIVE...")
                stream_info = self.check_stream_status()

                if not stream_info:
                    log_info("STREAM_MONITOR", f"😴 Stream is currently OFFLINE. Waiting {self.poll_interval}s before next check...")
                    time.sleep(self.poll_interval)
                    continue

                if stream_info.get("is_ended"):
                    log_warning("STREAM_MONITOR", "Agent monitor halted because this target event has ended.")
                    break

                log_success(
                    "STREAM_MONITOR",
                    f"🔴 [ACTIVE BROADCAST DETECTED] '{stream_info['title']}' by {stream_info['author']} ({stream_info['resolution']})",
                )

                # Capture fresh rolling buffer
                chunk_p = self.capture_live_chunk(
                    manifest_url=stream_info["manifest_url"],
                    video_id=stream_info["video_id"],
                    duration=self.chunk_duration,
                )

                if chunk_p:
                    buffers_captured += 1
                    log_info("STREAM_MONITOR", f"🚀 [PARALLEL PIPELINE] Buffer #{buffers_captured} queued for background clipping. Agent is immediately continuing to watch the live broadcast!")
                    chunk_queue.put((chunk_p, stream_info, buffers_captured))

                if self.max_clips > 0 and buffers_captured >= self.max_clips:
                    log_success("STREAM_MONITOR", f"🎉 Reached max requested buffers limit ({self.max_clips}). Waiting for final clips to finish processing...")
                    break

                # Sleep interval to allow stream to accumulate next fresh window
                log_info("STREAM_MONITOR", f"⏳ Watching active broadcast... Capturing next buffer in {self.poll_interval}s...")
                time.sleep(self.poll_interval)

        except KeyboardInterrupt:
            console.print("\n[bold yellow]Agent monitoring stopped by user (Ctrl+C).[/bold yellow]")
        finally:
            log_info("STREAM_MONITOR", "Waiting for pending background clips to complete...")
            stop_event.set()
            chunk_queue.put(None)
            worker_thread.join(timeout=15.0)
            console.print(f"[bold green]Total Shorts Generated: {clips_generated}[/bold green]\n")
