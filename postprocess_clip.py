#!/usr/bin/env python3
"""
Post-Process Clip Script:
Autonomous post-processor for arbitrary local videos and clips.
Features:
- Transcribes audio using faster-whisper word-level timestamps.
- Optional 1000Hz censor bleeping of swear words / profanity (ProfanityFilterService).
- Optional animated karaoke captions with highlight pop (SubtitlerService).
- Registers output clip into database/Supabase so it can be 1-click published to YouTube & Instagram.
"""

import os
import re
import sys
import time
import argparse
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import settings
from src.console import (
    log_stage,
    log_info,
    log_success,
    log_warning,
    log_error,
    console,
)
from src.models import ViralClip, VideoMetadata
from src.services.transcription import TranscriptionService
from src.services.profanity_filter import ProfanityFilterService
from src.services.subtitler import SubtitlerService
from src.services.database import DatabaseService


def get_video_info(video_path: str, ffmpeg_path: str) -> Tuple[float, int, int]:
    """Extract duration, width, and height of the video reliably via ffmpeg -i."""
    cmd = [
        ffmpeg_path,
        "-i", str(video_path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
        stderr = res.stderr or ""
        dur = 0.0
        width = 1080
        height = 1920
        dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", stderr)
        if dur_match:
            h, m, s = map(float, dur_match.groups())
            dur = h * 3600 + m * 60 + s

        res_match = re.search(r"Video:.*?,\s*(\d{3,4})x(\d{3,4})", stderr)
        if res_match:
            width, height = map(int, res_match.groups())

        if dur > 0:
            return dur, width, height
    except Exception as e:
        log_warning("POST_PROCESS", f"ffmpeg video probe fallback: {e}")

    return 60.0, 1080, 1920



def extract_16khz_audio(video_path: str, output_wav: Path, ffmpeg_path: str) -> bool:
    """Extract mono 16kHz audio for Whisper transcription."""
    cmd = [
        ffmpeg_path,
        "-y",
        "-i", str(video_path),
        "-vn",
        "-ar", "16000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        str(output_wav),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return output_wav.exists() and output_wav.stat().st_size > 1000


def postprocess_video(
    video_path: str,
    enable_captions: bool = True,
    bleep_profanity: bool = False,
    output_name: Optional[str] = None,
    title: Optional[str] = None,
) -> Path:
    start_time_all = time.time()
    in_path = Path(video_path).resolve()
    if not in_path.is_file():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    log_stage(1, "Post-Process Studio", f"Processing: {in_path.name}")
    log_info("POST_PROCESS", f"Options: Captions={enable_captions} | Bleep Swear Words={bleep_profanity}")

    ffmpeg_path = settings.FFMPEG_PATH
    output_dir = settings.OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = output_dir / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    base_stem = in_path.stem
    clean_title = title or base_stem.replace("_", " ").title()

    duration, width, height = get_video_info(str(in_path), ffmpeg_path)
    log_info("POST_PROCESS", f"Video Specs: {width}x{height} | Duration: {duration:.1f}s")

    # Step 1: Extract 16kHz audio for transcription if captions or bleeping enabled
    temp_wav = temp_dir / f"{base_stem}_16khz.wav"
    transcription = None

    if enable_captions or bleep_profanity:
        log_stage(2, "Audio Extraction", "Extracting 16kHz mono audio for Whisper transcription...")
        if not extract_16khz_audio(str(in_path), temp_wav, ffmpeg_path):
            log_warning("POST_PROCESS", "Audio extraction returned small or empty file, continuing...")

        log_stage(3, "Word-Level Transcription", "Running faster-whisper for precise word timestamps...")
        transcriber = TranscriptionService(model_size=settings.WHISPER_MODEL_SIZE)
        transcription = transcriber.transcribe(str(temp_wav), video_id=base_stem)
        log_success("POST_PROCESS", f"Transcribed {transcription.total_words} words across {len(transcription.segments)} segments.")

    # Step 2: Censor Profanity (1000Hz Bleeps)
    current_video_input = in_path
    bleep_intervals: List[Tuple[float, float, str]] = []

    if bleep_profanity and transcription:
        log_stage(4, "Profanity Filter", "Scanning for swear words and profanity...")
        p_filter = ProfanityFilterService()
        bleep_intervals = p_filter.find_profanity_intervals(transcription, clip_start=0.0, clip_end=duration)

        if bleep_intervals:
            words_found = [w for _, _, w in bleep_intervals]
            log_info(
                "POST_PROCESS",
                f"🤫 [PROFANITY DETECTED] Found {len(bleep_intervals)} swear word(s): ({', '.join(words_found)}). Applying 1000Hz censor bleeps..."
            )
            bleeped_output = temp_dir / f"{base_stem}_bleeped.mp4"
            conds = "+".join(f"between(t,{s:.2f},{e:.2f})" for s, e, _ in bleep_intervals)
            a_filter = (
                f"[0:a]volume='if({conds},0,1)':eval=frame[clean_a];"
                f"sine=frequency=1000:duration={duration:.2f},volume='if({conds},0.35,0)':eval=frame[beep_a];"
                f"[clean_a][beep_a]amix=inputs=2:duration=first:dropout_transition=0[aout]"
            )


            cmd_bleep = [
                ffmpeg_path,
                "-y",
                "-i", str(current_video_input),
                "-filter_complex", a_filter,
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                str(bleeped_output)
            ]
            res = subprocess.run(cmd_bleep, capture_output=True, text=True)
            if bleeped_output.exists() and bleeped_output.stat().st_size > 1000:
                current_video_input = bleeped_output
                log_success("POST_PROCESS", "Swear words successfully silenced and bleeped!")
            else:
                log_warning("POST_PROCESS", f"Audio bleep filter notice: {res.stderr[:200]}")
        else:
            log_info("POST_PROCESS", "No swear words detected in the audio.")

    # Step 3: Burn Animated Karaoke Captions
    final_output_path = output_dir / (output_name or f"{base_stem}_postprocessed.mp4")

    if enable_captions and transcription:
        log_stage(5, "Subtitles & Captions", "Generating ASS karaoke file and burning dynamic captions...")
        subtitler = SubtitlerService()
        dummy_clip = ViralClip(
            start_time=0.0,
            end_time=duration,
            hook_title=clean_title,
            hook_score=10,
        )
        words = subtitler.extract_clip_words(transcription, dummy_clip)
        log_info("POST_PROCESS", f"Synchronized {len(words)} karaoke words.")

        ass_path = settings.SUBTITLES_DIR / f"{base_stem}_postprocess.ass"
        subtitler.generate_ass_file(words, ass_path)

        clean_ass_path = str(ass_path.resolve()).replace("\\", "/")
        if ":" in clean_ass_path:
            clean_ass_path = clean_ass_path.replace(":", r"\:")

        cmd_sub = [
            ffmpeg_path,
            "-y",
            "-i", str(current_video_input),
            "-vf", f"ass='{clean_ass_path}'",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(final_output_path)
        ]
        res = subprocess.run(cmd_sub, capture_output=True, text=True)
        if not final_output_path.exists() or final_output_path.stat().st_size < 1000:
            log_warning("POST_PROCESS", f"Subtitle burn warning, copying video: {res.stderr[:200]}")
            import shutil
            shutil.copyfile(current_video_input, final_output_path)
        else:
            log_success("POST_PROCESS", "Animated karaoke captions burned successfully!")
    else:
        # Just copy/link current video if no subtitles
        if current_video_input != final_output_path:
            import shutil
            shutil.copyfile(current_video_input, final_output_path)

    elapsed_total = time.time() - start_time_all
    filesize_mb = final_output_path.stat().st_size / (1024 * 1024)
    log_success(
        "POST_PROCESS",
        f"Post-processing complete! Ready: {final_output_path.name} ({filesize_mb:.2f} MB in {elapsed_total:.1f}s)"
    )

    # Step 4: Register in SQLite database & Supabase so it appears in Pending Uploads
    try:
        db = DatabaseService()
        v_meta = VideoMetadata(
            video_id=f"postprocess_{int(time.time())}",
            title=clean_title,
            author="Post-Process Studio",
            duration=duration,
            resolution=f"{width}x{height}",
            filesize_mb=filesize_mb,
            was_live=False,
        )
        v_clip = ViralClip(
            start_time=0.0,
            end_time=duration,
            hook_title=clean_title,
            hook_score=9,
            description=f"{clean_title} #Shorts #Viral",
            tags=["postprocess", "shorts", "reels", "viral"],
            viral_reasoning="Post-processed with custom captions and censor filters."
        )
        rec_id = db.save_clip_record(
            source_url="",
            video_meta=v_meta,
            clip=v_clip,
            storage_url=None,
            local_path=str(final_output_path),
            youtube_id=None,
            part_number=1,
            total_parts=1,
            is_confirmed=False
        )
        log_success("POST_PROCESS", f"Registered clip #{rec_id} into Pending Uploads for 1-Click Publishing!")
    except Exception as e:
        log_warning("POST_PROCESS", f"Database registration note: {e}")

    print(f"\n[OK] OUTPUT_FILE: {final_output_path}")
    return final_output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Post-process any video with captions and censor beeping.")
    parser.add_argument("--video-path", type=str, required=True, help="Path to input video file")
    parser.add_argument("--captions", dest="captions", action="store_true", default=True, help="Enable animated captions")
    parser.add_argument("--no-captions", dest="captions", action="store_false", help="Disable captions")
    parser.add_argument("--bleep-profanity", dest="bleep", action="store_true", default=False, help="Beep swear words")
    parser.add_argument("--no-bleep-profanity", dest="bleep", action="store_false", help="Do not beep swear words")
    parser.add_argument("--output-name", type=str, default=None, help="Custom output filename")
    parser.add_argument("--title", type=str, default=None, help="Custom title for the video")

    args = parser.parse_args()

    postprocess_video(
        video_path=args.video_path,
        enable_captions=args.captions,
        bleep_profanity=args.bleep,
        output_name=args.output_name,
        title=args.title,
    )


if __name__ == "__main__":
    main()
