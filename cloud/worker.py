"""
Cloud job alert worker — runs as a GitHub Actions job.
Reads config from environment variables, scans LinkedIn + Indeed,
stores results in Supabase (PostgreSQL), sends new jobs to Telegram.

Required environment variables:
    SUPABASE_URL      Supabase project URL
    SUPABASE_KEY      Supabase anon key
Optional (overridden by Supabase bot_state settings):
    KEYWORDS          comma-separated, e.g. "IT support,IT HelpDesk"
    LOCATION          e.g. "United Arab Emirates"
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
    MAX_HOURS         how old a job can be and still be alerted (default: 24)
    LINKEDIN_COOKIE   optional; li_at=...
    HIDE_APPLIED      optional; "true" to skip applied jobs (default: false)
    SEARCH_LINKEDIN   optional; "false" to disable (default: true)
    SEARCH_INDEED     optional; "false" to disable (default: false)
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

# --- local modules (same cloud/ folder) ---
import db
import linkedin as li_scraper
import indeed as indeed_scraper
import telegram_notify as tg


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


_DEFAULT_KEYWORDS = "IT Support,IT Helpdesk,System Administrator,IT Infrastructure"
_DEFAULT_LOCATION = "United Arab Emirates"


def main() -> None:
    supabase_url   = _env("SUPABASE_URL")
    supabase_key   = _env("SUPABASE_KEY")
    tg_token       = _env("TELEGRAM_BOT_TOKEN")
    tg_chat        = _env("TELEGRAM_CHAT_ID")

    if not supabase_url or not supabase_key:
        _log("ERROR: SUPABASE_URL or SUPABASE_KEY env var is not set. Exiting.")
        sys.exit(1)

    # Seed defaults from env vars (may be empty — Supabase overrides below)
    keywords      = [k.strip() for k in _env("KEYWORDS", _DEFAULT_KEYWORDS).split(",") if k.strip()]
    location      = _env("LOCATION", _DEFAULT_LOCATION)
    max_hours     = int(_env("MAX_HOURS", "24"))
    cookie_header = _env("LINKEDIN_COOKIE")
    hide_applied  = _env_bool("HIDE_APPLIED", default=False)
    search_li     = _env_bool("SEARCH_LINKEDIN", default=True)
    search_indeed = _env_bool("SEARCH_INDEED", default=True)

    # Verify jobs table exists
    db.initialize_database(supabase_url, supabase_key)

    # --- Load settings from Supabase (set via mobile app / Windows GUI) ---
    # These override env vars so the laptop config is always respected even
    # when the GitHub Secret is stale or missing.
    try:
        setting_kw      = db.get_config(supabase_url, supabase_key, "setting_keywords", "")
        setting_loc     = db.get_config(supabase_url, supabase_key, "setting_location", "")
        setting_hours   = db.get_config(supabase_url, supabase_key, "setting_max_hours", "")
        setting_li      = db.get_config(supabase_url, supabase_key, "setting_search_linkedin", "")
        setting_indeed  = db.get_config(supabase_url, supabase_key, "setting_search_indeed", "")
        setting_cookie  = db.get_config(supabase_url, supabase_key, "setting_linkedin_cookie", "")
        setting_exclude = db.get_config(supabase_url, supabase_key, "setting_exclude_keywords", "")
        setting_tg_tok  = db.get_config(supabase_url, supabase_key, "setting_telegram_bot_token", "")
        setting_tg_chat = db.get_config(supabase_url, supabase_key, "setting_telegram_chat_id", "")

        if setting_kw:
            keywords = [k.strip() for k in setting_kw.split(",") if k.strip()]
            _log(f"Settings: {len(keywords)} keyword(s) from Supabase")
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
        if setting_tg_tok:
            tg_token = setting_tg_tok
        if setting_tg_chat:
            tg_chat = setting_tg_chat
    except Exception as exc:
        _log(f"Could not read Supabase settings (using env vars): {exc}")

    _log(f"Starting scan: {len(keywords)} keyword(s), location={location}, max_hours={max_hours}")

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
        if search_indeed:
            try:
                indeed_jobs = indeed_scraper.scrape_indeed(
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

        # Collect jobs fresh enough to alert on
        for job in li_jobs + indeed_jobs:
            age = li_scraper.get_posted_age_hours(job)
            canonical = db._canonical_url(job.get("Url", ""))
            if age <= max_hours and canonical and canonical not in sent_urls:
                all_new_jobs.append(job)
                sent_urls.add(canonical)  # prevent duplicate within this run

    _log(f"Scan complete. {len(all_new_jobs)} new job(s) to alert.")

    # Merge any pre-existing LLM scores (jobs enriched locally before this run)
    if all_new_jobs:
        try:
            score_map = db.get_scores_for_urls(
                supabase_url, supabase_key,
                [j.get("Url", "") for j in all_new_jobs],
            )
            if score_map:
                for job in all_new_jobs:
                    canonical = db._canonical_url(job.get("Url", ""))
                    if canonical in score_map:
                        job["llm_score"]   = score_map[canonical].get("llm_score")
                        job["llm_summary"] = score_map[canonical].get("llm_summary", "")
                _log(f"Merged LLM scores for {len(score_map)} job(s).")
        except Exception as exc:
            _log(f"Score merge error (non-fatal): {exc}")

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
