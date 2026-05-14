"""
Web search job discovery — cascades through Tavily → Brave → Google → Bing.
When one provider is rate-limited or has no key, the next one is tried.
Returns job dicts in the same shape as linkedin.py / indeed.py.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

import requests

# ── helpers ──────────────────────────────────────────────────────────────────

def _canonical_url(raw: str) -> str:
    try:
        p = urlparse(raw)
        return urlunparse((p.scheme, p.netloc, p.path, "", "", "")).rstrip("/")
    except Exception:
        return raw


def _url_id(url: str) -> str:
    return hashlib.sha256(_canonical_url(url).lower().encode()).hexdigest()[:16]


def _build_query(keyword: str, location: str) -> str:
    return f'"{keyword}" jobs "{location}"'


def _freshness_params(max_hours: int) -> dict:
    """Map max_hours to provider-neutral labels used by callers."""
    if max_hours <= 24:
        return {"tavily_days": 1,   "brave": "pd",    "google": "d1",    "bing": "Day"}
    if max_hours <= 168:
        return {"tavily_days": 7,   "brave": "pw",    "google": "w1",    "bing": "Week"}
    if max_hours <= 720:
        return {"tavily_days": 30,  "brave": "pm",    "google": "m1",    "bing": "Month"}
    return     {"tavily_days": 365, "brave": "py",    "google": "y1",    "bing": "Month"}


# ── result → job dict ─────────────────────────────────────────────────────────

_TITLE_SEPARATORS = re.compile(r"\s*[-|–—·•@]\s*")
_JOB_NOISE = re.compile(
    r"\b(apply now|urgent|hiring|vacancy|opening|job posting|career|"
    r"full[- ]time|part[- ]time|remote|onsite)\b", re.I
)
_SKIP_DOMAINS = {
    "google.com", "bing.com", "yahoo.com", "youtube.com",
    "facebook.com", "twitter.com", "reddit.com", "wikipedia.org",
}


def _is_job_url(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().lstrip("www.")
        if host in _SKIP_DOMAINS:
            return False
        return True
    except Exception:
        return False


def _parse_result(title: str, url: str, snippet: str, keyword: str, source_tag: str) -> dict | None:
    """Convert a single search result into a job dict. Returns None if it looks non-job."""
    if not _is_job_url(url):
        return None

    # Split "Job Title - Company | Site" or "Title at Company"
    parts = _TITLE_SEPARATORS.split(title)
    job_title = parts[0].strip() if parts else title.strip()
    company   = parts[1].strip() if len(parts) > 1 else ""

    # Drop pure navigation titles (e.g. "Jobs in UAE - Search Now")
    if not job_title or len(job_title) < 5:
        return None
    if re.search(r"\b(search|browse|find|explore|all jobs)\b", job_title, re.I):
        return None

    # Try to extract location from snippet
    loc_match = re.search(
        r"\b(Dubai|Abu Dhabi|Sharjah|Ajman|UAE|United Arab Emirates|Riyadh|Kuwait)\b",
        snippet, re.I
    )
    location_str = loc_match.group(0) if loc_match else "UAE"

    return {
        "Id":         _url_id(url),
        "Keyword":    keyword,
        "Title":      job_title,
        "Company":    company,
        "Location":   location_str,
        "Url":        _canonical_url(url),
        "PostedDate": "",
        "PostedText": "",
        "IsApplied":  False,
        "Source":     source_tag,
    }


def _dedupe(jobs: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for j in jobs:
        if j["Id"] not in seen:
            seen.add(j["Id"])
            out.append(j)
    return out


# ── provider implementations ─────────────────────────────────────────────────

def _tavily(query: str, keyword: str, api_key: str, fp: dict) -> list[dict] | None:
    """Returns list on success, None on rate-limit/error (try next provider)."""
    if not api_key:
        return None
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key":      api_key,
                "query":        query,
                "search_depth": "basic",
                "max_results":  15,
                "include_answer": False,
                "days":         fp["tavily_days"],
            },
            timeout=20,
        )
        if resp.status_code == 429:
            print("[WebSearch] Tavily rate-limited — trying next provider")
            return None
        if resp.status_code != 200:
            print(f"[WebSearch] Tavily HTTP {resp.status_code}")
            return None
        results = resp.json().get("results") or []
        jobs = []
        for r in results:
            j = _parse_result(r.get("title",""), r.get("url",""), r.get("content",""), keyword, "Web/Tavily")
            if j:
                jobs.append(j)
        return _dedupe(jobs)
    except Exception as exc:
        print(f"[WebSearch] Tavily error: {exc}")
        return None


def _brave(query: str, keyword: str, api_key: str, fp: dict) -> list[dict] | None:
    if not api_key:
        return None
    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": 20, "search_lang": "en", "freshness": fp["brave"]},
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": api_key,
            },
            timeout=20,
        )
        if resp.status_code == 429:
            print("[WebSearch] Brave rate-limited — trying next provider")
            return None
        if resp.status_code != 200:
            print(f"[WebSearch] Brave HTTP {resp.status_code}")
            return None
        web = resp.json().get("web", {}).get("results") or []
        jobs = []
        for r in web:
            j = _parse_result(r.get("title",""), r.get("url",""), r.get("description",""), keyword, "Web/Brave")
            if j:
                jobs.append(j)
        return _dedupe(jobs)
    except Exception as exc:
        print(f"[WebSearch] Brave error: {exc}")
        return None


def _google(query: str, keyword: str, api_key: str, cx: str, fp: dict) -> list[dict] | None:
    if not api_key or not cx:
        return None
    try:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": api_key, "cx": cx, "q": query, "num": 10, "dateRestrict": fp["google"]},
            timeout=20,
        )
        if resp.status_code in (429, 403):
            print(f"[WebSearch] Google {resp.status_code} — trying next provider")
            return None
        if resp.status_code != 200:
            print(f"[WebSearch] Google HTTP {resp.status_code}")
            return None
        items = resp.json().get("items") or []
        jobs = []
        for r in items:
            j = _parse_result(r.get("title",""), r.get("link",""), r.get("snippet",""), keyword, "Web/Google")
            if j:
                jobs.append(j)
        return _dedupe(jobs)
    except Exception as exc:
        print(f"[WebSearch] Google error: {exc}")
        return None


def _bing(query: str, keyword: str, api_key: str, fp: dict) -> list[dict] | None:
    if not api_key:
        return None
    try:
        resp = requests.get(
            "https://api.bing.microsoft.com/v7.0/search",
            params={"q": query, "count": 20, "mkt": "en-AE", "freshness": fp["bing"]},
            headers={"Ocp-Apim-Subscription-Key": api_key},
            timeout=20,
        )
        if resp.status_code == 429:
            print("[WebSearch] Bing rate-limited — trying next provider")
            return None
        if resp.status_code in (401, 403):
            print(f"[WebSearch] Bing auth error {resp.status_code}")
            return None
        if resp.status_code != 200:
            print(f"[WebSearch] Bing HTTP {resp.status_code}")
            return None
        web_pages = resp.json().get("webPages", {}).get("value") or []
        jobs = []
        for r in web_pages:
            j = _parse_result(r.get("name",""), r.get("url",""), r.get("snippet",""), keyword, "Web/Bing")
            if j:
                jobs.append(j)
        return _dedupe(jobs)
    except Exception as exc:
        print(f"[WebSearch] Bing error: {exc}")
        return None


# ── public entry point ────────────────────────────────────────────────────────

def search_jobs(
    keyword: str,
    location: str,
    tavily_key: str = "",
    brave_key: str = "",
    google_key: str = "",
    google_cx: str = "",
    bing_key: str = "",
    max_hours: int = 24,
) -> list[dict]:
    """
    Try each search provider in order: Tavily → Brave → Google → Bing.
    max_hours is converted to the native freshness/date parameter of each API
    so only recently-posted jobs are returned.
    Returns the first successful non-empty result set, or [] if all fail/are unconfigured.
    """
    query = _build_query(keyword, location)
    fp    = _freshness_params(max_hours)

    providers = [
        ("Tavily", lambda: _tavily(query, keyword, tavily_key, fp)),
        ("Brave",  lambda: _brave(query, keyword, brave_key,   fp)),
        ("Google", lambda: _google(query, keyword, google_key, google_cx, fp)),
        ("Bing",   lambda: _bing(query, keyword, bing_key,     fp)),
    ]

    for name, fn in providers:
        result = fn()
        if result is None:
            continue          # rate-limited or no key — try next
        if result:
            print(f"[WebSearch] {name} returned {len(result)} result(s) for '{keyword}' (max {max_hours}h)")
            return result
        # empty list from a working provider — still try next for more coverage
        print(f"[WebSearch] {name} returned 0 results for '{keyword}' — trying next")

    print(f"[WebSearch] All providers exhausted for '{keyword}'")
    return []
