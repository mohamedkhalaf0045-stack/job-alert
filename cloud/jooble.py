"""
Jooble job aggregator — free API, POST https://jooble.org/api/{key}
Returns jobs in the same dict shape as linkedin.py / indeed.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, urlunparse

import requests

_API_BASE = "https://jooble.org/api"


def _canonical_url(raw: str) -> str:
    try:
        p = urlparse(raw)
        return urlunparse((p.scheme, p.netloc, p.path, "", "", "")).rstrip("/")
    except Exception:
        return raw


def _parse_age(date_str: str) -> tuple[str, str]:
    """Return (posted_date ISO, posted_text) from a Jooble 'updated' field."""
    if not date_str:
        return "", ""
    try:
        # Jooble returns e.g. "2026-05-12T08:00:00" (no tz — treat as UTC)
        dt = datetime.fromisoformat(date_str.rstrip("Z")).replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        age_d = int(age_h // 24)
        if age_h < 1:
            text = "Just posted"
        elif age_h < 24:
            h = int(age_h)
            text = f"{h} hour{'s' if h != 1 else ''} ago"
        else:
            text = f"{age_d} day{'s' if age_d != 1 else ''} ago"
        return dt.strftime("%Y-%m-%d"), text
    except Exception:
        return "", ""


def scrape_jooble(keyword: str, location: str, api_key: str, max_results: int = 20) -> list[dict]:
    """
    Query Jooble API for jobs matching keyword + location.
    Returns [] if api_key is empty or on any error.
    """
    if not api_key:
        return []

    payload = {
        "keywords": keyword,
        "location": location,
        "resultsOnPage": max_results,
    }

    try:
        resp = requests.post(
            f"{_API_BASE}/{api_key}",
            json=payload,
            timeout=15,
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            print(f"[Jooble] HTTP {resp.status_code}")
            return []
        data = resp.json()
    except Exception as exc:
        print(f"[Jooble] Request error: {exc}")
        return []

    raw_jobs = data.get("jobs") or []
    jobs: list[dict] = []

    for r in raw_jobs:
        url = _canonical_url(r.get("link") or "")
        title   = (r.get("title")   or "").strip()
        company = (r.get("company") or "").strip()
        if not url or not title:
            continue

        posted_date, posted_text = _parse_age(r.get("updated") or "")

        jobs.append({
            "Id":         url,           # Jooble has no stable job ID — use URL
            "Keyword":    keyword,
            "Title":      title,
            "Company":    company,
            "Location":   (r.get("location") or "").strip(),
            "Url":        url,
            "PostedDate": posted_date,
            "PostedText": posted_text,
            "IsApplied":  False,
            "Source":     "Jooble",
        })

    return jobs
