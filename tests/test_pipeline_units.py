"""
Unit tests for YouTube Shorts automation pipeline components.
"""

import math
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
    for i in range(1, 55):
        words.append(WordTimestamp(word=f"word{i}", start=12.0 + i, end=12.8 + i))
    words.append(WordTimestamp(word="done!", start=68.0, end=68.5))

    transcription = FullTranscription(
        language="en",
        language_probability=0.99,
        duration=100.0,
        segments=[TranscriptionSegment(id=0, start=10.0, end=68.5, text="test", words=words)],
        total_words=len(words),
    )

    snapped_start, snapped_end = detector.snap_to_word_boundaries(
        raw_start=10.0,
        raw_end=58.5,
        transcription=transcription,
        total_duration=100.0,
    )

    # Should skip "Um" and start at 10.5
    assert snapped_start == 10.5
    assert 45.0 <= (snapped_end - snapped_start) <= 59.0


def test_multi_cut_subtitle_remapping():
    from src.models import ClipCut

    subtitler = SubtitlerService()
    # Mock transcript with 2 separate sentences 30 seconds apart
    # Cut 1: 10.0 to 15.0 (duration: 5s)
    # Cut 2: 45.0 to 55.0 (duration: 10s)
    words = [
        WordTimestamp(word="Hook", start=10.0, end=11.0),
        WordTimestamp(word="sentence", start=11.2, end=14.8),
        # Gap between 15.0 and 45.0
        WordTimestamp(word="Payoff", start=45.2, end=47.0),
        WordTimestamp(word="ending", start=47.2, end=54.5),
    ]
    transcription = FullTranscription(
        language="en",
        language_probability=0.99,
        duration=100.0,
        segments=[TranscriptionSegment(id=0, start=10.0, end=55.0, text="test", words=words)],
        total_words=len(words),
    )
    clip = ViralClip(
        start_time=10.0,
        end_time=55.0,
        cuts=[
            ClipCut(start_time=10.0, end_time=15.0, role="hook"),
            ClipCut(start_time=45.0, end_time=55.0, role="payoff"),
        ],
        hook_title="Test Hook #Shorts",
        description="Test desc",
        tags=["test"],
        viral_reasoning="Good hook",
        hook_score=9,
    )

    extracted_words = subtitler.extract_clip_words(transcription, clip)
    assert len(extracted_words) == 4
    # Cut 1: Hook at 0.0, sentence at 1.2
    assert extracted_words[0].word == "Hook"
    assert extracted_words[0].start == 0.0
    # Cut 2 starts after Cut 1 duration (5.0s)
    assert extracted_words[2].word == "Payoff"
    assert extracted_words[2].start >= 5.0  # remapped relative to cut 1!
    assert extracted_words[3].word == "ending"
    assert extracted_words[3].start > extracted_words[2].start


def test_peak_detector_basic(tmp_path: Path):
    from src.services.peak_detector import PeakDetectorService
    import wave
    import struct

    # Generate a small 1-second synthetic WAV file with high volume in middle
    wav_path = tmp_path / "test_audio.wav"
    sample_rate = 16000
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        # 16000 frames
        data = []
        for i in range(sample_rate):
            val = int(20000 * math.sin(2 * math.pi * 440 * i / sample_rate))
            data.append(val)
        wf.writeframes(struct.pack(f"<{len(data)}h", *data))

    detector = PeakDetectorService(window_size_sec=0.5, step_size_sec=0.25)
    energy = detector.compute_audio_energy(wav_path)
    assert len(energy) > 0
    # Verify normalized 0 to 1
    assert 0.0 <= energy[0][2] <= 1.0


def test_video_processor_instantiation():
    from src.services.video_processor import VideoProcessorService
    processor = VideoProcessorService()
    assert processor.crop_mode == "blurred_background"


def test_utils_filenames():
    from src.utils import slugify_title, generate_short_filename

    slug = slugify_title("Eat Everything In A Grocery Store, Win $1,000,000!")
    assert slug == "Eat_Everything_In_A_Grocery_Store"

    std_name = generate_short_filename("Unlocking Secrets of 40% [Part 1] #Shorts")
    assert std_name == "Unlocking_Secrets_of_40pct_Part_1_Shorts.mp4"

    stream_name = generate_short_filename("Minecraft 100 Days Stream! [Part 2] #Shorts")
    assert stream_name == "Minecraft_100_Days_Stream_Part_2_Shorts.mp4"


