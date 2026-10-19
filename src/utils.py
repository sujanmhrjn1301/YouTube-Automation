"""
Shared utility functions for file naming, slugification, and string formatting.
"""

import re
from typing import Any, Optional


def slugify_title(title: str, max_words: int = 6) -> str:
    """
    Converts video title into clean, readable slug without weird symbols or emojis.
    e.g. 'Eat Everything In A Grocery Store, Win $1,000,000' -> 'Eat_Everything_In_A_Grocery_Store'
    """
    clean = re.sub(r"[^\w\s-]", "", title)
    words = clean.strip().split()[:max_words]
    slug = "_".join(words)
    return slug if slug else "Video"


def generate_short_filename(
    title: str,
    video_id: Optional[str] = None,
    duration: Optional[float] = None,
    clip_index: Optional[int] = None,
    is_livestream: bool = False,
) -> str:
    """
    Generate clean, safe filename matching the YouTube title:
    e.g. 'Unlocking Secrets of 40% [Part 1] #Shorts' -> 'Unlocking_Secrets_of_40pct_Part_1_Shorts.mp4'
    Safe across Windows, Linux, URLs, and S3 / Supabase storage object keys.
    """
    clean = title.replace("#Shorts", "Shorts").replace("#shorts", "Shorts").replace("#", "")
    clean = clean.replace("%", "pct").replace("$", "")
    clean = re.sub(r'[\[\]\\/*?:"<>|!@+=;~`^,]', "", clean)
    words = [w.strip() for w in clean.split() if w.strip()]
    slug = "_".join(words) if words else "Short"
    # Ensure safe alphanumeric, dash, and underscore characters
    slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug)
    if not slug.endswith(".mp4"):
        return f"{slug}.mp4"
    return slug


def slice_transcription(transcription: Any, start_sec: float, end_sec: float) -> Any:
    """Extract a time-sliced sub-transcription window for localized peak evaluation."""
    from src.models import FullTranscription, TranscriptionSegment

    new_segs = []
    tot_words = 0
    for seg in transcription.segments:
        if seg.end >= start_sec and seg.start <= end_sec:
            matching_words = [w for w in seg.words if w.end >= start_sec and w.start <= end_sec]
            if matching_words:
                tot_words += len(matching_words)
                new_segs.append(
                    TranscriptionSegment(
                        id=seg.id,
                        start=matching_words[0].start,
                        end=matching_words[-1].end,
                        text=" ".join(w.word for w in matching_words),
                        words=matching_words,
                    )
                )
    return FullTranscription(
        language=transcription.language,
        language_probability=transcription.language_probability,
        duration=round(end_sec - start_sec, 2),
        segments=new_segs,
        total_words=tot_words,
    )


def cleanup_raw_source(video_path: str, audio_path: Optional[str] = None) -> float:
    """
    Delete specific raw downloaded video and extracted WAV audio to free space.
    Returns total MB freed.
    """
    from pathlib import Path
    freed_bytes = 0
    v_p = Path(video_path)
    if v_p.exists() and v_p.is_file():
        freed_bytes += v_p.stat().st_size
        try:
            v_p.unlink(missing_ok=True)
        except Exception:
            pass

    if audio_path:
        a_p = Path(audio_path)
        if a_p.exists() and a_p.is_file():
            freed_bytes += a_p.stat().st_size
            try:
                a_p.unlink(missing_ok=True)
            except Exception:
                pass

    return round(freed_bytes / (1024 * 1024), 2)


def clean_cache(
    include_downloads: bool = True,
    include_audio: bool = True,
    include_clips: bool = True,
    include_subtitles: bool = True,
) -> dict:
    """
    Purge cached raw videos, intermediate audio, clips, and subtitles.
    Preserves all final Shorts in output/ and database records.
    Returns: {"files_removed": int, "mb_freed": float, "categories": dict}
    """
    from pathlib import Path
    from src.config import settings

    target_dirs = []
    if include_downloads:
        target_dirs.append(("Raw Downloads", settings.DOWNLOADS_DIR))
    if include_audio:
        target_dirs.append(("Extracted Audio", settings.AUDIO_DIR))
    if include_clips:
        target_dirs.append(("Intermediate Clips", settings.CLIPS_DIR))
    if include_subtitles:
        target_dirs.append(("Subtitles (.ass)", settings.SUBTITLES_DIR))

    total_removed = 0
    total_bytes = 0
    cat_summary = {}

    for cat_name, directory in target_dirs:
        dir_removed = 0
        dir_bytes = 0
        if directory.exists():
            for f in directory.glob("*"):
                if f.is_file():
                    try:
                        sz = f.stat().st_size
                        f.unlink(missing_ok=True)
                        dir_removed += 1
                        dir_bytes += sz
                    except Exception:
                        pass
        cat_summary[cat_name] = {"files": dir_removed, "mb": round(dir_bytes / (1024 * 1024), 2)}
        total_removed += dir_removed
        total_bytes += dir_bytes

    return {
        "files_removed": total_removed,
        "mb_freed": round(total_bytes / (1024 * 1024), 2),
        "gb_freed": round(total_bytes / (1024 * 1024 * 1024), 3),
        "categories": cat_summary,
    }


def auto_cleanup_expired_cache(max_age_days: int = 14) -> dict:
    """
    Automatic age-based rolling garbage collection.
    Scans cache and temporary directories (downloads, audio, clips, subtitles)
    and removes any files older than max_age_days (default: 14 days).
    Always preserves final rendered Shorts in output/ and database records.
    Returns: {"files_removed": int, "mb_freed": float}
    """
    import time
    from pathlib import Path
    from src.config import settings

    target_dirs = [
        settings.DOWNLOADS_DIR,
        settings.AUDIO_DIR,
        settings.CLIPS_DIR,
        settings.SUBTITLES_DIR,
    ]

    now = time.time()
    cutoff_seconds = max_age_days * 86400  # 14 days in seconds
    total_removed = 0
    total_bytes = 0

    for directory in target_dirs:
        if directory.exists():
            for f in directory.glob("*"):
                if f.is_file():
                    try:
                        file_age = now - f.stat().st_mtime
                        if file_age > cutoff_seconds:
                            sz = f.stat().st_size
                            f.unlink(missing_ok=True)
                            total_removed += 1
                            total_bytes += sz
                    except Exception:
                        pass

    return {
        "files_removed": total_removed,
        "mb_freed": round(total_bytes / (1024 * 1024), 2),
    }
