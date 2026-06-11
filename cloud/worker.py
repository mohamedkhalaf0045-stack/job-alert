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

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _load_settings_json() -> dict:
    """Load settings.json from the standard locations (Linux or Windows).

    Search order:
      1. ~/.config/job-alert/settings.json   (Linux GUI)
      2. <repo-root>/settings.json           (Windows GUI / repo root)

    Values are only used as fallback defaults — env vars and Supabase
    bot_state overrides always take precedence (see main() below).
    """
    candidates = [
        Path.home() / ".config" / "job-alert" / "settings.json",
        Path(__file__).resolve().parent.parent / "settings.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8-sig"))
            except Exception:
                pass
    return {}


_SETTINGS_JSON: dict = _load_settings_json()

# --- local modules (same cloud/ folder) ---
import db
import linkedin as li_scraper
import bayt as bayt_scraper
import gulftalent as gt_scraper
import naukri_gulf as naukri_scraper
import indeed as indeed_scraper
import adzuna as adzuna_scraper
import websearch
import gmail_scan
import telegram_notify as tg
import relevance_engine
import url_safety

# Source priority for Telegram alert ordering and enricher scoring.
# Lower number = higher priority; LinkedIn (P1) always arrives in Telegram first.
_SOURCE_PRIORITY: dict[str, int] = {
    "LinkedIn":   1,
    "Bayt":       2,   # UAE's #1 job board
    "GulfTalent": 3,
    "NaukriGulf": 4,
    "Indeed":     5,
    "Gmail":      6,
    "Adzuna":     7,
}
# Web search sources (Web/Tavily, Web/Brave, Web/Google, Web/Bing) → priority 8.


# Mapping from env-var name → settings.json key (for Linux/Windows GUI fallback)
_ENV_TO_JSON: dict[str, str] = {
    "SUPABASE_URL":        "SupabaseUrl",
    "SUPABASE_KEY":        "SupabaseKey",
    "TELEGRAM_BOT_TOKEN":  "TelegramBotToken",
    "TELEGRAM_CHAT_ID":    "TelegramChatId",
    "LINKEDIN_COOKIE":     "LinkedInCookie",
    "KEYWORDS":            "Keywords",
    "LOCATION":            "Location",
    "OLLAMA_URL":          "OllamaUrl",
    "LLM_MIN_SCORE":       "MinAiScore",   # settings.json key for minimum score threshold
    # Search-source toggles — must be mapped so settings.json takes effect when
    # the env var is absent and Supabase bot_state hasn't been explicitly set.
    "SEARCH_LINKEDIN":     "SearchLinkedIn",
    "SEARCH_INDEED":       "SearchIndeed",
    "HIDE_APPLIED":        "HideAppliedJobs",
}


def _env(name: str, default: str = "") -> str:
    """Read env var; fall back to settings.json value if env var is empty."""
    val = os.environ.get(name, "").strip().lstrip("﻿")
    if val:
        return val
    # Fallback: settings.json
    json_key = _ENV_TO_JSON.get(name)
    if json_key and json_key in _SETTINGS_JSON:
        raw = _SETTINGS_JSON[json_key]
        if isinstance(raw, list):
            return ",".join(str(x) for x in raw)
        return str(raw).strip()
    return default