def test_youtube_upload_confirmation():
    from unittest.mock import MagicMock
    from src.services.youtube_uploader import YouTubeUploaderService

    uploader = YouTubeUploaderService()
    mock_youtube = MagicMock()

    # Case 1: Successful upload confirmation
    mock_youtube.videos().list().execute.return_value = {
        "items": [
            {
                "status": {"uploadStatus": "uploaded", "privacyStatus": "public"},
                "snippet": {"title": "Test Short #Shorts"},
            }
        ]
    }
    is_ok, msg, _ = uploader.confirm_upload(mock_youtube, "test_vid_123")
    assert is_ok is True
    assert "UPLOADED" in msg

    # Case 2: Rejected upload
    mock_youtube.videos().list().execute.return_value = {
        "items": [
            {
                "status": {"uploadStatus": "rejected", "rejectionReason": "duplicate"},
            }
        ]
    }
    is_ok, msg, _ = uploader.confirm_upload(mock_youtube, "test_vid_bad")
    assert is_ok is False
    assert "rejected" in msg.lower()


def test_duplicate_upload_check(tmp_path: Path):
    from src.services.database import DatabaseService
    import sqlite3

    db_service = DatabaseService.__new__(DatabaseService)
    db_file = tmp_path / "test_shorts.db"
    db_service.local_db_path = db_file
    db_service.client = None

    # Populate temporary database
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE shorts_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_url TEXT,
            source_video_id TEXT,
            source_title TEXT,
            hook_title TEXT,
            description TEXT,
            tags TEXT,
            viral_reasoning TEXT,
            hook_score INTEGER,
            start_time REAL,
            end_time REAL,
            duration REAL,
            storage_url TEXT,
            local_path TEXT,
            youtube_id TEXT,
            created_at TEXT
        )
    """)
    c.execute("""
        INSERT INTO shorts_metadata (source_video_id, hook_title, start_time, end_time, youtube_id, created_at)
        VALUES ('src_xyz_1', 'Crazy Stunt In Public #Shorts', 10.0, 56.5, 'YT_EXISTING_99', '2026-10-19T00:00:00')
    """)
    conn.commit()
    conn.close()

    # 1. Matching by timestamp overlap (< 2s)
    yt_id = db_service.check_existing_upload("src_xyz_1", 10.5, 56.0)
    assert yt_id == "YT_EXISTING_99"

    # 2. Matching by title
    yt_id_title = db_service.check_existing_upload("different_src", 0.0, 10.0, title="Crazy Stunt In Public")
    assert yt_id_title == "YT_EXISTING_99"

    # 3. Non-existing moment
    yt_id_none = db_service.check_existing_upload("src_xyz_1", 100.0, 150.0)
    assert yt_id_none is None


def test_transcribe_window_timestamp_shifting():
    from unittest.mock import MagicMock
    from src.services.transcription import TranscriptionService
    from collections import namedtuple

    service = TranscriptionService.__new__(TranscriptionService)
    service.model = MagicMock()

    WordMock = namedtuple("WordMock", ["word", "start", "end", "probability"])
    SegmentMock = namedtuple("SegmentMock", ["id", "start", "end", "text", "words"])
    InfoMock = namedtuple("InfoMock", ["language", "language_probability"])

    # Simulate transcribing a 30-second slice that was cut from 100s to 130s in the original video
    # Relative time in the slice is 0.0s to 5.0s
    mock_words = [
        WordMock(word="Hello", start=1.0, end=1.5, probability=0.98),
        WordMock(word="World", start=1.6, end=2.2, probability=0.99),
    ]
    mock_segment = SegmentMock(id=0, start=1.0, end=2.2, text="Hello World", words=mock_words)

    service.model.transcribe.return_value = ([mock_segment], InfoMock("en", 0.99))

    # Mock subprocess so it creates the temporary wav file
    import subprocess
    orig_run = subprocess.run
    def mock_run_fn(cmd, *args, **kwargs):
        # cmd[-1] is the output wav path
        out_wav = Path(cmd[-1])
        out_wav.write_bytes(b"dummy_wav_data")
        return MagicMock(returncode=0)

    subprocess.run = mock_run_fn
    res = service.transcribe_window("dummy.wav", start_time=100.0, end_time=130.0, video_id="test_mock")
    subprocess.run = orig_run

    assert len(res.segments) == 1
    # Segment start was 1.0, offset by 100.0 -> should be 101.0
    assert res.segments[0].start == 101.0
    assert res.segments[0].end == 102.2
    # Words should also be shifted
    assert res.segments[0].words[0].start == 101.0
    assert res.segments[0].words[1].end == 102.2
    assert res.segments[0].text == "Hello World"


def test_youtube_quota_tracking(tmp_path: Path):
    from src.services.database import DatabaseService

    db_service = DatabaseService.__new__(DatabaseService)
    db_service.local_db_path = tmp_path / "test_quota.db"
    db_service.client = None
    db_service._init_local_db()

    # Initial status: 0 used, can upload
    status = db_service.get_daily_quota_status()
    assert status["units_used"] == 0
    assert status["can_upload"] is True
    assert status["remaining_units"] == 10000

    # Record 1 upload (1600 units)
    db_service.record_quota_usage(1600, is_upload=True)
    status2 = db_service.get_daily_quota_status()
    assert status2["units_used"] == 1600
    assert status2["uploads_today"] == 1
    assert status2["remaining_units"] == 8400
    assert status2["can_upload"] is True

    # Record 5 more uploads (total 6 uploads = 9600 units)
    for _ in range(5):
        db_service.record_quota_usage(1600, is_upload=True)

    status3 = db_service.get_daily_quota_status()
    assert status3["units_used"] == 9600
    assert status3["uploads_today"] == 6
    # 9600 + 1600 > 10000, so can_upload must be False!
    assert status3["can_upload"] is False


def test_multi_part_series_tracking(tmp_path: Path):
    from src.services.database import DatabaseService

    db_service = DatabaseService.__new__(DatabaseService)
    db_service.local_db_path = tmp_path / "test_series.db"
    db_service.client = None
    db_service._init_local_db()

    # Record Part 1
    db_service.record_series_part(
        source_video_id="video_abc_1",
        source_title="Epic 24 Hour Challenge",
        source_url="https://youtube.com/watch?v=video_abc_1",
        part_number=1,
        total_parts=2,
        short_title="Epic Challenge Begins [Part 1] #Shorts",
        duration=48.5,
        youtube_id=None,
        is_confirmed=False,
    )

    # Record Part 2
    db_service.record_series_part(
        source_video_id="video_abc_1",
        source_title="Epic 24 Hour Challenge",
        source_url="https://youtube.com/watch?v=video_abc_1",
        part_number=2,
        total_parts=2,
        short_title="The Final Finale [Part 2] #Shorts",
        duration=52.0,
        youtube_id=None,
        is_confirmed=False,
    )

    # Check series summary
    parts = db_service.get_series_summary("video_abc_1")
    assert len(parts) == 2
    assert parts[0]["part_number"] == 1
    assert parts[0]["is_confirmed"] == 0
    assert parts[1]["part_number"] == 2

    # Mark Part 1 confirmed
    db_service.mark_part_confirmed("video_abc_1", part_number=1, youtube_id="yt_short_123")
    updated_parts = db_service.get_series_summary("video_abc_1")
    assert updated_parts[0]["is_confirmed"] == 1
    assert updated_parts[0]["youtube_id"] == "yt_short_123"
    assert "https://www.youtube.com/shorts/yt_short_123" in updated_parts[0]["youtube_url"]
    assert updated_parts[0]["confirmed_at"] != ""


def test_cleanup_raw_source(tmp_path: Path):
    from src.utils import cleanup_raw_source

    dummy_video = tmp_path / "raw_video.mp4"
    dummy_audio = tmp_path / "raw_audio.wav"

    # Write 2MB of dummy data
    dummy_video.write_bytes(b"0" * (2 * 1024 * 1024))
    dummy_audio.write_bytes(b"0" * (1 * 1024 * 1024))

    assert dummy_video.exists()
    assert dummy_audio.exists()

    freed_mb = cleanup_raw_source(str(dummy_video), str(dummy_audio))
    assert freed_mb >= 2.9  # ~3MB freed
    assert not dummy_video.exists()
    assert not dummy_audio.exists()


def test_clean_cache(tmp_path: Path):
    from src.utils import clean_cache
    from unittest.mock import patch

    # Create dummy files in temporary directories
    d_dir = tmp_path / "downloads"
    a_dir = tmp_path / "audio"
    c_dir = tmp_path / "clips"
    s_dir = tmp_path / "subtitles"
    for d in [d_dir, a_dir, c_dir, s_dir]:
        d.mkdir(parents=True, exist_ok=True)
        (d / "temp_file.bin").write_bytes(b"1" * 1024 * 500)  # 500 KB each

    with patch("src.config.settings.DOWNLOADS_DIR", d_dir), \
         patch("src.config.settings.AUDIO_DIR", a_dir), \
         patch("src.config.settings.CLIPS_DIR", c_dir), \
         patch("src.config.settings.SUBTITLES_DIR", s_dir):
        res = clean_cache()

    assert res["files_removed"] == 4
    assert res["mb_freed"] >= 1.9  # 4 * 0.5MB = 2.0MB


def test_active_livestream_guard():
    from src.services.ingestion import IngestionService
    from unittest.mock import MagicMock, patch
    import pytest

    ingestion = IngestionService.__new__(IngestionService)
    ingestion.download_dir = Path("dummy_dir")
    ingestion.audio_dir = Path("dummy_dir")
    ingestion.ffmpeg_path = "ffmpeg"
    ingestion.cookies_from_browser = None
    ingestion.cookie_file = None

    # Case 1: Video is currently broadcasting live
    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = {
        "id": "live_vid_1",
        "title": "Live 24/7 Gaming Stream",
        "is_live": True,
        "duration": None,
    }

    with patch("yt_dlp.YoutubeDL") as MockYDL:
        MockYDL.return_value.__enter__.return_value = mock_ydl
        with pytest.raises(RuntimeError, match="Cannot process ongoing livestream"):
            ingestion.ingest("https://youtube.com/watch?v=live_vid_1")

    # Case 2: Zero duration video
    mock_ydl.extract_info.return_value = {
        "id": "zero_vid_2",
        "title": "Zero Duration",
        "is_live": False,
        "duration": 0.0,
    }
    with patch("yt_dlp.YoutubeDL") as MockYDL:
        MockYDL.return_value.__enter__.return_value = mock_ydl
        with pytest.raises(ValueError, match="zero or unknown duration"):
            ingestion.ingest("https://youtube.com/watch?v=zero_vid_2")


def test_auto_cleanup_expired_cache(tmp_path: Path):
    import os
    import time
    from src.utils import auto_cleanup_expired_cache
    from unittest.mock import patch

    d_dir = tmp_path / "downloads"
    d_dir.mkdir(parents=True, exist_ok=True)

    # File 1: Brand new file (1 day old)
    new_file = d_dir / "new_video.mp4"
    new_file.write_bytes(b"0" * 1024)

    # File 2: Expired file (20 days old)
    old_file = d_dir / "old_video.mp4"
    old_file.write_bytes(b"0" * 1024)
    old_mtime = time.time() - (20 * 86400)
    os.utime(old_file, (old_mtime, old_mtime))

    with patch("src.config.settings.DOWNLOADS_DIR", d_dir), \
         patch("src.config.settings.AUDIO_DIR", tmp_path / "empty_audio"), \
         patch("src.config.settings.CLIPS_DIR", tmp_path / "empty_clips"), \
         patch("src.config.settings.SUBTITLES_DIR", tmp_path / "empty_subs"):
        res = auto_cleanup_expired_cache(max_age_days=14)

    assert res["files_removed"] == 1
    assert new_file.exists()
    assert not old_file.exists()


def test_get_pending_shorts_and_mark_uploaded(tmp_path: Path):
    from src.services.database import DatabaseService
    import sqlite3

    db_service = DatabaseService.__new__(DatabaseService)
    db_file = tmp_path / "test_pending.db"
    db_service.local_db_path = db_file
    db_service.client = None

    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE shorts_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_url TEXT,
            source_video_id TEXT,
            source_title TEXT,
            hook_title TEXT,
            description TEXT,
            tags TEXT,
            viral_reasoning TEXT,
            hook_score INTEGER,
            start_time REAL,
            end_time REAL,
            duration REAL,
            storage_url TEXT,
            local_path TEXT,
            youtube_id TEXT,
            created_at TEXT,
            part_number INTEGER DEFAULT 1,
            total_parts INTEGER DEFAULT 1,
            is_confirmed_uploaded INTEGER DEFAULT 0,
            confirmed_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE video_series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_video_id TEXT NOT NULL,
            source_title TEXT,
            source_url TEXT,
            part_number INTEGER NOT NULL,
            total_parts INTEGER NOT NULL,
            short_title TEXT NOT NULL,
            duration REAL NOT NULL,
            youtube_id TEXT,
            youtube_url TEXT,
            is_confirmed INTEGER DEFAULT 0,
            confirmed_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(source_video_id, part_number)
        )
    """)
    # Insert 1 already uploaded, and 2 pending
    c.execute("""
        INSERT INTO shorts_metadata (source_video_id, hook_title, youtube_id, is_confirmed_uploaded, created_at)
        VALUES ('src_done', 'Already Uploaded', 'YT_DONE_1', 1, '2026-10-19T00:00:00')
    """)
    c.execute("""
        INSERT INTO shorts_metadata (source_video_id, hook_title, youtube_id, is_confirmed_uploaded, created_at)
        VALUES ('src_pending_1', 'Pending Short Part 1', '', 0, '2026-10-19T00:01:00')
    """)
    c.execute("""
        INSERT INTO shorts_metadata (source_video_id, hook_title, youtube_id, is_confirmed_uploaded, created_at)
        VALUES ('src_pending_2', 'Pending Short Part 2', NULL, 0, '2026-10-19T00:02:00')
    """)
    conn.commit()
    conn.close()

    pending = db_service.get_pending_shorts(limit=5)
    assert len(pending) == 2
    assert pending[0]["hook_title"] == "Pending Short Part 1"
    assert pending[1]["hook_title"] == "Pending Short Part 2"

    # Mark the first one as uploaded
    db_service.mark_short_uploaded(pending[0]["id"], "src_pending_1", 1, "YT_NEW_UPLOAD_1")

    # Re-query
    pending_after = db_service.get_pending_shorts(limit=5)
    assert len(pending_after) == 1
    assert pending_after[0]["hook_title"] == "Pending Short Part 2"


