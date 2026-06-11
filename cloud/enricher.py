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
import cv_analyzer
import relevance_engine

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


# ── Settings.json fallback (Linux GUI / Windows GUI) ─────────────────────────
def _load_settings_json() -> dict:
    """Load settings.json from ~/.config/job-alert/ or the repo root.

    Uses utf-8-sig so a Windows-written BOM is transparently stripped.
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

_ENV_TO_JSON: dict[str, str] = {
    "SUPABASE_URL":       "SupabaseUrl",
    "SUPABASE_KEY":       "SupabaseKey",
    "OLLAMA_URL":         "OllamaUrl",
    "TELEGRAM_BOT_TOKEN": "TelegramBotToken",
    "TELEGRAM_CHAT_ID":   "TelegramChatId",
    "LINKEDIN_COOKIE":    "LinkedInCookie",
    "LLM_MIN_SCORE":      "MinAiScore",   # settings.json key for minimum score threshold
}


def _env(name: str, default: str = "") -> str:
    """Read env var; fall back to settings.json if env var is empty."""
    val = os.environ.get(name, "").strip().lstrip("﻿")
    if val:
        return val
    json_key = _ENV_TO_JSON.get(name)
    if json_key and json_key in _SETTINGS_JSON:
        raw = _SETTINGS_JSON[json_key]
        if isinstance(raw, list):
            return ",".join(str(x) for x in raw)
        return str(raw).strip()
    return default


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
    """Return the already-loaded settings dict (supports both Linux and Windows paths)."""
    return _SETTINGS_JSON


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
      1. Structured CV profile stored in Supabase via cv_analyzer (best quality)
      2. --cv command-line arg
      3. settings.json `ProfileText` key (plain text resume)
      4. settings.json `UserProfile` key (PDF path / LinkedIn URL / text)
      5. Supabase bot_state `setting_user_profile`
      6. Hardcoded DEFAULT_PROFILE
    """
    # 1. Structured CV profile (from cv_analyzer.py -- most accurate)
    try:
        cv_profile = cv_analyzer.get_cv_profile(supabase_url, supabase_key)
        if cv_profile:
            formatted = cv_analyzer.format_profile_for_prompt(cv_profile)
            if formatted:
                analyzed_at = cv_profile.get("cv_analyzed_at", "unknown")
                skill_count = len(cv_profile.get("skills", []))
                _log(f"Profile source: structured CV profile ({skill_count} skills, analyzed {analyzed_at[:10]})")
                return formatted, f"structured CV ({skill_count} skills)"
    except Exception as exc:
        _vlog(f"Structured CV profile lookup failed (non-fatal): {exc}")

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

    _log("Profile fallback: all sources empty -- using DEFAULT_PROFILE")
    return DEFAULT_PROFILE, "default"


# ── Ollama ────────────────────────────────────────────────────────────────────

