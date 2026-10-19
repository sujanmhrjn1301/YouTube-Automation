"""
Stage 2: Word-Level Transcription Service using faster-whisper.
Extracts phrase segments and precise word-level timestamps with real-time feedback.
"""

import subprocess
import time
from typing import List, Tuple, Optional
import torch
from faster_whisper import WhisperModel

from src.console import (
    log_stage,
    log_info,
    log_warning,
    log_success,
    log_table,
    console,
    get_timestamp,
)
from src.models import (
    FullTranscription,
    TranscriptionSegment,
    WordTimestamp,
    WhisperModelSize,
)


class TranscriptionService:
    """Transcription service powered by CTranslate2 faster-whisper."""

    def __init__(self, model_size: str = "base") -> None:
        self.model_size = model_size
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.compute_type = "float16" if self.device == "cuda" else "int8"
        self.model: WhisperModel = None

    def load_model(self) -> None:
        """Load Whisper model with progress reporting."""
        log_info(
            "TRANSCRIPTION",
            f"Loading WhisperModel(size='{self.model_size}', device='{self.device}', compute_type='{self.compute_type}')...",
        )
        start_load = time.time()
        self.model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
        )
        elapsed = time.time() - start_load
        log_success("TRANSCRIPTION", f"Whisper model loaded into memory in {elapsed:.2f}s")

    def transcribe(self, audio_path: str, video_id: Optional[str] = None) -> FullTranscription:
        """
        Execute transcription on 16kHz audio file.
        Extracts both sentence segments and word-level timestamps.
        Caches results to disk for fast idempotent re-runs.
        """
        log_stage(2, "Word-Level Transcription", f"faster-whisper ({self.model_size})")

        from src.config import settings
        from pathlib import Path
        vid = video_id or Path(audio_path).stem.replace("_16khz", "")
        cache_file = settings.TRANSCRIPTS_DIR / f"{vid}.json"

        if cache_file.exists() and cache_file.stat().st_size > 100:
            try:
                cached = FullTranscription.model_validate_json(cache_file.read_text(encoding="utf-8"))
                log_success(
                    "TRANSCRIPTION",
                    f"Loaded cached transcription: {cache_file} ({cached.total_words} words across {len(cached.segments)} segments)",
                )
                return cached
            except Exception as e:
                log_warning("TRANSCRIPTION", f"Failed to load cache ({e}), re-transcribing...")

        if self.model is None:
            self.load_model()

        log_info("TRANSCRIPTION", f"Beginning transcription on: {audio_path}")
        start_time = time.time()

        segments_generator, info = self.model.transcribe(
            audio_path,
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        log_table("Detected Audio Properties", {
            "Detected Language": f"{info.language.upper()} ({info.language_probability * 100:.1f}% confidence)",
            "Audio Duration": f"{info.duration:.2f} seconds",
            "Execution Device": self.device.upper(),
        })

        parsed_segments: List[TranscriptionSegment] = []
        total_word_count = 0

        console.print("\n[bold dim cyan]--- Real-Time Segment Feed ---[/bold dim cyan]")

        for segment in segments_generator:
            words_list: List[WordTimestamp] = []
            if segment.words:
                for w in segment.words:
                    words_list.append(
                        WordTimestamp(
                            word=w.word.strip(),
                            start=round(w.start, 3),
                            end=round(w.end, 3),
                            probability=round(w.probability, 3),
                        )
                    )

            total_word_count += len(words_list)

            parsed_segment = TranscriptionSegment(
                id=segment.id,
                start=round(segment.start, 2),
                end=round(segment.end, 2),
                text=segment.text.strip(),
                words=words_list,
            )
            parsed_segments.append(parsed_segment)

            # Real-time console line
            ts = get_timestamp()
            console.print(
                f"[{ts}] [bold yellow][{segment.start:06.2f}s -> {segment.end:06.2f}s][/bold yellow] "
                f"[white]{segment.text.strip()}[/white]"
            )

        elapsed = time.time() - start_time
        log_success(
            "TRANSCRIPTION",
            f"Transcription complete! Processed {total_word_count} words across {len(parsed_segments)} segments in {elapsed:.2f}s",
        )

        result = FullTranscription(
            language=info.language,
            language_probability=info.language_probability,
            duration=info.duration,
            segments=parsed_segments,
            total_words=total_word_count,
        )

        try:
            cache_file.write_text(result.model_dump_json(indent=2), encoding="utf-8")
            log_success("TRANSCRIPTION", f"Saved transcription cache to: {cache_file}")
        except Exception as e:
            log_warning("TRANSCRIPTION", f"Failed to save transcription cache: {e}")

        return result

    def transcribe_window(
        self,
        audio_path: str,
        start_time: float,
        end_time: float,
        video_id: Optional[str] = None,
    ) -> FullTranscription:
        """
        Fast targeted transcription of a specific candidate window (e.g. 90-120s) for stream processing.
        Extracts a tiny WAV slice, transcribes in seconds, and shifts timestamps to master timeline.
        """
        from src.config import settings
        from pathlib import Path

        vid = video_id or Path(audio_path).stem.replace("_16khz", "")
        cache_file = settings.TRANSCRIPTS_DIR / f"{vid}_window_{int(start_time)}_{int(end_time)}.json"

        if cache_file.exists():
            try:
                if cache_file.stat().st_size > 100:
                    cached = FullTranscription.model_validate_json(cache_file.read_text(encoding="utf-8"))
                    log_success(
                        "TRANSCRIPTION",
                        f"Loaded cached window transcription [{start_time:.1f}s -> {end_time:.1f}s]: {cached.total_words} words",
                    )
                    return cached
            except Exception as e:
                log_warning("TRANSCRIPTION", f"Failed to load window cache ({e}), re-transcribing...")

        if self.model is None:
            self.load_model()

        # Slice 16kHz audio window with FFmpeg
        temp_slice = settings.AUDIO_DIR / f"temp_{vid}_{int(start_time)}_{int(end_time)}_{int(time.time() * 1000)}.wav"
        slice_cmd = [
            settings.FFMPEG_PATH,
            "-y",
            "-ss", str(start_time),
            "-to", str(end_time),
            "-i", str(audio_path),
            "-c", "copy",
            str(temp_slice),
        ]
        subprocess.run(slice_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

        if not temp_slice.exists():
            log_warning("TRANSCRIPTION", f"Audio slice failed for window {start_time}-{end_time}")
            return FullTranscription(language="en", language_probability=1.0, duration=end_time - start_time, segments=[], total_words=0)

        start_t = time.time()
        segments_generator, info = self.model.transcribe(
            str(temp_slice),
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        parsed_segments: List[TranscriptionSegment] = []
        total_word_count = 0

        for segment in segments_generator:
            words_list: List[WordTimestamp] = []
            if segment.words:
                for w in segment.words:
                    words_list.append(
                        WordTimestamp(
                            word=w.word.strip(),
                            start=round(w.start + start_time, 3),
                            end=round(w.end + start_time, 3),
                            probability=round(w.probability, 3),
                        )
                    )
            total_word_count += len(words_list)
            parsed_segments.append(
                TranscriptionSegment(
                    id=segment.id,
                    start=round(segment.start + start_time, 2),
                    end=round(segment.end + start_time, 2),
                    text=segment.text.strip(),
                    words=words_list,
                )
            )

        try:
            temp_slice.unlink(missing_ok=True)
        except Exception:
            pass

        elapsed = time.time() - start_t
        log_success(
            "TRANSCRIPTION",
            f"Transcribed window [{start_time:.1f}s -> {end_time:.1f}s]: {total_word_count} words in {elapsed:.2f}s",
        )

        result = FullTranscription(
            language=info.language,
            language_probability=info.language_probability,
            duration=round(end_time - start_time, 2),
            segments=parsed_segments,
            total_words=total_word_count,
        )

        try:
            cache_file.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        except Exception:
            pass

        return result
