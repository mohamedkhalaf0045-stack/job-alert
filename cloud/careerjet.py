"""
CareerJet job aggregator — free affiliate API for UAE.
GET http://public.api.careerjet.net/search
Requires a Referer header — without it returns HTTP 403.
Returns jobs in the same dict shape as adzuna.py / linkedin.py.

API docs: https://www.careerjet.com/partners/api/
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import requests

_API_BASE   = "http://public.api.careerjet.net/search"
_REFERER    = "https://www.careerjet.ae/"
_PAGE_SIZE  = 20


def _canonical_url(raw: str) -> str:
    if not raw:
        return raw
    # Strip query params that vary per-session (tracking tokens)
    from urllib.parse import urlparse, urlunparse
    try:
        p = urlparse(raw)
        return urlunparse((p.scheme, p.netloc, p.path, "", "", "")).rstrip("/")
    except Exception:
        return raw


def _parse_date(date_str: str) -> tuple[str, str]:
    """Return (posted_date ISO string, posted_text) from CareerJet date field.

    CareerJet returns RFC 2822 dates ("Sun, 21 Jun 2026 07:59:13 GMT"),
    relative strings ("2 days ago", "Today"), or ISO dates ("2026-06-19").
    """
    if not date_str:
        return "", ""
    raw = date_str.strip()
    raw_lower = raw.lower()
    now = datetime.now(timezone.utc)

    # RFC 2822: "Sun, 21 Jun 2026 07:59:13 GMT"
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(raw)
        dt = dt.astimezone(timezone.utc)
        age_h = (now - dt).total_seconds() / 3600
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
        pass

    # ISO date: "2026-06-19" or "2026-06-19T..."
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        try:
            dt = datetime.fromisoformat(raw[:10]).replace(tzinfo=timezone.utc)
            age_d = int((now - dt).total_seconds() / 86400)
            text = "Today" if age_d == 0 else f"{age_d} day{'s' if age_d != 1 else ''} ago"
            return raw[:10], text
        except Exception:
            pass

    # Relative strings
    if raw_lower in ("today", "just posted", "less than 1 hour ago"):
        return now.strftime("%Y-%m-%d"), "Just posted"

    import re
    from datetime import timedelta
    m = re.match(r"(\d+)\s+hour", raw_lower)
    if m:
        h = int(m.group(1))
        dt = now - timedelta(hours=h)
        return dt.strftime("%Y-%m-%d"), f"{h} hour{'s' if h != 1 else ''} ago"
    m = re.match(r"(\d+)\s+day", raw_lower)
    if m:
        d = int(m.group(1))
        dt = now - timedelta(days=d)
        return dt.strftime("%Y-%m-%d"), f"{d} day{'s' if d != 1 else ''} ago"
    m = re.match(r"(\d+)\s+week", raw_lower)
    if m:
        w = int(m.group(1))
        dt = now - timedelta(weeks=w)
        return dt.strftime("%Y-%m-%d"), f"{w} week{'s' if w != 1 else ''} ago"
    m = re.match(r"(\d+)\s+month", raw_lower)
    if m:
        mo = int(m.group(1))
        dt = now - timedelta(days=mo * 30)
        return dt.strftime("%Y-%m-%d"), f"{mo} month{'s' if mo != 1 else ''} ago"

    return "", raw


def _stable_id(url: str, title: str, company: str) -> str:
    """Derive a stable job_id from the canonical URL when no ID is provided."""
    key = f"{_canonical_url(url)}|{title}|{company}".encode("utf-8")
    return "cj_" + hashlib.sha1(key).hexdigest()[:12]


def scrape_careerjet(
    keyword: str,
    location: str,
    affid: str,
    max_results: int = 20,
) -> list[dict]:
    """
    Query CareerJet API for jobs matching keyword + location.
    Returns [] if the API key (affid) is missing or on any error.
    """
    if not affid:
        return []

    try:
        my_ip = requests.get("https://api.ipify.org", timeout=5).text.strip()
    except Exception:
        my_ip = "0.0.0.0"

    jobs: list[dict] = []
    seen_ids: set[str] = set()
    pages = max(1, (max_results + _PAGE_SIZE - 1) // _PAGE_SIZE)

    for page in range(1, pages + 1):
        params = {
            "keywords":    keyword,
            "location":    location,
            "affid":       affid,
            "user_ip":     my_ip,
            "user_agent":  "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "locale_code": "en_AE",
            "pagesize":    _PAGE_SIZE,
            "page":        page,
            "sort":        "date",
        }
        try:
            resp = requests.get(
                _API_BASE,
                headers={"Referer": _REFERER},
                params=params,
                timeout=20,
            )
        except Exception as exc:
            print(f"[CareerJet] Request error (page {page}): {exc}")
            break

        if resp.status_code == 403:
            print(f"[CareerJet] HTTP 403 — check affid or Referer header")
            break
        if resp.status_code != 200:
            print(f"[CareerJet] HTTP {resp.status_code}")
            break

        try:
            data = resp.json()
        except Exception as exc:
            print(f"[CareerJet] JSON parse error: {exc}")
            break

        if data.get("type") == "ERROR":
            print(f"[CareerJet] API error: {data.get('error')}")
            break

        raw_jobs = data.get("jobs") or []
        if not raw_jobs:
            break

        for r in raw_jobs:
            url     = (r.get("url")     or "").strip()
            title   = (r.get("title")   or "").strip()
            company = (r.get("company") or "").strip()
            loc     = (r.get("locations") or "").strip()
            desc    = (r.get("description") or "").strip()
            date_raw = (r.get("date") or "").strip()

            if not url or not title:
                continue

            job_id = _stable_id(url, title, company)
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            posted_date, posted_text = _parse_date(date_raw)

            job: dict = {
                "Id":         job_id,
                "Keyword":    keyword,
                "Title":      title,
                "Company":    company,
                "Location":   loc,
                "Url":        url,
                "PostedDate": posted_date,
                "PostedText": posted_text,
                "IsApplied":  False,
                "Source":     "CareerJet",
            }
            if desc:
                job["Description"] = desc

            salary = (r.get("salary") or "").strip()
            if salary:
                job["SalaryText"] = salary

            jobs.append(job)

        if len(raw_jobs) < _PAGE_SIZE:
            break

    return jobs
