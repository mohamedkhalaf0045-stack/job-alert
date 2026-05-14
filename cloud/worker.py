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
import adzuna as adzuna_scraper
import websearch
import gmail_scan
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
    cookie_header  = _env("LINKEDIN_COOKIE")
    hide_applied   = _env_bool("HIDE_APPLIED", default=False)
    search_li      = _env_bool("SEARCH_LINKEDIN", default=True)
    search_indeed  = _env_bool("SEARCH_INDEED", default=False)
    search_adzuna  = _env_bool("SEARCH_ADZUNA",  default=False)
    adzuna_app_id  = _env("ADZUNA_APP_ID")
    adzuna_app_key = _env("ADZUNA_APP_KEY")
    search_web     = _env_bool("SEARCH_WEB",     default=False)
    tavily_key     = _env("TAVILY_API_KEY")
    brave_key      = _env("BRAVE_API_KEY")
    google_key     = _env("GOOGLE_API_KEY")
    google_cx      = _env("GOOGLE_CX")
    bing_key       = _env("BING_API_KEY")
    search_gmail   = _env_bool("SEARCH_GMAIL",   default=False)
    gmail_email    = _env("GMAIL_EMAIL")
    gmail_password = _env("GMAIL_APP_PASSWORD")

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
        setting_tg_tok      = db.get_config(supabase_url, supabase_key, "setting_telegram_bot_token", "")
        setting_tg_chat     = db.get_config(supabase_url, supabase_key, "setting_telegram_chat_id", "")
        setting_adzuna      = db.get_config(supabase_url, supabase_key, "setting_search_adzuna", "")
        setting_adzuna_id   = db.get_config(supabase_url, supabase_key, "setting_adzuna_app_id", "")
        setting_adzuna_key  = db.get_config(supabase_url, supabase_key, "setting_adzuna_app_key", "")

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
        if setting_adzuna:
            search_adzuna = setting_adzuna.lower() not in ("false", "0", "no", "off")
        if setting_adzuna_id:
            adzuna_app_id = setting_adzuna_id
        if setting_adzuna_key:
            adzuna_app_key = setting_adzuna_key

        setting_web        = db.get_config(supabase_url, supabase_key, "setting_search_web", "")
        setting_tavily     = db.get_config(supabase_url, supabase_key, "setting_tavily_api_key", "")
        setting_brave      = db.get_config(supabase_url, supabase_key, "setting_brave_api_key", "")
        setting_google_key = db.get_config(supabase_url, supabase_key, "setting_google_api_key", "")
        setting_google_cx  = db.get_config(supabase_url, supabase_key, "setting_google_cx", "")
        setting_bing       = db.get_config(supabase_url, supabase_key, "setting_bing_api_key", "")

        if setting_web:
            search_web = setting_web.lower() not in ("false", "0", "no", "off")
        if setting_tavily:
            tavily_key = setting_tavily
        if setting_brave:
            brave_key = setting_brave
        if setting_google_key:
            google_key = setting_google_key
        if setting_google_cx:
            google_cx = setting_google_cx
        if setting_bing:
            bing_key = setting_bing
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

    all_new_jobs: list[dict] = []

    for idx, keyword in enumerate(keywords):
        if idx > 0:
            jitter = 2.0 + (idx * 0.5)
            _log(f"Waiting {jitter:.1f}s before next keyword to avoid rate limits...")
            time.sleep(jitter)

        _log(f"Scanning keyword: '{keyword}'")

        # --- LinkedIn ---
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
                all_new_jobs.extend(summary.get("new_jobs", []))
            except Exception as exc:
                _log(f"LinkedIn error for '{keyword}': {exc}")

        # --- Indeed ---
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
                all_new_jobs.extend(summary.get("new_jobs", []))
            except Exception as exc:
                _log(f"Indeed error for '{keyword}': {exc}")

        # --- Adzuna ---
        if search_adzuna and adzuna_app_id and adzuna_app_key:
            try:
                adzuna_jobs = adzuna_scraper.scrape_adzuna(
                    keyword=keyword,
                    location=location,
                    app_id=adzuna_app_id,
                    app_key=adzuna_app_key,
                )
                summary = db.sync_jobs(supabase_url, supabase_key, adzuna_jobs, source="Adzuna")
                _log(
                    f"Adzuna '{keyword}': "
                    f"inserted={summary['inserted']}, updated={summary['updated']}, "
                    f"seen={summary['seen']}, invalid={summary['invalid']}"
                )
                all_new_jobs.extend(summary.get("new_jobs", []))
            except Exception as exc:
                _log(f"Adzuna error for '{keyword}': {exc}")
        elif search_adzuna and not (adzuna_app_id and adzuna_app_key):
            _log("Adzuna skipped — ADZUNA_APP_ID or ADZUNA_APP_KEY not set")

        # --- Web search (Tavily → Brave → Google → Bing cascade) ---
        if search_web:
            try:
                web_jobs = websearch.search_jobs(
                    keyword=keyword,
                    location=location,
                    tavily_key=tavily_key,
                    brave_key=brave_key,
                    google_key=google_key,
                    google_cx=google_cx,
                    bing_key=bing_key,
                )
                if web_jobs:
                    # Web search embeds location in the query but results can
                    # still include jobs from neighbouring countries.  Filter
                    # the same way we filter Gmail.
                    before = len(web_jobs)
                    web_jobs = [
                        j for j in web_jobs
                        if gmail_scan._job_location_matches(
                            j.get("Location", ""), location
                        )
                    ]
                    dropped = before - len(web_jobs)
                    if dropped:
                        _log(f"WebSearch '{keyword}': dropped {dropped} job(s) outside '{location}'")
                if web_jobs:
                    summary = db.sync_jobs(supabase_url, supabase_key, web_jobs, source="Web")
                    _log(
                        f"WebSearch '{keyword}': "
                        f"inserted={summary['inserted']}, updated={summary['updated']}, "
                        f"seen={summary['seen']}, invalid={summary['invalid']}"
                    )
                    all_new_jobs.extend(summary.get("new_jobs", []))
            except Exception as exc:
                _log(f"WebSearch error for '{keyword}': {exc}")

    # --- Gmail job alert emails ---
    if search_gmail:
        try:
            # Pass the active location so jobs from other countries are dropped
            # before they ever reach Supabase or Telegram.
            gm_jobs = gmail_scan.scan_gmail(
                gmail_email, gmail_password, location=location
            )
            if gm_jobs:
                by_source: dict[str, list] = {}
                for job in gm_jobs:
                    by_source.setdefault(job.get("Source", "Gmail"), []).append(job)
                for src, src_jobs in by_source.items():
                    summary = db.sync_jobs(supabase_url, supabase_key, src_jobs, source=src)
                    _log(
                        f"{src}: inserted={summary['inserted']}, "
                        f"seen={summary['seen']}, invalid={summary['invalid']}"
                    )
                    all_new_jobs.extend(summary.get("new_jobs", []))
        except Exception as exc:
            _log(f"Gmail scan error: {exc}")
    elif not gmail_email:
        _log("Gmail skipped — GMAIL_EMAIL / GMAIL_APP_PASSWORD not set")

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
