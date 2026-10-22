"""
Studio Dashboard - local control server.

Thin wrapper around the existing pipeline CLIs. It never imports or modifies
backend code: every action is launched as a subprocess of the same commands
you would type in a terminal (cli.py, monitor_stream.py, upload_pending.py).

Run:
    python dashboard/server.py
Then open http://127.0.0.1:8765
"""

import copy
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
STATIC_DIR = Path(__file__).resolve().parent / "static"
DB_PATH = ROOT / "output" / "shorts.db"
HOST = "127.0.0.1"
PORT = int(os.environ.get("DASHBOARD_PORT", "8765"))

ACCOUNTS_FILE = ROOT / "dashboard" / "accounts.json"
TOKENS_DIR = ROOT / "tokens"

DEFAULT_ACCOUNTS_CONFIG = {
    "active_id": "alternate",
    "accounts": [
        {
            "id": "alternate",
            "email": "mhrznsuzan.alternate@gmail.com",
            "name": "Eiji Shorts",
            "handle": "@eijishorts",
            "token_file": "tokens/token_alternate.json",
        },
        {
            "id": "official",
            "email": "maharjansujan.official@gmail.com",
            "name": "Official Channel",
            "handle": "@MR.EIJI05",
            "token_file": "tokens/token_official.json",
        },
    ],
}


def _ensure_accounts_setup() -> Dict[str, Any]:
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    root_token = ROOT / "token.json"
    alt_token = TOKENS_DIR / "token_alternate.json"

    # If root token.json exists, initialize token_alternate.json with it if missing
    if root_token.exists() and not alt_token.exists():
        try:
            shutil.copyfile(root_token, alt_token)
        except Exception:
            pass

    if not ACCOUNTS_FILE.exists():
        state = copy.deepcopy(DEFAULT_ACCOUNTS_CONFIG)
        try:
            with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass
        return state

    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return copy.deepcopy(DEFAULT_ACCOUNTS_CONFIG)


def get_accounts_state() -> Dict[str, Any]:
    return _ensure_accounts_setup()


def save_accounts_state(state: Dict[str, Any]) -> None:
    try:
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def get_accounts_summary() -> Dict[str, Any]:
    state = get_accounts_state()
    active_id = state.get("active_id", "alternate")
    accounts_list = []
    for acc in state.get("accounts", []):
        t_path = ROOT / acc.get("token_file", "")
        is_auth = False
        ch_handle = acc.get("handle", "")
        if t_path.exists():
            try:
                with open(t_path, "r", encoding="utf-8") as tf:
                    data = json.load(tf)
                    is_auth = bool(data.get("refresh_token") or data.get("token"))
            except Exception:
                is_auth = False
        accounts_list.append({
            "id": acc["id"],
            "email": acc["email"],
            "name": acc.get("name", acc["email"]),
            "handle": ch_handle,
            "authenticated": is_auth,
            "active": acc["id"] == active_id,
        })
    return {
        "active_id": active_id,
        "accounts": accounts_list,
    }


def switch_active_account(target_id: str) -> Dict[str, Any]:
    state = get_accounts_state()
    found = False
    active_acc = None
    for acc in state.get("accounts", []):
        if acc["id"] == target_id:
            found = True
            active_acc = acc
            break
    if not found or not active_acc:
        raise ValueError(f"Account '{target_id}' not found.")
    state["active_id"] = target_id
    save_accounts_state(state)

    # Sync to root token.json so standalone CLIs also use this token automatically
    t_path = ROOT / active_acc.get("token_file", "")
    if t_path.exists():
        try:
            shutil.copyfile(t_path, ROOT / "token.json")
        except Exception:
            pass

    return get_accounts_summary()

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
STAGE_RE = re.compile(r"STAGE\s+(\d+):\s*([^\-\n]+?)(?:\s+-\s+(.*))?$")
URL_RE = re.compile(r"^https?://(www\.|m\.)?(youtube\.com|youtu\.be)/\S+$", re.IGNORECASE)

CROP_MODES = {"blurred_background", "center_crop", "face_tracking"}
MODEL_SIZES = {"tiny", "base", "small", "medium", "large-v3"}
MAX_LOG_LINES = 5000


