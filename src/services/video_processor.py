"""
Stage 4: Video Processing and 9:16 Vertical Reframing Service.
Executes FFmpeg filter graphs for face tracking, blurred background, or center crop.
"""

import subprocess
import time
from pathlib import Path
from typing import List, Optional, Tuple

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

    def _render_segment(
        self,
        input_video_path: str,
        start_time: float,
        end_time: float,
        output_path: Path,
        bleep_intervals: Optional[List[Tuple[float, float, str]]] = None,
    ) -> str:
        """Render a single 9:16 vertical segment with selected crop mode and optional profanity bleeps."""
        filter_graph = ""

        if self.crop_mode == CropMode.FACE_TRACKING.value:
            tracking_points = self.face_tracker.track_clip(
                input_video_path,
                start_time,
                end_time,
            )
            if tracking_points:
                x_offsets = [pt[1] for pt in tracking_points]
                median_x = int(sorted(x_offsets)[len(x_offsets) // 2])
            else:
                median_x = 0
            filter_graph = f"crop=ih*(9/16):ih:{median_x}:0,scale=1080:1920"

        elif self.crop_mode == CropMode.CENTER_CROP.value:
            filter_graph = "crop=ih*(9/16):ih:(iw-ow)/2:0,scale=1080:1920"

        else:  # BLURRED_BACKGROUND
            filter_graph = (
                "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920,boxblur=25:5[bg];"
                "[0:v]scale=1080:-2[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
            )

        # Build audio filter if profanity censor bleeps are requested
        dur = end_time - start_time
        a_filter = ""
        if bleep_intervals:
            conds = "+".join(f"between(t,{s:.2f},{e:.2f})" for s, e, _ in bleep_intervals)
            a_filter = (
                f"[0:a]volume=enable='{conds}':volume=0[clean_a];"
                f"sine=frequency=1000:duration={dur:.2f},volume=enable='{conds}':volume=0.35[beep_a];"
                f"[clean_a][beep_a]amix=inputs=2:duration=first:dropout_transition=0[aout]"
            )

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-ss", str(start_time),
            "-to", str(end_time),
            "-i", str(input_video_path),
        ]

        if "[v]" in filter_graph:
            if a_filter:
                full_filter = f"{filter_graph};{a_filter}"
                cmd.extend(["-filter_complex", full_filter, "-map", "[v]", "-map", "[aout]"])
            else:
                cmd.extend(["-filter_complex", filter_graph, "-map", "[v]", "-map", "0:a?"])
        else:
            if a_filter:
                full_filter = f"[0:v]{filter_graph}[v];{a_filter}"
                cmd.extend(["-filter_complex", full_filter, "-map", "[v]", "-map", "[aout]"])
            else:
                cmd.extend(["-vf", filter_graph, "-map", "0:a?"])

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

        return str(output_path)

    def _concat_segments(self, segment_paths: List[Path], output_path: Path) -> str:
        """Concatenate multiple 9:16 cuts into a single video with zero re-encoding loss."""
        concat_list_file = self.clips_dir / f"concat_list_{int(time.time() * 1000)}.txt"
        with open(concat_list_file, "w", encoding="utf-8") as f:
            for sp in segment_paths:
                clean_p = str(sp.resolve()).replace("\\", "/")
                f.write(f"file '{clean_p}'\n")

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_file),
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ]

        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        try:
            concat_list_file.unlink(missing_ok=True)
        except Exception:
            pass

        if proc.returncode != 0:
            log_error("VIDEO_PROCESSOR", f"Concat failed: {proc.stderr}")
            raise RuntimeError(f"FFmpeg concat failed: {proc.stderr}")

        return str(output_path)

    def process_clip(
        self,
        input_video_path: str,
        clip: ViralClip,
        video_id: str,
        bleep_intervals: Optional[List[Tuple[float, float, str]]] = None,
    ) -> str:
        """
        Extract the viral segment (single continuous or multi-cut jump-cuts) and reframe to 9:16.
        Applies profanity censor bleeps if bleep_intervals are provided.
        """
        log_stage(4, "Reframing & Video Processing", f"Strategy: {self.crop_mode.upper()}")

        effective_cuts = clip.get_effective_cuts()
        output_filename = f"{video_id}_clip_{int(clip.start_time)}_{int(clip.end_time)}_{self.crop_mode}.mp4"
        output_path = self.clips_dir / output_filename

        start_t = time.time()

        if len(effective_cuts) == 1:
            cut = effective_cuts[0]
            log_info(
                "VIDEO_PROCESSOR",
                f"Continuous Segment: {cut.start_time:.2f}s to {cut.end_time:.2f}s (Duration: {cut.end_time - cut.start_time:.2f}s)",
            )
            self._render_segment(input_video_path, cut.start_time, cut.end_time, output_path, bleep_intervals=bleep_intervals)
        else:
            total_dur = clip.total_duration
            log_info(
                "VIDEO_PROCESSOR",
                f"Local Multi-Cut Condensation: {len(effective_cuts)} cuts (Total Condensed Duration: {total_dur:.2f}s)",
            )
            temp_cut_paths: List[Path] = []
            for idx, cut in enumerate(effective_cuts):
                cut_dur = cut.end_time - cut.start_time
                log_info("VIDEO_PROCESSOR", f"  Cut #{idx + 1} ({cut.role}): {cut.start_time:.2f}s -> {cut.end_time:.2f}s ({cut_dur:.2f}s)")
                temp_p = self.clips_dir / f"{video_id}_temp_cut_{idx}_{int(time.time() * 1000)}.mp4"
                self._render_segment(input_video_path, cut.start_time, cut.end_time, temp_p)
                temp_cut_paths.append(temp_p)

            log_info("VIDEO_PROCESSOR", f"Stitching {len(temp_cut_paths)} cuts with seamless jump-cuts...")
            self._concat_segments(temp_cut_paths, output_path)

            for tp in temp_cut_paths:
                try:
                    tp.unlink(missing_ok=True)
                except Exception:
                    pass

        elapsed = time.time() - start_t
        filesize_mb = output_path.stat().st_size / (1024 * 1024)
        log_success(
            "VIDEO_PROCESSOR",
            f"Rendered 9:16 Shorts video: {output_path} ({filesize_mb:.2f} MB in {elapsed:.2f}s)",
        )
        return str(output_path)
