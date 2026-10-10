"""
Fast lane: get a relevant, AI-scored job alert within minutes of posting.

The normal worker scans ~200 keyword x location combos per pass (15-20 min) and
the cloud schedulers run every few hours, so a new job can take a day to reach
you. This lane instead polls LinkedIn for just the last few minutes of postings
for a small keyword/location set (each request is <1s), inserts what's new,
then immediately scores *only those jobs* with enricher.py and sends a Telegram
alert for the ones that score KEEP. Nothing is sent unscored.

    python cloud/fastlane.py            # one cycle
    python cloud/fastlane.py --loop 90  # forever, one cycle every ~90s

Config (bot_state, comma separated; defaults below):
    setting_fast_keywords    e.g. "IT Support,Help Desk,System Administrator"
    setting_fast_locations   e.g. "United Arab Emirates,Egypt"
Credentials come from env vars or settings.json (SupabaseUrl, SupabaseKey,
LinkedInCookie; the enricher reads the Telegram token/chat from the same place).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)
import db
import linkedin as li
import relevance_engine

DEFAULT_KEYWORDS = [
    "IT Support", "IT Helpdesk", "Help Desk", "System Administrator",
    "IT Infrastructure", "Desktop Support", "IT Administrator", "Network Engineer",
]
DEFAULT_LOCATIONS = ["United Arab Emirates", "Egypt"]

# Look back 15 min every cycle. Overlap between cycles is harmless: db.sync_jobs
# only reports jobs it hasn't stored before, so each job is scored/alerted once.
WINDOW_SECONDS = 900

# After downtime (PC off, network down) widen the look-back to cover the gap,
# up to this cap, so jobs posted while we were away are still picked up.
MAX_CATCHUP_SECONDS = 6 * 3600

_SETTINGS_FILE = Path(_DIR).parent / "settings.json"
_STATE_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".job-alert") / "JobAlert"


def _log(msg: str) -> None:
    print(f"[fastlane {datetime.now():%H:%M:%S}] {msg}", flush=True)


def _settings() -> dict:
    try:
        return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _cfg(env_key: str, json_key: str) -> str:
    return os.environ.get(env_key, "").strip() or str(_settings().get(json_key, "") or "").strip()


def _csv_setting(url: str, key: str, name: str, default: list[str]) -> list[str]:
    try:
        raw = db.get_config(url, key, name, "")
    except Exception:
        raw = ""
    items = [x.strip() for x in raw.split(",") if x.strip()]
    return items or default


def _ensure_ollama() -> bool:
    """Scoring needs the local Ollama. If it isn't answering, start the installed
    one hidden (it normally auto-starts at login, but can be closed or crash)."""
    import requests

    def up() -> bool:
        try:
            return requests.get("http://localhost:11434/api/tags", timeout=3).ok
        except requests.RequestException:
            return False

    if up():
        return True
    exe = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    if not exe.exists():
        _log("Ollama is not running and ollama.exe was not found - cannot score")
        return False
    _log("Ollama is down - starting 'ollama serve'")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen([str(exe), "serve"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=flags)
    for _ in range(15):
        time.sleep(2)
        if up():
            return True
    _log("Ollama did not come up within 30s")
    return False


def _last_ok_file() -> Path:
    return _STATE_DIR / "fastlane_last_ok.txt"


# Cloud mode (GitHub Actions): score with Groq instead of local Ollama, and keep
# the last-good-cycle time in bot_state because the runner's disk is wiped.
_CLOUD = False
_CLOUD_STATE_KEY = "fastlane_cloud_last_ok"


def _read_last_ok(url: str, key: str) -> float | None:
    try:
        if _CLOUD:
            return float(db.get_config(url, key, _CLOUD_STATE_KEY, ""))
        return float(_last_ok_file().read_text().strip())
    except Exception:
        return None


def _window_seconds(url: str = "", key: str = "") -> int:
    """Look-back window: 15 min normally, wider if the last good cycle was long ago."""
    last = _read_last_ok(url, key)
    if last is None:
        return WINDOW_SECONDS
    since = time.time() - last
    return int(min(max(since + 300, WINDOW_SECONDS), MAX_CATCHUP_SECONDS))


def _mark_ok(url: str = "", key: str = "") -> None:
    try:
        if _CLOUD:
            db.set_config(url, key, _CLOUD_STATE_KEY, str(time.time()))
            return
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        _last_ok_file().write_text(str(time.time()))
    except Exception:
        pass


def _heartbeat(url: str, key: str, beat: dict) -> None:
    """Cloud mode only: last cycle's stats in bot_state (Actions logs aren't easy to reach)."""
    if not _CLOUD:
        return
    try:
        db.set_config(url, key, "fastlane_cloud_heartbeat", json.dumps(beat))
    except Exception:
        pass


def run_cycle() -> int:
    """One poll -> insert -> score -> alert pass. Returns number of new jobs."""
    url    = _cfg("SUPABASE_URL", "SupabaseUrl")
    key    = _cfg("SUPABASE_KEY", "SupabaseKey")
    cookie = _cfg("LINKEDIN_COOKIE", "LinkedInCookie")
    if not url or not key:
        _log("SUPABASE_URL / SUPABASE_KEY missing - nothing to do")
        return 0

    keywords  = _csv_setting(url, key, "setting_fast_keywords", DEFAULT_KEYWORDS)
    locations = _csv_setting(url, key, "setting_fast_locations", DEFAULT_LOCATIONS)

    try:
        engine = relevance_engine.RelevanceEngine.from_supabase(url, key, keywords)
    except Exception as exc:
        _log(f"RelevanceEngine load failed ({exc}) - keyword-only fallback")
        engine = relevance_engine.RelevanceEngine(keywords, set(), set(), set())

    window = _window_seconds(url, key)
    pages = 1 if window <= WINDOW_SECONDS * 2 else 3
    if window > WINDOW_SECONDS:
        _log(f"catch-up: looking back {window // 60} min ({pages} page(s)/query)")
    t0 = time.time()
    found: dict[str, dict] = {}
    ok_queries = 0
    errors: list[str] = []
    for kw in keywords:
        for loc in locations:
            try:
                jobs = li.scrape_linkedin(
                    kw, loc, cookie, max_pages=pages, max_hours=window // 3600 + 1,
                    window_seconds=window, sort_recent=True,
                )
                if jobs:
                    ok_queries += 1   # empty may mean blocked, so it doesn't count
            except Exception as exc:
                _log(f"scrape error '{kw}' / '{loc}': {exc}")
                errors.append(f"{type(exc).__name__}: {exc}"[:300])
                continue
            jobs = [j for j in jobs if not relevance_engine.is_nationals_only(j)]
            jobs, _dropped = engine.filter_jobs(jobs, log_prefix=f"fast '{kw}'")
            for j in jobs:
                found.setdefault(str(j.get("Id", "")), j)
            time.sleep(0.4)

    if ok_queries:
        _mark_ok(url, key)
    beat = {"at": datetime.utcnow().isoformat() + "Z", "window_min": window // 60,
            "queries": len(keywords) * len(locations), "nonempty_queries": ok_queries,
            "matched": len(found), "new": 0, "scan_secs": round(time.time() - t0),
            "errors": len(errors), "first_error": errors[0] if errors else ""}
    if not found:
        _heartbeat(url, key, beat)
        _log(f"no matching postings in the last {window // 60} min "
             f"({len(keywords) * len(locations)} queries, {time.time() - t0:.0f}s)")
        return 0

    summary = db.sync_jobs(url, key, list(found.values()), source="LinkedIn")
    new_ids = [db._job_id(j) for j in summary.get("new_jobs", [])]
    new_ids = [i for i in dict.fromkeys(new_ids) if i]
    beat["new"] = len(new_ids)
    _heartbeat(url, key, beat)
    _log(f"{len(found)} matching posting(s), {len(new_ids)} new "
         f"(scan {time.time() - t0:.0f}s)")
    if not new_ids:
        return 0
    if not _CLOUD and not _ensure_ollama():
        # Jobs are stored unscored; the normal pipeline will pick them up later.
        return len(new_ids)

    env = dict(os.environ, SUPABASE_URL=url, SUPABASE_KEY=key, LINKEDIN_COOKIE=cookie)
    python = sys.executable
    if python.lower().endswith("pythonw.exe"):
        python = python[:-len("pythonw.exe")] + "python.exe"
    cmd = [python, os.path.join(_DIR, "enricher.py"),
           "--job-ids", ",".join(new_ids), "--alert"]
    if _CLOUD:
        cmd.append("--prefer-cloud")   # Groq; GROQ_API_KEY comes from the env
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=900, creationflags=flags)
        for line in (proc.stdout or "").splitlines():
            if "Score:" in line or "Telegram" in line or "Done." in line:
                _log("  enricher: " + line.strip())
        if proc.returncode != 0:
            _log(f"enricher exited {proc.returncode}: {(proc.stderr or '')[-400:]}")
    except subprocess.TimeoutExpired:
        _log("enricher timed out after 900s")
    return len(new_ids)


def _acquire_single_instance():
    """Keep only one loop alive (startup shortcut + manual launches)."""
    import msvcrt
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    fh = open(_STATE_DIR / "fastlane.lock", "w")
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return None
    return fh


def main() -> None:
    global _CLOUD
    parser = argparse.ArgumentParser(description="Fast-lane job alerts")
    parser.add_argument("--loop", type=int, default=0,
                        help="Run forever, one cycle every N seconds (0 = single cycle)")
    parser.add_argument("--cloud", action="store_true",
                        help="GitHub Actions mode: Groq scoring, state in bot_state, log to stdout")
    parser.add_argument("--duration", type=int, default=0,
                        help="With --loop: stop after this many seconds (0 = forever)")
    args = parser.parse_args()
    _CLOUD = args.cloud

    if not args.loop:
        run_cycle()
        return

    if not _CLOUD:
        lock = _acquire_single_instance()
        if lock is None:
            return
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        log = open(_STATE_DIR / "fastlane.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
    deadline = time.time() + args.duration if args.duration else float("inf")
    _log(f"fast lane started ({'cloud' if _CLOUD else 'local'}, cycle every {args.loop}s, "
         f"window {WINDOW_SECONDS // 60} min"
         + (f", stopping after {args.duration // 60} min)" if args.duration else ")"))
    while time.time() < deadline:
        started = time.time()
        try:
            run_cycle()
        except Exception as exc:
            _log(f"cycle error: {exc}")
        time.sleep(max(5, min(args.loop - (time.time() - started), deadline - time.time())))
    _log("fast lane stopping (duration reached)")


if __name__ == "__main__":
    main()
