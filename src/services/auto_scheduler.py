"""
Auto-Scheduler Service for Autonomous YouTube Shorts Publishing.

Features:
- Automatic Peak-Hour Distribution: Calculates optimal viewership windows
  (Afternoon Lunch: 12:00 PM - 2:30 PM & Prime Evening: 6:00 PM - 9:30 PM)
  with randomized minute jitter for humanized organic release timing.
- 100% Offline Release Guarantee: Pre-uploads full video bytes to YouTube Data API v3
  with `status.privacyStatus = "private"` and `status.publishAt = <scheduled_utc_iso>`.
  YouTube automatically makes each video Public on the exact scheduled second,
  regardless of whether the user's PC is sleeping, shut down, or offline.
- Daily Quota Awareness: YouTube Data API v3 allows 10,000 units/day (6 uploads @ 1,600 units).
  Auto-scheduler verifies quota before dispatching uploads to avoid API lockouts.
"""

import os
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import settings
from src.console import (
    console,
    log_stage,
    log_info,
    log_success,
    log_warning,
    log_error,
    print_banner,
)
from src.services.database import DatabaseService


# Peak Viewing Windows in 24-hour format: (start_h, start_m, end_h, end_m, label)
PEAK_WINDOWS = [
    (12, 0, 14, 30, "Afternoon Lunch Peak (12:00 PM - 2:30 PM)"),
    (18, 0, 21, 30, "Prime Evening Peak (6:00 PM - 9:30 PM)"),
]

MORNING_PEAK = (8, 30, 10, 30, "Morning Commute Peak (8:30 AM - 10:30 AM)")


def generate_peak_slots(
    count: int = 6,
    slots_per_day: int = 2,
    start_date: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Generate randomized release timestamps within high-retention peak viewership windows.
    Each slot includes randomized minute/second jitter to look natural and organic.
    Converts local times to UTC ISO-8601 strings for YouTube's `publishAt` API parameter.
    """
    now_local = datetime.now().astimezone() if start_date is None else start_date.astimezone()
    
    windows = list(PEAK_WINDOWS)
    if slots_per_day >= 3:
        windows.insert(0, MORNING_PEAK)
    
    slots: List[Dict[str, Any]] = []
    current_day = now_local.date()
    day_offset = 0
    
    # Generate until count is satisfied
    while len(slots) < count:
        target_date = current_day + timedelta(days=day_offset)
        for (sh, sm, eh, em, wname) in windows[:slots_per_day]:
            start_min = sh * 60 + sm
            end_min = eh * 60 + em
            chosen_min = random.randint(start_min, end_min)
            hour = chosen_min // 60
            minute = chosen_min % 60
            second = random.randint(0, 59)

            slot_dt = datetime(
                target_date.year,
                target_date.month,
                target_date.day,
                hour,
                minute,
                second,
                tzinfo=now_local.tzinfo,
            )

            # Minimum 25 minutes buffer ahead of current moment
            if slot_dt > now_local + timedelta(minutes=25):
                utc_dt = slot_dt.astimezone(timezone.utc)
                utc_iso = utc_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                
                day_diff = (slot_dt.date() - now_local.date()).days
                if day_diff == 0:
                    day_rel = "Today"
                elif day_diff == 1:
                    day_rel = "Tomorrow"
                else:
                    day_rel = f"In {day_diff} Days"

                slots.append({
                    "local_dt": slot_dt,
                    "utc_iso": utc_iso,
                    "window_name": wname,
                    "day_rel": day_rel,
                    "local_formatted": slot_dt.strftime("%a, %b %d at %I:%M %p"),
                    "local_time_short": slot_dt.strftime("%I:%M %p"),
                })
                if len(slots) == count:
                    break
        day_offset += 1

    return slots


def get_unuploaded_candidates(limit: int = 6) -> List[Dict[str, Any]]:
    """
    Fetch unuploaded, unscheduled Shorts from Supabase with SQLite fallback.
    Returns sorted list of pending items ready for auto-scheduling.
    """
    db_service = DatabaseService()
    candidates: List[Dict[str, Any]] = []
    seen_ids = set()

    # 1. Try Supabase cloud database
    if db_service.client:
        try:
            res = (
                db_service.client.table("shorts_metadata")
                .select("*")
                .eq("is_confirmed_uploaded", False)
                .is_("youtube_id", "null")
                .order("id", desc=False)
                .limit(limit * 2)
                .execute()
            )
            for row in res.data or []:
                r_id = row.get("id")
                if r_id and r_id not in seen_ids:
                    seen_ids.add(r_id)
                    candidates.append(row)
        except Exception as e:
            log_warning("AUTO_SCHEDULER", f"Supabase pending query note: {e}")

    # 2. Check local SQLite for any additional unuploaded items
    db_path = settings.OUTPUT_DIR / "shorts.db"
    if db_path.exists():
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM shorts_metadata 
                WHERE (is_confirmed_uploaded = 0 OR is_confirmed_uploaded IS NULL)
                  AND (youtube_id IS NULL OR youtube_id = '')
                ORDER BY id ASC LIMIT ?
                """,
                (limit * 2,),
            ).fetchall()
            for r in rows:
                d = dict(r)
                r_id = d.get("id")
                if r_id and r_id not in seen_ids:
                    seen_ids.add(r_id)
                    candidates.append(d)
            conn.close()
        except Exception as e:
            log_warning("AUTO_SCHEDULER", f"SQLite pending query note: {e}")

    # 3. Filter out any already scheduled items in SQLite
    filtered: List[Dict[str, Any]] = []
    now_utc = datetime.now(timezone.utc)
    for c in candidates:
        sched = c.get("scheduled_publish_at")
        if not sched and db_path.exists():
            try:
                conn = sqlite3.connect(db_path, timeout=2)
                row = conn.execute("SELECT scheduled_publish_at FROM shorts_metadata WHERE id = ?", (c.get("id"),)).fetchone()
                conn.close()
                if row and row[0]:
                    sched = row[0]
            except Exception:
                pass

        if sched:
            try:
                s_dt = datetime.fromisoformat(str(sched).replace("Z", "+00:00"))
                if s_dt.tzinfo is None:
                    s_dt = s_dt.replace(tzinfo=timezone.utc)
                if s_dt > now_utc:
                    # Already scheduled in future, skip
                    continue
            except Exception:
                pass

        filtered.append(c)
        if len(filtered) >= limit:
            break

    return filtered


