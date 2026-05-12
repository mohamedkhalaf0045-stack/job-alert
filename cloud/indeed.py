"""
Indeed job scraper — HTTP-only, no Playwright.
Extracts the embedded JSON blob from Indeed's search results page.
Returns a list of job dicts in the same shape as linkedin.py.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
})

_BOT_SIGNALS = ("cf-ray", "x-amz-cf-id", "x-amz-request-id")


def _search_url(keyword: str, location: str, start: int = 0) -> str:
    q = quote(keyword)
    l = quote(location)
    return (
        f"https://ae.indeed.com/jobs"
        f"?q={q}&l={l}&fromage=1&start={start}&sort=date"
    )


def _fetch(url: str) -> str | None:
    """Fetch a URL; returns None on bot-detection or error."""
    try:
        resp = _SESSION.get(url, timeout=20)
        # Detect bot challenge pages
        low = resp.text[:2000].lower()
        if resp.status_code in (403, 429):
            print(f"[Indeed] {resp.status_code} on {url} — bot-detected or rate-limited")
            return None
        if any(h in resp.headers for h in _BOT_SIGNALS) and "jobsearch" not in resp.text:
            print("[Indeed] Bot-detection page returned (no job data)")
            return None
        if "captcha" in low or "please verify" in low or "are you a robot" in low:
            print("[Indeed] CAPTCHA page returned — skipping")
            return None
        if resp.status_code != 200:
            print(f"[Indeed] HTTP {resp.status_code}")
            return None
        return resp.text
    except requests.RequestException as exc:
        print(f"[Indeed] Request error: {exc}")
        return None


def _extract_jobs(html: str, keyword: str) -> list[dict]:
    """Pull jobs out of the window.mosaic.providerData JSON blob."""
    # Indeed embeds job data as a JS variable
    patterns = [
        r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.*?\});',
        r'"jobKeysWithInfo"\s*:\s*(\{.*?\})\s*,\s*"',
        r'_initialData\s*=\s*(\{.*?"jobKeys".*?\});',
    ]

    raw = None
    for pat in patterns:
        m = re.search(pat, html, re.DOTALL)
        if m:
            raw = m.group(1)
            break

    if not raw:
        # Try the newer /jobcard API embedded format
        m = re.search(r'"results"\s*:\s*(\[.*?\])\s*,\s*"', html, re.DOTALL)
        if m:
            try:
                return _parse_results_array(json.loads(m.group(1)), keyword)
            except Exception:
                pass
        print("[Indeed] No job data blob found in page — may be bot-detected or page structure changed")
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[Indeed] JSON parse error: {exc}")
        return []

    # Navigate to the job list — structure varies by Indeed version
    results = (
        data.get("metaData", {}).get("mosaicProviderJobCardsModel", {}).get("results")
        or data.get("results")
        or []
    )
    return _parse_results_array(results, keyword)


def _parse_results_array(results: list, keyword: str) -> list[dict]:
    jobs = []
    now = datetime.now(timezone.utc)

    for r in results:
        job_id  = str(r.get("jobkey") or r.get("jobKey") or "")
        title   = r.get("title") or r.get("displayTitle") or ""
        company = (r.get("company") or r.get("companyName") or "").strip()
        location = (r.get("formattedLocation") or r.get("jobLocationCity") or "").strip()
        url_path = r.get("link") or r.get("jobUrl") or ""
        if url_path and not url_path.startswith("http"):
            url = f"https://ae.indeed.com{url_path}"
        else:
            url = url_path

        if not job_id or not title or not url:
            continue

        # Posted date — Indeed gives relative "postDate" in days
        posted_text = ""
        posted_date = ""
        post_age_days = r.get("postDate") or r.get("postDateL") or r.get("ageInDays")
        if post_age_days is not None:
            try:
                d = int(post_age_days)
                posted_date = (now - timedelta(days=d)).strftime("%Y-%m-%d")
                posted_text = "Today" if d == 0 else f"{d} day{'s' if d != 1 else ''} ago"
            except (ValueError, TypeError):
                pass

        jobs.append({
            "Id":         job_id,
            "Keyword":    keyword,
            "Title":      title,
            "Company":    company,
            "Location":   location,
            "Url":        url,
            "PostedDate": posted_date,
            "PostedText": posted_text,
            "IsApplied":  False,
            "Source":     "Indeed",
        })
    return jobs


def scrape_indeed(keyword: str, location: str, max_hours: int = 24) -> list[dict]:
    """
    Scrape Indeed for jobs matching keyword+location.
    Returns list of job dicts; returns [] silently if bot-detected.
    """
    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    for start in (0, 10, 20):
        url  = _search_url(keyword, location, start)
        html = _fetch(url)
        if html is None:
            break

        jobs = _extract_jobs(html, keyword)
        if not jobs:
            break

        for job in jobs:
            if job["Id"] not in seen_ids:
                seen_ids.add(job["Id"])
                all_jobs.append(job)

        if len(jobs) < 10:
            break  # last page

        if start < 20:
            time.sleep(2.0)

    return all_jobs
