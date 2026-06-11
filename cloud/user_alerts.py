#!/usr/bin/env python3
"""
Multi-user alert sender — Phases 5 + 6.

Reads active user profiles + preferences from Supabase, finds new matches
via user_jobs_feed(), and sends email (Resend) and/or Telegram alerts.
Deduplicates via user_alert_log (PK = user_id, job_id, channel).

Usage:
  python cloud/user_alerts.py --mode instant   # 'instant'-frequency users only
  python cloud/user_alerts.py --mode digest    # 'daily' users at their local digest_hour
  python cloud/user_alerts.py --mode all       # all non-paused users
  python cloud/user_alerts.py --mode instant --dry-run

Credentials (env var or settings.json key):
  SUPABASE_URL        / SupabaseUrl
  SUPABASE_KEY        / SupabaseKey          (service_role key)
  TELEGRAM_BOT_TOKEN  / TelegramBotToken
  RESEND_API_KEY      / ResendApiKey
  RESEND_FROM_EMAIL   / ResendFromEmail      (optional; default alerts@jobalert.app)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db
import email_notify
import telegram_notify

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    _HAS_ZONEINFO = True
except ImportError:
    _HAS_ZONEINFO = False

# ── Settings ─────────────────────────────────────────────────────────────────

_ENV_TO_JSON: dict[str, str] = {
    "SUPABASE_URL":       "SupabaseUrl",
    "SUPABASE_KEY":       "SupabaseKey",
    "TELEGRAM_BOT_TOKEN": "TelegramBotToken",
    "RESEND_API_KEY":     "ResendApiKey",
    "RESEND_FROM_EMAIL":  "ResendFromEmail",
}
_SETTINGS_FILE = Path(__file__).resolve().parent.parent / "settings.json"


def _cfg(env_key: str, default: str = "") -> str:
    val = os.environ.get(env_key, "")
    if val:
        return val
    json_key = _ENV_TO_JSON.get(env_key, "")
    if json_key and _SETTINGS_FILE.exists():
        try:
            return json.loads(_SETTINGS_FILE.read_text()).get(json_key, default)
        except Exception:
            pass
    return default


# ── Timezone helper ───────────────────────────────────────────────────────────

def _local_hour(tz_name: str) -> int:
    """Current hour in an IANA timezone, falling back to UTC on error."""
    if not _HAS_ZONEINFO:
        return datetime.now(timezone.utc).hour
    try:
        return datetime.now(ZoneInfo(tz_name)).hour  # type: ignore[arg-type]
    except Exception:
        return datetime.now(timezone.utc).hour


# ── Telegram digest format ────────────────────────────────────────────────────

def _tg_digest(jobs: list[dict]) -> str:
    n      = len(jobs)
    header = f"\U0001f4cb {n} new job match{'es' if n != 1 else ''}\n"
    lines  = []
    for j in jobs[:15]:
        score  = j.get("llm_score")
        badge  = f"[{score}/10] " if score is not None else ""
        title  = j.get("title", "")
        co     = j.get("company", "")
        url    = j.get("url", "")
        lines.append(f"{badge}{title} @ {co}\n{url}")
    return header + "\n\n".join(lines)


# ── Core runner ───────────────────────────────────────────────────────────────

def run(mode: str, dry_run: bool = False) -> None:
    supabase_url = _cfg("SUPABASE_URL")
    supabase_key = _cfg("SUPABASE_KEY")
    bot_token    = _cfg("TELEGRAM_BOT_TOKEN")
    resend_key   = _cfg("RESEND_API_KEY")
    from_email   = _cfg("RESEND_FROM_EMAIL") or "JobAlert <alerts@jobalert.app>"

    if not supabase_url or not supabase_key:
        print("[Alerts] ERROR: SUPABASE_URL and SUPABASE_KEY are required.")
        sys.exit(1)

    profiles   = db.get_active_profiles(supabase_url, supabase_key)
    now_utc    = datetime.now(timezone.utc)
    total_sent = 0

    print(f"[Alerts] mode={mode} dry_run={dry_run} profiles={len(profiles)} utc={now_utc.strftime('%H:%M')}")

    for profile in profiles:
        uid  = profile["user_id"]
        freq = profile["alert_frequency"]

        # Skip based on mode
        if mode == "instant" and freq != "instant":
            continue
        if mode == "digest"  and freq != "daily":
            continue

        # For digest users, only run when local hour == digest_hour
        if freq == "daily":
            local_h = _local_hour(profile.get("timezone") or "Asia/Dubai")
            if local_h != (profile.get("digest_hour") or 8):
                continue

        # Determine which channels to send
        channels: list[str] = []
        if profile.get("alert_email") and profile.get("email") and resend_key:
            channels.append("email")
        if profile.get("alert_telegram") and profile.get("telegram_chat_id") and bot_token:
            channels.append("telegram")
        if not channels:
            continue

        # Fetch the user's personalised, filtered job list
        matches = db.get_user_matches(supabase_url, supabase_key, uid, limit=50)
        if not matches:
            continue

        for ch in channels:
            alerted = db.get_alerted_job_ids(supabase_url, supabase_key, uid, ch)
            last_at = db.get_last_alert_at(supabase_url, supabase_key, uid, ch)

            new_jobs = [
                j for j in matches
                if j["job_id"] not in alerted
                and (last_at is None or (j.get("date_collected") or "") > last_at)
            ]
            if not new_jobs:
                continue

            label = profile.get("email") or uid
            print(f"[Alerts]   {ch} → {label}: {len(new_jobs)} job(s)")
            if dry_run:
                continue

            sent = False
            if ch == "email":
                sent = email_notify.send_job_alert_email(
                    resend_key,
                    profile["email"],
                    new_jobs,
                    from_email=from_email,
                    display_name=profile.get("display_name") or "",
                )
            elif ch == "telegram":
                sent = telegram_notify.send_message(
                    bot_token, profile["telegram_chat_id"], _tg_digest(new_jobs)
                )

            if sent:
                db.log_user_alert(
                    supabase_url, supabase_key, uid,
                    [j["job_id"] for j in new_jobs], ch,
                )
                total_sent += len(new_jobs)
            else:
                print(f"[Alerts]   {ch} send FAILED for {label}")

    print(f"[Alerts] Done — {total_sent} job-alert(s) delivered.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Send per-user job alerts.")
    parser.add_argument(
        "--mode", choices=["instant", "digest", "all"], default="instant",
        help="instant = 'instant'-freq users; digest = 'daily'-freq users at their digest_hour; all = both",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be sent without actually delivering.",
    )
    args = parser.parse_args()
    run(args.mode, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
