"""
Local LLM enrichment for job-alert.
Reads unscored jobs from Supabase, fetches descriptions, scores with Ollama,
writes llm_score + llm_summary back to Supabase.

Run locally (Ollama must be running):
    python cloud/enricher.py

Or with explicit args:
    python cloud/enricher.py --limit 30 --model llama3.1 --min-score 4
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# Local modules
_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)
import db
import dedup
import linkedin as li
import preferences

DEFAULT_PROFILE = (
    "IT Support Engineer / System Administrator with 3-5 years experience in UAE. "
    "Skills: Windows Server, Active Directory, networking, helpdesk, troubleshooting. "
    "Looking for roles in UAE with competitive salary."
)

DEFAULT_MODEL    = "llama3.1:latest"
DEFAULT_OLLAMA   = "http://localhost:11434"
DEFAULT_MIN_SCORE = 4

# Per-user cache + log directory: %LOCALAPPDATA%\JobAlert on Windows, ~/.job-alert elsewhere
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA")
if _LOCALAPPDATA:
    _STATE_DIR = Path(_LOCALAPPDATA) / "JobAlert"
else:
    _STATE_DIR = Path.home() / ".job-alert"
_STATE_DIR.mkdir(parents=True, exist_ok=True)
_PROFILE_CACHE_PATH = _STATE_DIR / "profile-cache.json"
_ENRICHER_LOG_PATH  = _STATE_DIR / "enricher.log"
_PROFILE_CACHE_TTL_HOURS = 24

# Verbosity flags set by main() — affect _log() behaviour
_VERBOSE      = False
_DEBUG_PROMPT = False
_LOG_TO_FILE  = True


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip().lstrip("﻿")


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if _LOG_TO_FILE:
        try:
            with open(_ENRICHER_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass


def _vlog(msg: str) -> None:
    """Verbose-only log (silent unless --verbose)."""
    if _VERBOSE:
        _log(msg)


def _load_settings_json() -> dict:
    """Read settings.json from the project root (one level above cloud/). Tolerant to missing file / BOM."""
    settings_path = os.path.join(_DIR, "..", "settings.json")
    try:
        with open(settings_path, encoding="utf-8-sig") as f:
            return json.load(f) or {}
    except Exception:
        return {}


# ── Profile resolution ────────────────────────────────────────────────────────

def _extract_pdf(path: str) -> str:
    """Extract plain text from a PDF file using pypdf."""
    try:
        from pypdf import PdfReader
    except ImportError:
        _log("pypdf not installed — run: pip install pypdf")
        return ""
    try:
        reader = PdfReader(path)
        pages = [page.extract_text() or "" for page in reader.pages]
        text = " ".join(pages)
        return re.sub(r"\s+", " ", text).strip()[:5000]
    except Exception as exc:
        _log(f"PDF read error ({os.path.basename(path)}): {exc}")
        return ""


def _load_cached_profile(source_key: str) -> str:
    """Return cached profile text for the given source key if <24h old, else ''."""
    try:
        if not _PROFILE_CACHE_PATH.exists():
            return ""
        with open(_PROFILE_CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f) or {}
        entry = cache.get(source_key)
        if not entry:
            return ""
        cached_at = datetime.fromisoformat(entry.get("cached_at", ""))
        if datetime.now(timezone.utc) - cached_at > timedelta(hours=_PROFILE_CACHE_TTL_HOURS):
            return ""
        text = entry.get("text", "") or ""
        if text:
            _vlog(f"Profile cache HIT for {source_key[:60]} ({len(text)} chars, cached {cached_at.isoformat()})")
        return text
    except Exception:
        return ""


def _save_cached_profile(source_key: str, text: str) -> None:
    """Persist profile text in the local cache with current UTC timestamp."""
    if not text:
        return
    try:
        cache: dict = {}
        if _PROFILE_CACHE_PATH.exists():
            with open(_PROFILE_CACHE_PATH, encoding="utf-8") as f:
                cache = json.load(f) or {}
        cache[source_key] = {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "text": text,
        }
        with open(_PROFILE_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as exc:
        _vlog(f"Profile cache write failed: {exc}")


def _fetch_linkedin_profile(url: str, cookie: str = "") -> str:
    """Scrape a LinkedIn profile page and return a structured text summary.

    Uses a local 24h cache keyed on the URL to avoid re-fetching on every
    enricher run. Honors the LINKEDIN_COOKIE env var (passed in as `cookie`)
    so the public-page wall doesn't strip everything.
    """
    cache_key = f"linkedin::{url}"
    cached = _load_cached_profile(cache_key)
    if cached:
        return cached

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    if cookie:
        headers["Cookie"] = cookie
    else:
        _vlog("LinkedIn profile: no cookie provided (LINKEDIN_COOKIE env var empty) — expect login-wall page")
    try:
        r = requests.get(url, headers=headers, timeout=25)
        r.raise_for_status()
        html = r.text
    except Exception as exc:
        _log(f"LinkedIn profile fetch error: {exc}")
        return ""

    def _plain(s: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"&[a-z]+;", " ", s))).strip()

    parts: list[str] = []

    # Name from title tag
    m = re.search(r"<title>([^<|]+)", html)
    if m:
        parts.append(m.group(1).strip())

    # Headline / summary from JSON-LD or meta
    for pat in [r'"headline"\s*:\s*"([^"]{5,300})"', r'"occupation"\s*:\s*"([^"]{5,200})"']:
        m = re.search(pat, html)
        if m:
            parts.append(_plain(m.group(1)))
            break

    m = re.search(r'"summary"\s*:\s*"([^"]{10,2000})"', html)
    if m:
        parts.append(_plain(m.group(1)))

    # Experience entries
    for m in re.finditer(r'"title"\s*:\s*"([^"]{3,100})"[^}]*"companyName"\s*:\s*"([^"]{2,100})"', html):
        parts.append(f"{_plain(m.group(1))} at {_plain(m.group(2))}")
        if len(parts) > 12:
            break

    # Skills
    skills = re.findall(r'"name"\s*:\s*"([A-Za-z][^"]{1,50})"', html)
    seen = dict.fromkeys(skills)  # deduplicate while preserving order
    if seen:
        parts.append("Skills: " + ", ".join(list(seen)[:25]))

    result = "\n".join(p for p in parts if p)
    if not result:
        _log("LinkedIn profile: could not extract structured data (may need cookie for full access)")
    else:
        _save_cached_profile(cache_key, result[:4000])
    return result[:4000]


def resolve_profile(source: str, cookie: str = "") -> tuple[str, str]:
    """
    Accepts a CV PDF path, a LinkedIn profile URL, or plain text.
    Returns (profile_text, source_label).
    """
    if not source or not source.strip():
        return "", "default"

    s = source.strip()

    # PDF file
    if s.lower().endswith(".pdf") and os.path.isfile(s):
        text = _extract_pdf(s)
        if text:
            _log(f"Profile source: CV PDF — {os.path.basename(s)} ({len(text)} chars)")
            return text, f"CV: {os.path.basename(s)}"
        _log("WARNING: PDF extraction returned empty — falling back to default profile")
        return "", "default"

    # LinkedIn profile URL
    if "linkedin.com/in/" in s.lower():
        text = _fetch_linkedin_profile(s, cookie)
        if text:
            _log(f"Profile source: LinkedIn profile ({len(text)} chars)")
            return text, "LinkedIn profile"
        _log("WARNING: LinkedIn profile fetch returned empty — falling back to default profile")
        return "", "default"

    # Plain text (anything not a .pdf path or LinkedIn URL)
    _log(f"Profile source: text ({len(s)} chars)")
    return s, "text"


def resolve_profile_with_fallback(args_cv: str, supabase_url: str, supabase_key: str, cookie: str) -> tuple[str, str]:
    """
    Walk the full profile-source fallback chain and return (profile_text, label).

    Priority (first non-empty wins):
      1. --cv command-line arg
      2. settings.json `ProfileText` key (plain text resume — new in Phase 1)
      3. settings.json `UserProfile` key (PDF path / LinkedIn URL / text)
      4. Supabase bot_state `setting_user_profile`
      5. Hardcoded DEFAULT_PROFILE
    """
    settings = _load_settings_json()

    chain: list[tuple[str, str]] = []
    if args_cv:
        chain.append(("--cv arg", args_cv.strip()))
    profile_text_setting = str(settings.get("ProfileText") or "").strip()
    if profile_text_setting:
        chain.append(("settings.json:ProfileText", profile_text_setting))
    user_profile_setting = str(settings.get("UserProfile") or "").strip()
    if user_profile_setting:
        chain.append(("settings.json:UserProfile", user_profile_setting))
    try:
        sb_setting = (db.get_config(supabase_url, supabase_key, "setting_user_profile", "") or "").strip()
    except Exception:
        sb_setting = ""
    if sb_setting:
        chain.append(("supabase:setting_user_profile", sb_setting))

    for origin, source in chain:
        _vlog(f"Profile fallback: trying {origin} ({len(source)} chars)")
        text, label = resolve_profile(source, cookie)
        if text:
            return text, f"{label} (from {origin})"

    _log("Profile fallback: all sources empty — using DEFAULT_PROFILE")
    return DEFAULT_PROFILE, "default"


# ── Ollama ────────────────────────────────────────────────────────────────────

_FEW_SHOT_EXAMPLES = """\
EXAMPLE 1 (obvious match):
  Candidate: IT Support Engineer, 4 years UAE, Windows Server / AD / networking / O365.
  Job: "Senior IT Support, Dubai" at TechCorp. Manages Windows servers + AD + helpdesk.
  Output: {"skills_match": 9, "experience_match": 9, "location_match": 10, "seniority_match": 9, "overall_score": 9,
           "matched_skills": ["Windows Server","Active Directory","Helpdesk"],
           "missing_skills": [], "red_flags": [],
           "reasoning": "Strong overlap on every axis: skills, seniority, and UAE location all align."}