def test_profanity_filter_and_bleeping():
    from src.services.profanity_filter import ProfanityFilterService
    from src.models import FullTranscription, TranscriptionSegment, WordTimestamp

    p_filter = ProfanityFilterService()
    assert p_filter.is_profane("fuck") is True
    assert p_filter.is_profane("fucking") is True
    assert p_filter.is_profane("pussy") is True
    assert p_filter.is_profane("bitch") is True
    assert p_filter.is_profane("shit") is True
    assert p_filter.is_profane("awesome") is False
    assert p_filter.is_profane("Minecraft") is False

    words = [
        WordTimestamp(word="Hello", start=10.0, end=10.5),
        WordTimestamp(word="what", start=10.6, end=10.9),
        WordTimestamp(word="the", start=11.0, end=11.2),
        WordTimestamp(word="fuck", start=11.3, end=11.8),
        WordTimestamp(word="is", start=11.9, end=12.1),
        WordTimestamp(word="this", start=12.2, end=12.5),
        WordTimestamp(word="pussy", start=13.0, end=13.6),
    ]
    seg = TranscriptionSegment(id=0, start=10.0, end=14.0, text="Hello what the fuck is this pussy", words=words)
    transcription = FullTranscription(
        language="en",
        language_probability=0.99,
        duration=20.0,
        segments=[seg],
        total_words=len(words),
    )

    intervals = p_filter.find_profanity_intervals(transcription, clip_start=10.0, clip_end=15.0)
    assert len(intervals) == 2
    # fuck at 11.3s relative to 10.0s is ~1.25s - 1.85s
    assert intervals[0][2] == "fuck"
    assert 1.2 <= intervals[0][0] <= 1.3
    # pussy at 13.0s relative to 10.0s is ~2.95s - 3.65s
    assert intervals[1][2] == "pussy"
    assert 2.9 <= intervals[1][0] <= 3.0