# ─────────────────────────────────────────────────────────────
# Command builders (whitelisted, argv lists only - never a shell)
# ─────────────────────────────────────────────────────────────
def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def build_command(kind: str, opts: Dict[str, Any]) -> List[str]:
    py = sys.executable
    if kind == "process":
        url = str(opts.get("url", "")).strip()
        if not URL_RE.match(url):
            raise ValueError("Enter a valid YouTube video URL.")
        argv = [py, "cli.py", "--url", url]
        argv += ["--clips-count", str(_clamp_int(opts.get("clips"), 1, 10, 3))]
        crop = opts.get("crop", "blurred_background")
        if crop in CROP_MODES:
            argv += ["--crop-mode", crop]
        model = opts.get("model", "base")
        if model in MODEL_SIZES:
            argv += ["--model-size", model]
        if opts.get("autoUpload"):
            argv.append("--auto-upload")
        if opts.get("streamMode"):
            argv.append("--stream-mode")
        if opts.get("enableCaptions"):
            argv.append("--captions")
        else:
            argv.append("--no-captions")
        if opts.get("noBleep"):
            argv.append("--no-bleep-profanity")
        if opts.get("keepRaw"):
            argv.append("--keep-raw")
        if opts.get("prompt"):
            argv += ["--prompt", str(opts["prompt"]).strip()]
        if opts.get("searchEngine"):
            argv += ["--search-engine", str(opts["searchEngine"]).strip()]
        return argv

    if kind == "monitor":
        url = str(opts.get("url", "")).strip()
        if not URL_RE.match(url):
            raise ValueError("Enter a valid YouTube channel or livestream URL.")
        argv = [py, "monitor_stream.py", "--url", url]
        argv += ["--chunk-duration", str(_clamp_int(opts.get("chunk"), 60, 600, 150))]
        argv += ["--poll-interval", str(_clamp_int(opts.get("poll"), 15, 600, 45))]
        crop = opts.get("crop", "blurred_background")
        if crop in CROP_MODES:
            argv += ["--crop-mode", crop]
        if opts.get("once"):
            argv.append("--once")
        else:
            max_clips = _clamp_int(opts.get("maxClips"), 0, 500, 0)
            if max_clips:
                argv += ["--max-clips", str(max_clips)]
        if opts.get("autoUpload"):
            argv.append("--auto-upload")
        if opts.get("enableCaptions"):
            argv.append("--captions")
        else:
            argv.append("--no-captions")
        if opts.get("noBleep"):
            argv.append("--no-bleep-profanity")
        return argv

    if kind == "longform":
        url = str(opts.get("url", "")).strip()
        if not URL_RE.match(url):
            raise ValueError("Enter a valid YouTube livestream or video URL.")
        argv = [py, "edit_longform.py", "--url", url]
        if opts.get("targetRuntime"):
            argv += ["--target-runtime", str(_clamp_int(opts.get("targetRuntime"), 420, 540, 480))]
        if opts.get("focusTimestamp"):
            argv += ["--focus-timestamp", str(opts.get("focusTimestamp"))]
        if opts.get("prompt"):
            argv += ["--prompt", str(opts["prompt"]).strip()]
        if opts.get("searchEngine"):
            argv += ["--search-engine", str(opts["searchEngine"]).strip()]
        return argv

    if kind == "montage":
        url = str(opts.get("url", "")).strip()
        if not URL_RE.match(url):
            raise ValueError("Enter a valid YouTube video URL.")
        argv = [py, "create_montage.py", "--url", url]
        creator = str(opts.get("creator", "ishowspeed")).strip().lower()
        if creator in {"ishowspeed", "mrbeast", "generic"}:
            argv += ["--creator", creator]
        target_runtime = _clamp_int(opts.get("targetRuntime"), 120, 1800, 720)
        argv += ["--target-duration", str(target_runtime)]
        clip_count = _clamp_int(opts.get("clipCount"), 3, 40, 12)
        argv += ["--clip-count", str(clip_count)]
        if opts.get("upload"):
            argv.append("--upload")
        else:
            argv.append("--no-upload")
        if opts.get("prompt"):
            argv += ["--prompt", str(opts["prompt"]).strip()]
        if opts.get("searchEngine"):
            argv += ["--search-engine", str(opts["searchEngine"]).strip()]
        return argv

    if (kind == "upload_next"):
        return [py, "upload_pending.py"]
    if kind == "upload_single":
        short_id = str(opts.get("id", "")).strip()
        if not short_id or not short_id.isdigit():
            raise ValueError("Valid Short ID is required.")
        cmd = [py, "dashboard/upload_single.py", "--id", short_id]
        if opts.get("publish_at"):
            cmd.extend(["--publish-at", str(opts["publish_at"])])
        return cmd
    if kind == "upload_all":
        return [py, "cli.py", "--upload-all-pending"]
    if kind == "auto_schedule":
        count = _clamp_int(opts.get("count"), 1, 6, 6)
        slots_per_day = _clamp_int(opts.get("slots_per_day"), 1, 3, 2)
        cmd = [py, "auto_schedule.py", "--count", str(count), "--slots-per-day", str(slots_per_day)]
        if opts.get("dry_run"):
            cmd.append("--dry-run")
        if opts.get("account_id"):
            cmd.extend(["--account", str(opts["account_id"])])
        return cmd
    if kind == "doctor":
        return [py, "cli.py", "--doctor"]
    if kind == "auth":
        return [py, "cli.py", "--auth-youtube"]
    if kind == "clean":
        return [py, "cli.py", "--clean-cache"]

    raise ValueError(f"Unknown action: {kind}")


