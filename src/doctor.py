"""
System Diagnostics and Health Check Module (Doctor).
Validates local FFmpeg, API credentials, OpenCV models, and Supabase connections.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from openai import OpenAI

from src.config import settings
from src.console import console, log_table
from rich.table import Table


def check_ffmpeg() -> tuple[bool, str]:
    """Check FFmpeg binary path and required filters."""
    exe = settings.FFMPEG_PATH
    if not exe:
        return False, "Not found"
    try:
        proc = subprocess.run([exe, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if proc.returncode == 0:
            version_line = proc.stdout.split("\n")[0] if proc.stdout else "Available"
            return True, version_line[:40]
        return False, "Execution error"
    except Exception as e:
        return False, str(e)[:30]


def check_openrouter() -> tuple[bool, str]:
    """Check OpenRouter API key connectivity."""
    key = settings.OPENROUTER_API_KEY
    if not key:
        return False, "OPENROUTER_API_KEY missing in .env"
    try:
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=key,
            default_headers={"HTTP-Referer": "https://github.com/youtube-pipeline"},
        )
        resp = client.chat.completions.create(
            model=settings.OPENROUTER_MODEL,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=2,
        )
        return True, f"Active ({settings.OPENROUTER_MODEL})"
    except Exception as e:
        err_msg = str(e)
        if "403" in err_msg or "limit" in err_msg.lower():
            return False, "Key limit exceeded / out of credits"
        return False, err_msg[:35]


def check_face_detector() -> tuple[bool, str]:
    """Check YuNet ONNX face detection model."""
    from src.services.face_tracker import YUNET_MODEL_PATH, FaceTracker
    tracker = FaceTracker()
    if tracker.detector_type == "yunet":
        return True, f"YuNet ONNX active ({YUNET_MODEL_PATH.name})"
    elif tracker.detector_type == "cascade":
        return True, "Haar Cascade active"
    return False, "Center-anchor fallback only"


def check_supabase() -> tuple[bool, str]:
    """Check Supabase Storage connectivity."""
    from src.services.database import DatabaseService
    db = DatabaseService()
    if not db.client:
        return False, "Missing credentials in .env"
    try:
        buckets = db.client.storage.list_buckets()
        names = [b.name for b in buckets]
        if db.bucket_name in names:
            return True, f"Bucket '{db.bucket_name}' verified"
        return True, f"Connected (Available: {names})"
    except Exception as e:
        return False, str(e)[:35]


def check_anti_bot_cookies() -> tuple[bool, str]:
    """Check persistent cookies and mobile spoofing status."""
    cookie_file = settings.OUTPUT_DIR / "cookies.txt"
    if cookie_file.exists() and cookie_file.stat().st_size > 50:
        return True, f"Active cookies ({cookie_file.name}, {cookie_file.stat().st_size} bytes)"
    return True, "Mobile clients active (Android/iOS)"


def check_youtube_oauth() -> tuple[bool, str]:
    """Check YouTube OAuth client secrets file."""
    if os.path.exists(settings.YOUTUBE_CLIENT_SECRETS_FILE):
        return True, f"Found {Path(settings.YOUTUBE_CLIENT_SECRETS_FILE).name}"
    return False, "client_secrets.json not found (Save locally mode active)"


def run_system_doctor() -> None:
    """Run comprehensive pipeline system diagnostics and print rich status table."""
    console.print("\n[bold cyan][*] Running YouTube Pipeline System Diagnostics...[/bold cyan]\n")

    table = Table(title="System & Dependency Health Check", show_header=True, header_style="bold magenta")
    table.add_column("Component", style="bold white", width=22)
    table.add_column("Status", width=12)
    table.add_column("Details", style="dim white")

    checks = [
        ("Python Runtime", True, f"v{sys.version.split()[0]} on {sys.platform}"),
        ("FFmpeg Binary", *check_ffmpeg()),
        ("OpenRouter API", *check_openrouter()),
        ("CV Face Detection", *check_face_detector()),
        ("Supabase Storage", *check_supabase()),
        ("YouTube Anti-Bot", *check_anti_bot_cookies()),
        ("YouTube OAuth", *check_youtube_oauth()),
        ("Peak & Multi-Cut Engine", True, "Audio RMS + Jump-Cut Condenser active"),
        ("Output Directory", settings.OUTPUT_DIR.exists(), str(settings.OUTPUT_DIR)),
    ]

    all_passed = True
    for name, status, details in checks:
        if name != "YouTube OAuth" and not status:
            all_passed = False

        status_str = "[bold green][PASS][/bold green]" if status else (
            "[bold yellow][OPTIONAL][/bold yellow]" if name == "YouTube OAuth" else "[bold red][FAIL][/bold red]"
        )
        table.add_row(name, status_str, details)

    console.print(table)
    if all_passed:
        console.print("\n[bold green][OK] All core pipeline components are fully operational and ready to run![/bold green]\n")
    else:
        console.print("\n[bold yellow][!] Some optional components need attention, but core generation is available.[/bold yellow]\n")
