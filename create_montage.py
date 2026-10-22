#!/usr/bin/env python3
"""
CLI Tool: Automated Longform Montage & Highlights Composer
Automatically executes peak audio detection, extracts top unhinged/peak moments,
applies 1.18x punch-in zooms and sound design, and renders a finished viral montage video.

Usage:
    python create_montage.py --creator ishowspeed --url "https://www.youtube.com/watch?v=..." --target-duration 720
"""

import sys

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import argparse
from pathlib import Path
from src.console import print_banner, console, log_error, log_info
from src.services.montage_composer import MontageComposer


def main() -> None:
    print_banner()

    parser = argparse.ArgumentParser(
        description="Autonomous Longform Montage Builder: Peak Audio Detection, Dynamic Punch-Ins, and YouTube Audio Mastering."
    )
    parser.add_argument(
        "--url",
        type=str,
        required=True,
        help="YouTube video/livestream URL or path to local video file",
    )
    parser.add_argument(
        "--creator",
        type=str,
        default="ishowspeed",
        choices=["ishowspeed", "mrbeast", "generic"],
        help="Creator pacing & style preset (default: ishowspeed)",
    )
    parser.add_argument(
        "--target-duration",
        type=int,
        default=720,
        help="Target runtime in seconds (default: 720 for 12 minutes; dynamically adapts if source is shorter)",
    )
    parser.add_argument(
        "--clip-count",
        type=int,
        default=20,
        help="Target number of peak clips to extract (default: 20)",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        default=False,
        help="Upload finished montage to Supabase longform-videos storage bucket",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        default=True,
        help="Keep montage locally and skip Supabase upload (default: True for local test runs)",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default="",
        help="Custom scene directives or timestamps to pin (e.g. 'anchor at 14:20; find loud screams')",
    )
    parser.add_argument(
        "--search-engine",
        type=str,
        default="both",
        choices=["both", "hybrid", "twelvelabs"],
        help="AI scene search engine: 'both' (Ensemble), 'hybrid' (Option 1), 'twelvelabs' (Option 2)",
    )

    args = parser.parse_args()

    # Determine whether to upload to Supabase
    should_upload = args.upload and not args.no_upload

    composer = MontageComposer()
    try:
        res = composer.create_montage(
            url=args.url,
            creator=args.creator,
            target_duration=args.target_duration,
            clip_count=args.clip_count,
            upload_to_supabase=should_upload,
            prompt=args.prompt,
            search_engine=args.search_engine,
        )
        console.print(f"[bold green][SUCCESS][/bold green] Montage generated successfully: [cyan]{res['video_path']}[/cyan]")
    except Exception as e:
        log_error("MONTAGE", f"Execution failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
