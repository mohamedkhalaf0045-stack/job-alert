"""
CrewAI multi-agent job scanner.

Architecture
------------
Agent 1  LinkedIn Scout   ─┐
Agent 2  Bayt Scout       ─┤  parallel (ThreadPoolExecutor)
Agent 3  GulfTalent Scout ─┤
Agent 4  NaukriGulf Scout ─┘
         ↓ all new jobs collected
Agent 5  Analyst          — scores every new job with Groq (llama-3.3-70b-versatile)
         ↓ scored jobs
Agent 6  Alert Dispatcher — sends Telegram immediately with score + salary breakdown

Why this is better than worker.py + separate enricher:
  • All sources scrape simultaneously (8-12 min → ~2-3 min per run)
  • Groq scores jobs inline — no Ollama, works in GitHub Actions
  • Telegram fires instantly when score >= min_score (no 15-min user_alerts.py wait)
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── cloud/ path setup ─────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent))

import db
import linkedin as li_scraper
import bayt as bayt_scraper
import gulftalent as gt_scraper
import naukri_gulf as naukri_scraper
import telegram_notify as tg
import relevance_engine

from crewai.tools import tool


# ── Logging ───────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", errors="replace").decode("ascii"), flush=True)


# ── Environment ───────────────────────────────────────────────────────────────

def _e(name: str, default: str = "") -> str:
    """Read env var, stripping BOM artifacts that GitHub Actions sometimes adds."""
    return os.environ.get(name, default).strip().lstrip("﻿")


SUPABASE_URL    = _e("SUPABASE_URL")
SUPABASE_KEY    = _e("SUPABASE_KEY")
TG_TOKEN        = _e("TELEGRAM_BOT_TOKEN")
TG_CHAT         = _e("TELEGRAM_CHAT_ID")
LI_COOKIE       = _e("LINKEDIN_COOKIE")
GROQ_API_KEY    = _e("GROQ_API_KEY")
OPENAI_API_KEY  = _e("OPENAI_API_KEY")
MAX_HOURS       = int(_e("MAX_HOURS", "72"))
_DEFAULT_MIN    = 4

# Thread-safe bucket for results from parallel scraper agents
_ALL_NEW_JOBS: list[dict] = []
_JOBS_LOCK = threading.Lock()


# ── Config loader ─────────────────────────────────────────────────────────────

class _Config:
    scan_targets: list[tuple[str, str]]
    engine: Any
    min_score: int
    profile: str
    active_users: int


def _load_config() -> _Config:
    cfg = _Config()

    # Pull active user preferences
    active_prefs: list[dict] = []
    try:
        active_prefs = db.get_active_profiles(SUPABASE_URL, SUPABASE_KEY)
    except Exception as exc:
        _log(f"Could not load active profiles (using env defaults): {exc}")

    targets: set[tuple[str, str]] = set()
    for user in active_prefs:
        for kw in (user.get("keywords") or []):
            for loc in (user.get("locations") or []):
                if kw.strip() and loc.strip():
                    targets.add((kw.strip(), loc.strip()))

    if not targets:
        _log("No active user profiles found — using default keywords")
        for kw in ["IT Support", "System Administrator", "IT HelpDesk", "IT Infrastructure"]:
            targets.add((kw, "United Arab Emirates"))

    cfg.scan_targets = sorted(targets)
    cfg.active_users = len(active_prefs)

    all_kws = sorted({kw for kw, _ in targets})
    try:
        cfg.engine = relevance_engine.RelevanceEngine.from_supabase(
            SUPABASE_URL, SUPABASE_KEY, all_kws
        )
    except Exception:
        cfg.engine = relevance_engine.RelevanceEngine(all_kws, set(), set(), set())

    # Min score from Supabase or env
    cfg.min_score = _DEFAULT_MIN
    try:
        s = db.get_config(SUPABASE_URL, SUPABASE_KEY, "setting_llm_min_score", "")
        if s:
            cfg.min_score = int(s)
    except Exception:
        pass

    # CV profile for scoring context
    cfg.profile = (
        "IT Support Engineer / System Administrator, 3-5 years UAE experience. "
        "Skills: Windows Server, Active Directory, Office 365, networking, helpdesk."
    )
    try:
        titles = db.get_config(SUPABASE_URL, SUPABASE_KEY, "cv_job_titles", "")
        skills = db.get_config(SUPABASE_URL, SUPABASE_KEY, "cv_skills", "")
        summary = db.get_config(SUPABASE_URL, SUPABASE_KEY, "cv_summary", "")
        if titles or skills:
            cfg.profile = f"Job titles: {titles}. Skills: {skills}. {summary}".strip()
    except Exception:
        pass

    return cfg


# ── Groq scorer ───────────────────────────────────────────────────────────────

_SCORE_SYSTEM = (
    "You are a job-match analyst. Score this job for the given candidate profile.\n"
    "Return ONLY valid JSON — no markdown fences, no commentary.\n"
    "Required fields:\n"
    "  overall_score      (int 1-10)\n"
    "  skills_match       (int 1-10)\n"
    "  experience_match   (int 1-10)\n"
    "  location_match     (int 1-10)\n"
    "  seniority_match    (int 1-10)\n"
    "  matched_skills     (list of strings, max 5)\n"
    "  missing_skills     (list of strings, max 5)\n"
    "  red_flags          (list of strings, max 3)\n"
    "  reasoning          (string, ≤120 chars)\n"
    "  salary             (object with min/max/avg/currency/period/source — or null)"
)

import requests as _req


def _score_job_with_groq(job: dict, profile: str) -> dict | None:
    """Call Groq and return a scoring breakdown dict, or None on failure."""
    if not GROQ_API_KEY:
        return None

    title    = (job.get("title") or job.get("Title") or "").strip()
    company  = (job.get("company") or job.get("Company") or "").strip()
    location = (job.get("location") or job.get("Location") or "").strip()
    desc     = (job.get("description") or "")[:1500]

    user_msg = (
        f"Profile:\n{profile}\n\n"
        f"Job: {title} at {company} ({location})\n"
        f"{desc}\n\n"
        "Score this match. Return only JSON."
    )

    for attempt in range(1, 3):
        try:
            resp = _req.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": _SCORE_SYSTEM},
                        {"role": "user",   "content": user_msg},
                    ],
                    "max_tokens": 400,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
                timeout=30,
            )
            if resp.status_code != 200:
                _log(f"Groq HTTP {resp.status_code} for '{title}'")
                return None
            content = resp.json()["choices"][0]["message"]["content"].strip()
            # Strip accidental markdown fences
            if content.startswith("```"):
                parts = content.split("```")
                content = parts[1].lstrip("json").strip() if len(parts) > 1 else content
            return json.loads(content)
        except Exception as exc:
            if attempt == 1:
                _log(f"Groq scoring attempt {attempt} failed for '{title}': {exc}")
                time.sleep(1)
            else:
                _log(f"Groq scoring failed for '{title}': {exc}")
    return None


# ── Single-source scraper (runs inside ThreadPoolExecutor) ────────────────────

def _scrape_one(source: str, keyword: str, location: str, engine: Any) -> list[dict]:
    """Scrape one source for one keyword/location. Returns list of new job dicts."""
    label = f"{source} '{keyword}'"
    try:
        if source == "LinkedIn":
            jobs = li_scraper.scrape_linkedin(
                keyword=keyword, location=location,
                cookie_header=LI_COOKIE, max_hours=MAX_HOURS,
            )
        elif source == "Bayt":
            jobs = bayt_scraper.scrape_bayt(keyword=keyword, location=location)
        elif source == "GulfTalent":
            jobs = gt_scraper.scrape_gulftalent(keyword=keyword, location=location)
        elif source == "NaukriGulf":
            jobs = naukri_scraper.scrape_naukri_gulf(keyword=keyword, location=location)
        else:
            return []

        jobs, dropped = engine.filter_jobs(jobs, log_prefix=label)
        if dropped:
            _log(f"{label}: dropped {dropped} unrelated")

        summary = db.sync_jobs(SUPABASE_URL, SUPABASE_KEY, jobs, source=source)
        _log(
            f"{label}: inserted={summary['inserted']} "
            f"updated={summary['updated']} seen={summary['seen']}"
        )
        new_jobs = summary.get("new_jobs", [])

        # Pre-fetch LinkedIn descriptions for newly inserted jobs
        if source == "LinkedIn":
            for nj in new_jobs[:8]:
                nj_id  = str(nj.get("Id", "")).strip()
                nj_url = nj.get("Url", "")
                if nj_id and nj_url:
                    try:
                        desc = li_scraper.fetch_job_description(nj_url, LI_COOKIE)
                        if desc:
                            db.update_job_description(SUPABASE_URL, SUPABASE_KEY, nj_id, desc)
                            nj["description"] = desc
                    except Exception:
                        pass

        return new_jobs

    except Exception as exc:
        _log(f"{label} error: {exc}")
        return []


# ── CrewAI tools ──────────────────────────────────────────────────────────────

@tool("parallel_scrape_all_sources")
def parallel_scrape_all_sources(targets_json: str) -> str:
    """
    Scrape LinkedIn, Bayt, GulfTalent, and NaukriGulf simultaneously.

    Input: JSON string {"scan_targets": [["keyword", "location"], ...]}
    Output: JSON string {"new_jobs": [...], "total": N}
    """
    try:
        data = json.loads(targets_json)
        scan_targets: list[list[str]] = data.get("scan_targets", [])

        if not scan_targets:
            return json.dumps({"new_jobs": [], "total": 0, "error": "No targets"})

        all_kws = list({kw for kw, _ in scan_targets})
        engine  = relevance_engine.RelevanceEngine(all_kws, set(), set(), set())

        sources = ["LinkedIn", "Bayt", "GulfTalent", "NaukriGulf"]
        work_items = [
            (src, kw, loc)
            for kw, loc in scan_targets
            for src in sources
        ]

        collected: list[dict] = []
        with ThreadPoolExecutor(max_workers=min(len(work_items), 12)) as pool:
            futs = {pool.submit(_scrape_one, src, kw, loc, engine): (src, kw, loc)
                    for src, kw, loc in work_items}
            for fut in as_completed(futs):
                collected.extend(fut.result())

        _log(f"[Scout] Parallel scrape done — {len(collected)} new jobs across all sources")
        # Store in global so Analyst agent can also access them
        with _JOBS_LOCK:
            _ALL_NEW_JOBS.clear()
            _ALL_NEW_JOBS.extend(collected)

        return json.dumps({"new_jobs": collected, "total": len(collected)})

    except Exception as exc:
        _log(f"[Scout] parallel_scrape error: {exc}")
        return json.dumps({"new_jobs": [], "total": 0, "error": str(exc)})


@tool("score_and_dispatch_alerts")
def score_and_dispatch_alerts(payload_json: str) -> str:
    """
    Score new jobs with Groq and send Telegram alerts immediately for matches.

    Input: JSON string {"new_jobs": [...], "profile": "...", "min_score": 4}
    Output: JSON string {"scored": N, "alerted": N, "total": N}
    """
    try:
        data      = json.loads(payload_json)
        new_jobs  = data.get("new_jobs") or []
        profile   = data.get("profile", "IT Support Engineer in UAE")
        min_score = int(data.get("min_score", _DEFAULT_MIN))

        # Fallback: try global bucket if new_jobs was empty (LLM truncated the list)
        if not new_jobs:
            with _JOBS_LOCK:
                new_jobs = list(_ALL_NEW_JOBS)
            if new_jobs:
                _log(f"[Analyst] Used global job bucket ({len(new_jobs)} jobs)")

        if not new_jobs:
            _log("[Analyst] No new jobs to score")
            return json.dumps({"scored": 0, "alerted": 0, "total": 0})

        scored = alerted = 0
        _log(f"[Analyst] Scoring {len(new_jobs)} new jobs with Groq …")

        for job in new_jobs:
            job_id = str(job.get("Id") or job.get("job_id") or "").strip()
            url    = (job.get("Url") or job.get("url") or "").strip()

            breakdown = _score_job_with_groq(job, profile)

            if breakdown:
                scored += 1
                score = max(1, min(10, int(breakdown.get("overall_score", 0))))
                summary_text = (breakdown.get("reasoning") or "")[:200]

                # Persist score to DB
                if job_id:
                    db.update_job_enrichment(
                        SUPABASE_URL, SUPABASE_KEY,
                        job_id=job_id,
                        description=(job.get("description") or "")[:4000],
                        score=score,
                        summary=summary_text,
                        min_score=min_score,
                        breakdown=breakdown,
                    )

                # Alert for matches above threshold
                if score >= min_score and TG_TOKEN and TG_CHAT:
                    sent = tg.send_score_update(TG_TOKEN, TG_CHAT, job, breakdown, job_id=job_id)
                    if sent:
                        alerted += 1
                        if url:
                            db.mark_telegram_sent(SUPABASE_URL, SUPABASE_KEY, url)
                        _log(
                            f"[Dispatcher] Alerted: score={score}/10 "
                            f"'{job.get('title') or job.get('Title')[:50]}'"
                        )

            else:
                # Groq unavailable — alert unscored jobs directly
                if TG_TOKEN and TG_CHAT:
                    sent = tg.send_job_alert_with_button(TG_TOKEN, TG_CHAT, job, job_id=job_id)
                    if sent:
                        alerted += 1
                        if url:
                            db.mark_telegram_sent(SUPABASE_URL, SUPABASE_KEY, url)

        _log(f"[Analyst/Dispatcher] Done — scored={scored} alerted={alerted} total={len(new_jobs)}")
        return json.dumps({"scored": scored, "alerted": alerted, "total": len(new_jobs)})

    except Exception as exc:
        _log(f"[Analyst] score_and_dispatch error: {exc}")
        return json.dumps({"scored": 0, "alerted": 0, "total": 0, "error": str(exc)})


# ── Main runner (direct — no LLM needed for orchestration) ───────────────────

def build_and_run_crew(cfg: _Config) -> None:
    """Run parallel scraping + Groq scoring directly without CrewAI agent loop."""
    if not GROQ_API_KEY:
        _log("WARNING: GROQ_API_KEY not set — jobs will be scraped but not scored")

    _log(
        f"Starting worker — {cfg.active_users} active user(s), "
        f"{len(cfg.scan_targets)} scrape target(s), min_score={cfg.min_score}"
    )

    # Step 1: Parallel scraping across all sources
    targets_arg = json.dumps({"scan_targets": cfg.scan_targets})
    scrape_json = parallel_scrape_all_sources.run(targets_arg)
    scrape = json.loads(scrape_json)
    new_jobs = scrape.get("new_jobs", [])
    _log(f"Scrape complete — {len(new_jobs)} new job(s) found")

    if not new_jobs:
        _log("No new jobs this run.")
        return

    # Step 2: Score with Groq + send Telegram alerts immediately
    payload = json.dumps({
        "new_jobs": new_jobs,
        "profile": cfg.profile,
        "min_score": cfg.min_score,
    })
    result_json = score_and_dispatch_alerts.run(payload)
    result = json.loads(result_json)
    _log(
        f"Done — scored={result.get('scored')} "
        f"alerted={result.get('alerted')} "
        f"total={result.get('total')}"
    )


# ── Telegram command handler (same as worker.py) ──────────────────────────────

def _handle_telegram_commands(cfg: _Config) -> None:
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        offset  = int(db.get_config(SUPABASE_URL, SUPABASE_KEY, "telegram_offset", "0"))
        updates = tg.get_updates(TG_TOKEN, offset=offset)

        for cb in tg.extract_callbacks(updates):
            data = cb["data"]
            if data.startswith("cover_"):
                job_id = data[len("cover_"):]
                cover  = db.get_cover_letter(SUPABASE_URL, SUPABASE_KEY, job_id)
                tg.answer_callback_query(TG_TOKEN, cb["callback_query_id"])
                msg = ("\U0001f4dd Cover Letter Draft\n\n" + cover) if cover else (
                    "\U0001f4dd Cover letter not ready yet.\n"
                    "Run: python cloud/enricher.py --limit 30"
                )
                tg.send_message(TG_TOKEN, cb["chat_id"], msg)

            elif data.startswith("cv_"):
                job_id = data[len("cv_"):]
                cv     = db.get_tailored_cv(SUPABASE_URL, SUPABASE_KEY, job_id)
                tg.answer_callback_query(TG_TOKEN, cb["callback_query_id"])
                msg = ("\U0001f4c4 Tailored CV Draft\n\n" + cv) if cv else (
                    "\U0001f4c4 Tailored CV not ready yet.\n"
                    "Run: python cloud/enricher.py --limit 30"
                )
                tg.send_message(TG_TOKEN, cb["chat_id"], msg)

            elif data.startswith("bad_") or data.startswith("good_"):
                is_bad = data.startswith("bad_")
                job_id = data[4:]
                db.set_job_status(SUPABASE_URL, SUPABASE_KEY, job_id,
                                  "dismissed" if is_bad else "applied")
                tg.answer_callback_query(
                    TG_TOKEN, cb["callback_query_id"],
                    text="👎 Got it — fewer like this" if is_bad else "👍 Noted — more like this",
                )

        for cmd in tg.extract_commands(updates):
            if cmd["command"] == "/status":
                tg.send_message(
                    TG_TOKEN, cmd["chat_id"],
                    f"CrewAI Worker — running OK\n"
                    f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
                    f"Active users: {cfg.active_users}\n"
                    f"Targets: {len(cfg.scan_targets)}\n"
                    f"Min score: {cfg.min_score}/10\n"
                    f"Groq scoring: {'✅ enabled' if GROQ_API_KEY else '❌ GROQ_API_KEY not set'}"
                )

        if updates:
            new_offset = max(u["update_id"] for u in updates) + 1
            db.set_config(SUPABASE_URL, SUPABASE_KEY, "telegram_offset", str(new_offset))

    except Exception as exc:
        _log(f"Telegram command poll error (non-fatal): {exc}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    if not SUPABASE_URL or not SUPABASE_KEY:
        _log("ERROR: SUPABASE_URL or SUPABASE_KEY env var not set. Exiting.")
        sys.exit(1)

    _log("CrewAI Job Alert Worker v1 starting …")

    db.initialize_database(SUPABASE_URL, SUPABASE_KEY)
    cfg = _load_config()

    # Handle pending Telegram commands before scraping
    _handle_telegram_commands(cfg)

    # Build and run the multi-agent crew
    try:
        build_and_run_crew(cfg)
    except Exception as exc:
        _log(f"Crew error: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Record heartbeat
    try:
        db.set_config(SUPABASE_URL, SUPABASE_KEY, "worker_last_run",
                      datetime.now(timezone.utc).isoformat())
    except Exception:
        pass

    _log("CrewAI Worker finished.")


if __name__ == "__main__":
    main()
