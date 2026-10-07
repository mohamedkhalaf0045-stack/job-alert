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

    t0 = time.time()
    found: dict[str, dict] = {}
    for kw in keywords:
        for loc in locations:
            try:
                jobs = li.scrape_linkedin(
                    kw, loc, cookie, max_pages=1, max_hours=1,
                    window_seconds=WINDOW_SECONDS, sort_recent=True,
                )
            except Exception as exc:
                _log(f"scrape error '{kw}' / '{loc}': {exc}")
                continue
            jobs = [j for j in jobs if not relevance_engine.is_nationals_only(j)]
            jobs, _dropped = engine.filter_jobs(jobs, log_prefix=f"fast '{kw}'")
            for j in jobs:
                found.setdefault(str(j.get("Id", "")), j)
            time.sleep(0.4)

    if not found:
        _log(f"no matching postings in the last {WINDOW_SECONDS // 60} min "
             f"({len(keywords) * len(locations)} queries, {time.time() - t0:.0f}s)")
        return 0

    summary = db.sync_jobs(url, key, list(found.values()), source="LinkedIn")
    new_ids = [db._job_id(j) for j in summary.get("new_jobs", [])]
    new_ids = [i for i in dict.fromkeys(new_ids) if i]
    _log(f"{len(found)} matching posting(s), {len(new_ids)} new "
         f"(scan {time.time() - t0:.0f}s)")
    if not new_ids:
        return 0
    if not _ensure_ollama():
        # Jobs are stored unscored; the normal pipeline will pick them up later.
        return len(new_ids)

    env = dict(os.environ, SUPABASE_URL=url, SUPABASE_KEY=key, LINKEDIN_COOKIE=cookie)
    python = sys.executable
    if python.lower().endswith("pythonw.exe"):
        python = python[:-len("pythonw.exe")] + "python.exe"
    cmd = [python, os.path.join(_DIR, "enricher.py"),
           "--job-ids", ",".join(new_ids), "--alert"]
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
    parser = argparse.ArgumentParser(description="Fast-lane job alerts")
    parser.add_argument("--loop", type=int, default=0,
                        help="Run forever, one cycle every N seconds (0 = single cycle)")
    args = parser.parse_args()

    if not args.loop:
        run_cycle()
        return

    lock = _acquire_single_instance()
    if lock is None:
        return
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = open(_STATE_DIR / "fastlane.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log
    _log(f"fast lane started (cycle every {args.loop}s, window {WINDOW_SECONDS // 60} min)")
    while True:
        started = time.time()
        try:
            run_cycle()
        except Exception as exc:
            _log(f"cycle error: {exc}")
        time.sleep(max(5, args.loop - (time.time() - started)))


if __name__ == "__main__":
    main()
