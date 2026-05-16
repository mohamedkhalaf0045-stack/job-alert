"""
CV Intelligence -- analyze the user's CV with Ollama and store
a structured skills profile in Supabase bot_state.

Run once after uploading a new CV:
    python cloud/cv_analyzer.py --cv "C:\\path\\to\\cv.pdf"

Show the currently stored profile without re-analyzing:
    python cloud/cv_analyzer.py --show

The stored profile is used by cloud/enricher.py when scoring jobs,
giving the LLM a clean structured candidate description rather than a
raw PDF text dump.  This produces more accurate matched_skills /
missing_skills lists in every scored job.

bot_state keys written:
    cv_skills           comma-separated list of technical skills
    cv_summary          2-3 sentence professional summary
    cv_job_titles       comma-separated recent job titles
    cv_years_experience integer string
    cv_certifications   comma-separated list
    cv_languages        comma-separated list
    cv_education        comma-separated list
    cv_domain_terms     comma-separated filter words (auto-derived from skills+titles)
    cv_analyzed_at      ISO timestamp (UTC)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

import requests

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)
import db

DEFAULT_MODEL  = "llama3.1:latest"
DEFAULT_OLLAMA = "http://localhost:11434"

# Stopwords stripped when generating domain filter terms from the CV.
# These common words add no signal to a title-matching rule.
_DOMAIN_STOPWORDS = frozenset({
    "and", "or", "the", "of", "in", "at", "for", "to", "with",
    "using", "via", "a", "an", "be", "are", "is", "was", "as",
    "on", "by", "from", "up", "into", "over", "under", "its",
    "that", "this", "has", "have", "not", "but",
})


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _load_settings_json() -> dict:
    settings_path = os.path.join(_DIR, "..", "settings.json")
    try:
        with open(settings_path, encoding="utf-8-sig") as f:
            return json.load(f) or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_cv_text(path: str) -> str:
    """Extract plain text from a CV/resume PDF file using pypdf."""
    if not path or not os.path.isfile(path):
        _log(f"CV file not found: {path}")
        return ""
    try:
        from pypdf import PdfReader
    except ImportError:
        _log("pypdf not installed -- run: pip install pypdf")
        return ""
    try:
        reader = PdfReader(path)
        pages  = [page.extract_text() or "" for page in reader.pages]
        text   = " ".join(pages)
        return re.sub(r"\s+", " ", text).strip()[:6000]
    except Exception as exc:
        _log(f"PDF read error ({os.path.basename(path)}): {exc}")
        return ""


# ---------------------------------------------------------------------------
# Ollama analysis
# ---------------------------------------------------------------------------

_CV_ANALYSIS_PROMPT = """\
You are a CV/resume parser. Extract structured information from the CV text below.
Output STRICT JSON only -- no markdown, no prose outside the JSON.

Schema (values must come from the CV -- do not invent):
{{
  "skills":           [<up to 30 technical tools, platforms, and technologies>],
  "years_experience": <int -- total years of professional experience>,
  "job_titles":       [<up to 5 most recent job titles held>],
  "certifications":   [<certifications and courses, e.g. CCNA, CompTIA A+>],
  "languages":        [<spoken languages, e.g. English, Arabic>],
  "education":        [<degree + institution per qualification, e.g. "BSc CS, XYZ University">],
  "summary":          "<2-3 sentence professional summary of this candidate>"
}}

Rules:
- skills: technical tools and technologies only (e.g. Windows Server, Active Directory,
  Linux, Cisco, VMware, Python, AWS). No soft skills like "teamwork" or "communication".
- years_experience: estimate from the date range of jobs if not stated explicitly.
- If a field has no data, return an empty list [] or empty string "".

