"""
LinkedIn job scraper — port of shared-functions.ps1 Get-LinkedInJobs / Parse-JobCards.
Uses only the requests library (no browser needed for LinkedIn guest API).
"""

from __future__ import annotations

import html
import re
import time
from urllib.parse import quote, urlparse, urlunparse

import requests

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
})


def _guest_url(keyword: str, location: str, start: int) -> str:
    k = quote(keyword)
    l = quote(location)
    return (
        f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        f"?keywords={k}&location={l}&start={start}"
    )


def _auth_url(keyword: str, location: str, start: int) -> str:
    k = quote(keyword)
    l = quote(location)
    return (
        f"https://www.linkedin.com/jobs/search/"
        f"?keywords={k}&location={l}&start={start}"
    )


def _plain_text(value: str) -> str:
    decoded = html.unescape(value or "")
    stripped = re.sub(r"<.*?>", " ", decoded, flags=re.DOTALL)
    return re.sub(r"\s+", " ", stripped).strip()


def _canonical_url(raw: str) -> str:
    try:
        p = urlparse(raw)
        return urlunparse((p.scheme, p.netloc, p.path, "", "", "")).rstrip("/")
    except Exception:
        return raw


def _fetch(url: str, cookie_header: str, attempt: int = 1) -> str | None:
    headers = {}
    if cookie_header:
        headers["Cookie"] = cookie_header
    try:
        resp = _SESSION.get(url, headers=headers, timeout=25)
        if resp.status_code == 429:
            return None  # rate-limited — caller will skip
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        if attempt < 3:
            time.sleep(attempt)
            return _fetch(url, cookie_header, attempt + 1)
        print(f"[LinkedIn] fetch failed after 3 attempts: {exc}")
        return None


def _parse_cards(html_text: str, keyword: str) -> list[dict]:
    jobs = []
    for card in re.finditer(r"<li\b.*?</li>", html_text, re.DOTALL):
        chunk = card.group(0)

        id_m       = re.search(r"jobPosting:(\d+)", chunk)
        url_m      = re.search(r'base-card__full-link[^>]+href="([^"]+)"', chunk)
        title_m    = re.search(r'base-search-card__title">\s*(.*?)\s*</h3>', chunk, re.DOTALL)
        company_m  = re.search(r'base-search-card__subtitle">\s*(.*?)\s*</h4>', chunk, re.DOTALL)
        location_m = re.search(r'job-search-card__location">\s*(.*?)\s*</span>', chunk, re.DOTALL)
        time_m     = re.search(r'<time[^>]*datetime="([^"]+)"[^>]*>(.*?)</time>', chunk, re.DOTALL)

        if not (id_m and url_m and title_m):
            continue

        plain = _plain_text(chunk).lower()
        is_applied = bool(re.search(r'\b(applied|application submitted|submitted|already applied)\b', plain))

        jobs.append({
            "Id":         id_m.group(1),
            "Keyword":    keyword,
            "Title":      _plain_text(title_m.group(1)),
            "Company":    _plain_text(company_m.group(1)) if company_m else "",
            "Location":   _plain_text(location_m.group(1)) if location_m else "",
            "Url":        _canonical_url(html.unescape(url_m.group(1))),
            "PostedDate": _plain_text(time_m.group(1)) if time_m else "",
            "PostedText": _plain_text(time_m.group(2)) if time_m else "",
            "IsApplied":  is_applied,
            "Source":     "LinkedIn",
        })
    return jobs


def fetch_job_description(job_url: str, cookie_header: str = "") -> str:
    """Fetch the full description text for a single job URL.

    LinkedIn: uses the guest jobPosting API (no login required).
    Indeed:   fetches the job page directly.
    Returns plain text, max 3000 chars. Empty string on failure.
    """
    try:
        url_lower = job_url.lower()
        if "linkedin.com" in url_lower:
            # Extract numeric job ID from URL path, e.g. /jobs/view/1234567890
            m = re.search(r"/(?:view|jobs/view)/(\d+)", job_url)
            if not m:
                return ""
            job_id = m.group(1)
            api_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
            html_text = _fetch(api_url, cookie_header)
            if not html_text:
                return ""
            # Extract description block
            desc_m = re.search(
                r'class="show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>',
                html_text, re.DOTALL
            )
            raw = desc_m.group(1) if desc_m else html_text
        elif "indeed.com" in url_lower:
            html_text = _fetch(job_url, cookie_header)
            if not html_text:
                return ""
            desc_m = re.search(
                r'id="jobDescriptionText"[^>]*>(.*?)</div>',
                html_text, re.DOTALL
            )
            raw = desc_m.group(1) if desc_m else html_text
        else:
            html_text = _fetch(job_url, cookie_header)
            raw = html_text or ""

        return _plain_text(raw)[:3000]
    except Exception as exc:
        print(f"[Description] fetch failed for {job_url}: {exc}")
        return ""


def get_posted_age_hours(job: dict) -> float:
    text = job.get("PostedText", "")
    date = job.get("PostedDate", "")
    if text:
        m = re.search(r"(\d+)\s*hour", text, re.I)
        if m:
            return float(m.group(1))
        m = re.search(r"(\d+)\s*minute", text, re.I)
        if m:
            return 0.0
        m = re.search(r"(\d+)\s*day", text, re.I)
        if m:
            return float(m.group(1)) * 24
        m = re.search(r"(\d+)\s*week", text, re.I)
        if m:
            return float(m.group(1)) * 24 * 7
        if re.search(r"just now|just posted|today", text, re.I):
            return 0.0
    if date:
        from datetime import datetime, timezone
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                dt = datetime.strptime(date[:len(fmt)], fmt).replace(tzinfo=timezone.utc)
                delta = datetime.now(timezone.utc) - dt
                return max(0.0, delta.total_seconds() / 3600)
            except ValueError:
                continue
    return float("inf")


def scrape_linkedin(
    keyword: str,
    location: str,
    cookie_header: str = "",
    hide_applied: bool = False,
    max_pages: int = 2,
) -> list[dict]:
    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    for page_idx in range(max_pages):
        start = page_idx * 25
        url = _guest_url(keyword, location, start)
        html_text = _fetch(url, cookie_header)
        if html_text is None:
            print(f"[LinkedIn] HTTP 429 on '{keyword}' page {page_idx + 1} — skipping")
            break

        jobs = _parse_cards(html_text, keyword)
        if not jobs:
            break

        for job in jobs:
            if job["Id"] in seen_ids:
                continue
            if hide_applied and job["IsApplied"]:
                continue
            seen_ids.add(job["Id"])
            all_jobs.append(job)

        if page_idx < max_pages - 1:
            time.sleep(1.5)  # pace requests to stay under LinkedIn rate limit

    return all_jobs