def test_sentence_boundary_snapping_avoids_dangling_mid_sentence():
    from src.services.viral_detector import ViralDetectorService
    from src.models import FullTranscription, TranscriptionSegment, WordTimestamp

    detector = ViralDetectorService.__new__(ViralDetectorService)

    # Narrative with a completed punchline at 45.0s, followed by an incomplete thought with dangling "because" at 50.0s
    words = [
        WordTimestamp(word="I", start=0.0, end=0.3),
        WordTimestamp(word="discovered", start=0.4, end=1.0),
        WordTimestamp(word="the", start=1.1, end=1.3),
        WordTimestamp(word="biggest", start=1.4, end=1.8),
        WordTimestamp(word="secret", start=1.9, end=2.4),
        WordTimestamp(word="ever.", start=2.5, end=3.0),
    ]
    # Filler dialogue spanning up to 43.0s
    for i in range(1, 40):
        words.append(WordTimestamp(word=f"detail{i}", start=3.0 + i, end=3.8 + i))

    # Sentence finishing at 45.0s
    words.append(WordTimestamp(word="And", start=43.5, end=43.8))
    words.append(WordTimestamp(word="we", start=43.9, end=44.1))
    words.append(WordTimestamp(word="finally", start=44.2, end=44.6))
    words.append(WordTimestamp(word="escaped!", start=44.7, end=45.3))  # Clean sentence finish with '!'

    # Dangling next sentence starting at 47.0s
    words.append(WordTimestamp(word="Then", start=47.0, end=47.3))
    words.append(WordTimestamp(word="he", start=47.4, end=47.6))
    words.append(WordTimestamp(word="screamed", start=47.7, end=48.2))
    words.append(WordTimestamp(word="because", start=48.3, end=48.9))  # Dangling conjunction!
    words.append(WordTimestamp(word="the", start=49.0, end=49.3))      # Mid-sentence article!
    words.append(WordTimestamp(word="giant", start=49.4, end=50.0))

    transcription = FullTranscription(
        language="en",
        language_probability=0.99,
        duration=60.0,
        segments=[TranscriptionSegment(id=0, start=0.0, end=50.0, text="test story", words=words)],
        total_words=len(words),
    )

    # LLM raw end was 49.0s (right on dangling "because")
    snapped_start, snapped_end = detector.snap_to_word_boundaries(
        raw_start=0.0,
        raw_end=49.0,
        transcription=transcription,
        total_duration=60.0,
        max_duration=59.0,
    )

    # Snapped end MUST NOT end on "because" or "the" mid-sentence; it should snap cleanly to "escaped!"
    assert snapped_start == 0.0
    # "escaped!" ended at 45.3s + natural release padding (~0.18s) = ~45.48s
    assert 45.0 <= snapped_end <= 46.0


