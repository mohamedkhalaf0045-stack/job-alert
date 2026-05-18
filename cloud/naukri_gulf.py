"""
NaukriGulf.com job scraper — major job board for the Gulf/UAE region.
Parses the HTML search results page (no API key required).
Falls back gracefully if blocked or if beautifulsoup4 is unavailable.
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse, quote_plus

import requests

try:
    from bs4 import BeautifulSoup
    _BS4 = True
except ImportError:
    _BS4 = False

_BASE   = "https://www.naukrigulf.com"
_SEARCH = "https://www.naukrigulf.com/it-jobs-in-uae"   # base; overridden per keyword

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
    "Accept-Language":         "en-US,en;q=0.9",
    "Accept-Encoding":         "gzip, deflate, br",
    "Referer":                 "https://www.google.com/",
    "DNT":                     "1",
    "Upgrade-Insecure-Requests": "1",
}

_AGO_RE       = re.compile(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", re.I)
_TODAY_RE     = re.compile(r"\b(just\s+now|today|new|fresh)\b",  re.I)
_YESTERDAY_RE = re.compile(r"\byesterday\b",                       re.I)


def _parse_age(text: str) -> tuple[str, str]:
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
        return (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), "Yesterday"
    return "", text


def _canonical_url(href: str) -> str:
    if href.startswith("http"):
        try:
            p = urlparse(href)
            return urlunparse((p.scheme, p.netloc, p.path, "", "", "")).rstrip("/")
        except Exception:
            return href
    return (_BASE + href).rstrip("/")


def _url_id(url: str) -> str:
    return hashlib.sha256(url.lower().encode()).hexdigest()[:16]


def _build_url(keyword: str) -> str:
    """Build NaukriGulf search URL for keyword in UAE.
    NaukriGulf uses slugified keyword in the path: /it-support-jobs-in-uae"""
    slug = re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")
    return f"{_BASE}/{slug}-jobs-in-united-arab-emirates"


def scrape_naukri_gulf(
    keyword: str,
    location: str = "United Arab Emirates",
    max_results: int = 25,
    max_pages: int = 3,
) -> list[dict]:
    """
    Scrape NaukriGulf.com for jobs matching keyword in UAE.
    Returns [] if blocked or BS4 unavailable.
    """
    if not _BS4:
        print("[NaukriGulf] beautifulsoup4 not installed — skipping")
        return []

    jobs: list[dict] = []
    seen: set[str]   = set()
    base_url = _build_url(keyword)
    page = 1

    while page <= max_pages and len(jobs) < max_results:
        # NaukriGulf pagination: append -N to the path for page N
        url = base_url if page == 1 else f"{base_url}-{page}"

        try:
            resp = requests.get(url, headers=_HEADERS, timeout=20)
        except Exception as exc:
            print(f"[NaukriGulf] Request error (page {page}): {exc}")
            break

        if resp.status_code in (403, 404, 429, 503):
            print(f"[NaukriGulf] HTTP {resp.status_code} for {url}")
            break
        if resp.status_code != 200:
            print(f"[NaukriGulf] HTTP {resp.status_code}")
            break

        soup = BeautifulSoup(resp.text, "html.parser")

        # NaukriGulf job cards: <article class="job-listing ..."> or similar
        cards = (
            soup.find_all("article", class_=re.compile(r"job", re.I)) or
            soup.find_all("div",     class_=re.compile(r"job[\-_]listing|job[\-_]card|job[\-_]item", re.I)) or
            soup.find_all("li",      class_=re.compile(r"job", re.I))
        )

        if not cards:
            print(
                f"[NaukriGulf] No job cards on page {page} for '{keyword}' — "
                "possibly blocked or HTML structure changed"
            )
            break

        page_count = 0
        for card in cards:
            # Title + URL: look for the main job link
            link = (
                card.find("a", class_=re.compile(r"title|heading|designation|name", re.I))
                or card.find("a", href=re.compile(r"/job-listings|/jobs/|/\d{6,}", re.I))
            )
            if not link:
                h = card.find(["h2", "h3"])
                link = h.find("a") if h else None
            if not link:
                continue

            title = (link.get_text(strip=True) or link.get("title", "")).strip()
            href  = link.get("href", "")
            if not title or not href or len(title) < 4:
                continue

            job_url = _canonical_url(href)
            uid     = _url_id(job_url)
            if uid in seen:
                continue

            # Company
            co_tag = card.find(class_=re.compile(r"company|employer|org|client", re.I))
            company = co_tag.get_text(strip=True) if co_tag else ""

            # Location
            loc_tag = card.find(class_=re.compile(r"location|city|area", re.I))
            loc = loc_tag.get_text(strip=True) if loc_tag else location

            # Date
            date_tag = (
                card.find("time")
                or card.find(class_=re.compile(r"date|posted|freshness|age", re.I))
            )
            date_raw = date_tag.get_text(strip=True) if date_tag else ""
            posted_iso, posted_text = _parse_age(date_raw)

            seen.add(uid)
            jobs.append({
                "Id":         uid,
                "Keyword":    keyword,
                "Title":      title,
                "Company":    company,
                "Location":   loc or location,
                "Url":        job_url,
                "PostedDate": posted_iso,
                "PostedText": posted_text,
                "IsApplied":  False,
                "Source":     "NaukriGulf",
            })
            page_count += 1

            if len(jobs) >= max_results:
                break

        print(f"[NaukriGulf] Page {page}: {page_count} job(s) for '{keyword}'")
        if page_count == 0:
            break

        page += 1
        if page <= max_pages and len(jobs) < max_results:
            time.sleep(1.5)

    return jobs
