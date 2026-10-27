"""
Configuration management and environment loader.
Reads variables from .env and resolves system tool paths.
"""

import os
import shutil
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load .env from workspace root
load_dotenv()


def resolve_ffmpeg_path() -> str:
    """
    Find ffmpeg executable.
    Checks system PATH first, then falls back to imageio_ffmpeg bundled binary.
    Ensures standard 'ffmpeg.exe' alias exists and directory is on PATH.
    """
    path_from_env = os.getenv("FFMPEG_PATH")
    if path_from_env and os.path.exists(path_from_env):
        ffmpeg_dir = os.path.dirname(path_from_env)
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
        return path_from_env

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    try:
        import imageio_ffmpeg
        raw_exe = imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_dir = os.path.dirname(raw_exe)
        standard_exe = os.path.join(ffmpeg_dir, "ffmpeg.exe")
        if not os.path.exists(standard_exe) and os.path.exists(raw_exe):
            try:
                shutil.copyfile(raw_exe, standard_exe)
            except Exception:
                standard_exe = raw_exe

        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
        return standard_exe if os.path.exists(standard_exe) else raw_exe
    except Exception:
        return "ffmpeg"


class Settings:
    """Application settings and API credentials."""

    # Working Directories
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    OUTPUT_DIR: Path = BASE_DIR / "output"
    DOWNLOADS_DIR: Path = OUTPUT_DIR / "downloads"
    AUDIO_DIR: Path = OUTPUT_DIR / "audio"
    TRANSCRIPTS_DIR: Path = OUTPUT_DIR / "transcripts"
    CLIPS_DIR: Path = OUTPUT_DIR / "clips"
    SUBTITLES_DIR: Path = OUTPUT_DIR / "subtitles"
    LIVESTREAM_AGENT_DIR: Path = OUTPUT_DIR / "livestream_agent"
    LONGFORM_DIR: Path = OUTPUT_DIR / "longform_videos"

    # API Keys
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
    OPENROUTER_API_KEY: Optional[str] = os.getenv("OPENROUTER_API_KEY")
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    HF_TOKEN: Optional[str] = os.getenv("HF_TOKEN")
    TWELVELABS_API_KEY: Optional[str] = os.getenv("TWELVELABS_API_KEY")
    WHISPER_MODEL_SIZE: str = os.getenv("WHISPER_MODEL_SIZE", "base")

    # Supabase (Database & Storage)
    SUPABASE_URL: Optional[str] = os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    SUPABASE_STORAGE_BUCKET: str = os.getenv("SUPABASE_STORAGE_BUCKET", "reels")
    SUPABASE_SHORTS_BUCKET: str = os.getenv("SUPABASE_SHORTS_BUCKET", "youtube-shorts")
    SUPABASE_LIVESTREAM_SHORTS_BUCKET: str = os.getenv("SUPABASE_LIVESTREAM_SHORTS_BUCKET", "livestream-shorts")
    SUPABASE_LONGFORM_BUCKET: str = os.getenv("SUPABASE_LONGFORM_BUCKET", "longform-videos")

    # YouTube API OAuth Configuration
    YOUTUBE_CLIENT_SECRETS_FILE: str = os.getenv(
        "YOUTUBE_CLIENT_SECRETS_FILE",
        str(BASE_DIR / "client_secrets.json")
    )
    YOUTUBE_TOKEN_FILE: str = os.getenv(
        "YOUTUBE_TOKEN_FILE",
        str(BASE_DIR / "token.json")
    )
    YOUTUBE_TARGET_EMAIL: str = os.getenv("YOUTUBE_TARGET_EMAIL", "maharjansujan.official@gmail.com")
    YOUTUBE_TARGET_HANDLE: str = os.getenv("YOUTUBE_TARGET_HANDLE", "@MR.EIJI05")

    try:
        _acc_file = BASE_DIR / "dashboard" / "accounts.json"
        if _acc_file.exists():
            import json as _json
            with open(_acc_file, "r", encoding="utf-8") as _f:
                _acc_data = _json.load(_f)
            _act_id = _acc_data.get("active_id")
            for _a in _acc_data.get("accounts", []):
                if _a.get("id") == _act_id:
                    if _a.get("handle"):
                        YOUTUBE_TARGET_HANDLE = _a.get("handle")
                    if _a.get("email"):
                        YOUTUBE_TARGET_EMAIL = _a.get("email")
                    break
    except Exception:
        pass

    # FFmpeg Binary Path
    FFMPEG_PATH: str = resolve_ffmpeg_path()

    @classmethod
    def ensure_directories(cls) -> None:
        """Create necessary working directory tree if missing."""
        for directory in [cls.OUTPUT_DIR, cls.DOWNLOADS_DIR, cls.AUDIO_DIR, cls.TRANSCRIPTS_DIR, cls.CLIPS_DIR, cls.SUBTITLES_DIR, cls.LIVESTREAM_AGENT_DIR, cls.LONGFORM_DIR]:
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