def _env_bool(name: str, default: bool = True) -> bool:
    val = _env(name).lower()
    if not val:
        return default
    return val not in ("false", "0", "no", "off")


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        # Windows console with narrow code page (cp1252) — strip non-ASCII
        print(line.encode("ascii", errors="replace").decode("ascii"), flush=True)


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
    max_hours     = int(_env("MAX_HOURS", "72"))
    min_score     = int(_env("LLM_MIN_SCORE", "4"))  # Supabase override applied below
    li_geo_id     = _env("LINKEDIN_GEOID", "")       # e.g. "104305776" for UAE
    cookie_header  = _env("LINKEDIN_COOKIE")
    hide_applied   = _env_bool("HIDE_APPLIED", default=False)
    search_li         = _env_bool("SEARCH_LINKEDIN",    default=True)
    search_bayt       = _env_bool("SEARCH_BAYT",        default=True)
    search_gulftalent = _env_bool("SEARCH_GULFTALENT",  default=True)
    search_naukri     = _env_bool("SEARCH_NAUKRIGULF",  default=True)
    search_indeed     = _env_bool("SEARCH_INDEED",      default=False)
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
        # SECURITY: credentials (LinkedIn cookie, Telegram token/chat id,
        # search-API keys) are intentionally NOT read from bot_state — that
        # table is readable with the public anon key shipped in the mobile
        # app. Secrets come from env vars (GitHub Actions Secrets) only.
        setting_kw      = db.get_config(supabase_url, supabase_key, "setting_keywords", "")
        setting_loc     = db.get_config(supabase_url, supabase_key, "setting_location", "")
        setting_hours   = db.get_config(supabase_url, supabase_key, "setting_max_hours", "")
        setting_li      = db.get_config(supabase_url, supabase_key, "setting_search_linkedin", "")
        setting_indeed  = db.get_config(supabase_url, supabase_key, "setting_search_indeed", "")
        setting_exclude = db.get_config(supabase_url, supabase_key, "setting_exclude_keywords", "")
        setting_adzuna      = db.get_config(supabase_url, supabase_key, "setting_search_adzuna", "")
        setting_adzuna_id   = db.get_config(supabase_url, supabase_key, "setting_adzuna_app_id", "")
        setting_min_score   = db.get_config(supabase_url, supabase_key, "setting_llm_min_score", "")
        setting_li_geoid    = db.get_config(supabase_url, supabase_key, "setting_linkedin_geoid", "")

        if setting_kw:
            keywords = [k.strip() for k in setting_kw.split(",") if k.strip()]
            _log(f"Settings: {len(keywords)} keyword(s) from Supabase")
        if setting_loc:
            location = setting_loc
        if setting_hours:
            max_hours = int(setting_hours)
        if setting_li:
            search_li = setting_li.lower() not in ("false", "0", "no", "off")

        setting_bayt = db.get_config(supabase_url, supabase_key, "setting_search_bayt", "")
        if setting_bayt:
            search_bayt = setting_bayt.lower() not in ("false", "0", "no", "off")

        setting_gt = db.get_config(supabase_url, supabase_key, "setting_search_gulftalent", "")
        if setting_gt:
            search_gulftalent = setting_gt.lower() not in ("false", "0", "no", "off")

        setting_naukri = db.get_config(supabase_url, supabase_key, "setting_search_naukrigulf", "")
        if setting_naukri:
            search_naukri = setting_naukri.lower() not in ("false", "0", "no", "off")

        if setting_indeed:
            search_indeed = setting_indeed.lower() not in ("false", "0", "no", "off")
        if setting_adzuna:
            search_adzuna = setting_adzuna.lower() not in ("false", "0", "no", "off")
        if setting_adzuna_id:
            adzuna_app_id = setting_adzuna_id
        if setting_min_score:
            try:
                min_score = int(setting_min_score)
            except ValueError:
                pass
        if setting_li_geoid:
            li_geo_id = setting_li_geoid.strip()

        setting_web        = db.get_config(supabase_url, supabase_key, "setting_search_web", "")
        setting_google_cx  = db.get_config(supabase_url, supabase_key, "setting_google_cx", "")

        if setting_web:
            search_web = setting_web.lower() not in ("false", "0", "no", "off")
        if setting_google_cx:
            google_cx = setting_google_cx

        # Blocked source domains (e.g. Jobsora) — dropped before DB insert.
        # jobsora.com is built in; this lets the user add more via the dashboard
        # or mobile app without a code change.
        setting_blocked = db.get_config(supabase_url, supabase_key, "setting_blocked_domains", "")
        if setting_blocked:
            db.set_blocked_domains(setting_blocked)

    except Exception as exc:
        _log(f"Could not read Supabase settings (using env vars): {exc}")

    # Phase 6: legacy single-user Telegram gate.
    # Once the owner is receiving alerts via user_alerts.py (the multi-user
    # sender), set bot_state key "setting_legacy_telegram" = "false" in the
    # Supabase SQL Editor to stop worker.py from sending a duplicate alert.
    # Default is "true" (backward-compatible — keeps working until explicitly
    # disabled).
    try:
        _legacy_tg = db.get_config(supabase_url, supabase_key, "setting_legacy_telegram", "true")
        if _legacy_tg.strip().lower() in ("false", "0", "no", "off"):
            tg_chat = ""   # disables all worker.py Telegram sends
            _log("Phase 6: legacy Telegram disabled — alerts handled by user_alerts.py")
    except Exception:
        pass  # keep tg_chat as-is on any error

    # --- Build relevance engine (CV-driven, replaces all hardcoded regex filters) ---
    try:
        engine = relevance_engine.RelevanceEngine.from_supabase(
            supabase_url, supabase_key, keywords
        )
    except Exception as exc:
        _log(f"RelevanceEngine load error (non-fatal, using keyword-only fallback): {exc}")
        engine = relevance_engine.RelevanceEngine(keywords, set(), set(), set())

    # Multiple locations: `location` may be a comma-separated list
    # (e.g. "United Arab Emirates, Egypt"). Each location is searched
    # independently for every keyword. The configured LinkedIn geo_id only
    # makes sense for a single location, so it's applied only when there's
    # exactly one — multi-location runs rely on the text location + the
    # per-location _loc_filter instead.
    locations = [loc.strip() for loc in (location or "").split(",") if loc.strip()] \
        or [_DEFAULT_LOCATION]
    if len(locations) == 1:
        location_pairs = [(locations[0], li_geo_id)]
    else:
        location_pairs = [(loc, "") for loc in locations]

    geo_info = f", geoId={li_geo_id}" if (len(locations) == 1 and li_geo_id) \
        else " (text-location fallback — set setting_linkedin_geoid for best results)"
    _log(f"Starting scan: {len(keywords)} keyword(s) × {len(locations)} location(s) "
         f"[{', '.join(locations)}]{geo_info}, max_hours={max_hours}")

    # --- Handle pending Telegram commands (/status etc.) and cover-letter button presses ---
    if tg_token and tg_chat:
        try:
            tg_offset = int(db.get_config(supabase_url, supabase_key, "telegram_offset", "0"))
            updates   = tg.get_updates(tg_token, offset=tg_offset)

            # ── Inline-button callbacks (Cover Letter + Tailored CV) ──────────
            # NOTE: answerCallbackQuery must be called within 30 s of the tap
            # to dismiss the loading indicator.  The worker runs every 5 min,
            # so that window is almost always expired.  We call it anyway
            # (best-effort) but always follow up with a regular send_message
            # so the user gets a visible response regardless of timing.
            for cb in tg.extract_callbacks(updates):
                data = cb["data"]

                if data.startswith("cover_"):
                    job_id = data[len("cover_"):]
                    cover  = db.get_cover_letter(supabase_url, supabase_key, job_id)
                    # Best-effort button acknowledgement (may be ignored after 30 s)
                    tg.answer_callback_query(tg_token, cb["callback_query_id"])
                    if cover:
                        tg.send_message(
                            tg_token, cb["chat_id"],
                            "\U0001f4dd Cover Letter Draft\n\n" + cover,
                        )
                        _log(f"Sent cover letter for job_id={job_id}")
                    else:
                        tg.send_message(
                            tg_token, cb["chat_id"],
                            "\U0001f4dd Cover letter not ready yet for this job.\n\n"
                            "Make sure Ollama is running on your laptop, then run:\n"
                            "python cloud/enricher.py --limit 30\n\n"
                            "It will generate cover letters for all high-scoring jobs automatically.",
                        )
                        _log(f"Cover letter not in DB yet for job_id={job_id} — sent instructions")

                elif data.startswith("cv_"):
                    job_id = data[len("cv_"):]
                    cv_draft = db.get_tailored_cv(supabase_url, supabase_key, job_id)
                    # Best-effort button acknowledgement (may be ignored after 30 s)
                    tg.answer_callback_query(tg_token, cb["callback_query_id"])
                    if cv_draft:
                        tg.send_message(
                            tg_token, cb["chat_id"],
                            "\U0001f4c4 Tailored CV Draft\n\n" + cv_draft,
                        )
                        _log(f"Sent tailored CV for job_id={job_id}")
                    else:
                        tg.send_message(
                            tg_token, cb["chat_id"],
                            "\U0001f4c4 Tailored CV not ready yet for this job.\n\n"
                            "Make sure Ollama is running on your laptop, then run:\n"
                            "python cloud/enricher.py --limit 30\n\n"
                            "It will generate tailored CVs for all high-scoring jobs automatically.",
                        )
                        _log(f"Tailored CV not in DB yet for job_id={job_id} — sent instructions")

                elif data.startswith("bad_") or data.startswith("good_"):
                    # 👍 / 👎 feedback → set job status, which feeds the
                    # Phase 4 active-learning loop (preferences.py reads
                    # applied + dismissed to bias future scoring).
                    is_bad  = data.startswith("bad_")
                    job_id  = data[len("bad_"):] if is_bad else data[len("good_"):]
                    new_status = "dismissed" if is_bad else "applied"
                    ok = db.set_job_status(supabase_url, supabase_key, job_id, new_status)
                    tg.answer_callback_query(
                        tg_token, cb["callback_query_id"],
                        text=("👎 Got it — fewer like this" if is_bad
                              else "👍 Noted — more like this"),
                    )
                    if ok:
                        tg.send_message(
                            tg_token, cb["chat_id"],
                            ("\U0001f44e Thanks — marked *not for me*. The AI will "
                             "learn to score similar roles lower."
                             if is_bad else
                             "\U0001f44d Thanks — marked *good match*. The AI will "
                             "learn to score similar roles higher."),
                        )
                        _log(f"Feedback {'👎' if is_bad else '👍'} → status={new_status} job_id={job_id}")
                    else:
                        _log(f"Feedback save failed for job_id={job_id}")
            # ─────────────────────────────────────────────────────────────────

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
            _log(f"Telegram command/callback poll error: {exc}")

    def _loc_filter(jobs: list[dict]) -> tuple[list[dict], int]:
        """Drop jobs whose Location doesn't match the active location setting.
        Returns (kept_jobs, dropped_count). Pass-through when location is empty."""
        if not location:
            return jobs, 0
        kept = [j for j in jobs if gmail_scan._job_location_matches(j.get("Location", ""), location)]
        return kept, len(jobs) - len(kept)

    def _age_filter(jobs: list[dict], source_label: str) -> tuple[list[dict], int]:
        """Drop jobs whose PostedDate is set and older than max_hours.

        Jobs with no PostedDate are passed through — we can't verify their age,
        but the search-API freshness parameter already made a best-effort filter.
        This is a safety net for cases where search engines ignore their own
        freshness parameter (e.g. returning a 1-year-old Tes Jobs post for a
        "past day" query).
        """
        if max_hours <= 0:
            return jobs, 0
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_hours)
        kept: list[dict] = []
        dropped = 0
        for job in jobs:
            raw = (job.get("PostedDate") or "").strip()
            if not raw:
                kept.append(job)   # unknown age — accept
                continue
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                # Date-only strings (e.g. "2026-05-19") have no time component.
                # Parsing them as midnight UTC causes valid same-day jobs to be
                # dropped when the worker runs past midnight UTC.
                # Treat date-only as end-of-day (23:59:59) to be conservative.
                if len(raw) == 10 and "T" not in raw:
                    dt = dt.replace(hour=23, minute=59)
                if dt < cutoff:
                    dropped += 1
                    _log(
                        f"{source_label}: DROPPED stale job '{job.get('Title','?')}' "
                        f"(posted ~{raw[:10]}, limit {max_hours}h)"
                    )
                    continue
            except (ValueError, TypeError):
                pass  # unparseable date — accept
            kept.append(job)
        return kept, dropped

    def _nat_filter(jobs: list[dict], source_label: str) -> list[dict]:
        """Drop jobs explicitly restricted to nationals / citizens of any country.
        Logs the count of dropped jobs so it's visible in the GitHub Actions log."""
        kept = [j for j in jobs if not relevance_engine.is_nationals_only(j)]
        dropped = len(jobs) - len(kept)
        if dropped:
            _log(f"{source_label}: dropped {dropped} job(s) restricted to nationals/citizens")
        return kept

    all_new_jobs: list[dict] = []

    # LinkedIn health tracking — used to detect an expired li_at cookie.
    # A live cookie returns SOMETHING (new, updated, seen or invalid) across a run.
    # A run-total of exactly 0 across every keyword means the scraper got nothing,
    # which is the signature of an expired/blocked session — not "no new jobs".
    li_attempted = False
    li_run_total = 0

    # --- Heartbeat: detect & report worker downtime since the last run ---
    # If the worker was off (laptop asleep, crash, GitHub cron throttle) the gap
    # between worker_last_run and now exceeds the normal ~5 min cadence.  Alert
    # the user ONCE per gap on resume.
    #
    # Idempotency: two near-simultaneous runs (e.g. a scheduled run + a manual
    # dispatch) used to both read the same stale worker_last_run and BOTH alert.
    # Now we (a) dedupe on the stale value via worker_downtime_notified, and
    # (b) claim worker_last_run = now immediately, so any overlapping/next run
    # sees a fresh value and stays silent.
    if tg_token and tg_chat:
        try:
            last_run_iso = db.get_config(supabase_url, supabase_key, "worker_last_run", "")
            if last_run_iso:
                last_dt = datetime.fromisoformat(last_run_iso.replace("Z", "+00:00"))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                gap_min = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
                if gap_min > 30:   # > 6 missed cycles
                    already = db.get_config(supabase_url, supabase_key, "worker_downtime_notified", "")
                    if already != last_run_iso:
                        # Claim this gap immediately so concurrent runs don't re-alert.
                        db.set_config(supabase_url, supabase_key, "worker_downtime_notified", last_run_iso)
                        db.set_config(supabase_url, supabase_key, "worker_last_run",
                                      datetime.now(timezone.utc).isoformat())
                        hrs = gap_min / 60
                        tg.send_message(
                            tg_token, tg_chat,
                            f"⚠️ Worker was offline for ~{hrs:.1f}h "
                            f"(last run {last_run_iso[:16]} UTC).\n"
                            f"Resuming now — jobs posted during the gap may have been missed.",
                        )
                        _log(f"Downtime detected: {gap_min:.0f} min gap — user alerted (once)")
                    else:
                        _log(f"Downtime gap already alerted for {last_run_iso[:16]} — skipping duplicate")
        except Exception as exc:
            _log(f"Heartbeat check error (non-fatal): {exc}")

    # Load already-notified URLs BEFORE scanning starts so per-source instant
    # alerts (below) never double-send a URL that was notified in a previous run.
    already_sent: set[str] = set()
    if tg_token and tg_chat:
        try:
            already_sent = db.get_telegram_sent_urls(supabase_url, supabase_key)
        except Exception:
            pass

    ntfy_url = db.get_config(supabase_url, supabase_key, "setting_ntfy_url", "")

    def _alert_new(new_jobs: list[dict]) -> None:
        """Alert Telegram (and optionally ntfy.sh) immediately for freshly-inserted jobs.
        Called right after each sync_jobs() so LinkedIn jobs reach the user's phone
        within seconds of being found — not after waiting for all other sources to finish.
        Every URL is validated by url_safety before being sent."""
        if not new_jobs:
            return
        from datetime import timedelta
        _alert_cutoff = datetime.now(timezone.utc) - timedelta(hours=max_hours) if max_hours > 0 else None
        for job in new_jobs:
            raw_url = job.get("Url", "") or job.get("url", "")
            if not raw_url or raw_url in already_sent:
                continue

            # ── Age gate: never alert on jobs older than max_hours ────────────
            # This is a second line of defence — the collection-time _age_filter
            # passes jobs with unparseable dates through; this catches them here.
            if _alert_cutoff:
                posted_raw = (job.get("PostedDate") or job.get("date_collected") or "").strip()
                if posted_raw:
                    try:
                        posted_dt = datetime.fromisoformat(posted_raw.replace("Z", "+00:00"))
                        if posted_dt.tzinfo is None:
                            posted_dt = posted_dt.replace(tzinfo=timezone.utc)
                        # Date-only (no time) → treat as end-of-day so same-day
                        # jobs aren't silently skipped when the clock passes midnight UTC.
                        if len(posted_raw) == 10 and "T" not in posted_raw:
                            posted_dt = posted_dt.replace(hour=23, minute=59, second=59)
                        if posted_dt < _alert_cutoff:
                            title = job.get("Title") or job.get("title") or "?"
                            _log(f"  ALERT SKIPPED (stale {posted_raw[:10]}): {title[:60]}")
                            # Mark as sent so we don't keep re-alerting it every run
                            try:
                                db.mark_telegram_sent(supabase_url, supabase_key, raw_url)
                            except Exception:
                                pass
                            already_sent.add(raw_url)
                            continue
                    except (ValueError, TypeError):
                        pass   # unparseable date — allow through
            # ─────────────────────────────────────────────────────────────────

            llm_score = job.get("llm_score")
            if llm_score is not None and llm_score < min_score:
                continue

            # ── URL safety check ─────────────────────────────────────────────
            safe, reason = url_safety.check_url(raw_url)
            if not safe:
                _log(f"URL BLOCKED ({reason}): {raw_url[:120]}")
                continue
            if reason.startswith("unverified-domain:"):
                _log(f"URL notice — {reason} (allowing, not in trusted list): {raw_url[:100]}")
            # Strip tracking params before sending to user
            clean_url = url_safety.sanitize_url(raw_url)
            # Patch job dict so the sanitized URL is what the user receives
            if clean_url != raw_url:
                job = dict(job)   # shallow copy — don't mutate the original
                key = "Url" if "Url" in job else "url"
                job[key] = clean_url
            job_url = clean_url
            # ─────────────────────────────────────────────────────────────────

            # --- Telegram (with 📝 Cover Letter inline button) ---
            if tg_token and tg_chat:
                job_id = job.get("Id") or job.get("id") or ""
                ok = tg.send_job_alert_with_button(tg_token, tg_chat, job, job_id=job_id)
                if ok:
                    already_sent.add(raw_url)    # track original URL for dedup
                    already_sent.add(job_url)    # also track clean URL
                    try:
                        db.mark_telegram_sent(supabase_url, supabase_key, raw_url)
                    except Exception:
                        pass
                    time.sleep(0.3)
            # --- ntfy.sh push notification (optional, high-score jobs only) ---
            if ntfy_url and (llm_score is None or llm_score >= 7):
                try:
                    title   = job.get("Title") or job.get("title") or "New Job"
                    company = job.get("Company") or job.get("company") or ""
                    score_tag = f" [{llm_score}/10]" if llm_score is not None else ""
                    import requests as _req
                    _req.post(
                        ntfy_url,
                        data=f"{title}{score_tag} @ {company}\n{job_url}".encode("utf-8"),
                        headers={
                            "Title": f"Job Alert{score_tag}",
                            "Priority": "high" if (llm_score or 0) >= 8 else "default",
                            "Tags": "briefcase",
                        },
                        timeout=8,
                    )
                except Exception:
                    pass

    # Circuit-breaker: track consecutive failures per source.
    # If a source returns 0 results (blocked/timeout) on 2 keywords in a row,
    # disable it for the rest of this run so we don't waste time on dead sources.
    _source_fails: dict[str, int] = {
        "bayt": 0, "gulftalent": 0, "naukri": 0,
        "indeed": 0, "adzuna": 0, "web": 0,
    }
    _FAIL_THRESHOLD = 2   # disable after this many consecutive zero-result attempts

    # One scan per (keyword, location). `location` and `li_geo_id` are rebound
    # each iteration — every scraper call and the _loc_filter closure already
    # read these names, so they transparently use the current location.
    scan_targets = [(kw, loc, geo) for (loc, geo) in location_pairs for kw in keywords]
    for idx, (keyword, location, li_geo_id) in enumerate(scan_targets):
        if idx > 0:
            # Fixed 1.5 s between scans (was 2.0 + 0.5*idx → up to 7 s).
            # LinkedIn rate-limits per session, not per-IP, so a short fixed
            # delay is enough without growing linearly with keyword count.
            time.sleep(1.5)

        if len(locations) > 1:
            _log(f"Scanning keyword: '{keyword}' in '{location}'")
        else:
            _log(f"Scanning keyword: '{keyword}'")

        # --- LinkedIn ---
        if search_li:
            try:
                li_jobs = li_scraper.scrape_linkedin(
                    keyword=keyword,
                    location=location,
                    cookie_header=cookie_header,
                    hide_applied=hide_applied,
                    max_hours=max_hours,
                    geo_id=li_geo_id,
                )
                li_jobs, li_age_dropped = _age_filter(li_jobs, f"LinkedIn '{keyword}'")
                if li_age_dropped:
                    _log(f"LinkedIn '{keyword}': dropped {li_age_dropped} stale job(s) (>{max_hours}h old)")
                li_jobs, li_dropped = _loc_filter(li_jobs)
                if li_dropped:
                    _log(f"LinkedIn '{keyword}': dropped {li_dropped} job(s) outside '{location}'")
                li_jobs = _nat_filter(li_jobs, f"LinkedIn '{keyword}'")
                li_jobs, li_kw_dropped = engine.filter_jobs(li_jobs, log_prefix=f"LinkedIn '{keyword}'")
                if li_kw_dropped:
                    _log(f"LinkedIn '{keyword}': dropped {li_kw_dropped} unrelated job(s)")
                summary = db.sync_jobs(supabase_url, supabase_key, li_jobs, source="LinkedIn")
                _log(
                    f"LinkedIn '{keyword}': "
                    f"inserted={summary['inserted']}, updated={summary['updated']}, "
                    f"seen={summary['seen']}, invalid={summary['invalid']}"
                )
                li_attempted = True
                li_run_total += (summary["inserted"] + summary["updated"]
                                 + summary["seen"] + summary["invalid"])
                all_new_jobs.extend(summary.get("new_jobs", []))
                _alert_new(summary.get("new_jobs", []))
            except Exception as exc:
                _log(f"LinkedIn error for '{keyword}': {exc}")
                li_attempted = True

        # --- Bayt ---
        if search_bayt and _source_fails["bayt"] < _FAIL_THRESHOLD:
            try:
                bayt_jobs = bayt_scraper.scrape_bayt(
                    keyword=keyword,
                    location=location,
                )
                bayt_jobs, bt_age_dropped = _age_filter(bayt_jobs, f"Bayt '{keyword}'")
                if bt_age_dropped:
                    _log(f"Bayt '{keyword}': dropped {bt_age_dropped} stale job(s) (>{max_hours}h old)")
                bayt_jobs, bt_loc_dropped = _loc_filter(bayt_jobs)
                if bt_loc_dropped:
                    _log(f"Bayt '{keyword}': dropped {bt_loc_dropped} job(s) outside '{location}'")
                bayt_jobs = _nat_filter(bayt_jobs, f"Bayt '{keyword}'")
                bayt_jobs, bt_kw_dropped = engine.filter_jobs(bayt_jobs, log_prefix=f"Bayt '{keyword}'")
                if bt_kw_dropped:
                    _log(f"Bayt '{keyword}': dropped {bt_kw_dropped} unrelated job(s)")
                summary = db.sync_jobs(supabase_url, supabase_key, bayt_jobs, source="Bayt")
                _log(
                    f"Bayt '{keyword}': "
                    f"inserted={summary['inserted']}, updated={summary['updated']}, "
                    f"seen={summary['seen']}, invalid={summary['invalid']}"
                )
                all_new_jobs.extend(summary.get("new_jobs", []))
                _alert_new(summary.get("new_jobs", []))
                if summary["seen"] == 0 and summary["inserted"] == 0:
                    _source_fails["bayt"] += 1
                else:
                    _source_fails["bayt"] = 0
            except Exception as exc:
                _log(f"Bayt error for '{keyword}': {exc}")
                _source_fails["bayt"] += 1
        elif search_bayt:
            _log(f"Bayt: skipped (blocked on previous keywords)")

        # --- GulfTalent ---
        if search_gulftalent and _source_fails["gulftalent"] < _FAIL_THRESHOLD:
            try:
                gt_jobs = gt_scraper.scrape_gulftalent(
                    keyword=keyword,
                    location=location,
                )
                gt_jobs, gt_age_dropped = _age_filter(gt_jobs, f"GulfTalent '{keyword}'")
                if gt_age_dropped:
                    _log(f"GulfTalent '{keyword}': dropped {gt_age_dropped} stale job(s)")
                gt_jobs, gt_loc_dropped = _loc_filter(gt_jobs)
                if gt_loc_dropped:
                    _log(f"GulfTalent '{keyword}': dropped {gt_loc_dropped} job(s) outside '{location}'")
                gt_jobs = _nat_filter(gt_jobs, f"GulfTalent '{keyword}'")
                gt_jobs, gt_kw_dropped = engine.filter_jobs(gt_jobs, log_prefix=f"GulfTalent '{keyword}'")
                if gt_kw_dropped:
                    _log(f"GulfTalent '{keyword}': dropped {gt_kw_dropped} unrelated job(s)")
                summary = db.sync_jobs(supabase_url, supabase_key, gt_jobs, source="GulfTalent")
                _log(
                    f"GulfTalent '{keyword}': "
                    f"inserted={summary['inserted']}, updated={summary['updated']}, "
                    f"seen={summary['seen']}, invalid={summary['invalid']}"
                )
                all_new_jobs.extend(summary.get("new_jobs", []))
                _alert_new(summary.get("new_jobs", []))
                if summary["seen"] == 0 and summary["inserted"] == 0:
                    _source_fails["gulftalent"] += 1
                else:
                    _source_fails["gulftalent"] = 0
            except Exception as exc:
                _log(f"GulfTalent error for '{keyword}': {exc}")
                _source_fails["gulftalent"] += 1
        elif search_gulftalent:
            _log(f"GulfTalent: skipped (blocked on previous keywords)")

        # --- NaukriGulf ---
        if search_naukri and _source_fails["naukri"] < _FAIL_THRESHOLD:
            try:
                naukri_jobs = naukri_scraper.scrape_naukri_gulf(
                    keyword=keyword,
                    location=location,
                )
                naukri_jobs, nk_age_dropped = _age_filter(naukri_jobs, f"NaukriGulf '{keyword}'")
                if nk_age_dropped:
                    _log(f"NaukriGulf '{keyword}': dropped {nk_age_dropped} stale job(s)")
                naukri_jobs, nk_loc_dropped = _loc_filter(naukri_jobs)
                if nk_loc_dropped:
                    _log(f"NaukriGulf '{keyword}': dropped {nk_loc_dropped} job(s) outside '{location}'")
                naukri_jobs = _nat_filter(naukri_jobs, f"NaukriGulf '{keyword}'")
                naukri_jobs, nk_kw_dropped = engine.filter_jobs(naukri_jobs, log_prefix=f"NaukriGulf '{keyword}'")
                if nk_kw_dropped:
                    _log(f"NaukriGulf '{keyword}': dropped {nk_kw_dropped} unrelated job(s)")
                summary = db.sync_jobs(supabase_url, supabase_key, naukri_jobs, source="NaukriGulf")
                _log(
                    f"NaukriGulf '{keyword}': "
                    f"inserted={summary['inserted']}, updated={summary['updated']}, "
                    f"seen={summary['seen']}, invalid={summary['invalid']}"
                )
                all_new_jobs.extend(summary.get("new_jobs", []))
                _alert_new(summary.get("new_jobs", []))
                if summary["seen"] == 0 and summary["inserted"] == 0:
                    _source_fails["naukri"] += 1
                else:
                    _source_fails["naukri"] = 0
            except Exception as exc:
                _log(f"NaukriGulf error for '{keyword}': {exc}")
                _source_fails["naukri"] += 1
        elif search_naukri:
            _log(f"NaukriGulf: skipped (blocked/timeout on previous keywords)")

        # --- Indeed ---
        if search_indeed and _source_fails["indeed"] < _FAIL_THRESHOLD:
            try:
                indeed_jobs = indeed_scraper.scrape_indeed(
                    keyword=keyword,
                    location=location,
                    max_hours=max_hours,
                )
                indeed_jobs, ind_age_dropped = _age_filter(indeed_jobs, f"Indeed '{keyword}'")
                if ind_age_dropped:
                    _log(f"Indeed '{keyword}': dropped {ind_age_dropped} stale job(s) (>{max_hours}h old)")
                indeed_jobs, indeed_dropped = _loc_filter(indeed_jobs)
                if indeed_dropped:
                    _log(f"Indeed '{keyword}': dropped {indeed_dropped} job(s) outside '{location}'")
                indeed_jobs = _nat_filter(indeed_jobs, f"Indeed '{keyword}'")
                indeed_jobs, indeed_kw_dropped = engine.filter_jobs(indeed_jobs, log_prefix=f"Indeed '{keyword}'")
                if indeed_kw_dropped:
                    _log(f"Indeed '{keyword}': dropped {indeed_kw_dropped} unrelated job(s)")
                summary = db.sync_jobs(supabase_url, supabase_key, indeed_jobs, source="Indeed")
                _log(
                    f"Indeed '{keyword}': "
                    f"inserted={summary['inserted']}, updated={summary['updated']}, "
                    f"seen={summary['seen']}, invalid={summary['invalid']}"
                )
                all_new_jobs.extend(summary.get("new_jobs", []))
                _alert_new(summary.get("new_jobs", []))
                if summary["seen"] == 0 and summary["inserted"] == 0:
                    _source_fails["indeed"] += 1
                else:
                    _source_fails["indeed"] = 0
            except Exception as exc:
                _log(f"Indeed error for '{keyword}': {exc}")
                _source_fails["indeed"] += 1
        elif search_indeed:
            _log(f"Indeed: skipped (blocked on previous keywords)")

        # --- Adzuna ---
        if search_adzuna and adzuna_app_id and adzuna_app_key and _source_fails["adzuna"] < _FAIL_THRESHOLD:
            try:
                adzuna_jobs = adzuna_scraper.scrape_adzuna(
                    keyword=keyword,
                    location=location,
                    app_id=adzuna_app_id,
                    app_key=adzuna_app_key,
                )
                adzuna_jobs, az_age_dropped = _age_filter(adzuna_jobs, f"Adzuna '{keyword}'")
                if az_age_dropped:
                    _log(f"Adzuna '{keyword}': dropped {az_age_dropped} stale job(s) (>{max_hours}h old)")
                adzuna_jobs, adzuna_dropped = _loc_filter(adzuna_jobs)
                if adzuna_dropped:
                    _log(f"Adzuna '{keyword}': dropped {adzuna_dropped} job(s) outside '{location}'")
                adzuna_jobs = _nat_filter(adzuna_jobs, f"Adzuna '{keyword}'")
                adzuna_jobs, adzuna_kw_dropped = engine.filter_jobs(adzuna_jobs, log_prefix=f"Adzuna '{keyword}'")
                if adzuna_kw_dropped:
                    _log(f"Adzuna '{keyword}': dropped {adzuna_kw_dropped} unrelated job(s)")
                summary = db.sync_jobs(supabase_url, supabase_key, adzuna_jobs, source="Adzuna")
                _log(
                    f"Adzuna '{keyword}': "
                    f"inserted={summary['inserted']}, updated={summary['updated']}, "
                    f"seen={summary['seen']}, invalid={summary['invalid']}"
                )
                all_new_jobs.extend(summary.get("new_jobs", []))
                _alert_new(summary.get("new_jobs", []))
                if summary["seen"] == 0 and summary["inserted"] == 0:
                    _source_fails["adzuna"] += 1
                else:
                    _source_fails["adzuna"] = 0
            except Exception as exc:
                _log(f"Adzuna error for '{keyword}': {exc}")
                _source_fails["adzuna"] += 1
        elif search_adzuna and not (adzuna_app_id and adzuna_app_key):
            _log("Adzuna skipped — ADZUNA_APP_ID or ADZUNA_APP_KEY not set")
        elif search_adzuna:
            _log(f"Adzuna: skipped (blocked on previous keywords)")

        # --- Web search (Tavily → Brave → Google → Bing cascade) ---
        if search_web and _source_fails["web"] < _FAIL_THRESHOLD:
            try:
                web_jobs = websearch.search_jobs(
                    keyword=keyword,
                    location=location,
                    tavily_key=tavily_key,
                    brave_key=brave_key,
                    google_key=google_key,
                    google_cx=google_cx,
                    bing_key=bing_key,
                    max_hours=max_hours,
                )
                if web_jobs:
                    web_jobs, wb_age_dropped = _age_filter(web_jobs, f"WebSearch '{keyword}'")
                    if wb_age_dropped:
                        _log(f"WebSearch '{keyword}': dropped {wb_age_dropped} stale job(s) (>{max_hours}h old)")
                    web_jobs, web_dropped = _loc_filter(web_jobs)
                    if web_dropped:
                        _log(f"WebSearch '{keyword}': dropped {web_dropped} job(s) outside '{location}'")
                    web_jobs = _nat_filter(web_jobs, f"WebSearch '{keyword}'")
                    web_jobs, web_kw_dropped = engine.filter_jobs(web_jobs, log_prefix=f"WebSearch '{keyword}'")
                    if web_kw_dropped:
                        _log(f"WebSearch '{keyword}': dropped {web_kw_dropped} unrelated job(s)")
                if web_jobs:
                    summary = db.sync_jobs(supabase_url, supabase_key, web_jobs, source="Web")
                    _log(
                        f"WebSearch '{keyword}': "
                        f"inserted={summary['inserted']}, updated={summary['updated']}, "
                        f"seen={summary['seen']}, invalid={summary['invalid']}"
                    )
                    all_new_jobs.extend(summary.get("new_jobs", []))
                    _alert_new(summary.get("new_jobs", []))
                if not web_jobs:
                    _source_fails["web"] += 1
                else:
                    _source_fails["web"] = 0
            except Exception as exc:
                _log(f"WebSearch error for '{keyword}': {exc}")
                _source_fails["web"] += 1
        elif search_web:
            _log(f"WebSearch: skipped (all providers exhausted on previous keywords)")

    # --- LinkedIn cookie-expiry detection ---------------------------------------
    # A live session returns at least something across a full run.  A run-total of
    # exactly 0 (across every keyword) for several runs in a row means the li_at
    # cookie has expired or the session is blocked.  Alert the user ONCE so they
    # can refresh it — instead of silently receiving zero LinkedIn jobs for days.
    if search_li and li_attempted and tg_token and tg_chat:
        try:
            streak = int(db.get_config(supabase_url, supabase_key, "linkedin_zero_streak", "0") or "0")
        except ValueError:
            streak = 0

        if li_run_total == 0:
            streak += 1
            db.set_config(supabase_url, supabase_key, "linkedin_zero_streak", str(streak))
            already_alerted = (db.get_config(supabase_url, supabase_key,
                                             "linkedin_cookie_alerted", "") == "true")
            if streak >= 3 and not already_alerted:
                tg.send_message(
                    tg_token, tg_chat,
                    "🍪 LinkedIn returned 0 results for 3 scans in a row — "
                    "your li_at cookie has most likely expired.\n\n"
                    "Fix it in ~30 seconds:\n"
                    "1. Open linkedin.com in your browser (logged in)\n"
                    "2. F12 → Application → Cookies → linkedin.com\n"
                    "3. Copy the value of  li_at\n"
                    "4. Paste it into the Job Alert GUI → Settings → LinkedIn Cookie → Save\n\n"
                    "Indeed, Bayt and GulfTalent keep working in the meantime.",
                )
                db.set_config(supabase_url, supabase_key, "linkedin_cookie_alerted", "true")
                _log(f"LinkedIn zero-streak={streak} — cookie-expiry alert sent")
            else:
                _log(f"LinkedIn zero-streak={streak} (alert at 3, already_alerted={already_alerted})")
        else:
            # LinkedIn is healthy again — reset streak and re-arm the alert.
            if streak != 0:
                db.set_config(supabase_url, supabase_key, "linkedin_zero_streak", "0")
            if db.get_config(supabase_url, supabase_key, "linkedin_cookie_alerted", "") == "true":
                db.set_config(supabase_url, supabase_key, "linkedin_cookie_alerted", "false")
                _log("LinkedIn healthy again — cookie alert re-armed")

    # --- Gmail job alert emails ---
    if search_gmail:
        try:
            # Fetch unfiltered, then keep jobs matching ANY configured location
            # (the worker may track several, e.g. UAE + Egypt) so jobs from
            # other countries are dropped before Supabase or Telegram.
            gm_jobs = gmail_scan.scan_gmail(
                gmail_email, gmail_password, location=""
            )
            if gm_jobs:
                before = len(gm_jobs)
                gm_jobs = [
                    j for j in gm_jobs
                    if any(gmail_scan._job_location_matches(j.get("Location", ""), loc)
                           for loc in locations)
                ]
                gm_loc_dropped = before - len(gm_jobs)
                if gm_loc_dropped:
                    _log(f"Gmail: dropped {gm_loc_dropped} job(s) outside {locations}")
            if gm_jobs:
                gm_jobs, gm_age_dropped = _age_filter(gm_jobs, "Gmail")
                if gm_age_dropped:
                    _log(f"Gmail: dropped {gm_age_dropped} stale job(s) (>{max_hours}h old)")
            if gm_jobs:
                gm_jobs = _nat_filter(gm_jobs, "Gmail")
            if gm_jobs:
                # Gmail jobs have no per-keyword context — the engine already
                # carries all active keywords so a single pass covers them all.
                gm_jobs, gm_dropped = engine.filter_jobs(gm_jobs, log_prefix="Gmail")
                if gm_dropped:
                    _log(f"Gmail: dropped {gm_dropped} unrelated job(s) (not matching any keyword or CV skills)")
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
                    _alert_new(summary.get("new_jobs", []))
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

    # Sort new jobs by source priority: LinkedIn P1 → Indeed P2 → Gmail P3 → Adzuna P4 → Web P5.
    # This ensures the most reliable source (LinkedIn) always arrives first in Telegram,
    # regardless of which source happened to finish scanning first.
    if len(all_new_jobs) > 1:
        def _src_rank(job: dict) -> int:
            src = job.get("Source", "")
            for prefix, rank in _SOURCE_PRIORITY.items():
                if src.startswith(prefix):
                    return rank
            return 5  # Web/Tavily, Web/Brave, Web/Google, Web/Bing
        all_new_jobs.sort(key=_src_rank)
        _log(
            f"Alert order (top {min(5, len(all_new_jobs))}): "
            + " -> ".join(
                f"{j.get('Source','?').split('/')[0]}:{j.get('Title','?')[:25]}"
                for j in all_new_jobs[:5]
            )
            + ("..." if len(all_new_jobs) > 5 else "")
        )

    # --- Send Telegram alerts ---
    # Worker sends a basic "new job" alert for every new relevant job immediately.
    # Enricher (runs locally with Ollama) later sends a richer "scored" alert,
    # but only for jobs scoring >= min_score that were NOT already notified here.
    # This ensures the user always gets timely notifications — even when enricher
    # isn't running — because non-IT junk is already filtered out by the
    # relevance engine before jobs ever reach this point.
    #
    # Exception: if a job was pre-scored (rare) and its score is below min_score,
    # it is suppressed here too — no alert at all.
    if tg_token and tg_chat:
        sent_count = 0
        skipped_sent = 0
        skipped_low_score = 0
        # already_sent was loaded before the scan loop and updated live by _alert_new().
        # This pass is a safety net for any jobs that slipped through (score merge, etc.)

        for job in all_new_jobs:
            raw_url = job.get("Url", "")

            if raw_url in already_sent:
                skipped_sent += 1
                continue

            llm_score = job.get("llm_score")

            # Job was pre-scored (rare — enricher ran before this worker cycle)
            # and score is below threshold. Suppress silently.
            if llm_score is not None and llm_score < min_score:
                skipped_low_score += 1
                _log(f"Telegram: skipped pre-scored low-score job ({llm_score}/{min_score}) — {job.get('Title', '?')}")
                continue

            # URL safety check
            safe, reason = url_safety.check_url(raw_url)
            if not safe:
                _log(f"Telegram: URL BLOCKED ({reason}): {raw_url[:100]}")
                skipped_sent += 1
                continue
            clean_url = url_safety.sanitize_url(raw_url)
            if clean_url != raw_url:
                job = dict(job)
                job["Url"] = clean_url

            job_id = job.get("Id") or job.get("id") or ""
            ok = tg.send_job_alert_with_button(tg_token, tg_chat, job, job_id=job_id)
            if ok:
                sent_count += 1
                already_sent.add(raw_url)
                try:
                    db.mark_telegram_sent(supabase_url, supabase_key, raw_url)
                except Exception:
                    pass
                time.sleep(0.3)  # avoid Telegram flood limits
            else:
                _log(f"Failed to send Telegram alert for: {job.get('Title', '?')}")

        if skipped_sent:
            _log(f"Telegram: skipped {skipped_sent} already-notified job(s).")
        if skipped_low_score:
            _log(f"Telegram: suppressed {skipped_low_score} pre-scored low-score job(s) (score < {min_score}).")
        _log(f"Telegram: sent {sent_count}/{len(all_new_jobs)} alert(s).")

        # --- Re-alert scan: catch jobs that entered the DB but were never notified ---
        # Covers: Telegram failure mid-run, worker crash after DB write, LinkedIn API
        # returning a job on run N but not again (so it never appears in all_new_jobs again).
        # Window: collected between (max_hours*2 ago) and (30 min ago) — recent enough
        # to still be relevant, old enough to not race with the current run's inserts.
        try:
            catchup = db.get_unnotified_jobs(
                supabase_url, supabase_key,
                min_age_minutes=5,   # was 30 — retry stuck jobs after just 5 min
                max_age_hours=max_hours * 2,
                limit=20,
            )
            if catchup:
                _log(f"Re-alert: {len(catchup)} unnotified job(s) found in DB — sending now")
                catchup_sent = 0
                for job in catchup:
                    raw_url = job.get("url", "")
                    if not raw_url or raw_url in already_sent:
                        continue
                    llm_score = job.get("llm_score")
                    if llm_score is not None and llm_score < min_score:
                        _log(f"Re-alert: skip low-score ({llm_score}/{min_score}) — {job.get('title','?')}")
                        continue
                    # URL safety check
                    safe, reason = url_safety.check_url(raw_url)
                    if not safe:
                        _log(f"Re-alert: URL BLOCKED ({reason}): {raw_url[:100]}")
                        continue
                    clean_url = url_safety.sanitize_url(raw_url)
                    if clean_url != raw_url:
                        job = dict(job)
                        job["url"] = clean_url
                    ok = tg.send_job_alert(tg_token, tg_chat, job)
                    if ok:
                        catchup_sent += 1
                        already_sent.add(raw_url)
                        try:
                            db.mark_telegram_sent(supabase_url, supabase_key, raw_url)
                        except Exception:
                            pass
                        time.sleep(0.3)
                    else:
                        _log(f"Re-alert: failed to send — {job.get('title','?')}")
                if catchup_sent:
                    _log(f"Re-alert: sent {catchup_sent} late-find notification(s)")
            else:
                _log("Re-alert: all caught up — no unnotified jobs in DB")
        except Exception as exc:
            _log(f"Re-alert scan error (non-fatal): {exc}")

    else:
        _log("Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing). Skipping alerts.")

    # --- Heartbeat: record this run + ping external dead-man's switch ----------
    # worker_last_run powers the downtime-detection alert at the top of the next
    # run.  setting_healthcheck_url (optional) lets an external monitor such as
    # healthchecks.io page you if the worker stops pinging entirely.
    try:
        db.set_config(supabase_url, supabase_key, "worker_last_run",
                      datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        _log(f"Heartbeat write error (non-fatal): {exc}")

    healthcheck_url = db.get_config(supabase_url, supabase_key, "setting_healthcheck_url", "")
    if healthcheck_url:
        try:
            import requests as _hc_req
            _hc_req.get(healthcheck_url, timeout=8)
            _log("Heartbeat: external health-check pinged")
        except Exception as exc:
            _log(f"Heartbeat ping error (non-fatal): {exc}")

    _log("Worker finished.")


if __name__ == "__main__":
    main()
