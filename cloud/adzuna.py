"""
Adzuna job aggregator — free API, country code "ae" for UAE.
GET https://api.adzuna.com/v1/api/jobs/ae/search/{page}
Returns jobs in the same dict shape as linkedin.py / indeed.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse, quote

import requests

_API_BASE = "https://api.adzuna.com/v1/api/jobs/ae/search"
_RESULTS_PER_PAGE = 20


def _canonical_url(raw: str) -> str:
    try:
        p = urlparse(raw)
        return urlunparse((p.scheme, p.netloc, p.path, "", "", "")).rstrip("/")
    except Exception:
        return raw


def _parse_age(date_str: str) -> tuple[str, str]:
    """Return (posted_date ISO, posted_text) from Adzuna 'created' field."""
    if not date_str:
        return "", ""
    try:
        # Adzuna returns ISO-8601, e.g. "2026-05-12T08:00:00Z"
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


def scrape_adzuna(
    keyword: str,
    location: str,
    app_id: str,
    app_key: str,
    max_results: int = 20,
) -> list[dict]:
    """
    Query Adzuna API for jobs matching keyword + location in UAE.
    Returns [] if credentials are missing or on any error.
    """
    if not app_id or not app_key:
        return []

    jobs: list[dict] = []
    seen_ids: set[str] = set()
    pages = max(1, (max_results + _RESULTS_PER_PAGE - 1) // _RESULTS_PER_PAGE)

    for page in range(1, pages + 1):
        params = {
            "app_id":          app_id,
            "app_key":         app_key,
            "what":            keyword,
            "where":           location,
            "results_per_page": _RESULTS_PER_PAGE,
            "sort_by":         "date",
            "content-type":    "application/json",
        }
        try:
            resp = requests.get(
                f"{_API_BASE}/{page}",
                params=params,
                timeout=15,
            )
            if resp.status_code == 401:
                print("[Adzuna] Invalid app_id/app_key (401)")
                break
            if resp.status_code != 200:
                print(f"[Adzuna] HTTP {resp.status_code}")
                break
            data = resp.json()
        except Exception as exc:
            print(f"[Adzuna] Request error: {exc}")
            break

        raw_jobs = data.get("results") or []
        if not raw_jobs:
            break

        for r in raw_jobs:
            job_id = str(r.get("id") or "")
            url    = _canonical_url(r.get("redirect_url") or "")
            title  = (r.get("title") or "").strip()
            company = (r.get("company", {}) or {}).get("display_name", "").strip()
            loc     = (r.get("location", {}) or {}).get("display_name", "").strip()

            if not job_id or not url or not title:
                continue
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            posted_date, posted_text = _parse_age(r.get("created") or "")

            jobs.append({
                "Id":         job_id,
                "Keyword":    keyword,
                "Title":      title,
                "Company":    company,
                "Location":   loc,
                "Url":        url,
                "PostedDate": posted_date,
                "PostedText": posted_text,
                "IsApplied":  False,
                "Source":     "Adzuna",
            })

        if len(raw_jobs) < _RESULTS_PER_PAGE:
            break

    return jobs
