#!/usr/bin/env python3
"""
Data retention cleanup — deletes old rows per policy.

Policy:
  jobs (status != saved/applied)  : older than 60 days
  user_alert_log                  : older than 90 days
  telegram_claude_history         : older than 30 days

Usage:
  python cloud/cleanup.py
  python cloud/cleanup.py --dry-run      # print counts, delete nothing

Env vars (or settings.json fallback):
  SUPABASE_URL
  SUPABASE_KEY   (service_role key required)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db as _db

_SETTINGS = Path(__file__).resolve().parent.parent / "settings.json"


def _cfg(key: str, json_key: str = "") -> str:
    val = os.environ.get(key, "").strip()
    if val:
        return val
    if json_key and _SETTINGS.exists():
        try:
            return json.loads(_SETTINGS.read_text()).get(json_key, "")
        except Exception:
            pass
    return ""


def _utc_ago(**kwargs) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kwargs)).isoformat()


def run(dry_run: bool = False) -> None:
    url = _cfg("SUPABASE_URL", "SupabaseUrl")
    key = _cfg("SUPABASE_KEY", "SupabaseKey")
    if not url or not key:
        print("[Cleanup] ERROR: SUPABASE_URL and SUPABASE_KEY required.")
        sys.exit(1)

    sb = _db._get_client(url, key)
    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"[Cleanup] mode={mode}  utc={datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}")

    # ── Jobs (non-saved/applied older than 60 days) ───────────────────────────
    cutoff_jobs = _utc_ago(days=60)
    count_resp = (
        sb.table("jobs")
        .select("job_id", count="exact")
        .not_.in_("status", ["saved", "applied"])
        .lt("date_collected", cutoff_jobs)
        .execute()
    )
    job_count = count_resp.count or 0
    print(f"[Cleanup]   jobs to delete (>60d, not saved/applied): {job_count}")
    if not dry_run and job_count > 0:
        (
            sb.table("jobs")
            .delete()
            .not_.in_("status", ["saved", "applied"])
            .lt("date_collected", cutoff_jobs)
            .execute()
        )
        print(f"[Cleanup]   ✓ {job_count} jobs deleted (alert_log rows cascade automatically)")

    # ── User alert log (older than 90 days) ───────────────────────────────────
    cutoff_log = _utc_ago(days=90)
    log_resp = (
        sb.table("user_alert_log")
        .select("user_id", count="exact")
        .lt("sent_at", cutoff_log)
        .execute()
    )
    log_count = log_resp.count or 0
    print(f"[Cleanup]   user_alert_log to delete (>90d): {log_count}")
    if not dry_run and log_count > 0:
        sb.table("user_alert_log").delete().lt("sent_at", cutoff_log).execute()
        print(f"[Cleanup]   ✓ {log_count} alert log rows deleted")

    # ── Telegram history (older than 30 days) ─────────────────────────────────
    cutoff_tg = _utc_ago(days=30)
    tg_resp = (
        sb.table("telegram_claude_history")
        .select("id", count="exact")
        .lt("created_at", cutoff_tg)
        .execute()
    )
    tg_count = tg_resp.count or 0
    print(f"[Cleanup]   telegram_claude_history to delete (>30d): {tg_count}")
    if not dry_run and tg_count > 0:
        sb.table("telegram_claude_history").delete().lt("created_at", cutoff_tg).execute()
        print(f"[Cleanup]   ✓ {tg_count} history rows deleted")

    print("[Cleanup] Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