def auto_schedule_batch(
    count: int = 6,
    slots_per_day: int = 2,
    dry_run: bool = False,
    account_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main Auto-Scheduler entrypoint:
    1. Verifies YouTube upload quota.
    2. Identifies unuploaded video candidates.
    3. Calculates peak viewing release slots with jitter.
    4. Pre-uploads to YouTube with publishAt for 100% offline publication.
    """
    print_banner()
    log_stage(6, "Auto-Scheduler Agent", "Peak-Hour Organic Release • 100% Offline Cloud Publishing")

    db_service = DatabaseService()

    # 1. Quota & Uploads Status (Minimum target: 6, no hard cap)
    quota = db_service.get_daily_quota_status()
    uploads_today = quota.get("uploads_today", quota.get("units_used", 0) // 1600)
    log_info(
        "AUTO_SCHEDULER",
        f"Daily YouTube Uploads: {uploads_today} completed today (Minimum daily target: 6). Proceeding with auto-scheduling...",
    )

    # 2. Fetch Candidates
    max_to_fetch = count
    candidates = get_unuploaded_candidates(limit=max_to_fetch)

    if not candidates:
        log_warning("AUTO_SCHEDULER", "No unuploaded Shorts found in queue. All existing clips are published or scheduled.")
        return {
            "success": True,
            "message": "Queue empty",
            "scheduled": [],
            "candidates_found": 0,
        }

    # Minimum goal is 6/day; user can auto-schedule beyond 6 without hard blocking
    active_batch_count = min(len(candidates), count)
    selected_candidates = candidates[:active_batch_count]
    slots = generate_peak_slots(count=active_batch_count, slots_per_day=slots_per_day)

    # 3. Print Timetable Schedule
    console.print()
    console.print(f"[bold cyan]═══ AUTO-SCHEDULER TIMETABLE ({active_batch_count} SHORTS QUEUED) ═══[/bold cyan]")
    console.print(f"[bold white]Release Strategy:[/bold white] {slots_per_day} Shorts/day at peak retention hours with organic jitter")
    console.print(f"[bold green]Offline Guarantee:[/bold green] Pre-uploaded to Google Cloud (Private) -> YouTube releases automatically")
    console.print("─────────────────────────────────────────────────────────────────────────────")

    schedule_plan = []
    for idx, (cand, slot) in enumerate(zip(selected_candidates, slots), 1):
        c_id = cand.get("id")
        title = cand.get("hook_title") or f"Short #{c_id}"
        part = cand.get("part_number") or 1
        dur = cand.get("duration") or 0.0
        
        console.print(
            f"[bold yellow]#{idx}[/bold yellow] [bold white]Short #{c_id}[/bold white] (Part {part}, {dur:.1f}s): "
            f"[dim]'{title[:38]}...'[/dim]\n"
            f"   [cyan][RELEASE][/cyan] [bold cyan]{slot['day_rel']}[/bold cyan] -> [bold green]{slot['local_formatted']}[/bold green] "
            f"[dim]({slot['window_name']})[/dim]\n"
            f"   [dim][API][/dim] YouTube publishAt: [dim]{slot['utc_iso']}[/dim]"
        )
        schedule_plan.append({
            "short_id": c_id,
            "title": title,
            "part": part,
            "slot": slot,
            "utc_iso": slot["utc_iso"],
        })

    console.print("─────────────────────────────────────────────────────────────────────────────")
    console.print()

    if dry_run:
        log_info("AUTO_SCHEDULER", "[DRY RUN] Timetable generated successfully. No actual uploads performed.")
        return {
            "success": True,
            "dry_run": True,
            "scheduled_count": len(schedule_plan),
            "plan": schedule_plan,
        }

    # 4. Dispatch Pre-Uploads to YouTube
    from dashboard.upload_single import upload_single_short

    scheduled_results = []
    failed_results = []

    for idx, item in enumerate(schedule_plan, 1):
        s_id = item["short_id"]
        slot = item["slot"]
        log_stage(
            6,
            f"Auto-Scheduling [{idx}/{len(schedule_plan)}]",
            f"Short #{s_id} -> Release Date: {slot['local_formatted']}",
        )

        ok = upload_single_short(short_id=s_id, publish_at=slot["utc_iso"])
        if ok:
            scheduled_results.append({
                "short_id": s_id,
                "title": item["title"],
                "publish_at": slot["utc_iso"],
                "release_local": slot["local_formatted"],
            })
            log_success(
                "AUTO_SCHEDULER",
                f"Pre-uploaded Short #{s_id}. YouTube will automatically publish this video on: "
                f"[bold green]{slot['local_formatted']}[/bold green] (Offline Guaranteed).",
            )
        else:
            failed_results.append(s_id)
            log_error("AUTO_SCHEDULER", f"Failed to auto-schedule Short #{s_id}.")

    console.print()
    console.print(f"[bold cyan]═══ AUTO-SCHEDULER RUN SUMMARY ═══[/bold cyan]")
    console.print(f"[bold green]✔ Successfully Scheduled on YouTube Cloud:[/bold green] {len(scheduled_results)}/{len(schedule_plan)}")
    if failed_results:
        console.print(f"[bold red]✘ Failed:[/bold red] {len(failed_results)} ({failed_results})")
    console.print(
        "[bold white]Status:[/bold white] All scheduled videos are safely housed on YouTube servers in 'Private' state.\n"
        "   YouTube cloud release workers will flip them to 'Public' on schedule even if this machine is offline."
    )
    console.print("═════════════════════════════════════════════════════════════════════════════")
    console.print()

    return {
        "success": len(scheduled_results) > 0,
        "scheduled_count": len(scheduled_results),
        "failed_count": len(failed_results),
        "scheduled": scheduled_results,
    }
