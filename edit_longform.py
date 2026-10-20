#!/usr/bin/env python3
"""
CLI entry point for Longform Video Editor Agent.
Transforms raw livestream VODs into 7-9 minute YouTube-ready narrative features.
"""

import sys
import argparse
from pathlib import Path

from src.services.longform_editor import LongformVideoEditor
from src.console import console


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transform multi-hour livestreams and VODs into 7-9 min YouTube feature videos."
    )
    parser.add_argument("--url", type=str, required=True, help="YouTube livestream or VOD URL")
    parser.add_argument(
        "--target-runtime",
        type=int,
        default=480,
        help="Target video length in seconds (strictly between 420s / 7m and 540s / 9m). Default: 480 (8m)",
    )
    parser.add_argument(
        "--focus-timestamp",
        type=float,
        default=0.0,
        help="Optional key moment timestamp in seconds (e.g. 4210 for Warden fight)",
    )

    args = parser.parse_args()

    # Parse timestamp from URL if provided (e.g. &t=4210s)
    focus_ts = args.focus_timestamp
    if focus_ts == 0.0 and "t=" in args.url:
        try:
            t_str = args.url.split("t=")[-1].split("&")[0].rstrip("s")
            focus_ts = float(t_str)
        except Exception:
            pass

    editor = LongformVideoEditor()
    res = editor.execute_edit_pipeline(
        url=args.url,
        focus_timestamp=focus_ts,
        target_runtime_sec=args.target_runtime,
    )
    print(f"\n[OK] Video generated successfully: {res['output_path']}")


if __name__ == "__main__":
    main()
