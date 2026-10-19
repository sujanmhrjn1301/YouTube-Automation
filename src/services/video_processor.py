"""
Stage 4: Video Processing and 9:16 Vertical Reframing Service.
Executes FFmpeg filter graphs for face tracking, blurred background, or center crop.
"""

import subprocess
import time
from pathlib import Path
from typing import Optional

from src.config import settings
from src.console import (
    log_stage,
    log_info,
    log_success,
    log_error,
    console,
)
from src.models import CropMode, ViralClip
from src.services.face_tracker import FaceTracker


class VideoProcessorService:
    """Reframes horizontal video into 1080x1920 vertical format for YouTube Shorts."""

    def __init__(self, crop_mode: str = "blurred_background") -> None:
        self.crop_mode = crop_mode.lower()
        self.ffmpeg_path = settings.FFMPEG_PATH
        self.clips_dir = settings.CLIPS_DIR
        self.face_tracker = FaceTracker()

    def process_clip(
        self,
        input_video_path: str,
        clip: ViralClip,
        video_id: str,
    ) -> str:
        """
        Extract the viral segment and reframe to 9:16 (1080x1920).
        """
        log_stage(4, "Reframing & Video Processing", f"Strategy: {self.crop_mode.upper()}")

        output_filename = f"{video_id}_clip_{int(clip.start_time)}_{int(clip.end_time)}_{self.crop_mode}.mp4"
        output_path = self.clips_dir / output_filename

        duration = clip.end_time - clip.start_time
        log_info(
            "VIDEO_PROCESSOR",
            f"Segment: {clip.start_time:.2f}s to {clip.end_time:.2f}s (Duration: {duration:.2f}s)",
        )

        filter_graph = ""

        if self.crop_mode == CropMode.FACE_TRACKING.value:
            log_info("VIDEO_PROCESSOR", "Running face tracking to determine optimal crop coordinates...")
            tracking_points = self.face_tracker.track_clip(
                input_video_path,
                clip.start_time,
                clip.end_time,
            )

            # Compute weighted median crop X offset
            if tracking_points:
                x_offsets = [pt[1] for pt in tracking_points]
                median_x = int(sorted(x_offsets)[len(x_offsets) // 2])
            else:
                median_x = 0  # Fallback to left or center

            log_info("VIDEO_PROCESSOR", f"Applying face-centered crop at X offset: {median_x}px")
            # Crop 9:16 aspect ratio based on height, then scale to standard Shorts 1080x1920
            filter_graph = f"crop=ih*(9/16):ih:{median_x}:0,scale=1080:1920"

        elif self.crop_mode == CropMode.CENTER_CROP.value:
            log_info("VIDEO_PROCESSOR", "Applying 9:16 Center Crop filter...")
            filter_graph = "crop=ih*(9/16):ih:(iw-ow)/2:0,scale=1080:1920"

        else:  # BLURRED_BACKGROUND (Default and most visually appealing for general podcasts/videos)
            log_info("VIDEO_PROCESSOR", "Synthesizing dynamic Blurred Background with centered foreground...")
            filter_graph = (
                "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920,boxblur=25:5[bg];"
                "[0:v]scale=1080:-2[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
            )

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-ss", str(clip.start_time),
            "-to", str(clip.end_time),
            "-i", str(input_video_path),
        ]

        if "[v]" in filter_graph:
            cmd.extend([
                "-filter_complex", filter_graph,
                "-map", "[v]",
                "-map", "0:a?",
            ])
        else:
            cmd.extend([
                "-vf", filter_graph,
            ])

        cmd.extend([
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-c:a", "aac",
            "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path),
        ])

        log_info("VIDEO_PROCESSOR", f"Executing FFmpeg filter graph: {' '.join(cmd[:12])}...")
        start_t = time.time()

        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        if proc.returncode != 0:
            log_error("VIDEO_PROCESSOR", f"FFmpeg failed with error:\n{proc.stderr}")
            raise RuntimeError(f"FFmpeg processing failed with exit code {proc.returncode}")

        elapsed = time.time() - start_t
        filesize_mb = output_path.stat().st_size / (1024 * 1024)
        log_success(
            "VIDEO_PROCESSOR",
            f"Rendered 9:16 Shorts video: {output_path} ({filesize_mb:.2f} MB in {elapsed:.2f}s)",
        )

        return str(output_path)