_FEW_SHOT_EXAMPLES = """\
EXAMPLE 1 (obvious IT match):
  Candidate: IT Support Engineer, 4 years UAE, Windows Server / AD / networking / O365.
  Job: "Senior IT Support, Dubai" at TechCorp. Manages Windows servers + AD + helpdesk.
  Output: {"skills_match": 9, "experience_match": 9, "location_match": 10, "seniority_match": 9, "overall_score": 9,
           "matched_skills": ["Windows Server","Active Directory","Helpdesk"],
           "missing_skills": [], "red_flags": [],
           "reasoning": "Strong overlap on every axis: skills, seniority, and UAE location all align."}

EXAMPLE 2 (completely wrong field — real estate/property):
  Candidate: IT Support Engineer, 4 years UAE.
  Job: "Property Consultant - Russian/European Speaker" at Property Shop Investment.
       Description: Sell residential properties, meet clients, manage listings.
  FIELD CHECK: "property consultant" is real estate sales — NOT an IT/technology role.
  Output: {"skills_match": 0, "experience_match": 0, "location_match": 10, "seniority_match": 0, "overall_score": 1,
           "matched_skills": [],
           "missing_skills": ["Real estate sales","Property market knowledge","Russian/European language"],
           "red_flags": ["Wrong field — real estate sales, not IT","Language requirement (Russian/European)"],
           "reasoning": "Not an IT role. Field domain mismatch overrides location and experience scores."}

EXAMPLE 2b (completely wrong field — oil & gas engineering):
  Candidate: IT Support Engineer, 4 years UAE, Windows Server / AD / networking.
  Job: "PMC Engineering Manager - Site" at Wood. 20+ years oil & gas required. LNG, FEED, ADNOC, EPC projects.
  FIELD CHECK: "Engineering Manager" in oil & gas — NOT an IT/technology role. The word "engineering" does NOT make it IT.
  Output: {"skills_match": 0, "experience_match": 0, "location_match": 10, "seniority_match": 0, "overall_score": 0,
           "matched_skills": [],
           "missing_skills": ["Oil & gas engineering","LNG/FEED experience","20+ years EPC projects"],
           "red_flags": ["Wrong field — oil & gas engineering, not IT","Requires 20+ years O&G experience"],
           "reasoning": "Oil & gas engineering management role. No overlap with IT support background whatsoever."}

EXAMPLE 3 (completely wrong field — sales/marketing):
  Candidate: IT Support Engineer, 4 years UAE, no sales background.
  Job: "Digital Marketing Manager, Dubai". Manages campaigns, SEO, social media.
  FIELD CHECK: Marketing — NOT an IT/technology role.
  Output: {"skills_match": 1, "experience_match": 1, "location_match": 10, "seniority_match": 3, "overall_score": 1,
           "matched_skills": [],
           "missing_skills": ["Digital marketing","SEO","Campaign management"],
           "red_flags": ["Wrong field — marketing, not IT"],
           "reasoning": "Not an IT role. Location match cannot compensate for a complete field mismatch."}

EXAMPLE 3a (completely wrong field — construction/site engineering):
  Candidate: IT Support Engineer, 4 years UAE, Windows Server / AD / networking / O365.
  Job: "Site Engineer" at ALEC Holdings. Manages construction site, procurement, QA/QC, health & safety.
  FIELD CHECK: Construction site management — NOT an IT/technology role.
  Microsoft Office (Word/Excel) is used on every job — it does NOT make this an IT role.
  Output: {"skills_match": 0, "experience_match": 0, "location_match": 9, "seniority_match": 0, "overall_score": 1,
           "matched_skills": [],
           "missing_skills": ["Construction project management","Site coordination","Procurement","QA/QC"],
           "red_flags": ["Wrong field — construction site engineering, not IT","Generic office tools are not IT skills"],
           "reasoning": "Construction site management role. Word/Excel does not make this an IT position."}

EXAMPLE 3b (completely wrong field — compliance/finance/legal):
  Candidate: IT Support Engineer, 4 years UAE, Windows Server / AD / networking.
  Job: "Head Financial Crime Compliance (Crypto)" at Revolut, UAE.
       Requires AML, KYC, regulatory compliance, financial crime investigation.
  FIELD CHECK: Financial compliance / legal — NOT an IT/technology role.
  "Crypto" in the title does NOT make it an IT job; the role is about financial regulation.
  Output: {"skills_match": 0, "experience_match": 0, "location_match": 10, "seniority_match": 0, "overall_score": 0,
           "matched_skills": [],
           "missing_skills": ["AML/KYC expertise","Financial crime investigation","Regulatory compliance","Legal background"],
           "red_flags": ["Wrong field — financial compliance, not IT","Crypto context is regulatory, not technical"],
           "reasoning": "Financial crime compliance is a legal/regulatory role. No technical IT skills required."}

EXAMPLE 3c (IT role AT a non-IT company — NOT wrong field):
  Candidate: IT Support Engineer, 4 years UAE, Windows Server / AD / networking / O365.
  Job: "Information Technology Specialist" at H&R Real Estate Brokerage.
       Manages company IT infrastructure, AD, network, helpdesk tickets.
  FIELD CHECK: The EMPLOYER is a real estate company, but the JOB is IT work.
  Every company needs IT staff. An IT Specialist at a real estate firm is STILL an IT role.
  Do NOT flag as wrong field just because the employer's industry is non-IT.
  Output: {"skills_match": 8, "experience_match": 7, "location_match": 9, "seniority_match": 7, "overall_score": 7,
           "matched_skills": ["Active Directory","Windows Server","Networking","O365","Helpdesk"],
           "missing_skills": [],
           "red_flags": [],
           "reasoning": "IT role at a real estate firm — employer industry is irrelevant, job duties are core IT support."}

EXAMPLE 4a (different IT specialisation — NOT wrong field, just skill gap):
  Candidate: IT Support Engineer, 4 years UAE, Windows Server / AD / networking.
  Job: "Database Administrator (DBA)" at nx. Requires Oracle/SQL Server DBA skills, backup, performance tuning.
  FIELD CHECK: DBA is IT/technology — do NOT flag as wrong field. It is a different IT specialisation.
  Output: {"skills_match": 3, "experience_match": 5, "location_match": 10, "seniority_match": 6, "overall_score": 5,
           "matched_skills": ["SQL Server","Windows Server"],
           "missing_skills": ["Oracle DBA","Database performance tuning","Backup & recovery","RMAN"],
           "red_flags": ["Requires dedicated DBA experience — significant skill gap"],
           "reasoning": "DBA is an IT role; candidate has foundational IT background but lacks database administration depth."}

EXAMPLE 4b (borderline IT-adjacent, partial fit):
  Candidate: IT Support Engineer, 4 years UAE, no cloud cert yet.
  Job: "Cloud Infrastructure Engineer (AWS), Abu Dhabi". Requires AWS cert, Linux, scripting.
  Output: {"skills_match": 5, "experience_match": 6, "location_match": 9, "seniority_match": 7, "overall_score": 6,
           "matched_skills": ["Linux","Scripting"],
           "missing_skills": ["AWS certification","Cloud infrastructure"],
           "red_flags": ["AWS cert is a hard requirement"],
           "reasoning": "Partial fit; foundational IT skills transfer but cloud-specific requirements are gaps."}

"""


# ── Score-response parsing (shared by Ollama + cloud fallback) ────────────────

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