CV TEXT:
{cv_text}
"""


def analyze_cv(
    text: str,
    ollama_url: str = DEFAULT_OLLAMA,
    model: str = DEFAULT_MODEL,
) -> dict | None:
    """
    Send CV text to Ollama and return a structured profile dict.

    Keys: skills, years_experience, job_titles, certifications,
          languages, education, summary.
    Returns None on failure.
    """
    if not text.strip():
        return None

    prompt = _CV_ANALYSIS_PROMPT.replace("{cv_text}", text[:5000])

    try:
        r = requests.post(
            f"{ollama_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=180,
        )
        if not r.ok:
            # Surface the actual Ollama error (e.g. "model requires more memory")
            try:
                body = r.json()
                detail = body.get("error", r.text[:300])
            except Exception:
                detail = r.text[:300]
            _log(f"ERROR: Ollama returned HTTP {r.status_code}: {detail}")
            return None
        raw = r.json().get("response", "{}")
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            _log(f"CV analysis: Ollama returned no JSON object. Raw: {raw[:300]}")
            return None
        data = json.loads(m.group(0))
    except requests.exceptions.ConnectionError:
        _log(f"ERROR: Cannot reach Ollama at {ollama_url} -- is 'ollama serve' running?")
        return None
    except Exception as exc:
        _log(f"CV analysis error: {exc}")
        return None

    def _clean_list(v, max_items: int = 30) -> list:
        if not isinstance(v, list):
            return []
        return [str(s).strip() for s in v[:max_items] if str(s).strip()]

    return {
        "skills":           _clean_list(data.get("skills"), 30),
        "years_experience": max(0, int(data.get("years_experience") or 0)),
        "job_titles":       _clean_list(data.get("job_titles"), 5),
        "certifications":   _clean_list(data.get("certifications"), 10),
        "languages":        _clean_list(data.get("languages"), 5),
        "education":        _clean_list(data.get("education"), 5),
        "summary":          str(data.get("summary") or "").strip()[:500],
    }


# ---------------------------------------------------------------------------
# Domain term generation
# ---------------------------------------------------------------------------

def generate_domain_terms(profile: dict) -> list[str]:
    """Derive job-domain filter words from the CV's skills and job titles.

    Splits every word in skills + job_titles on whitespace / hyphens / slashes,
    lower-cases, strips non-alphanumeric chars (except +/#), removes stopwords,
    keeps words ≥ 3 characters, and deduplicates.

    Example:
      skills     = ["Windows Server", "Active Directory", "PowerShell", "Networking"]
      job_titles = ["IT Support Engineer", "System Administrator"]
      → domain_terms = ["active", "administrator", "directory", "engineer",
                         "networking", "powershell", "server", "support",
                         "system", "windows"]

    These terms are stored as cv_domain_terms in Supabase and used by
    relevance_engine.RelevanceEngine as the Tier-4 catch-all domain filter.
    """
    words: set[str] = set()
    sources = profile.get("skills", []) + profile.get("job_titles", [])
    for item in sources:
        for word in re.split(r"[\s/\-\.]+", str(item).lower()):
            word = re.sub(r"[^a-z0-9+#]", "", word)
            if len(word) >= 3 and word not in _DOMAIN_STOPWORDS:
                words.add(word)
    return sorted(words)


# ---------------------------------------------------------------------------
# Supabase storage
# ---------------------------------------------------------------------------

def store_cv_profile(supabase_url: str, supabase_key: str, profile: dict) -> None:
    """Persist the structured CV profile to Supabase bot_state.

    Also generates and stores cv_domain_terms — the word-level filter set used
    by relevance_engine.RelevanceEngine (Tier-4 domain catch-all).
    """
    def _csv(lst: list) -> str:
        return ", ".join(str(s) for s in lst if str(s).strip())

    db.set_config(supabase_url, supabase_key, "cv_skills",           _csv(profile.get("skills", [])))
    db.set_config(supabase_url, supabase_key, "cv_summary",          profile.get("summary", ""))
    db.set_config(supabase_url, supabase_key, "cv_job_titles",       _csv(profile.get("job_titles", [])))
    db.set_config(supabase_url, supabase_key, "cv_years_experience", str(profile.get("years_experience", 0)))
    db.set_config(supabase_url, supabase_key, "cv_certifications",   _csv(profile.get("certifications", [])))
    db.set_config(supabase_url, supabase_key, "cv_languages",        _csv(profile.get("languages", [])))
    db.set_config(supabase_url, supabase_key, "cv_education",        _csv(profile.get("education", [])))

    # Generate and store domain filter terms (used by RelevanceEngine T4 tier)
    domain_terms = generate_domain_terms(profile)
    db.set_config(supabase_url, supabase_key, "cv_domain_terms",
                  ", ".join(domain_terms))

    db.set_config(supabase_url, supabase_key, "cv_analyzed_at",
                  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    skill_count = len(profile.get("skills", []))
    _log(f"CV profile stored ({skill_count} skills, {len(domain_terms)} domain filter term(s))")
    # Print a parseable line so the PowerShell GUI can update its status label
    print(f"CV_SKILL_COUNT={skill_count}", flush=True)


def get_cv_profile(supabase_url: str, supabase_key: str) -> dict | None:
    """
    Retrieve the structured CV profile from Supabase bot_state.
    Returns a dict, or None if the CV has never been analyzed.
    """
    analyzed_at = db.get_config(supabase_url, supabase_key, "cv_analyzed_at", "")
    if not analyzed_at:
        return None

    def _to_list(s: str) -> list:
        return [x.strip() for x in s.split(",") if x.strip()] if s else []

    return {
        "skills":           _to_list(db.get_config(supabase_url, supabase_key, "cv_skills",           "")),
        "summary":          db.get_config(supabase_url, supabase_key, "cv_summary",          ""),
        "job_titles":       _to_list(db.get_config(supabase_url, supabase_key, "cv_job_titles",       "")),
        "years_experience": int(db.get_config(supabase_url, supabase_key, "cv_years_experience", "0") or 0),
        "certifications":   _to_list(db.get_config(supabase_url, supabase_key, "cv_certifications",   "")),
        "languages":        _to_list(db.get_config(supabase_url, supabase_key, "cv_languages",        "")),
        "education":        _to_list(db.get_config(supabase_url, supabase_key, "cv_education",        "")),
        "domain_terms":     _to_list(db.get_config(supabase_url, supabase_key, "cv_domain_terms",     "")),
        "cv_analyzed_at":   analyzed_at,
    }


# ---------------------------------------------------------------------------
# Prompt formatting
# ---------------------------------------------------------------------------

def format_profile_for_prompt(profile: dict) -> str:
    """
    Format the structured CV profile as a clean prompt section.
    Replaces the raw PDF text dump that was previously used in scoring.
    """
    lines: list[str] = []

    yrs    = profile.get("years_experience", 0)
    titles = profile.get("job_titles", [])
    if titles:
        exp_str = (f"{yrs} year(s) as {' / '.join(titles[:3])}" if yrs
                   else " / ".join(titles[:3]))
        lines.append(f"Experience: {exp_str}")
    elif yrs:
        lines.append(f"Experience: {yrs} year(s)")

    skills = profile.get("skills", [])
    if skills:
        lines.append(f"Skills: {', '.join(skills[:25])}")

    certs = profile.get("certifications", [])
    if certs:
        lines.append(f"Certifications: {', '.join(certs)}")

    langs = profile.get("languages", [])
    if langs:
        lines.append(f"Languages: {', '.join(langs)}")

    edu = profile.get("education", [])
    if edu:
        lines.append(f"Education: {', '.join(edu[:2])}")

    summary = profile.get("summary", "")
    if summary:
        lines.append(f"Summary: {summary}")

    return "\n".join(lines) if lines else ""


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Windows: force UTF-8 stdout so non-ASCII chars don't crash under cp1252
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="Analyze CV with AI and store structured profile to Supabase"
    )
    parser.add_argument("--cv",     default="",            help="Path to CV PDF file")
    parser.add_argument("--model",  default=DEFAULT_MODEL, help="Ollama model name")
    parser.add_argument("--ollama", default="",            help="Ollama base URL")
    parser.add_argument("--show",   action="store_true",   help="Print stored profile without re-analyzing")
    args = parser.parse_args()

    cfg          = _load_settings_json()
    supabase_url = (os.environ.get("SUPABASE_URL", "") or cfg.get("SupabaseUrl") or "").strip()
    supabase_key = (os.environ.get("SUPABASE_KEY", "") or cfg.get("SupabaseKey") or "").strip()
    ollama       = (os.environ.get("OLLAMA_URL",   "") or args.ollama
                    or cfg.get("OllamaUrl") or DEFAULT_OLLAMA).strip()

    if not supabase_url or not supabase_key:
        _log("ERROR: Set SUPABASE_URL / SUPABASE_KEY env vars or fill them in settings.json.")
        sys.exit(1)

    # --show: print current profile and exit
    if args.show:
        profile = get_cv_profile(supabase_url, supabase_key)
        if not profile:
            _log("No CV profile stored yet. Run: python cloud/cv_analyzer.py --cv path/to/cv.pdf")
            sys.exit(0)
        print("\n=== Stored CV Profile ===")
        print(f"Analyzed at   : {profile['cv_analyzed_at']}")
        print(f"Skills ({len(profile['skills'])}): {', '.join(profile['skills'])}")
        print(f"Job titles    : {', '.join(profile['job_titles'])}")
        print(f"Experience    : {profile['years_experience']} years")
        print(f"Certifications: {', '.join(profile['certifications'])}")
        print(f"Languages     : {', '.join(profile['languages'])}")
        print(f"Education     : {', '.join(profile['education'])}")
        print(f"Summary       : {profile['summary']}")
        domain_terms = profile.get("domain_terms", [])
        print(f"Domain filter ({len(domain_terms)} terms): {', '.join(domain_terms[:30])}{'...' if len(domain_terms) > 30 else ''}")
        print("\n=== Scoring prompt block ===")
        print(format_profile_for_prompt(profile))
        sys.exit(0)

    # Resolve CV path: --cv arg > settings.json UserProfile
    cv_path = (args.cv or cfg.get("UserProfile") or "").strip()
    if not cv_path:
        _log("ERROR: No CV path. Use --cv path/to/cv.pdf or set UserProfile in settings.json.")
        sys.exit(1)
    if not os.path.isfile(cv_path):
        _log(f"ERROR: File not found: {cv_path}")
        sys.exit(1)

    _log(f"Extracting text from: {cv_path}")
    text = extract_cv_text(cv_path)
    if not text:
        _log("ERROR: Could not extract text from CV (empty or unsupported format).")
        sys.exit(1)
    _log(f"Extracted {len(text)} characters")

    _log(f"Sending to Ollama ({ollama}) model={args.model} ...")
    profile = analyze_cv(text, ollama_url=ollama, model=args.model)
    if not profile:
        _log("ERROR: Analysis returned empty. Check Ollama is running: ollama serve")
        sys.exit(1)

    skills = profile.get("skills", [])
    _log(f"Extracted {len(skills)} skills: "
         f"{', '.join(skills[:15])}{'...' if len(skills) > 15 else ''}")
    _log(f"Job titles    : {', '.join(profile.get('job_titles', []))}")
    _log(f"Experience    : {profile.get('years_experience', 0)} years")
    if profile.get("certifications"):
        _log(f"Certifications: {', '.join(profile['certifications'])}")
    if profile.get("languages"):
        _log(f"Languages     : {', '.join(profile['languages'])}")

    store_cv_profile(supabase_url, supabase_key, profile)
    _log("Done. Future enricher runs will use this structured profile for job scoring.")


if __name__ == "__main__":
    main()