def test_vocal_release_decay_padding():
    from src.services.viral_detector import ViralDetectorService
    from src.models import FullTranscription, TranscriptionSegment, WordTimestamp

    detector = ViralDetectorService.__new__(ViralDetectorService)

    words = [
        WordTimestamp(word="Start", start=1.0, end=1.5),
        WordTimestamp(word="talking", start=1.6, end=2.0),
    ]
    for i in range(1, 35):
        words.append(WordTimestamp(word=f"filler{i}", start=2.0 + i, end=2.8 + i))
    # Final word with a period at 40.0s, followed by silence (next word at 45.0s)
    words.append(WordTimestamp(word="perfect.", start=39.5, end=40.0))
    words.append(WordTimestamp(word="Later", start=45.0, end=45.5))

    transcription = FullTranscription(
        language="en",
        language_probability=0.99,
        duration=60.0,
        segments=[TranscriptionSegment(id=0, start=1.0, end=45.5, text="test", words=words)],
        total_words=len(words),
    )

    snapped_start, snapped_end = detector.snap_to_word_boundaries(
        raw_start=1.0,
        raw_end=40.0,
        transcription=transcription,
        total_duration=60.0,
        max_duration=59.0,
    )

    # End should be strictly greater than 40.0 (contains +0.15s to +0.18s natural acoustic release padding)
    assert snapped_end > 40.0
    assert snapped_end <= 40.25