def _breakdown_from_json(raw: str) -> dict:
    """Parse a raw LLM JSON string into a normalised breakdown dict.

    Shared by the Ollama path and the cloud-fallback path so both produce
    identical, validated output. Returns {} if no JSON object is found.
    """
    m = re.search(r'\{.*\}', raw or "", re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except Exception:
        return {}

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
    return breakdown


# ── Cloud LLM fallback (Groq — free, OpenAI-compatible, very fast) ─────────────

DEFAULT_CLOUD_MODEL = "llama-3.3-70b-versatile"
_GROQ_ENDPOINT      = "https://api.groq.com/openai/v1/chat/completions"


def cloud_score(prompt: str, cloud_key: str,
                cloud_model: str = DEFAULT_CLOUD_MODEL) -> tuple[int, str, dict]:
    """Score a job via Groq's OpenAI-compatible chat API.

    Used as a fallback when the local Ollama instance is unreachable or times
    out (the common case on a low-RAM Windows box).  Groq's free tier is fast
    enough to clear a large backlog in minutes.

    Returns (overall_score, reasoning, breakdown) or (-1, "", {}) on failure.
    """
    if not cloud_key:
        return -1, "", {}
    try:
        r = requests.post(
            _GROQ_ENDPOINT,
            headers={
                "Authorization": f"Bearer {cloud_key}",
                "Content-Type":  "application/json",
            },
            json={
                "model": cloud_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
            timeout=60,
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"]
        breakdown = _breakdown_from_json(raw)
        if not breakdown:
            return -1, "", {}
        return breakdown["overall_score"], breakdown["reasoning"], breakdown
    except Exception as exc:
        _log(f"Cloud-fallback (Groq) error: {exc}")
        return -1, "", {}


def ollama_score(
    job: dict,
    description: str,
    profile: str,
    model: str,
    ollama_url: str,
    dynamic_few_shot: str = "",
    cloud_key: str = "",
    cloud_model: str = DEFAULT_CLOUD_MODEL,
    prefer_cloud: bool = False,
) -> tuple[int, str, dict]:
    """Call Ollama to score a job on 4 axes + overall.

    Falls back to the Groq cloud API when Ollama is unreachable or times out,
    provided a cloud_key is configured.  When prefer_cloud is True and a
    cloud_key is set, Ollama is skipped entirely and scoring goes straight to
    Groq — much faster for clearing a large backlog.

    Returns (overall_score, reasoning_summary, full_breakdown_dict).
    Breakdown keys: skills_match, experience_match, location_match, seniority_match,
                    overall_score, matched_skills, missing_skills, red_flags, reasoning.
    """
    desc_excerpt = description[:3000] if description else "(no description available)"

    prompt = (
        "You are a job-fit scorer for an IT professional. Rate how well this job matches the candidate.\n"
        "Output STRICT JSON only — no markdown, no prose outside the JSON.\n\n"
        "=== CRITICAL RULE — FIELD DOMAIN CHECK ===\n"
        "BEFORE scoring, decide: is this job in the IT / technology field?\n"
        "\n"
        "IT roles include ALL of these (do NOT flag as wrong field):\n"
        "  IT Support, System Administrator, Network Engineer, Database Administrator (DBA),\n"
        "  DevOps, Cloud Engineer, Security Engineer, Pre-Sales Engineer at a tech/IT company,\n"
        "  Software Developer, Data Engineer, ERP Administrator, SCADA/OT (industrial IT),\n"
        "  IT Procurement, IT Project Manager — any role where the PRIMARY work is with technology.\n"
        "\n"
        "EMPLOYER INDUSTRY RULE (CRITICAL):\n"
        "  The employer's industry does NOT determine the field — only the JOB DUTIES do.\n"
        "  An IT Support / IT Specialist / System Admin role at a real estate company, bank,\n"
        "  hospital, hotel, airline, or law firm is STILL an IT role. Every company needs IT staff.\n"
        "  Only flag 'Wrong field' when the actual WORK the person does is non-IT\n"
        "  (e.g. selling properties, performing surgery, managing a construction site).\n"
        "\n"
        "Non-IT roles (flag as 'Wrong field — <field>, not IT'):\n"
        "  Real Estate SALES Agent / Property Consultant / Leasing Consultant (the job is selling property),\n"
        "  Marketing Executive / SEO Specialist / Brand Manager (the job is marketing),\n"
        "  HR Recruiter / People & Culture Manager (the job is human resources),\n"
        "  Finance / Accounting / Audit roles (the job is financial work),\n"
        "  Hospitality / Guest Relations / Cabin Crew (the job is customer-facing service),\n"
        "  Medical / Healthcare / Clinical roles (the job is patient care),\n"
        "  Legal / Compliance / Paralegal (the job is legal work),\n"
        "  Retail Sales / Key Account Executive (the job is selling products),\n"
        "  Construction / Civil / Site Engineer (buildings, not servers),\n"
        "  Oil & Gas field operations (drilling, field work), Aeronautical / Aviation operations.\n"
        "\n"
        "IMPORTANT — generic office tools are NOT IT skills:\n"
        "  Microsoft Word, Excel, PowerPoint, Outlook are used in every office job.\n"
        "  Do NOT list them as matched_skills or use them to raise skills_match above 1.\n"
        "  Only count explicitly IT tools: Windows Server, Active Directory, Azure, Intune,\n"
        "  Exchange, SQL Server, PowerShell, networking gear, SIEM tools, etc.\n"
        "\n"
        "If the job is truly NOT in IT/technology:\n"
        "  - Set skills_match=0, experience_match=0, seniority_match=0\n"
        "  - Set overall_score to 0 or 1 (max 1, regardless of location match)\n"
        "  - Add 'Wrong field — <field>, not IT' as the first red_flag\n"
        "  - Leave matched_skills empty []\n"
        "Location match (10/10 UAE) does NOT compensate for a field mismatch.\n"
        "=== END CRITICAL RULE ===\n\n"
        "Schema:\n"
        "{\n"
        '  "skills_match":     <int 0-10>,  // skills explicitly required in the job description that the candidate has\n'
        '  "experience_match": <int 0-10>,  // years/level vs candidate background\n'
        '  "location_match":   <int 0-10>,  // job location vs candidate location\n'
        '  "seniority_match":  <int 0-10>,  // role level (junior/mid/senior) vs candidate level\n'
        '  "overall_score":    <int 0-10>,  // weighted overall fit (field mismatch caps this at 1)\n'
        '  "matched_skills":   [<short strings>],  // ONLY skills that appear in BOTH the job description AND the candidate profile. Do NOT list candidate skills that are absent from the job description.\n'
        '  "missing_skills":   [<short strings>],  // up to 5 skills the job requires but the candidate lacks\n'
        '  "red_flags":        [<short strings>],  // up to 3 hard blockers (wrong field, language req, nationals only, etc.)\n'
        '  "reasoning":        "<one sentence explaining the overall_score>"\n'
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

    def _try_cloud(reason: str):
        """Attempt the Groq cloud fallback; log whether it was available."""
        if cloud_key:
            _log(f"          Ollama {reason} — falling back to cloud ({cloud_model})")
            return cloud_score(prompt, cloud_key, cloud_model)
        return None

    # Fast path: skip Ollama entirely and score via cloud (backlog clearing).
    if prefer_cloud and cloud_key:
        return cloud_score(prompt, cloud_key, cloud_model)

    try:
        r = requests.post(
            f"{ollama_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=300,
        )
        r.raise_for_status()
        raw = r.json().get("response", "{}")
        if _DEBUG_PROMPT:
            _log(f"Ollama raw response: {raw[:800]}")
        breakdown = _breakdown_from_json(raw)
        if not breakdown:
            # Ollama replied but the JSON was unparseable — try cloud before giving up
            cloud = _try_cloud("returned unparseable JSON")
            if cloud and cloud[0] != -1:
                return cloud
            return -1, "", {}
        return breakdown["overall_score"], breakdown["reasoning"], breakdown
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        kind = "timed out" if isinstance(exc, requests.exceptions.Timeout) else "unreachable"
        cloud = _try_cloud(kind)
        if cloud is not None:
            return cloud
        _log(f"ERROR: Ollama at {ollama_url} {kind} - is 'ollama serve' running? "
             f"(set the GROQ_API_KEY env var for cloud fallback)")
        return -1, "", {}
    except Exception as exc:
        cloud = _try_cloud(f"error: {exc}")
        if cloud is not None and cloud[0] != -1:
            return cloud
        _log(f"Ollama error: {exc}")
        return -1, "", {}


# ── Cover-letter generation (Phase 5) ─────────────────────────────────────────

DEFAULT_COVER_LETTER_THRESHOLD = 7   # only generate for jobs scoring this or higher
DEFAULT_COVER_LETTER_PER_RUN   = 3   # cap so a 60-job backfill doesn't take 1h


def generate_cover_letter(job: dict, description: str, profile: str,
                           model: str, ollama_url: str,
                           breakdown: dict | None = None) -> str:
    """Generate a 200-word cover letter draft tailored to this specific job.

    Returns the plain-text draft (no markdown). Empty string on failure.
    Uses the same Ollama model as scoring - quality is sufficient for a
    first draft the user will edit anyway.
    """
    desc_excerpt = (description or "")[:2500] or "(no description available)"
    breakdown    = breakdown or {}
    matched      = ", ".join(breakdown.get("matched_skills") or [])
    missing      = ", ".join(breakdown.get("missing_skills") or [])

    prompt = (
        "Write a 200-word cover letter for the candidate applying to this job.\n"
        "Structure: 3 short paragraphs.\n"
        "  Paragraph 1: open with a strong hook tying the candidate's most\n"
        "    relevant experience to the role. Name the company.\n"
        "  Paragraph 2: 2-3 sentences highlighting the candidate's strongest\n"
        "    matched skills and a specific accomplishment from their CV.\n"
        "  Paragraph 3: confident close with a clear call to action\n"
        "    (interview / next steps).\n"
        "Tone: professional but human. Specific, not generic.\n"
        "Use the candidate's actual experience from the profile.\n"
        "Plain text only. No markdown. No bullet points. No salutation or sign-off block\n"
        "(the user will add those). Do not invent details not in the profile.\n\n"
        f"CANDIDATE PROFILE:\n{profile}\n\n"
        f"JOB TITLE:    {job.get('title', '')}\n"
        f"COMPANY:      {job.get('company', '')}\n"
        f"LOCATION:     {job.get('location', '')}\n"
    )
    if matched:
        prompt += f"AI-DETECTED MATCHED SKILLS: {matched}\n"
    if missing:
        prompt += f"AI-DETECTED GAPS (acknowledge briefly but pivot to strengths): {missing}\n"
    prompt += f"\nJOB DESCRIPTION:\n{desc_excerpt}\n"

    try:
        r = requests.post(
            f"{ollama_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=180,
        )
        r.raise_for_status()
        text = (r.json().get("response") or "").strip()
        # Strip leading "Here is a ... cover letter ...:" preamble the model sometimes adds
        text = re.sub(r"^\s*(here\s+is|here'?s|below\s+is|the\s+following\s+is)\b[^\n]{0,160}:\s*\n+",
                      "", text, count=1, flags=re.IGNORECASE).strip()
        # Trim any trailing sign-off the model might add anyway
        text = re.sub(r"\n+(Sincerely|Regards|Best|Best regards|Thank you|Yours).*$",
                      "", text, flags=re.IGNORECASE | re.DOTALL).strip()
        return text[:3000]   # hard cap; Telegram + UI can handle ~2.5 KB easily
    except requests.exceptions.ConnectionError:
        _log(f"          Cover letter: Ollama unreachable")
        return ""
    except Exception as exc:
        _log(f"          Cover letter error: {exc}")
        return ""


# ── Tailored CV generation ────────────────────────────────────────────────────

DEFAULT_TAILORED_CV_THRESHOLD = 7   # only generate for jobs scoring >= this
DEFAULT_TAILORED_CV_PER_RUN   = 3   # cap per run so a backfill doesn't take forever


def generate_tailored_cv(job: dict, description: str, profile: str,
                          model: str, ollama_url: str,
                          breakdown: dict | None = None) -> str:
    """Generate a CV rewritten and reordered for this specific job.

    The CV is NOT invented — every section comes from the candidate's profile.
    The LLM reorders, emphasises, and rewrites bullet points so the most
    relevant experience appears first and directly addresses what this job needs.

    Returns plain text (no markdown). Empty string on failure.
    Max ~600 words so it fits comfortably as a Telegram file.
    """
    desc_excerpt = (description or "")[:2500] or "(no description available)"
    breakdown    = breakdown or {}
    matched      = ", ".join(breakdown.get("matched_skills") or [])
    missing      = ", ".join(breakdown.get("missing_skills") or [])

    prompt = (
        "Rewrite the candidate's CV tailored specifically for this job.\n"
        "RULES:\n"
        "  1. Do NOT invent skills, experience, or qualifications not in the profile.\n"
        "  2. DO reorder content: most relevant skills and experience come first.\n"
        "  3. Professional Summary MUST name this company and role explicitly.\n"
        "  4. Every bullet point in Experience should echo language from the job description.\n"
        "  5. Plain text only — no markdown, no asterisks, no bullet symbols.\n"
        "     Use dashes (-) for list items.\n"
        "  6. Max 600 words total.\n\n"
        "OUTPUT FORMAT (use these exact section headers):\n"
        "PROFESSIONAL SUMMARY\n"
        "<2-3 sentences opening that directly addresses what this job requires>\n\n"
        "CORE SKILLS\n"
        "<most relevant skills for THIS job listed first, comma-separated>\n\n"
        "PROFESSIONAL EXPERIENCE\n"
        "<same jobs from the profile, bullet points rewritten to match the role>\n\n"
        "EDUCATION & CERTIFICATIONS\n"
        "<from profile, no changes>\n\n"
        f"CANDIDATE PROFILE:\n{profile}\n\n"
        f"TARGET JOB: {job.get('title', '')} at {job.get('company', '')}\n"
        f"LOCATION:   {job.get('location', '')}\n"
    )
    if matched:
        prompt += f"MATCHED SKILLS (lead with these): {matched}\n"
    if missing:
        prompt += f"GAPS (acknowledge briefly, pivot to strengths): {missing}\n"
    prompt += f"\nJOB DESCRIPTION:\n{desc_excerpt}\n"

    try:
        r = requests.post(
            f"{ollama_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=180,
        )
        r.raise_for_status()
        text = (r.json().get("response") or "").strip()
        # Strip leading preamble the model sometimes adds
        text = re.sub(
            r"^\s*(here\s+is|here'?s|below\s+is|the\s+following\s+is)\b[^\n]{0,160}:\s*\n+",
            "", text, count=1, flags=re.IGNORECASE,
        ).strip()
        return text[:8000]
    except requests.exceptions.ConnectionError:
        _log("          Tailored CV: Ollama unreachable")
        return ""
    except Exception as exc:
        _log(f"          Tailored CV error: {exc}")
        return ""


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
    parser.add_argument("--cover-letter-threshold", type=int, default=DEFAULT_COVER_LETTER_THRESHOLD,
                        help=f"Generate cover letter for jobs scoring >= this (default {DEFAULT_COVER_LETTER_THRESHOLD}, 0=disable)")
    parser.add_argument("--cover-letter-max-per-run", type=int, default=DEFAULT_COVER_LETTER_PER_RUN,
                        help=f"Cap cover-letter generations per run (default {DEFAULT_COVER_LETTER_PER_RUN})")
    parser.add_argument("--tailored-cv-threshold", type=int, default=DEFAULT_TAILORED_CV_THRESHOLD,
                        help=f"Generate tailored CV for jobs scoring >= this (default {DEFAULT_TAILORED_CV_THRESHOLD}, 0=disable)")
    parser.add_argument("--tailored-cv-max-per-run", type=int, default=DEFAULT_TAILORED_CV_PER_RUN,
                        help=f"Cap tailored-CV generations per run (default {DEFAULT_TAILORED_CV_PER_RUN})")
    parser.add_argument("--analyze-cv", action="store_true",
                        help="Analyze CV and store structured profile to Supabase, then exit")
    parser.add_argument("--groq-key",   default="",
                        help="Groq API key for cloud fallback when Ollama is down (or set the GROQ_API_KEY env var)")
    parser.add_argument("--groq-model", default=DEFAULT_CLOUD_MODEL,
                        help=f"Groq model for cloud fallback (default {DEFAULT_CLOUD_MODEL})")
    parser.add_argument("--prefer-cloud", action="store_true",
                        help="Skip Ollama and score via Groq directly (fast backlog clearing; requires a Groq key)")
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

    _vlog(f"LinkedIn cookie: {'present' if cookie else 'EMPTY — LinkedIn profile fetches will hit login wall'}")

    # Read config overrides from Supabase bot_state
    model     = db.get_config(supabase_url, supabase_key, "setting_ollama_model", "") or args.model
    ollama    = db.get_config(supabase_url, supabase_key, "setting_ollama_url",   "") or args.ollama
    # Cloud LLM fallback (Groq) — used when Ollama is unreachable or times out.
    # SECURITY: the key comes from env / CLI only — never from bot_state,
    # which is readable with the public anon key shipped in the mobile app.
    cloud_key   = (_env("GROQ_API_KEY") or args.groq_key).strip()
    cloud_model = (db.get_config(supabase_url, supabase_key, "setting_groq_model", "")
                   or args.groq_model).strip()
    prefer_cloud = args.prefer_cloud or (
        db.get_config(supabase_url, supabase_key, "setting_prefer_cloud", "")
        .strip().lower() in ("true", "1", "yes", "on"))
    if cloud_key:
        mode = "primary (Ollama skipped)" if prefer_cloud else "fallback when Ollama is down"
        _log(f"Cloud scoring enabled (Groq, model={cloud_model}) — {mode}")
    elif prefer_cloud:
        _log("WARNING: --prefer-cloud set but no Groq key configured — using Ollama")
        prefer_cloud = False
    # Priority: Supabase bot_state > settings.json MinAiScore > CLI --min-score > hardcoded default (4)
    _settings_min = _SETTINGS_JSON.get("MinAiScore")
    _fallback_min = int(_settings_min) if _settings_min is not None else args.min_score
    try:
        min_score = int(db.get_config(supabase_url, supabase_key, "setting_llm_min_score", "") or _fallback_min)
    except ValueError:
        min_score = _fallback_min

    # --analyze-cv: one-shot CV analysis, store to Supabase, then exit
    if args.analyze_cv:
        cv_path = args.cv.strip()
        if not cv_path:
            cfg = _load_settings_json()
            cv_path = (cfg.get("UserProfile") or "").strip()
        if not cv_path:
            _log("ERROR: No CV path. Use --cv path/to/cv.pdf or set UserProfile in settings.json.")
            sys.exit(1)
        _log(f"CV analysis requested: {cv_path}")
        text = cv_analyzer.extract_cv_text(cv_path)
        if not text:
            _log("ERROR: Could not extract text from CV file.")
            sys.exit(1)
        _log(f"Extracted {len(text)} chars -- sending to Ollama ({ollama}) model={model} ...")
        cv_profile = cv_analyzer.analyze_cv(text, ollama_url=ollama, model=model)
        if not cv_profile:
            _log("ERROR: Ollama returned empty response. Is 'ollama serve' running?")
            sys.exit(1)
        skills = cv_profile.get("skills", [])
        _log(f"Extracted {len(skills)} skills: "
             f"{', '.join(skills[:15])}{'...' if len(skills) > 15 else ''}")
        cv_analyzer.store_cv_profile(supabase_url, supabase_key, cv_profile)
        _log("Done. Future scoring runs will use this structured profile.")
        sys.exit(0)

    # Profile resolution with full fallback chain:
    # structured CV (Supabase) > --cv arg > ProfileText > UserProfile > Supabase setting > default
    profile, profile_label = resolve_profile_with_fallback(args.cv, supabase_url, supabase_key, cookie)

    # Load Telegram config for post-score alerts.
    # SECURITY: env / settings.json only — never bot_state, which is readable
    # with the public anon key shipped in the mobile app.
    _tg_cfg  = _load_settings_json()
    tg_token = _env("TELEGRAM_BOT_TOKEN") or str(_tg_cfg.get("TelegramBotToken", "") or "").strip()
    tg_chat  = _env("TELEGRAM_CHAT_ID")   or str(_tg_cfg.get("TelegramChatId", "") or "").strip()
    # Phase 6: optional compact alerts (score + title + URL only)
    tg_compact = (db.get_config(supabase_url, supabase_key, "setting_telegram_compact", "")
                  .strip().lower() in ("true", "1", "yes", "on"))

    # Read max_hours (freshness window) from Supabase — used as the notification
    # staleness cutoff.  Jobs posted longer ago than this are scored silently
    # (visible in the app) but never sent as a Telegram notification.
    try:
        max_hours_cfg = db.get_config(supabase_url, supabase_key, "setting_max_hours", "")
        max_notification_hours = int(max_hours_cfg) if max_hours_cfg else 120  # default 5 days
    except Exception:
        max_notification_hours = 120

    # Build relevance engine for the pre-LLM gate (replaces _ENRICHER_NON_IT_TITLE regex).
    # Uses the same CV profile stored in Supabase so the gate is always personalised.
    try:
        keywords_cfg = db.get_config(supabase_url, supabase_key, "setting_keywords", "")
        enricher_keywords = [k.strip() for k in keywords_cfg.split(",") if k.strip()]
        rel_engine = relevance_engine.RelevanceEngine.from_supabase(
            supabase_url, supabase_key, enricher_keywords
        )
    except Exception as exc:
        _log(f"RelevanceEngine load error (non-fatal, pre-LLM gate disabled): {exc}")
        rel_engine = None

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

    scored = dismissed = failed = cover_letters_generated = tailored_cvs_generated = 0

    for i, job in enumerate(jobs, 1):
        title   = job.get("title", "?")
        company = job.get("company", "?")
        _log(f"[{i}/{len(jobs)}] {title} @ {company}")

        # Skip jobs restricted to nationals/citizens — they slipped through the
        # worker filter (e.g. inserted before the filter was added) or the title
        # didn't reveal the restriction until the description was read.  We check
        # the title here; the description check happens further down when available.
        if re.search(
            r"\b(uae\s+national[s]?|emirati[s]?|gcc\s+national[s]?"
            r"|nationals\s+only|citizens\s+only)\b",
            title, re.I
        ):
            _log("          Skipping — job restricted to nationals/citizens")
            db.update_job_enrichment(
                supabase_url, supabase_key,
                job["job_id"], "", score=0,
                summary="Skipped — restricted to nationals/citizens",
                min_score=1,
            )
            dismissed += 1
            continue

        # Pre-LLM relevance gate — catches jobs in wrong fields (real estate, HR, etc.)
        # that slipped through the worker filter or entered the DB before the filter existed.
        # Using the engine avoids wasting Ollama time and is CV-driven, not hardcoded.
        if rel_engine is not None:
            relevant, rel_reason = rel_engine.is_relevant(title)
            if not relevant:
                _log(f"          Skipping — {rel_reason}")
                db.update_job_enrichment(
                    supabase_url, supabase_key,
                    job["job_id"], "", score=0,
                    summary=f"Filtered: {rel_reason}",
                    min_score=1,
                )
                dismissed += 1
                continue

        description = li.fetch_job_description(job.get("url", ""), cookie)
        if description:
            _log(f"          Description: {len(description)} chars")
            # Secondary check: restriction may be buried in the description body
            if re.search(
                r"\b(uae\s+national[s]?|emirati[s]?|gcc\s+national[s]?"
                r"|nationals\s+only|citizens\s+only|open\s+to\s+(?:uae\s+)?nationals)\b",
                description[:1000], re.I
            ):
                _log("          Skipping — description restricts to nationals/citizens")
                db.update_job_enrichment(
                    supabase_url, supabase_key,
                    job["job_id"], description[:500], score=0,
                    summary="Skipped — restricted to nationals/citizens",
                    min_score=1,
                )
                dismissed += 1
                continue
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
                                                  dynamic_few_shot=dynamic_few_shot,
                                                  cloud_key=cloud_key, cloud_model=cloud_model,
                                                  prefer_cloud=prefer_cloud)

        if score == -1:
            _log("          Scoring unavailable (Ollama down, no cloud fallback) - stopping enrichment")
            break

        # Auto-dismiss if LLM itself says "Wrong field" — score is irrelevant
        # when the model explicitly flags the job as the wrong profession.
        wrong_field = any(
            "wrong field" in (flag or "").lower()
            for flag in (breakdown.get("red_flags") or [])
        )
        if wrong_field and score < 8:
            # Override: treat as dismissed regardless of numeric score
            score = min(score, min_score - 1)

        verdict = "KEEP" if score >= min_score else "DISMISS"
        _log(f"          Score: {score}/10  [{verdict}]  S={breakdown.get('skills_match','?')} E={breakdown.get('experience_match','?')} L={breakdown.get('location_match','?')} Sr={breakdown.get('seniority_match','?')}")
        if breakdown.get("matched_skills"):
            _log(f"          Matched: {', '.join(breakdown['matched_skills'])}")
        if breakdown.get("missing_skills"):
            _log(f"          Missing: {', '.join(breakdown['missing_skills'])}")
        if breakdown.get("red_flags"):
            _log(f"          Red flags: {' | '.join(breakdown['red_flags'])}")

        saved = db.update_job_enrichment(
            supabase_url, supabase_key,
            job["job_id"], description, score, summary,
            min_score=min_score,
            breakdown=breakdown,
        )

        if not saved:
            # DB write failed — do NOT send a Telegram alert.
            # The job stays in get_unscored_jobs (llm_score still NULL) and will
            # be retried on the next enricher run.  Alerting here would cause a
            # duplicate alert every time the enricher retries this job.
            _log(f"          WARNING: DB update failed — skipping Telegram alert (will retry next run)")
            failed += 1
            continue

        # Phase 5: generate cover-letter draft for high-scoring jobs.
        # Throttled per run so a backfill doesn't take forever (~30s per draft).
        if (args.cover_letter_threshold > 0
                and score >= args.cover_letter_threshold
                and cover_letters_generated < args.cover_letter_max_per_run):
            _log(f"          Generating cover letter (score {score} >= {args.cover_letter_threshold})...")
            draft = generate_cover_letter(job, description, profile, model, ollama,
                                          breakdown=breakdown)
            if draft:
                db.update_cover_letter(supabase_url, supabase_key, job["job_id"], draft)
                cover_letters_generated += 1
                _log(f"          Cover letter saved ({len(draft)} chars) — user can request it via the button in Telegram")
                # Cover letter is NOT auto-sent. The user presses the
                # '📝 Cover Letter' button on the job alert in Telegram,
                # and the worker delivers it on the next run.
            else:
                _vlog("          Cover letter generation returned empty - skipping persist")

        # Phase 5b: generate tailored CV draft for high-scoring jobs.
        # Throttled per run so a backfill doesn't take forever (~60s per draft).
        if (args.tailored_cv_threshold > 0
                and score >= args.tailored_cv_threshold
                and tailored_cvs_generated < args.tailored_cv_max_per_run):
            _log(f"          Generating tailored CV (score {score} >= {args.tailored_cv_threshold})...")
            cv_draft = generate_tailored_cv(job, description, profile, model, ollama,
                                            breakdown=breakdown)
            if cv_draft:
                db.update_tailored_cv(supabase_url, supabase_key, job["job_id"], cv_draft)
                tailored_cvs_generated += 1
                _log(f"          Tailored CV saved ({len(cv_draft)} chars) — tap the Tailored CV button in Telegram")
                # NOT auto-sent. User taps '📄 Tailored CV' button in Telegram
                # and the worker delivers it on the next run.
            else:
                _vlog("          Tailored CV generation returned empty — skipping persist")

        # Send Telegram score notification for kept jobs (richer format with breakdown).
        # Skip if worker.py already sent a basic alert for this job.
        already_sent = bool(job.get("telegram_sent_at"))
        if score >= min_score and tg_token and tg_chat:
            if not already_sent:
                # Staleness gate — don't alert for jobs posted outside the freshness window.
                # Catches old jobs that leaked through LinkedIn's f_TPR filter or were
                # sitting unscored in the enricher backlog for too long.
                is_stale = False
                date_posted = job.get("date_posted") or ""
                if date_posted:
                    try:
                        posted_dt = datetime.fromisoformat(date_posted.replace("Z", "+00:00"))
                        # Date-only → treat as end-of-day (same fix as worker.py _age_filter)
                        if len(date_posted) == 10 and "T" not in date_posted:
                            posted_dt = posted_dt.replace(hour=23, minute=59)
                        hours_old = (datetime.now(timezone.utc) - posted_dt).total_seconds() / 3600
                        if hours_old > max_notification_hours:
                            is_stale = True
                            _log(
                                f"          Telegram: skipped — posted {int(hours_old / 24)}d ago "
                                f"(>{max_notification_hours}h freshness threshold). "
                                f"Job is visible in the app."
                            )
                    except Exception:
                        pass  # unknown date → allow notification

                if not is_stale:
                    try:
                        import telegram_notify as tg
                        tg.send_score_alert(tg_token, tg_chat, job, breakdown, compact=tg_compact)
                        db.mark_telegram_sent(supabase_url, supabase_key, job.get("url", ""))
                        time.sleep(0.3)
                    except Exception as exc:
                        _log(f"          Telegram score alert error: {exc}")
            else:
                # Job was already alerted by worker (no score then).
                # Send a brief score-update message so the user sees the rating.
                # Apply the same staleness gate as new alerts — don't send a
                # score update for a 3-day-old backlog job; the user has moved on.
                # Use max(max_notification_hours, 48) so a narrow max_hours setting
                # (e.g. 2h) doesn't suppress updates for genuinely recent jobs.
                update_max_hours = max(max_notification_hours, 48)
                update_is_stale = False
                date_posted = job.get("date_posted") or ""
                if date_posted:
                    try:
                        posted_dt = datetime.fromisoformat(date_posted.replace("Z", "+00:00"))
                        if len(date_posted) == 10 and "T" not in date_posted:
                            posted_dt = posted_dt.replace(hour=23, minute=59)
                        hours_old = (datetime.now(timezone.utc) - posted_dt).total_seconds() / 3600
                        if hours_old > update_max_hours:
                            update_is_stale = True
                            _log(
                                f"          Telegram: score update skipped — posted "
                                f"{int(hours_old / 24)}d ago (>{update_max_hours}h). "
                                f"Score saved in app."
                            )
                    except Exception:
                        pass  # unknown date → allow update
                if not update_is_stale:
                    try:
                        import telegram_notify as tg_mod
                        job_id = job.get("job_id") or ""
                        ok = tg_mod.send_score_update(tg_token, tg_chat, job, breakdown, job_id=job_id)
                        if ok:
                            _log(f"          Telegram: score update sent ({score}/10)")
                        else:
                            _log(f"          Telegram: score update failed — will retry next run")
                    except Exception as exc:
                        _log(f"          Telegram: score update error: {exc}")

        if score < min_score:
            dismissed += 1
        else:
            scored += 1

        if i < len(jobs):
            time.sleep(0.5)  # small pause between Ollama calls

    _log(f"Done. Scored={scored}, Auto-dismissed={dismissed}, Failed={failed}, CoverLetters={cover_letters_generated}, TailoredCVs={tailored_cvs_generated}")

    if args.health_check:
        if scored + dismissed > 0:
            _log("HEALTH-CHECK: PASS — Ollama reached, profile resolved, at least one job scored end-to-end.")
            sys.exit(0)
        else:
            _log("HEALTH-CHECK: FAIL — no job was scored. Check the messages above for the cause.")
            sys.exit(2)


if __name__ == "__main__":
    main()