EXAMPLE 2 (obvious mismatch):
  Candidate: IT Support Engineer, 4 years UAE, no sales experience.
  Job: "Senior Sales Manager, Real Estate, Dubai".
  Output: {"skills_match": 1, "experience_match": 1, "location_match": 10, "seniority_match": 3, "overall_score": 2,
           "matched_skills": [], "missing_skills": ["Sales","Real Estate"],
           "red_flags": ["Completely different field (sales vs IT)"],
           "reasoning": "Location aligns but role is in a different domain entirely."}

EXAMPLE 3 (borderline):
  Candidate: IT Support Engineer, 4 years UAE, no cloud cert yet.
  Job: "Cloud Infrastructure Engineer (AWS), Abu Dhabi". Requires AWS cert, Linux, scripting.
  Output: {"skills_match": 5, "experience_match": 6, "location_match": 9, "seniority_match": 7, "overall_score": 6,
           "matched_skills": ["Linux","Scripting"],
           "missing_skills": ["AWS certification","Cloud infrastructure"],
           "red_flags": ["AWS cert is a hard requirement"],
           "reasoning": "Partial fit; foundational IT skills transfer but the cloud-specific requirements are gaps."}

"""


def ollama_score(
    job: dict,
    description: str,
    profile: str,
    model: str,
    ollama_url: str,
    dynamic_few_shot: str = "",
) -> tuple[int, str, dict]:
    """Call Ollama to score a job on 4 axes + overall.

    Returns (overall_score, reasoning_summary, full_breakdown_dict).
    Breakdown keys: skills_match, experience_match, location_match, seniority_match,
                    overall_score, matched_skills, missing_skills, red_flags, reasoning.
    """
    desc_excerpt = description[:2000] if description else "(no description available)"

    prompt = (
        "You are a job-fit scorer. Rate how well this job matches the candidate on FOUR axes,\n"
        "then give an overall score that weighs them holistically (skills + experience matter most).\n"
        "Output STRICT JSON only - no markdown, no prose outside the JSON.\n\n"
        "Schema:\n"
        "{\n"
        '  "skills_match":     <int 0-10>,  // overlap of required skills with candidate skills\n'
        '  "experience_match": <int 0-10>,  // years/level vs candidate background\n'
        '  "location_match":   <int 0-10>,  // job location vs candidate location\n'
        '  "seniority_match":  <int 0-10>,  // role level (junior/mid/senior) vs candidate level\n'
        '  "overall_score":    <int 0-10>,  // weighted overall fit\n'
        '  "matched_skills":   [<short strings>],  // up to 5 skills present in both job and candidate\n'
        '  "missing_skills":   [<short strings>],  // up to 5 important skills required but candidate lacks\n'
        '  "red_flags":        [<short strings>],  // up to 3 hard mismatches (e.g., language requirement, on-site only)\n'
        '  "reasoning":        "<one sentence why this overall_score>"\n'
        "}\n\n"
        f"{_FEW_SHOT_EXAMPLES}"
        f"{dynamic_few_shot}"
        "NOW SCORE THIS JOB:\n"
        f"Candidate: {profile}\n\n"
        f"Job Title: {job.get('title', '')}\n"
        f"Company: {job.get('company', '')}\n"
        f"Location: {job.get('location', '')}\n"
        f"Description:\n{desc_excerpt}"
    )

    if _DEBUG_PROMPT:
        _log("--- PROMPT (debug) ---")
        _log(prompt[:6000] + (" ...[truncated]" if len(prompt) > 6000 else ""))
        _log("--- END PROMPT ---")

    def _clamp_int(v, lo=0, hi=10, default=5):
        try:    return max(lo, min(hi, int(v)))
        except: return default

    def _clean_list(v, max_items=5, max_len=60):
        if not isinstance(v, list):
            return []
        out = []
        for item in v[:max_items]:
            s = str(item).strip()[:max_len]
            if s:
                out.append(s)
        return out

    try:
        r = requests.post(
            f"{ollama_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=120,
        )
        r.raise_for_status()
        raw = r.json().get("response", "{}")
        if _DEBUG_PROMPT:
            _log(f"Ollama raw response: {raw[:800]}")
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}

        breakdown = {
            "skills_match":     _clamp_int(data.get("skills_match")),
            "experience_match": _clamp_int(data.get("experience_match")),
            "location_match":   _clamp_int(data.get("location_match")),
            "seniority_match":  _clamp_int(data.get("seniority_match")),
            "overall_score":    _clamp_int(data.get("overall_score")),
            "matched_skills":   _clean_list(data.get("matched_skills")),
            "missing_skills":   _clean_list(data.get("missing_skills")),
            "red_flags":        _clean_list(data.get("red_flags"), max_items=3, max_len=80),
            "reasoning":        str(data.get("reasoning", "")).strip()[:300],
        }
        # If overall_score wasn't returned, derive it from the 4 axes (weighted average)
        if data.get("overall_score") is None:
            axes = [
                (breakdown["skills_match"],     0.40),
                (breakdown["experience_match"], 0.30),
                (breakdown["seniority_match"],  0.15),
                (breakdown["location_match"],   0.15),
            ]
            weighted = sum(v * w for v, w in axes)
            breakdown["overall_score"] = _clamp_int(round(weighted))
        return breakdown["overall_score"], breakdown["reasoning"], breakdown
    except requests.exceptions.ConnectionError:
        _log(f"ERROR: Cannot reach Ollama at {ollama_url} - is 'ollama serve' running?")
        return -1, "", {}
    except Exception as exc:
        _log(f"Ollama error: {exc}")
        return -1, "", {}


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # Windows: force UTF-8 stdout/stderr so non-ASCII chars in job titles or
    # log output don't crash with 'charmap codec can't encode' under cp1252.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Enrich jobs with local LLM scoring")
    parser.add_argument("--limit",     type=int, default=20,              help="Max jobs to enrich per run")
    parser.add_argument("--model",     default=DEFAULT_MODEL,             help="Ollama model name")
    parser.add_argument("--ollama",    default=DEFAULT_OLLAMA,            help="Ollama base URL")
    parser.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE, help="Auto-dismiss below this score")
    parser.add_argument("--cv",        default="",                        help="CV PDF path, LinkedIn profile URL, or plain text profile")
    parser.add_argument("--verbose",      action="store_true", help="Verbose logging (profile chain, cache, prompt sizes)")
    parser.add_argument("--debug-prompt", action="store_true", help="Log the full LLM prompt + raw response (implies --verbose)")
    parser.add_argument("--health-check", action="store_true", help="Run a single end-to-end test, then exit with summary")
    args = parser.parse_args()

    global _VERBOSE, _DEBUG_PROMPT
    _VERBOSE      = args.verbose or args.debug_prompt or args.health_check
    _DEBUG_PROMPT = args.debug_prompt or args.health_check

    _log(f"Enricher invoked: limit={args.limit} health-check={args.health_check} verbose={_VERBOSE} debug-prompt={_DEBUG_PROMPT}")
    _log(f"State dir: {_STATE_DIR}  (log: {_ENRICHER_LOG_PATH.name}, cache: {_PROFILE_CACHE_PATH.name})")

    supabase_url = _env("SUPABASE_URL")
    supabase_key = _env("SUPABASE_KEY")

    # Cookie: env var first, then settings.json so script works when called standalone
    cookie = _env("LINKEDIN_COOKIE")
    if not (supabase_url and supabase_key) or not cookie:
        cfg = _load_settings_json()
        if not supabase_url: supabase_url = (cfg.get("SupabaseUrl", "") or "").strip()
        if not supabase_key: supabase_key = (cfg.get("SupabaseKey", "") or "").strip()
        if not cookie:       cookie       = (cfg.get("LinkedInCookie", "") or "").strip()

    if not supabase_url or not supabase_key:
        _log("ERROR: Set SUPABASE_URL and SUPABASE_KEY env vars or fill them in settings.json.")
        sys.exit(1)

    _vlog(f"LinkedIn cookie: {'present (' + str(len(cookie)) + ' chars)' if cookie else 'EMPTY — LinkedIn profile fetches will hit login wall'}")

    # Read config overrides from Supabase bot_state
    model     = db.get_config(supabase_url, supabase_key, "setting_ollama_model", "") or args.model
    ollama    = db.get_config(supabase_url, supabase_key, "setting_ollama_url",   "") or args.ollama
    try:
        min_score = int(db.get_config(supabase_url, supabase_key, "setting_llm_min_score", "") or args.min_score)
    except ValueError:
        min_score = args.min_score

    # Profile resolution with full fallback chain (--cv > ProfileText > UserProfile > Supabase > default)
    profile, profile_label = resolve_profile_with_fallback(args.cv, supabase_url, supabase_key, cookie)

    # Load Telegram config for post-score alerts
    tg_token = db.get_config(supabase_url, supabase_key, "setting_telegram_bot_token", "") or _env("TELEGRAM_BOT_TOKEN")
    tg_chat  = db.get_config(supabase_url, supabase_key, "setting_telegram_chat_id",   "") or _env("TELEGRAM_CHAT_ID")

    effective_limit = 1 if args.health_check else args.limit
    _log(f"Enricher starting - model={model}, min_score={min_score}, limit={effective_limit}, profile={profile_label}")

    # Phase 4: pull the user's recent applied/dismissed history once per run
    # and inject it as a dynamic few-shot block in every score's prompt.
    # Cached in bot_state with a 6h TTL; rebuilds automatically when stale.
    try:
        dynamic_few_shot = preferences.get_cached_or_refresh(supabase_url, supabase_key)
        if dynamic_few_shot:
            applied_n   = dynamic_few_shot.count("USER APPLIED:")
            dismissed_n = dynamic_few_shot.count("USER DISMISSED:")
            _log(f"Active learning: {applied_n} applied + {dismissed_n} dismissed examples loaded into prompt")
        else:
            _vlog("Active learning: no history yet - prompt uses static examples only")
    except Exception as exc:
        _log(f"Active learning failed (non-fatal, using static only): {exc}")
        dynamic_few_shot = ""

    # Health check: don't send Telegram alerts during a diagnostic run
    if args.health_check:
        tg_token = tg_chat = ""

    jobs = db.get_unscored_jobs(supabase_url, supabase_key, limit=effective_limit)
    if not jobs:
        _log("No unscored jobs found. All done.")
        if args.health_check:
            _log("HEALTH-CHECK: PASS (Ollama reachable assumed; no unscored jobs to score — try after a fresh scan)")
        return

    _log(f"Found {len(jobs)} unscored job(s). Scoring...")

    scored = dismissed = failed = 0

    for i, job in enumerate(jobs, 1):
        title   = job.get("title", "?")
        company = job.get("company", "?")
        _log(f"[{i}/{len(jobs)}] {title} @ {company}")

        description = li.fetch_job_description(job.get("url", ""), cookie)
        if description:
            _log(f"          Description: {len(description)} chars")
        else:
            _log("          No description fetched - scoring on title/company/location only")

        # Phase 3: dedup BEFORE scoring. If this job duplicates an existing one,
        # link it and skip the expensive LLM scoring + Telegram alert entirely.
        job_for_dedup = dict(job)
        if description:
            job_for_dedup["description"] = description
        dup_result = dedup.process_one_job(
            supabase_url, supabase_key, job_for_dedup,
            ollama_url=ollama,
        )
        if dup_result["action"] == "duplicate":
            _log(f"          DUPLICATE of {dup_result['duplicate_of_url'][:70]}  "
                 f"(sim={dup_result['similarity']:.3f}) - skipping score + alert")
            # Mark dismissed-as-duplicate so it doesn't reappear in unscored queries
            db.update_job_enrichment(
                supabase_url, supabase_key,
                job["job_id"], description, score=0,
                summary=f"Duplicate of {dup_result['duplicate_of_url']}",
                min_score=min_score,
            )
            continue
        elif dup_result["action"] == "no_embedding":
            _vlog("          Embedding failed - proceeding to score anyway")

        score, summary, breakdown = ollama_score(job, description, profile, model, ollama,
                                                  dynamic_few_shot=dynamic_few_shot)

        if score == -1:
            _log("          Ollama unreachable - stopping enrichment")
            break

        verdict = "KEEP" if score >= min_score else "DISMISS"
        _log(f"          Score: {score}/10  [{verdict}]  S={breakdown.get('skills_match','?')} E={breakdown.get('experience_match','?')} L={breakdown.get('location_match','?')} Sr={breakdown.get('seniority_match','?')}")
        if breakdown.get("matched_skills"):
            _log(f"          Matched: {', '.join(breakdown['matched_skills'])}")
        if breakdown.get("missing_skills"):
            _log(f"          Missing: {', '.join(breakdown['missing_skills'])}")
        if breakdown.get("red_flags"):
            _log(f"          Red flags: {' | '.join(breakdown['red_flags'])}")

        db.update_job_enrichment(
            supabase_url, supabase_key,
            job["job_id"], description, score, summary,
            min_score=min_score,
            breakdown=breakdown,
        )

        # Send Telegram score notification for kept jobs (richer format with breakdown)
        if score >= min_score and tg_token and tg_chat:
            try:
                import telegram_notify as tg
                tg.send_score_alert(tg_token, tg_chat, job, breakdown)
                time.sleep(0.3)
            except Exception as exc:
                _log(f"          Telegram score alert error: {exc}")

        if score < min_score:
            dismissed += 1
        else:
            scored += 1

        if i < len(jobs):
            time.sleep(0.5)  # small pause between Ollama calls

    _log(f"Done. Scored={scored}, Auto-dismissed={dismissed}, Failed={failed}")

    if args.health_check:
        if scored + dismissed > 0:
            _log("HEALTH-CHECK: PASS — Ollama reached, profile resolved, at least one job scored end-to-end.")
            sys.exit(0)
        else:
            _log("HEALTH-CHECK: FAIL — no job was scored. Check the messages above for the cause.")
            sys.exit(2)


if __name__ == "__main__":
    main()
