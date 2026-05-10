"""
Cloud job alert worker — runs as a GitHub Actions job.
Reads config from environment variables, scans LinkedIn + Indeed,
stores results in Supabase (PostgreSQL), sends new jobs to Telegram.

Required environment variables:
    KEYWORDS          comma-separated, e.g. "IT support,IT HelpDesk"
    LOCATION          e.g. "United Arab Emirates"
    DATABASE_URL      PostgreSQL connection string from Supabase
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
    MAX_HOURS         how old a job can be and still be alerted (default: 24)
    LINKEDIN_COOKIE   optional; li_at=...; JSESSIONID=... from browser
    HIDE_APPLIED      optional; "true" to skip applied jobs (default: false)
    SEARCH_LINKEDIN   optional; "false" to disable (default: true)
    SEARCH_INDEED     optional; "false" to disable (default: true)
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

# --- local modules (same cloud/ folder) ---
import db
import linkedin as li_scraper
import telegram_notify as tg

# indeed_scraper.py lives one level up (shared with Windows app)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR   = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _ROOT_DIR)

try:
    from indeed_scraper import scrape_indeed
    _HAS_INDEED = True
except ImportError:
    _HAS_INDEED = False


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip().lstrip('﻿')


def _env_bool(name: str, default: bool = True) -> bool:
    val = _env(name).lower()
    if not val:
        return default
    return val not in ("false", "0", "no", "off")


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def main() -> None:
    keywords_raw = _env("KEYWORDS")
    if not keywords_raw:
        _log("ERROR: KEYWORDS env var is not set. Exiting.")
        sys.exit(1)

    keywords       = [k.strip() for k in keywords_raw.split(",") if k.strip()]
    location       = _env("LOCATION", "United Arab Emirates")
    supabase_url   = _env("SUPABASE_URL")
    supabase_key   = _env("SUPABASE_KEY")
    tg_token       = _env("TELEGRAM_BOT_TOKEN")
    tg_chat        = _env("TELEGRAM_CHAT_ID")
    max_hours      = int(_env("MAX_HOURS", "24"))
    cookie_header  = _env("LINKEDIN_COOKIE")
    hide_applied   = _env_bool("HIDE_APPLIED", default=False)
    search_li      = _env_bool("SEARCH_LINKEDIN", default=True)
    search_indeed  = _env_bool("SEARCH_INDEED", default=True)

    if not supabase_url or not supabase_key:
        _log("ERROR: SUPABASE_URL or SUPABASE_KEY env var is not set. Exiting.")
        sys.exit(1)

    _log(f"Starting scan: {len(keywords)} keyword(s), location={location}, max_hours={max_hours}")

    # Verify jobs table exists
    db.initialize_database(supabase_url, supabase_key)

    # --- Override settings from Supabase (set via mobile app) ---
    try:
        setting_kw      = db.get_config(supabase_url, supabase_key, "setting_keywords", "")
        setting_loc     = db.get_config(supabase_url, supabase_key, "setting_location", "")
        setting_hours   = db.get_config(supabase_url, supabase_key, "setting_max_hours", "")
        setting_li      = db.get_config(supabase_url, supabase_key, "setting_search_linkedin", "")
        setting_indeed  = db.get_config(supabase_url, supabase_key, "setting_search_indeed", "")
        setting_cookie  = db.get_config(supabase_url, supabase_key, "setting_linkedin_cookie", "")
        setting_exclude = db.get_config(supabase_url, supabase_key, "setting_exclude_keywords", "")

        if setting_kw:
            keywords = [k.strip() for k in setting_kw.split(",") if k.strip()]
            _log(f"Settings override: {len(keywords)} keyword(s) from Supabase")
        if setting_loc:
            location = setting_loc
        if setting_hours:
            max_hours = int(setting_hours)
        if setting_li:
            search_li = setting_li.lower() not in ("false", "0", "no", "off")
        if setting_indeed:
            search_indeed = setting_indeed.lower() not in ("false", "0", "no", "off")
        if setting_cookie:
            cookie_header = setting_cookie
    except Exception as exc:
        _log(f"Could not read Supabase settings (using env vars): {exc}")

    # --- Handle pending Telegram commands (/status etc.) ---
    if tg_token and tg_chat:
        try:
            tg_offset = int(db.get_config(supabase_url, supabase_key, "telegram_offset", "0"))
            updates   = tg.get_updates(tg_token, offset=tg_offset)
            commands  = tg.extract_commands(updates)
            for cmd in commands:
                if cmd["command"] == "/status":
                    job_count = db.get_job_count(supabase_url, supabase_key)
                    kw_preview = ", ".join(keywords[:3]) + ("..." if len(keywords) > 3 else "")
                    msg = (
                        f"Cloud worker — running OK\n"
                        f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
                        f"Keywords ({len(keywords)}): {kw_preview}\n"
                        f"Location: {location}\n"
                        f"Jobs in DB: {job_count}\n"
                        f"Max age: {max_hours}h"
                    )
                    tg.send_message(tg_token, cmd["chat_id"], msg)
                    _log(f"Replied to /status from chat {cmd['chat_id']}")
            if updates:
                new_offset = max(u["update_id"] for u in updates) + 1
                db.set_config(supabase_url, supabase_key, "telegram_offset", str(new_offset))
        except Exception as exc:
            _log(f"Telegram command poll error: {exc}")

    # Load already-sent URLs to avoid duplicate Telegram alerts
    sent_urls = db.get_telegram_sent_urls(supabase_url, supabase_key)
    _log(f"Loaded {len(sent_urls)} previously sent URLs from DB.")

    all_new_jobs: list[dict] = []

    for idx, keyword in enumerate(keywords):
        if idx > 0:
            jitter = 2.0 + (idx * 0.5)
            _log(f"Waiting {jitter:.1f}s before next keyword to avoid rate limits...")
            time.sleep(jitter)

        _log(f"Scanning keyword: '{keyword}'")

        # --- LinkedIn ---
        li_jobs: list[dict] = []
        if search_li:
            try:
                li_jobs = li_scraper.scrape_linkedin(
                    keyword=keyword,
                    location=location,
                    cookie_header=cookie_header,
                    hide_applied=hide_applied,
                )
                summary = db.sync_jobs(supabase_url, supabase_key, li_jobs, source="LinkedIn")
                _log(
                    f"LinkedIn '{keyword}': "
                    f"inserted={summary['inserted']}, updated={summary['updated']}, "
                    f"seen={summary['seen']}, invalid={summary['invalid']}"
                )
            except Exception as exc:
                _log(f"LinkedIn error for '{keyword}': {exc}")

        # --- Indeed ---
        indeed_jobs: list[dict] = []
        if search_indeed and _HAS_INDEED:
            try:
                indeed_jobs = scrape_indeed(
                    keyword=keyword,
                    location=location,
                    max_hours=max_hours,
                )
                summary = db.sync_jobs(supabase_url, supabase_key, indeed_jobs, source="Indeed")
                _log(
                    f"Indeed '{keyword}': "
                    f"inserted={summary['inserted']}, updated={summary['updated']}, "
                    f"seen={summary['seen']}, invalid={summary['invalid']}"
                )
            except Exception as exc:
                _log(f"Indeed error for '{keyword}': {exc}")
        elif search_indeed and not _HAS_INDEED:
            _log("Indeed scraper not available (playwright not installed). Skipping Indeed.")

        # Collect jobs fresh enough to alert on
        for job in li_jobs + indeed_jobs:
            age = li_scraper.get_posted_age_hours(job)
            canonical = db._canonical_url(job.get("Url", ""))
            if age <= max_hours and canonical and canonical not in sent_urls:
                all_new_jobs.append(job)
                sent_urls.add(canonical)  # prevent duplicate within this run

    _log(f"Scan complete. {len(all_new_jobs)} new job(s) to alert.")

    # --- Send Telegram alerts ---
    if tg_token and tg_chat:
        sent_count = 0
        for job in all_new_jobs:
            ok = tg.send_job_alert(tg_token, tg_chat, job)
            if ok:
                db.mark_telegram_sent(supabase_url, supabase_key, job.get("Url", ""))
                sent_count += 1
                time.sleep(0.3)  # avoid Telegram flood limits
            else:
                _log(f"Failed to send Telegram alert for: {job.get('Title', '?')}")
        _log(f"Telegram: sent {sent_count}/{len(all_new_jobs)} alert(s).")
    else:
        _log("Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing). Skipping alerts.")

    _log("Worker finished.")


if __name__ == "__main__":
    main()
