"""
Stage 5: Subtitling and Animated Karaoke Captions Service.
Generates ASS format word-synchronized dynamic subtitles and burns them into 9:16 Shorts.
"""

import re
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
)
from src.models import FullTranscription, ViralClip, WordTimestamp
from src.services.profanity_filter import ProfanityFilterService


def format_ass_time(seconds: float) -> str:
    """Convert seconds into ASS timestamp format: H:MM:SS.cs"""
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis == 100:
        secs += 1
        centis = 0
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


class SubtitlerService:
    """Generates high-retention animated subtitles and burns them via FFmpeg."""

    def __init__(self) -> None:
        self.subtitles_dir = settings.SUBTITLES_DIR
        self.ffmpeg_path = settings.FFMPEG_PATH

    def extract_clip_words(
        self,
        transcription: FullTranscription,
        clip: ViralClip,
    ) -> List[WordTimestamp]:
        """
        Extract and normalize words falling inside the viral clip time windows.
        Supports seamless subtitle re-mapping across multi-cut jump-cuts.
        """
        clip_words: List[WordTimestamp] = []
        effective_cuts = clip.get_effective_cuts()

        p_filter = ProfanityFilterService()
        cumulative_offset = 0.0
        for cut in effective_cuts:
            cut_duration = cut.end_time - cut.start_time
            for seg in transcription.segments:
                for w in seg.words:
                    if w.end >= cut.start_time and w.start <= cut.end_time:
                        rel_start = cumulative_offset + max(0.0, w.start - cut.start_time)
                        rel_end = cumulative_offset + max(w.start - cut.start_time + 0.1, w.end - cut.start_time)
                        display_w = w.word
                        clean = re.sub(r"[^a-zA-Z]", "", display_w)
                        if clean and p_filter.is_profane(clean):
                            if len(clean) > 2:
                                masked = clean[0] + "*" * (len(clean) - 2) + clean[-1]
                            elif len(clean) == 2:
                                masked = clean[0] + "*"
                            else:
                                masked = "*"
                            display_w = display_w.replace(clean, masked)
                        clip_words.append(
                            WordTimestamp(
                                word=display_w,
                                start=round(rel_start, 3),
                                end=round(rel_end, 3),
                                probability=w.probability,
                            )
                        )
            cumulative_offset += cut_duration

        return sorted(clip_words, key=lambda x: x.start)

    def generate_ass_file(
        self,
        words: List[WordTimestamp],
        output_ass_path: Path,
        words_per_card: int = 4,
    ) -> None:
        """
        Build an Advanced SubStation Alpha (.ass) file with word-by-word karaoke color highlights.
        """
        ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ShortsKaraoke,Arial,68,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,60,60,680,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        dialogue_lines: List[str] = []

        # Group words into short dynamic reading cards
        cards: List[List[WordTimestamp]] = []
        for i in range(0, len(words), words_per_card):
            cards.append(words[i : i + words_per_card])

        for card in cards:
            if not card:
                continue

            card_start = card[0].start
            card_end = card[-1].end

            # For each word in the card, render a slice where that word is active
            for idx, active_word in enumerate(card):
                t_start = active_word.start
                # The word stays highlighted until the next word starts or card ends
                t_end = card[idx + 1].start if (idx + 1 < len(card)) else card_end

                if t_end <= t_start:
                    t_end = t_start + 0.25

                start_str = format_ass_time(t_start)
                end_str = format_ass_time(t_end)

                # Assemble line with active word in neon yellow (&H0000FFFF&) and inactive in bright white
                formatted_words: List[str] = []
                for j, w in enumerate(card):
                    clean_word = w.word.upper()
                    if j == idx:
                        # Highlighted active word with subtle pop
                        formatted_words.append(r"{\c&H0000FFFF&\b1}" + clean_word + r"{\rShortsKaraoke}")
                    else:
                        formatted_words.append(clean_word)

                caption_text = " ".join(formatted_words)
                dialogue = f"Dialogue: 0,{start_str},{end_str},ShortsKaraoke,,0,0,0,,{caption_text}"
                dialogue_lines.append(dialogue)

        full_ass_content = ass_header + "\n".join(dialogue_lines) + "\n"

        with open(output_ass_path, "w", encoding="utf-8") as f:
            f.write(full_ass_content)

    def burn_subtitles(
        self,
        video_path: str,
        transcription: FullTranscription,
        clip: ViralClip,
        video_id: str,
        output_filename: Optional[str] = None,
    ) -> str:
        """
        Generate dynamic word-level subtitles and burn them into the 9:16 Shorts video.
        """
        log_stage(5, "Subtitles & Dynamic Captions", "Word-Synchronized Karaoke Highlighting")

        words = self.extract_clip_words(transcription, clip)
        log_info("SUBTITLER", f"Extracted {len(words)} synchronized words for the {clip.total_duration:.1f}s clip.")

        ass_filename = f"{video_id}_{int(clip.start_time)}_{int(clip.end_time)}.ass"
        ass_path = self.subtitles_dir / ass_filename
        self.generate_ass_file(words, ass_path)
        log_success("SUBTITLER", f"Generated ASS karaoke subtitles file: {ass_path}")

        # Final subtitled video output path
        out_name = output_filename or f"{video_id}_final_shorts.mp4"
        output_path = settings.OUTPUT_DIR / out_name

        # Escape path for FFmpeg subtitles filter on Windows
        # Forward slashes with colon escaped: C\:/path/to/sub.ass
        clean_ass_path = str(ass_path.resolve()).replace("\\", "/")
        if ":" in clean_ass_path:
            clean_ass_path = clean_ass_path.replace(":", r"\:")

        log_info("SUBTITLER", f"Burning subtitles using FFmpeg libass filter...")
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", str(video_path),
            "-vf", f"ass='{clean_ass_path}'",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ]

        start_t = time.time()
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        if proc.returncode != 0:
            log_error("SUBTITLER", f"Subtitles burn-in error: {proc.stderr}")
            # Fallback to copy if ass filter encounters system font issue
            raise RuntimeError(f"FFmpeg subtitle burn failed with exit code {proc.returncode}")

        elapsed = time.time() - start_t
        filesize_mb = output_path.stat().st_size / (1024 * 1024)
        log_success(
            "SUBTITLER",
            f"Final subtitled Shorts ready: {output_path} ({filesize_mb:.2f} MB in {elapsed:.2f}s)",
        )

        return str(output_path)