LABELS = {
    "process": "Create Shorts",
    "monitor": "Live Agent",
    "longform": "Longform Video Editor",
    "montage": "Viral Montage Builder",
    "upload_next": "Publish next",
    "upload_single": "Publish Short",
    "upload_all": "Publish all",
    "auto_schedule": "Auto-Scheduler (Peak Hours)",
    "doctor": "Health check",
    "auth": "YouTube auth",
    "clean": "Clean cache",
}


# ─────────────────────────────────────────────────────────────
# Job manager
# ─────────────────────────────────────────────────────────────
class Job:
    def __init__(self, kind: str, argv: List[str], opts: Dict[str, Any]) -> None:
        self.id = uuid.uuid4().hex[:10]
        self.kind = kind
        self.label = LABELS.get(kind, kind)
        self.argv = argv
        self.target = str(opts.get("url", "")) or None
        self.lines: List[Dict[str, Any]] = []
        self.stages: List[Dict[str, Any]] = []
        self.clips_done = 0
        self.clips_total = _clamp_int(opts.get("clips"), 1, 10, 0)
        self.current_clip = 1
        self.status = "running"
        self.exit_code: Optional[int] = None
        self.started = time.time()
        self.ended: Optional[float] = None
        self.proc: Optional[subprocess.Popen] = None
        self.lock = threading.Lock()
        self.seq = 0

    def classify(self, text: str) -> str:
        if "[X]" in text or "Traceback" in text or "Error:" in text:
            return "error"
        if "[!]" in text:
            return "warn"
        if "[OK]" in text:
            return "ok"
        if "STAGE " in text:
            return "stage"
        return "info"

    def add_line(self, raw: str) -> None:
        text = ANSI_RE.sub("", raw).rstrip("\r\n")
        if not text.strip():
            return
        # Drop pure box-drawing / separator lines for readability
        if re.fullmatch(r"[\s\-=─━│┃╭╮╰╯┏┓┗┛┡┩└┘┌┐├┤┬┴┼|+]+", text):
            return
        level = self.classify(text)
        with self.lock:
            self.seq += 1
            self.lines.append({"n": self.seq, "t": text, "l": level})
            if len(self.lines) > MAX_LOG_LINES:
                self.lines = self.lines[-MAX_LOG_LINES:]
            
            # Multi-clip progress detection: e.g. "2/6 videos done", "Processing Part 3/6", "Clipping Video 3/6"
            m_done = re.search(r"(\d+)/(\d+)\s+videos?\s+done", text, re.IGNORECASE)
            if m_done:
                self.clips_done = int(m_done.group(1))
                self.clips_total = int(m_done.group(2))
                self.current_clip = min(self.clips_total, self.clips_done + 1)
            else:
                m_start = re.search(r"(?:Clipping Video|Processing Part|Processing Short)\s+(\d+)/(\d+)", text, re.IGNORECASE)
                if m_start:
                    self.current_clip = int(m_start.group(1))
                    self.clips_total = int(m_start.group(2))
                    self.clips_done = max(self.clips_done, self.current_clip - 1)

            m = STAGE_RE.search(text)
            if m:
                for s in self.stages:
                    s["done"] = True
                self.stages.append({
                    "num": int(m.group(1)),
                    "title": m.group(2).strip().title(),
                    "detail": (m.group(3) or "").strip(),
                    "done": False,
                })

    def summary(self) -> Dict[str, Any]:
        with self.lock:
            last = self.lines[-1]["t"] if self.lines else ""
            c_done = getattr(self, "clips_done", 0)
            c_tot = getattr(self, "clips_total", 0)
            c_cur = getattr(self, "current_clip", 1)
            label = f"{c_done}/{c_tot} videos done" if c_tot > 0 else None
            return {
                "id": self.id,
                "kind": self.kind,
                "label": self.label,
                "target": self.target,
                "status": self.status,
                "exitCode": self.exit_code,
                "started": self.started,
                "ended": self.ended,
                "stages": list(self.stages),
                "lastLine": last[:180],
                "command": " ".join(Path(a).name if i == 0 else a for i, a in enumerate(self.argv)),
                "clipProgress": {
                    "done": c_done,
                    "total": c_tot,
                    "current": c_cur,
                    "label": label,
                },
            }


