"""
Autonomous Peak-Hour YouTube Auto-Scheduler CLI.

Uploads up to 6 Shorts pre-scheduled to YouTube's cloud servers with `publishAt`
randomized inside peak viewership windows (Afternoon Lunch & Prime Evening).
Videos publish 100% autonomously on YouTube's servers regardless of system power/sleep state.

Usage:
    python auto_schedule.py                     # Schedule batch of up to 6 shorts at peak hours
    python auto_schedule.py --dry-run           # Preview schedule timetable without uploading
    python auto_schedule.py --count 3           # Schedule custom number of shorts
    python auto_schedule.py --slots-per-day 1   # Distribute 1 short per day
    python auto_schedule.py --list-pending      # List pending shorts ready to be scheduled
"""

import argparse
import sys
from pathlib import Path

# Fix Windows console UTF-8 encoding
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.console import console, print_banner, log_info, log_stage
from src.services.auto_scheduler import (
    auto_schedule_batch,
    get_unuploaded_candidates,
    generate_peak_slots,
)


def main():
    parser = argparse.ArgumentParser(
        description="Autonomous YouTube Shorts Peak-Hour Auto-Scheduler (100% Offline Guaranteed)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--count",
        type=int,
        default=6,
        help="Number of videos to auto-schedule (default: 6, max: 6 per daily API quota limit)",
    )
    parser.add_argument(
        "--slots-per-day",
        type=int,
        default=2,
        choices=[1, 2, 3],
        help="Number of release slots per day (default: 2, e.g. Lunch & Evening peaks)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the peak timetable and preview candidates without uploading to YouTube",
    )
    parser.add_argument(
        "--list-pending",
        action="store_true",
        help="List all unuploaded candidate Shorts currently waiting in the queue",
    )
    parser.add_argument(
        "--account",
        type=str,
        default=None,
        help="Target YouTube account ID (e.g. alternate, official)",
    )

    args = parser.parse_args()

    if args.list_pending:
        print_banner()
        log_stage(6, "Pending Upload Queue", "Inspecting unuploaded candidate Shorts")
        candidates = get_unuploaded_candidates(limit=20)
        console.print(f"\n[bold cyan]Found {len(candidates)} unuploaded candidate Shorts:[/bold cyan]\n")
        for idx, c in enumerate(candidates, 1):
            cid = c.get("id")
            title = c.get("hook_title") or f"Short #{cid}"
            part = c.get("part_number") or 1
            dur = c.get("duration") or 0.0
            console.print(f"  {idx}. [bold white]#{cid}[/bold white] (Part {part}, {dur:.1f}s) - [bold yellow]{title}[/bold yellow]")
        console.print()
        sys.exit(0)

    # Validate count
    count = max(1, min(args.count, 6))

    result = auto_schedule_batch(
        count=count,
        slots_per_day=args.slots_per_day,
        dry_run=args.dry_run,
        account_id=args.account,
    )

    if not result.get("success", False) and not args.dry_run:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
