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
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-Ch-Ua": '"Chromium";v="128", "Google Chrome";v="128", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
})


def _guest_url(keyword: str, location: str, start: int, max_hours: int = 24,
               geo_id: str = "") -> str:
    k   = quote(keyword)
    tpr = max(max_hours, 1) * 3600  # LinkedIn uses seconds
    if geo_id:
        # Use numeric geoId when available — this matches what LinkedIn's own
        # job-alert algorithm uses and returns a more complete, location-accurate
        # result set than the text-based location parameter.
        return (
            f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
            f"?keywords={k}&geoId={geo_id}&start={start}&f_TPR=r{tpr}"
        )
    l = quote(location)
    return (
        f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        f"?keywords={k}&location={l}&start={start}&f_TPR=r{tpr}"
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
    """Normalize a LinkedIn job URL for deduplication.

    LinkedIn job URLs come in two shapes depending on the source:
      - Guest API:   /jobs/view/4203456789
      - Web search:  /jobs/view/it-support-specialist-at-company-4203456789
    Both refer to the same job. Extract the trailing numeric ID and build a
    stable canonical form so different sources produce the same URL string.
    """
    try:
        raw = (raw or "").strip()
        if "linkedin.com/jobs/view/" in raw.lower():
            m = re.search(r'/jobs/view/[^/?#]*?(\d{7,})(?:[/?#]|$)', raw)
            if m:
                return f"https://www.linkedin.com/jobs/view/{m.group(1)}"
        p = urlparse(raw)
        return urlunparse((p.scheme, p.netloc, p.path, "", "", "")).rstrip("/")
    except Exception:
        return raw


def _fetch(url: str, cookie_header: str, attempt: int = 1, referer: str = "") -> str | None:
    headers = {}
    if cookie_header:
        headers["Cookie"] = cookie_header
    if referer:
        headers["Referer"] = referer
    try:
        resp = _SESSION.get(url, headers=headers, timeout=25)
        if resp.status_code == 429:
            print(f"[LinkedIn] HTTP 429 rate-limited: {url}")
            return None  # rate-limited — caller will skip
        if resp.status_code != 200:
            print(f"[LinkedIn] HTTP {resp.status_code} for: {url}")
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        if attempt < 3:
            time.sleep(attempt)
            return _fetch(url, cookie_header, attempt + 1, referer)
        print(f"[LinkedIn] fetch failed after 3 attempts: {exc}")
        return None


def _parse_cards(html_text: str, keyword: str) -> list[dict]:
    li_count = len(re.findall(r"<li\b", html_text, re.I))
    print(f"[LinkedIn] '{keyword}': HTML {len(html_text)} chars, {li_count} <li> elements")

    jobs = []
    for card in re.finditer(r"<li\b.*?</li>", html_text, re.DOTALL):
        chunk = card.group(0)

        # URL — try old class name first, then newer variant, then any LI job URL
        url_m = (
            re.search(r'base-card__full-link[^>]+href="([^"]+)"', chunk) or
            re.search(r'job-card-container__link[^>]+href="([^"]+)"', chunk) or
            re.search(r'href="(https://[^"]*linkedin\.com/jobs/view/[^"]+)"', chunk)
        )
        if not url_m:
            continue
        raw_url = html.unescape(url_m.group(1))

        # Job ID — URN attribute, data attribute, or last number in the job URL path
        id_m = (
            re.search(r"jobPosting:(\d+)", chunk) or
            re.search(r'data-job-id="(\d+)"', chunk) or
            re.search(r'/jobs/view/[^/?#]*?-(\d+)(?:[/?#]|$)', raw_url)
        )
        if not id_m:
            continue

        # Title
        title_m = (
            re.search(r'base-search-card__title">\s*(.*?)\s*</h3>', chunk, re.DOTALL) or
            re.search(r'job-card-list__title[^"]*"[^>]*>\s*(.*?)\s*</a>', chunk, re.DOTALL) or
            re.search(r'<h3[^>]*>\s*(.*?)\s*</h3>', chunk, re.DOTALL)
        )
        if not title_m:
            continue

        company_m = (
            re.search(r'base-search-card__subtitle">\s*(.*?)\s*</h4>', chunk, re.DOTALL) or
            re.search(r'job-card-container__company-name[^"]*"[^>]*>\s*(.*?)\s*</', chunk, re.DOTALL)
        )
        location_m = (
            re.search(r'job-search-card__location">\s*(.*?)\s*</span>', chunk, re.DOTALL) or
            re.search(r'job-card-container__metadata-item[^"]*"[^>]*>\s*(.*?)\s*</', chunk, re.DOTALL)
        )
        time_m = re.search(r'<time[^>]*datetime="([^"]+)"[^>]*>(.*?)</time>', chunk, re.DOTALL)

        # Fallback: when <time> element is missing or doesn't parse, search the
        # card's plain text for relative age strings like "1 week ago", "3 days ago".
        # This prevents f_TPR-leaked old jobs from slipping through the age filter.
        posted_text_fallback = ""
        if not time_m:
            plain_card = _plain_text(chunk)
            age_text_m = re.search(
                r'\b(\d+)\s+(second|minute|hour|day|week|month)s?\s+ago\b',
                plain_card, re.I
            )
            if age_text_m:
                posted_text_fallback = age_text_m.group(0)  # e.g. "1 week ago"

        plain = _plain_text(chunk).lower()
        is_applied = bool(re.search(r'\b(applied|application submitted|submitted|already applied)\b', plain))

        jobs.append({
            "Id":         id_m.group(1),
            "Keyword":    keyword,
            "Title":      _plain_text(title_m.group(1)),
            "Company":    _plain_text(company_m.group(1)) if company_m else "",
            "Location":   _plain_text(location_m.group(1)) if location_m else "",
            "Url":        _canonical_url(raw_url),
            "PostedDate": _plain_text(time_m.group(1)) if time_m else "",
            "PostedText": _plain_text(time_m.group(2)) if time_m else posted_text_fallback,
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
        m = re.search(r"(\d+)\s*month", text, re.I)
        if m:
            return float(m.group(1)) * 24 * 30
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
    max_pages: int = 6,
    max_hours: int = 72,
    geo_id: str = "",
) -> list[dict]:
    all_jobs: list[dict] = []
    seen_ids: set[str] = set()
    skipped_old = 0

    for page_idx in range(max_pages):
        start = page_idx * 25
        url = _guest_url(keyword, location, start, max_hours, geo_id=geo_id)
        html_text = _fetch(url, cookie_header, referer="https://www.linkedin.com/jobs/")
        if html_text is None:
            print(f"[LinkedIn] rate-limited on '{keyword}' page {page_idx + 1} — skipping")
            break

        jobs = _parse_cards(html_text, keyword)
        print(f"[LinkedIn] '{keyword}' page {page_idx + 1}: {len(jobs)} job(s) parsed")
        if not jobs:
            break

        new_on_page = 0
        for job in jobs:
            if job["Id"] in seen_ids:
                continue
            if hide_applied and job["IsApplied"]:
                continue
            age = get_posted_age_hours(job)
            # If age is unknown (no <time> in card), trust f_TPR pre-filtered at API level.
            # Only drop jobs whose age is positively confirmed to exceed the limit.
            if age != float("inf") and age > max_hours:
                skipped_old += 1
                continue
            seen_ids.add(job["Id"])
            all_jobs.append(job)
            new_on_page += 1

        # No fresh jobs on this page → LinkedIn has exhausted fresh results
        if new_on_page == 0 and page_idx > 0:
            break

        if page_idx < max_pages - 1:
            time.sleep(1.5)  # pace requests to stay under LinkedIn rate limit

    if skipped_old:
        print(f"[LinkedIn] '{keyword}': skipped {skipped_old} job(s) older than {max_hours}h")
    return all_jobs
