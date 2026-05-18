"""
Persistent loop runner — use this on Railway / Render / any always-on server
to scan every 2 minutes instead of GitHub Actions' 5-minute minimum.

Usage (Railway):  just deploy this repo; railway.toml points here.
Usage (local):    python cloud/runner.py
Usage (custom interval): SCAN_INTERVAL_SECONDS=90 python cloud/runner.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone

# How often to run the worker.  Default: 120s (2 min).
# GitHub Actions minimum is 300s (5 min) — this runner removes that limit.
INTERVAL = int(os.environ.get("SCAN_INTERVAL_SECONDS", "120"))
_DIR     = os.path.dirname(os.path.abspath(__file__))
_WORKER  = os.path.join(_DIR, "worker.py")


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    print(f"[{_ts()}] Runner started — scanning every {INTERVAL}s  (worker: {_WORKER})", flush=True)

    cycle = 0
    while True:
        cycle += 1
        t0 = time.monotonic()
        print(f"\n[{_ts()}] ── Cycle {cycle} ──────────────────────────────", flush=True)

        try:
            result = subprocess.run(
                [sys.executable, _WORKER],
                timeout=280,   # 4 min 40 s — must finish before next cycle starts
                cwd=_DIR,
            )
            elapsed = time.monotonic() - t0
            print(
                f"[{_ts()}] Worker finished in {elapsed:.0f}s "
                f"(exit code {result.returncode})",
                flush=True,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - t0
            print(
                f"[{_ts()}] Worker timed out after {elapsed:.0f}s — "
                "killing and skipping to next cycle",
                flush=True,
            )
        except Exception as exc:
            elapsed = time.monotonic() - t0
            print(f"[{_ts()}] Runner error after {elapsed:.0f}s: {exc}", flush=True)

        # Sleep the remainder of the interval, minimum 10s
        sleep_for = max(10, INTERVAL - (time.monotonic() - t0))
        print(f"[{_ts()}] Next scan in {sleep_for:.0f}s …", flush=True)
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