class JobManager:
    def __init__(self) -> None:
        self.jobs: Dict[str, Job] = {}
        self.lock = threading.Lock()

    def start(self, kind: str, opts: Dict[str, Any]) -> Job:
        argv = build_command(kind, opts)
        job = Job(kind, argv, opts)
        env = os.environ.copy()
        env.update({
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "NO_COLOR": "1",
            "TERM": "dumb",
            "COLUMNS": "120",
        })
        # Inject Active YouTube Target Account settings
        try:
            chosen_id = opts.get("account_id")
            acc_summary = get_accounts_summary()
            active_id = chosen_id or acc_summary.get("active_id", "alternate")
            state = get_accounts_state()
            for a in state.get("accounts", []):
                if a["id"] == active_id:
                    env["YOUTUBE_TOKEN_FILE"] = str(ROOT / a.get("token_file", "token.json"))
                    env["YOUTUBE_TARGET_EMAIL"] = a["email"]
                    if a.get("handle"):
                        env["YOUTUBE_TARGET_HANDLE"] = a["handle"]
                    break
        except Exception:
            pass
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        job.proc = subprocess.Popen(
            argv,
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        job.add_line(f"$ {job.summary()['command']}")
        threading.Thread(target=self._pump, args=(job,), daemon=True).start()
        with self.lock:
            self.jobs[job.id] = job
        return job

    def _pump(self, job: Job) -> None:
        assert job.proc and job.proc.stdout
        for line in job.proc.stdout:
            job.add_line(line)
        code = job.proc.wait()
        with job.lock:
            job.exit_code = code
            job.ended = time.time()
            if job.status != "stopped":
                job.status = "done" if code == 0 else "failed"
            for s in job.stages:
                s["done"] = job.status == "done" or s["done"]

    def stop(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or not job.proc or job.proc.poll() is not None:
            return False
        job.status = "stopped"
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(job.proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            job.proc.terminate()
        job.add_line("[!] Stopped from dashboard.")
        return True

    def list(self) -> List[Dict[str, Any]]:
        with self.lock:
            jobs = list(self.jobs.values())
        return [j.summary() for j in sorted(jobs, key=lambda j: j.started, reverse=True)]


JOBS = JobManager()


# ─────────────────────────────────────────────────────────────
# Read-only data access
# ─────────────────────────────────────────────────────────────
def _db() -> Optional[sqlite3.Connection]:
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def get_library(limit: int = 200) -> List[Dict[str, Any]]:
    client = get_supabase_client()
    raw_rows = []
    from_supabase = False

    if client:
        try:
            res = client.table("shorts_metadata").select("*").order("id", desc=True).limit(limit).execute()
            if res.data is not None:
                raw_rows = res.data
                from_supabase = True
        except Exception:
            raw_rows = []

    # If Supabase not connected or errored, fallback to local SQLite
    if not from_supabase:
        conn = _db()
        if conn:
            try:
                rows = conn.execute("SELECT * FROM shorts_metadata ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
                raw_rows = [dict(r) for r in rows]
            except sqlite3.Error:
                raw_rows = []
            finally:
                conn.close()

    # If authoritative from Supabase, prune any orphaned records in local SQLite that were deleted from Supabase
    if from_supabase and raw_rows and DB_PATH.exists():
        try:
            sb_ids = [int(r["id"]) for r in raw_rows if r.get("id")]
            if sb_ids:
                sync_conn = sqlite3.connect(DB_PATH, timeout=5)
                placeholders = ",".join("?" for _ in sb_ids)
                sync_conn.execute(f"DELETE FROM shorts_metadata WHERE id NOT IN ({placeholders})", sb_ids)
                sync_conn.commit()
                sync_conn.close()
        except Exception:
            pass

    items = []
    for d in raw_rows:
        url = d.get("storage_url") or ""
        yt = (d.get("youtube_id") or "").strip()
        local = d.get("local_path") or ""
        url_str = str(url).lower()
        local_str = str(local).replace("\\", "/").lower()
        if "longform-videos" in url_str or "longform_videos" in local_str or "feature_" in local_str:
            source = "longform"
        elif "livestream-shorts" in url_str or "livestreams_clips" in url_str or "livestream_agent" in local_str or "_live_" in local_str:
            source = "live"
        elif "post_livestreams" in url_str or "post_livestreams" in local_str or "post_live" in local_str:
            source = "post_live"
        else:
            source = "standard"
        scheduled_at = d.get("scheduled_publish_at")
        if not scheduled_at and DB_PATH.exists() and d.get("id"):
            try:
                lconn = sqlite3.connect(DB_PATH, timeout=2)
                lrow = lconn.execute("SELECT scheduled_publish_at FROM shorts_metadata WHERE id = ?", (d.get("id"),)).fetchone()
                lconn.close()
                if lrow and lrow[0]:
                    scheduled_at = lrow[0]
            except Exception:
                pass

        is_scheduled_pending = False
        is_scheduled_released = False
        if scheduled_at:
            try:
                clean_ts = str(scheduled_at).replace("Z", "+00:00")
                sched_dt = datetime.fromisoformat(clean_ts)
                if sched_dt.tzinfo is None:
                    sched_dt = sched_dt.replace(tzinfo=timezone.utc)
                if sched_dt > datetime.now(timezone.utc):
                    is_scheduled_pending = True
                else:
                    is_scheduled_released = True
            except Exception:
                is_scheduled_pending = True

        items.append({
            "id": d.get("id"),
            "title": d.get("hook_title") or "Untitled",
            "sourceTitle": d.get("source_title") or "",
            "sourceUrl": d.get("source_url") or "",
            "duration": d.get("duration"),
            "part": d.get("part_number") or 1,
            "parts": d.get("total_parts") or 1,
            "score": d.get("hook_score"),
            "description": d.get("description") or "",
            "reasoning": d.get("viral_reasoning") or "",
            "storageUrl": url or None,
            "videoUrl": f"/api/video?id={d.get('id')}",
            "youtubeId": yt or None,
            "uploaded": bool(yt) or bool(d.get("is_confirmed_uploaded")) or is_scheduled_released,
            "scheduledAt": scheduled_at if is_scheduled_pending else None,
            "originalScheduledAt": scheduled_at or None,
            "isScheduledPending": is_scheduled_pending,
            "isScheduledReleased": is_scheduled_released,
            "hasLocal": bool(local) and Path(local).exists(),
            "localPath": local if (bool(local) and Path(local).exists()) else None,
            "created": d.get("created_at"),
            "source": source,
        })
    return items


def get_overview() -> Dict[str, Any]:
    lib = get_library(limit=10000)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    units = 0
    conn = _db()
    if conn:
        try:
            row = conn.execute("SELECT units_used FROM youtube_quota WHERE date = ?", (today,)).fetchone()
            units = int(row[0]) if row else 0
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    running = [j for j in JOBS.list() if j["status"] == "running"]
    uploads_today = units // 1600
    min_goal = 6
    target_met = uploads_today >= min_goal
    uploads_left = max(0, min_goal - uploads_today)
    return {
        "total": len(lib),
        "uploaded": sum(1 for i in lib if i["uploaded"]),
        "pending": sum(1 for i in lib if not i["uploaded"]),
        "live": sum(1 for i in lib if i["source"] == "live"),
        "quota": {
            "used": units,
            "max": 10000,
            "perUpload": 1600,
            "uploadsToday": uploads_today,
            "minGoal": min_goal,
            "targetMet": target_met,
            "uploadsLeft": uploads_left,
            "canUpload": True,
        },
        "running": len(running),
        "recent": lib[:5],
        "accounts": get_accounts_summary(),
    }


# ─────────────────────────────────────────────────────────────
# Supabase data access
# ─────────────────────────────────────────────────────────────
_supabase_client = None

def get_supabase_client():
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    env_file = ROOT / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file)
        except ImportError:
            pass
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        _supabase_client = create_client(url, key)
        return _supabase_client
    except Exception:
        return None


def get_supabase_status() -> Dict[str, Any]:
    client = get_supabase_client()
    url = os.getenv("SUPABASE_URL", "")
    if not client or not url:
        return {"connected": False, "error": "SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not configured in .env"}

    tables_info: Dict[str, Any] = {}
    for tbl in ["shorts_metadata", "video_series"]:
        try:
            res = client.table(tbl).select("id", count="exact").limit(1).execute()
            tables_info[tbl] = res.count or 0
        except Exception as e:
            tables_info[tbl] = 0

    buckets_info = []
    try:
        buckets = client.storage.list_buckets()
        for b in buckets:
            buckets_info.append({
                "id": b.id,
                "name": b.name,
                "public": getattr(b, "public", True),
                "created_at": getattr(b, "created_at", None),
            })
    except Exception:
        buckets_info = [{"name": "youtube-shorts"}, {"name": "livestream-shorts"}, {"name": "reels"}]

    return {
        "connected": True,
        "url": url,
        "tables": tables_info,
        "buckets": buckets_info,
    }


def get_supabase_table_data(table_name: str, limit: int = 50, offset: int = 0, search: str = "", filter_key: str = "") -> Dict[str, Any]:
    client = get_supabase_client()
    if not client:
        return {"error": "Supabase not connected", "rows": [], "columns": [], "total": 0}
    if table_name not in ["shorts_metadata", "video_series"]:
        return {"error": "Invalid table", "rows": [], "columns": [], "total": 0}

    try:
        query = client.table(table_name).select("*", count="exact")
        if search:
            if table_name == "shorts_metadata":
                query = query.ilike("hook_title", f"%{search}%")
            elif table_name == "video_series":
                query = query.ilike("short_title", f"%{search}%")
        if filter_key == "uploaded":
            query = query.eq("is_confirmed_uploaded" if table_name == "shorts_metadata" else "is_confirmed", True)
        elif filter_key == "pending":
            query = query.eq("is_confirmed_uploaded" if table_name == "shorts_metadata" else "is_confirmed", False)

        res = query.order("id", desc=True).range(offset, offset + limit - 1).execute()
        rows = res.data or []
        columns = list(rows[0].keys()) if rows else []
        return {
            "table": table_name,
            "total": res.count or len(rows),
            "offset": offset,
            "limit": limit,
            "rows": rows,
            "columns": columns,
        }
    except Exception as e:
        return {"error": str(e), "rows": [], "columns": [], "total": 0}


def get_supabase_storage_items(bucket: str, prefix: str = "") -> Dict[str, Any]:
    client = get_supabase_client()
    if not client:
        return {"error": "Supabase not connected", "bucket": bucket, "prefix": prefix, "items": []}

    prefix = prefix.strip("/")
    try:
        raw_items = client.storage.from_(bucket).list(prefix)
        items = []
        for f in raw_items:
            name = f.get("name", "")
            if not name or name == ".emptyFolderPlaceholder":
                continue
            meta = f.get("metadata")
            is_dir = meta is None and not f.get("id")
            size = meta.get("size") if meta else None
            mimetype = meta.get("mimetype") if meta else None
            item_path = f"{prefix}/{name}" if prefix else name
            pub_url = None
            if not is_dir:
                try:
                    pub_url = client.storage.from_(bucket).get_public_url(item_path)
                except Exception:
                    pub_url = None
            items.append({
                "name": name,
                "isDir": is_dir,
                "size": size,
                "mimetype": mimetype,
                "created_at": f.get("created_at"),
                "updated_at": f.get("updated_at"),
                "path": item_path,
                "public_url": pub_url,
            })

        items.sort(key=lambda x: (not x["isDir"], x["name"].lower()))
        return {
            "bucket": bucket,
            "prefix": prefix,
            "items": items,
        }
    except Exception as e:
        return {"error": str(e), "bucket": bucket, "prefix": prefix, "items": []}



def delete_short(short_id: int) -> Dict[str, Any]:
    client = get_supabase_client()
    storage_url = ""
    local_path = ""
    hook_title = ""

    # Check Supabase first
    if client:
        try:
            res = client.table("shorts_metadata").select("*").eq("id", short_id).execute()
            if res.data:
                storage_url = res.data[0].get("storage_url") or ""
                local_path = res.data[0].get("local_path") or ""
                hook_title = res.data[0].get("hook_title") or ""
        except Exception:
            pass

    conn = None
    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(DB_PATH, timeout=5)
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM shorts_metadata WHERE id = ?", (short_id,)).fetchone()
            if row:
                if not storage_url:
                    storage_url = row["storage_url"] or ""
                if not local_path:
                    local_path = row["local_path"] or ""
                if not hook_title:
                    hook_title = row["hook_title"] or ""
        except sqlite3.Error:
            pass

    sb_storage_deleted = False
    sb_table_deleted = False

    if client:
        # Delete from Supabase cloud storage
        if storage_url:
            try:
                m = re.search(r"/object/(?:public|authenticated)/([^/]+)/(.+)$", storage_url)
                if m:
                    bkt = m.group(1)
                    obj_path = m.group(2)
                    client.storage.from_(bkt).remove([obj_path])
                    sb_storage_deleted = True
            except Exception:
                pass

        # Delete from Supabase table
        try:
            res = client.table("shorts_metadata").delete().eq("id", short_id).execute()
            if res.data:
                sb_table_deleted = True
            elif hook_title:
                res2 = client.table("shorts_metadata").delete().eq("hook_title", hook_title).execute()
                if res2.data:
                    sb_table_deleted = True
        except Exception:
            pass

    # Delete from local SQLite
    sqlite_deleted = False
    if conn:
        try:
            conn.execute("DELETE FROM shorts_metadata WHERE id = ?", (short_id,))
            conn.commit()
            sqlite_deleted = True
        except sqlite3.Error:
            pass
        finally:
            conn.close()

    # Delete local file from disk if present
    local_deleted = False
    if local_path and Path(local_path).is_file():
        try:
            Path(local_path).unlink()
            local_deleted = True
        except Exception:
            pass

def get_longform_videos_list() -> List[Dict[str, Any]]:
    vid_dir = ROOT / "output" / "longform_videos"
    if not vid_dir.exists():
        return []
    items = []
    for f in sorted(vid_dir.glob("Feature_*.mp4"), key=os.path.getmtime, reverse=True):
        meta_file = f.with_suffix(".json")
        meta = {}
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as jf:
                    meta = json.load(jf)
            except Exception:
                pass
        items.append({
            "filename": f.name,
            "title": meta.get("title", f.stem.replace("Feature_", "").replace("_", " ")),
            "description": meta.get("description", ""),
            "duration": meta.get("duration_formatted", "8:00"),
            "duration_sec": meta.get("duration_seconds", 480),
            "size_mb": meta.get("file_size_mb", round(f.stat().st_size / (1024 * 1024), 2)),
            "chapters": meta.get("chapters", []),
            "storage_url": meta.get("storage_url"),
            "created_at": meta.get("created_at", datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat()),
            "video_url": f"/api/editor/video/{f.name}"
        })
    return items


# ─────────────────────────────────────────────────────────────
# HTTP layer
# ─────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    server_version = "StudioDashboard/1.0"

    def do_HEAD(self) -> None:
        self.do_GET()

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet console
        pass

    def _json(self, payload: Any, status: int = 200) -> None:
        def _json_serial(o: Any) -> Any:
            if hasattr(o, "isoformat"):
                return o.isoformat()
            return str(o)
        body = json.dumps(payload, default=_json_serial).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            pass

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 64_000:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin in (f"http://{HOST}:{PORT}", f"http://localhost:{PORT}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/api/overview":
            return self._json(get_overview())
        if path == "/api/accounts":
            return self._json(get_accounts_summary())
        if path == "/api/library":
            return self._json(get_library())
        if path == "/api/jobs":
            return self._json(JOBS.list())
        if path == "/api/scheduler/preview":
            count = _clamp_int((qs.get("count") or ["6"])[0], 1, 6, 6)
            slots_per_day = _clamp_int((qs.get("slots_per_day") or ["2"])[0], 1, 3, 2)
            try:
                from src.services.auto_scheduler import get_unuploaded_candidates, generate_peak_slots
                from src.services.database import DatabaseService

                db = DatabaseService()
                quota = db.get_daily_quota_status()
                rem = quota.get("remaining_units", 0) // 1600
                candidates = get_unuploaded_candidates(limit=count)
                effective_count = min(len(candidates), count)
                slots = generate_peak_slots(count=effective_count, slots_per_day=slots_per_day)

                preview_items = []
                for c, s in zip(candidates, slots):
                    preview_items.append({
                        "id": c.get("id"),
                        "title": c.get("hook_title") or f"Short #{c.get('id')}",
                        "part": c.get("part_number") or 1,
                        "total_parts": c.get("total_parts") or 1,
                        "duration": c.get("duration") or 0.0,
                        "day_rel": s["day_rel"],
                        "local_formatted": s["local_formatted"],
                        "window_name": s["window_name"],
                        "utc_iso": s["utc_iso"],
                    })

                return self._json({
                    "quota": quota,
                    "uploads_left_today": rem,
                    "candidates_count": len(candidates),
                    "preview": preview_items,
                    "slots_per_day": slots_per_day,
                })
            except Exception as e:
                return self._json({"error": str(e), "preview": []}, 500)
        if path == "/api/supabase/status":
            return self._json(get_supabase_status())
        if path == "/api/supabase/table":
            tbl = (qs.get("name") or ["shorts_metadata"])[0]
            limit = _clamp_int((qs.get("limit") or ["50"])[0], 1, 200, 50)
            offset = _clamp_int((qs.get("offset") or ["0"])[0], 0, 100000, 0)
            search = (qs.get("search") or [""])[0].strip()
            flt = (qs.get("filter") or [""])[0].strip()
            return self._json(get_supabase_table_data(tbl, limit, offset, search, flt))
        if path == "/api/editor/list":
            return self._json(get_longform_videos_list())
        if path.startswith("/api/editor/video/"):
            fname = path.replace("/api/editor/video/", "").strip()
            vpath = (ROOT / "output" / "longform_videos" / fname).resolve()
            if vpath.is_file():
                return self._serve_video_file(vpath)
            return self._json({"error": "not found"}, 404)
        if path == "/api/supabase/storage":
            bkt = (qs.get("bucket") or ["youtube-shorts"])[0]
            prefix = (qs.get("prefix") or [""])[0]
            return self._json(get_supabase_storage_items(bkt, prefix))
        if path == "/api/video":
            short_id = _clamp_int((qs.get("id") or ["0"])[0], 0, 10**9, 0)
            storage_url = None
            local_path = None
            client = get_supabase_client()
            if client:
                try:
                    res = client.table("shorts_metadata").select("storage_url").eq("id", short_id).execute()
                    if res.data:
                        storage_url = res.data[0].get("storage_url")
                except Exception:
                    pass
            if not storage_url and not local_path:
                conn = _db()
                if conn:
                    try:
                        row = conn.execute("SELECT storage_url, local_path FROM shorts_metadata WHERE id = ?", (short_id,)).fetchone()
                        if row:
                            storage_url = row["storage_url"]
                            local_path = row["local_path"]
                    except sqlite3.Error:
                        pass
                    finally:
                        conn.close()

            if local_path and Path(local_path).is_file():
                return self._serve_video_file(Path(local_path))
            elif storage_url:
                self.send_response(302)
                self.send_header("Location", storage_url)
                self.end_headers()
                return
            return self._json({"error": "no video found"}, 404)
        m = re.fullmatch(r"/api/jobs/([a-f0-9]{10})/log", path)
        if m:
            job = JOBS.jobs.get(m.group(1))
            if not job:
                return self._json({"error": "not found"}, 404)
            after = _clamp_int((qs.get("after") or ["0"])[0], 0, 10**9, 0)
            with job.lock:
                lines = [l for l in job.lines if l["n"] > after]
            return self._json({"job": job.summary(), "lines": lines})

        # Static files
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC_DIR / rel).resolve()
        if STATIC_DIR not in target.parents and target != STATIC_DIR / "index.html":
            return self._json({"error": "forbidden"}, 403)
        if not target.is_file():
            return self._json({"error": "not found"}, 404)
        data = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        try:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(data)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            pass

    def do_POST(self) -> None:
        if not self._same_origin():
            return self._json({"error": "forbidden"}, 403)
        path = urlparse(self.path).path
        if path == "/api/run":
            body = self._read_json()
            try:
                job = JOBS.start(str(body.get("kind", "")), body.get("options") or {})
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            except OSError as e:
                return self._json({"error": f"Could not start process: {e}"}, 500)
            return self._json(job.summary(), 201)
        if path == "/api/publish/delete":
            body = self._read_json()
            short_id = _clamp_int(body.get("id"), 0, 10**9, 0)
            if not short_id:
                return self._json({"error": "Missing or invalid id"}, 400)
            res = delete_short(short_id)
            return self._json(res)
        if path == "/api/accounts/switch":
            body = self._read_json()
            target_id = str(body.get("id", "")).strip()
            if not target_id:
                return self._json({"error": "Missing account id"}, 400)
            try:
                res = switch_active_account(target_id)
                return self._json(res)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        if path == "/api/accounts/auth":
            body = self._read_json()
            target_id = str(body.get("id", "")).strip()
            if target_id:
                try:
                    switch_active_account(target_id)
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
            job = JOBS.start("auth", {})
            return self._json(job.summary(), 201)
        m = re.fullmatch(r"/api/jobs/([a-f0-9]{10})/stop", path)
        if m:
            return self._json({"stopped": JOBS.stop(m.group(1))})
        return self._json({"error": "not found"}, 404)

    def _serve_video_file(self, file_path: Path) -> None:
        try:
            file_size = file_path.stat().st_size
            range_header = self.headers.get("Range")
            if range_header:
                m = re.match(r"bytes=(\d+)-(\d*)", range_header)
                if m:
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else file_size - 1
                    end = min(end, file_size - 1)
                    length = end - start + 1
                    self.send_response(206)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                    self.send_header("Content-Length", str(length))
                    self.send_header("Accept-Ranges", "bytes")
                    self.end_headers()
                    with open(file_path, "rb") as f:
                        f.seek(start)
                        self.wfile.write(f.read(length))
                    return

            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(file_size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with open(file_path, "rb") as f:
                self.wfile.write(f.read())
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self._json({"error": str(e)}, 500)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Studio dashboard running at http://{HOST}:{PORT}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for j in JOBS.jobs.values():
            JOBS.stop(j.id)
        server.server_close()


if __name__ == "__main__":
    main()
