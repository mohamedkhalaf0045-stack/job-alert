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
from datetime import datetime, timezone

import requests

# Local modules
_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)
import db
import linkedin as li

DEFAULT_PROFILE = (
    "IT Support Engineer / System Administrator with 3-5 years experience in UAE. "
    "Skills: Windows Server, Active Directory, networking, helpdesk, troubleshooting. "
    "Looking for roles in UAE with competitive salary."
)

DEFAULT_MODEL    = "llama3.1"
DEFAULT_OLLAMA   = "http://localhost:11434"
DEFAULT_MIN_SCORE = 4


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip().lstrip("﻿")


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


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


def _fetch_linkedin_profile(url: str, cookie: str = "") -> str:
    """Scrape a LinkedIn profile page and return a structured text summary."""
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

    # Plain text
    _log(f"Profile source: text ({len(s)} chars)")
    return s, "text"


# ── Ollama ────────────────────────────────────────────────────────────────────

def ollama_score(
    job: dict,
    description: str,
    profile: str,
    model: str,
    ollama_url: str,
) -> tuple[int, str]:
    """Call Ollama to score a job 0-10. Returns (score, summary)."""
    desc_excerpt = description[:2000] if description else "(no description available)"

    prompt = (
        f"You are a job relevance scorer. Rate how relevant this job is for the candidate.\n"
        f"Reply with valid JSON only, no markdown, no extra text.\n"
        f"Format: {{\"score\": <integer 0-10>, \"summary\": \"<one sentence why>\"}}\n\n"
        f"Candidate: {profile}\n\n"
        f"Job Title: {job.get('title', '')}\n"
        f"Company: {job.get('company', '')}\n"
        f"Location: {job.get('location', '')}\n"
        f"Description:\n{desc_excerpt}"
    )

    try:
        r = requests.post(
            f"{ollama_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=90,
        )
        r.raise_for_status()
        raw = r.json().get("response", "{}")
        # Extract JSON even if there's surrounding text
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        score   = max(0, min(10, int(data.get("score", 5))))
        summary = str(data.get("summary", "")).strip()[:300]
        return score, summary
    except requests.exceptions.ConnectionError:
        _log("ERROR: Cannot reach Ollama at {ollama_url} — is 'ollama serve' running?")
        return -1, ""
    except Exception as exc:
        _log(f"Ollama error: {exc}")
        return -1, ""


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich jobs with local LLM scoring")
    parser.add_argument("--limit",     type=int, default=20,              help="Max jobs to enrich per run")
    parser.add_argument("--model",     default=DEFAULT_MODEL,             help="Ollama model name")
    parser.add_argument("--ollama",    default=DEFAULT_OLLAMA,            help="Ollama base URL")
    parser.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE, help="Auto-dismiss below this score")
    parser.add_argument("--cv",        default="",                        help="CV PDF path, LinkedIn profile URL, or plain text profile")
    args = parser.parse_args()

    supabase_url = _env("SUPABASE_URL")
    supabase_key = _env("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        # Try loading from settings.json next to this script's parent
        settings_path = os.path.join(_DIR, "..", "settings.json")
        try:
            with open(settings_path, encoding="utf-8-sig") as f:
                cfg = json.load(f)
            supabase_url = cfg.get("SupabaseUrl", "")
            supabase_key = cfg.get("SupabaseKey", "")
        except Exception:
            pass

    if not supabase_url or not supabase_key:
        _log("ERROR: Set SUPABASE_URL and SUPABASE_KEY environment variables.")
        sys.exit(1)

    # Read config overrides from Supabase bot_state
    model     = db.get_config(supabase_url, supabase_key, "setting_ollama_model", "") or args.model
    ollama    = db.get_config(supabase_url, supabase_key, "setting_ollama_url",   "") or args.ollama
    try:
        min_score = int(db.get_config(supabase_url, supabase_key, "setting_llm_min_score", "") or args.min_score)
    except ValueError:
        min_score = args.min_score

    cookie = _env("LINKEDIN_COOKIE")

    # Resolve profile: --cv arg > Supabase setting > default
    cv_source = args.cv.strip() if args.cv else ""
    if not cv_source:
        cv_source = db.get_config(supabase_url, supabase_key, "setting_user_profile", "")
    profile, profile_label = resolve_profile(cv_source, cookie)
    if not profile:
        profile = DEFAULT_PROFILE
        profile_label = "default"

    _log(f"Enricher starting — model={model}, min_score={min_score}, limit={args.limit}, profile={profile_label}")

    jobs = db.get_unscored_jobs(supabase_url, supabase_key, limit=args.limit)
    if not jobs:
        _log("No unscored jobs found. All done.")
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
            _log("          No description fetched — scoring on title/company/location only")

        score, summary = ollama_score(job, description, profile, model, ollama)

        if score == -1:
            _log("          Ollama unreachable — stopping enrichment")
            break

        verdict = "KEEP" if score >= min_score else "DISMISS"
        _log(f"          Score: {score}/10  [{verdict}]  {summary[:80]}")

        db.update_job_enrichment(
            supabase_url, supabase_key,
            job["job_id"], description, score, summary,
            min_score=min_score,
        )

        if score < min_score:
            dismissed += 1
        else:
            scored += 1

        if i < len(jobs):
            time.sleep(0.5)  # small pause between Ollama calls

    _log(f"Done. Scored={scored}, Auto-dismissed={dismissed}, Failed={failed}")


if __name__ == "__main__":
    main()
