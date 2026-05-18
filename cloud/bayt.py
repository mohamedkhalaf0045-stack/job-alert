"""
Bayt.com job scraper — UAE's #1 job board.
Parses the HTML search results page (no API key required).
Falls back gracefully if blocked by Cloudflare or if beautifulsoup4 is unavailable.
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse

import requests

try:
    from bs4 import BeautifulSoup
    _BS4 = True
except ImportError:
    _BS4 = False

_BASE   = "https://www.bayt.com"
_SEARCH = "https://www.bayt.com/en/uae/jobs/"

# Browser-like headers to reduce bot-detection chance
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language":         "en-US,en;q=0.9,ar;q=0.5",
    "Accept-Encoding":         "gzip, deflate, br",
    "Referer":                 "https://www.google.com/",
    "DNT":                     "1",
    "Upgrade-Insecure-Requests": "1",
}

# Relative-age phrase parser (same approach as websearch.py)
_AGO_RE       = re.compile(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", re.I)
_TODAY_RE     = re.compile(r"\b(just\s+now|today)\b",  re.I)
_YESTERDAY_RE = re.compile(r"\byesterday\b",            re.I)


def _parse_age(text: str) -> tuple[str, str]:
    """Return (iso_utc, human_text) from a Bayt posted-date string."""
    now  = datetime.now(timezone.utc)
    text = (text or "").strip()

    m = _AGO_RE.search(text)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        delta_map = {
            "second": timedelta(seconds=n),
            "minute": timedelta(minutes=n),
            "hour":   timedelta(hours=n),
            "day":    timedelta(days=n),
            "week":   timedelta(weeks=n),
            "month":  timedelta(days=n * 30),
            "year":   timedelta(days=n * 365),
        }
        dt = now - delta_map.get(unit, timedelta(0))
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), m.group(0)

    if _TODAY_RE.search(text):
        return now.strftime("%Y-%m-%dT%H:%M:%SZ"), "Today"
    if _YESTERDAY_RE.search(text):
        dt = now - timedelta(days=1)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "Yesterday"

    return "", text


def _canonical_url(href: str) -> str:
    """Turn a relative Bayt path into a full canonical URL."""
    if href.startswith("http"):
        try:
            p = urlparse(href)
            return urlunparse((p.scheme, p.netloc, p.path, "", "", "")).rstrip("/")
        except Exception:
            return href
    return (_BASE + href).rstrip("/")


def _url_id(url: str) -> str:
    return hashlib.sha256(url.lower().encode()).hexdigest()[:16]


def scrape_bayt(
    keyword: str,
    location: str = "United Arab Emirates",
    max_results: int = 25,
    max_pages: int = 3,
) -> list[dict]:
    """
    Scrape Bayt.com for jobs matching keyword in UAE.

    Returns a list of job dicts in the same shape as linkedin.py / adzuna.py.
    Returns [] if Cloudflare blocks the request, BS4 is unavailable, or no
    results are found.
    """
    if not _BS4:
        print("[Bayt] beautifulsoup4 not installed — skipping (add it to requirements.txt)")
        return []

    jobs: list[dict] = []
    seen: set[str]   = set()
    page = 1

    while page <= max_pages and len(jobs) < max_results:
        params: dict = {"q": keyword, "sfc": "1"}   # sfc=1 → sort by freshness
        if page > 1:
            params["p"] = page

        try:
            resp = requests.get(
                _SEARCH,
                params=params,
                headers=_HEADERS,
                timeout=20,
            )
        except Exception as exc:
            print(f"[Bayt] Request error (page {page}): {exc}")
            break

        if resp.status_code in (403, 429, 503):
            print(f"[Bayt] HTTP {resp.status_code} — likely Cloudflare/rate-limit block")
            break
        if resp.status_code != 200:
            print(f"[Bayt] HTTP {resp.status_code}")
            break

        soup = BeautifulSoup(resp.text, "html.parser")

        # Primary selector: <li data-job-id="..."> (Bayt marks every job card this way)
        cards = soup.find_all("li", attrs={"data-job-id": True})
        if not cards:
            # Fallback: any element with data-job-id
            cards = soup.find_all(attrs={"data-job-id": True})

        if not cards:
            print(
                f"[Bayt] No job cards on page {page} for '{keyword}' — "
                "possibly blocked or HTML structure changed"
            )
            break

        page_count = 0
        for card in cards:
            job_id = str(card.get("data-job-id", "")).strip()
            if not job_id or job_id in seen:
                continue

            # ── Title + URL ──────────────────────────────────────────────────
            title_tag = (
                card.find("h2", class_=re.compile(r"jb-title", re.I))
                or card.find("h2")
            )
            if not title_tag:
                continue
            link = title_tag.find("a")
            if not link:
                continue
            title = (link.get_text(strip=True) or link.get("title", "")).strip()
            href  = link.get("href", "")
            if not title or not href:
                continue

            url = _canonical_url(href)

            # ── Company ──────────────────────────────────────────────────────
            company_tag = (
                card.find(class_=re.compile(r"jb-company", re.I))
                or card.find(itemprop="hiringOrganization")
                or card.find("b", itemprop="name")
            )
            company = company_tag.get_text(strip=True) if company_tag else ""

            # ── Location ─────────────────────────────────────────────────────
            loc_tag = (
                card.find(class_=re.compile(r"jb-location", re.I))
                or card.find(itemprop="addressLocality")
                or card.find(class_=re.compile(r"location", re.I))
            )
            loc = loc_tag.get_text(strip=True) if loc_tag else location

            # ── Posted date ──────────────────────────────────────────────────
            date_tag = (
                card.find(class_=re.compile(r"jb-date", re.I))
                or card.find("time")
                or card.find(itemprop="datePosted")
                or card.find(class_=re.compile(r"date", re.I))
            )
            date_raw = date_tag.get_text(strip=True) if date_tag else ""
            posted_iso, posted_text = _parse_age(date_raw)

            seen.add(job_id)
            jobs.append({
                "Id":         job_id,
                "Keyword":    keyword,
                "Title":      title,
                "Company":    company,
                "Location":   loc or location,
                "Url":        url,
                "PostedDate": posted_iso,
                "PostedText": posted_text,
                "IsApplied":  False,
                "Source":     "Bayt",
            })
            page_count += 1

            if len(jobs) >= max_results:
                break

        print(f"[Bayt] Page {page}: {page_count} job(s) for '{keyword}'")
        if page_count == 0:
            break

        page += 1
        if page <= max_pages and len(jobs) < max_results:
            time.sleep(1.5)   # polite delay between pages

    return jobs
