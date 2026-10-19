"""
Unit tests for YouTube Shorts automation pipeline components.
"""

from pathlib import Path
from src.models import (
    WordTimestamp,
    TranscriptionSegment,
    FullTranscription,
    ViralClip,
)
from src.services.subtitler import SubtitlerService, format_ass_time
from src.services.face_tracker import FaceTracker
from src.config import settings


def test_ass_time_formatting():
    assert format_ass_time(0.0) == "0:00:00.00"
    assert format_ass_time(65.45) == "0:01:05.45"
    assert format_ass_time(3600.0) == "1:00:00.00"


def test_ass_generation(tmp_path: Path):
    subtitler = SubtitlerService()
    words = [
        WordTimestamp(word="This", start=0.0, end=0.3),
        WordTimestamp(word="is", start=0.3, end=0.5),
        WordTimestamp(word="a", start=0.5, end=0.7),
        WordTimestamp(word="viral", start=0.7, end=1.2),
        WordTimestamp(word="moment", start=1.2, end=1.8),
    ]
    out_file = tmp_path / "test.ass"
    subtitler.generate_ass_file(words, out_file)
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "[Script Info]" in content
    assert "ShortsKaraoke" in content
    assert "VIRAL" in content


def test_ffmpeg_detected():
    assert settings.FFMPEG_PATH is not None
    assert Path(settings.FFMPEG_PATH).exists() or settings.FFMPEG_PATH == "ffmpeg"


def test_face_tracker_instantiation():
    tracker = FaceTracker()
    assert tracker.detector_type in ["yunet", "cascade", "none"]


def test_snap_to_word_boundaries():
    from src.services.viral_detector import ViralDetectorService

    detector = ViralDetectorService.__new__(ViralDetectorService)
    
    # Mock transcript with 50 words, starting with filler "um" at 10.0s
    words = [
        WordTimestamp(word="Um", start=10.0, end=10.4),
        WordTimestamp(word="here", start=10.5, end=10.9),
        WordTimestamp(word="is", start=10.9, end=11.2),
        WordTimestamp(word="the", start=11.2, end=11.4),
        WordTimestamp(word="truth.", start=11.4, end=12.0),
    ]
    # Add words to span 45 seconds
    for i in range(1, 40):
        words.append(WordTimestamp(word=f"word{i}", start=12.0 + i, end=12.8 + i))
    words.append(WordTimestamp(word="done!", start=53.0, end=53.8))

    transcription = FullTranscription(
        language="en",
        language_probability=0.99,
        duration=100.0,
        segments=[TranscriptionSegment(id=0, start=10.0, end=53.8, text="test", words=words)],
        total_words=len(words),
    )

    snapped_start, snapped_end = detector.snap_to_word_boundaries(
        raw_start=10.0,
        raw_end=53.5,
        transcription=transcription,
        total_duration=100.0,
    )

    # Should skip "Um" and start at 10.5
    assert snapped_start == 10.5
    # Should snap to sentence end "done!" at 53.8
    assert snapped_end == 53.8
    assert 30.0 <= (snapped_end - snapped_start) <= 58.0