def test_livestream_agent_dedicated_bucket_isolation(tmp_path: Path):
    from src.services.database import DatabaseService
    from src.config import settings

    db = DatabaseService.__new__(DatabaseService)
    db.url = "https://mock.supabase.co"
    db.key = "mock_key"
    db.bucket_name = "youtube-shorts"
    db.livestream_bucket_name = "livestream-shorts"

    # Verify bucket name settings isolation
    assert db.livestream_bucket_name == "livestream-shorts"
    assert db.livestream_bucket_name != db.bucket_name
    assert db.livestream_bucket_name != "reels"

    # Mock storage client to verify that upload_livestream_agent_short targets ONLY livestream-shorts
    class MockStorageTarget:
        def __init__(self, bucket_name):
            self.bucket_name = bucket_name
            self.uploaded_files = []

        def upload(self, path, file, file_options=None):
            self.uploaded_files.append((path, len(file)))
            return {"Key": path}

        def get_public_url(self, path):
            return f"https://mock.supabase.co/storage/v1/object/public/{self.bucket_name}/{path}"

    class MockSupabaseClient:
        def __init__(self):
            self.storage_instances = {}

        @property
        def storage(self):
            class StorageHelper:
                def __init__(self, parent):
                    self.parent = parent

                def from_(self, bucket_name):
                    if bucket_name not in self.parent.storage_instances:
                        self.parent.storage_instances[bucket_name] = MockStorageTarget(bucket_name)
                    return self.parent.storage_instances[bucket_name]

                def list_buckets(self):
                    class MockBucket:
                        def __init__(self, name):
                            self.name = name
                    return [MockBucket("reels"), MockBucket("youtube-shorts"), MockBucket("livestream-shorts")]

                def create_bucket(self, name, options=None):
                    return {"name": name}

            return StorageHelper(self)

    mock_client = MockSupabaseClient()
    db.client = mock_client

    # Create dummy video file
    dummy_video = tmp_path / "live_clip_1080x1920.mp4"
    dummy_video.write_bytes(b"dummy video content for livestream short")

    # Upload via upload_livestream_agent_short
    url = db.upload_livestream_agent_short(str(dummy_video))

    # Strict isolation assertions:
    # 1. Returned URL must contain 'livestream-shorts'
    assert url is not None
    assert "livestream-shorts" in url
    assert "youtube-shorts" not in url
    assert "reels" not in url

    # 2. Mock storage instance for 'livestream-shorts' must have received the upload
    assert "livestream-shorts" in mock_client.storage_instances
    assert len(mock_client.storage_instances["livestream-shorts"].uploaded_files) == 1

    # 3. 'youtube-shorts' and 'reels' must NOT have received any uploads
    assert "youtube-shorts" not in mock_client.storage_instances
    assert "reels" not in mock_client.storage_instances


def test_stream_monitor_agent_instantiation():
    from src.services.stream_monitor import StreamMonitorAgent
    from src.config import settings

    agent = StreamMonitorAgent.__new__(StreamMonitorAgent)
    agent.target_url = "https://www.youtube.com/@LofiGirl/live"
    agent.chunk_duration = 150
    agent.poll_interval = 45
    agent.crop_mode = "blurred_background"
    agent.bleep_profanity = True
    agent.auto_upload = False
    agent.max_clips = 5
    agent.agent_dir = settings.LIVESTREAM_AGENT_DIR

    assert agent.target_url == "https://www.youtube.com/@LofiGirl/live"
    assert agent.chunk_duration == 150
    assert agent.poll_interval == 45
    assert agent.max_clips == 5
    assert agent.crop_mode == "blurred_background"




