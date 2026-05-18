"""
GulfTalent.com job scraper — one of the top 3 job boards in UAE/Gulf.
Parses the HTML search results page (no API key required).
Falls back gracefully if blocked or if beautifulsoup4 is unavailable.
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse, quote

import requests

try:
    from bs4 import BeautifulSoup
    _BS4 = True
except ImportError:
    _BS4 = False

_BASE   = "https://www.gulftalent.com"
_SEARCH = "https://www.gulftalent.com/jobs"

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
_TODAY_RE     = re.compile(r"\b(just\s+now|today|new)\b", re.I)
_YESTERDAY_RE = re.compile(r"\byesterday\b", re.I)


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


def scrape_gulftalent(
    keyword: str,
    location: str = "United Arab Emirates",
    max_results: int = 25,
    max_pages: int = 3,
) -> list[dict]:
    """
    Scrape GulfTalent.com for jobs matching keyword in UAE.
    Returns [] if blocked or BS4 unavailable.
    """
    if not _BS4:
        print("[GulfTalent] beautifulsoup4 not installed — skipping")
        return []

    jobs: list[dict] = []
    seen: set[str]   = set()
    page = 1

    while page <= max_pages and len(jobs) < max_results:
        params: dict = {
            "keywords": keyword,
            "country":  "UAE",
            "sort":     "date",     # newest first
        }
        if page > 1:
            params["page"] = page

        try:
            resp = requests.get(
                _SEARCH,
                params=params,
                headers=_HEADERS,
                timeout=20,
            )
        except Exception as exc:
            print(f"[GulfTalent] Request error (page {page}): {exc}")
            break

        if resp.status_code in (403, 429, 503):
            print(f"[GulfTalent] HTTP {resp.status_code} — likely blocked")
            break
        if resp.status_code != 200:
            print(f"[GulfTalent] HTTP {resp.status_code}")
            break

        soup = BeautifulSoup(resp.text, "html.parser")

        # GulfTalent job cards: <div class="job ..."> or <article class="job-...">
        cards = (
            soup.find_all("div",     class_=re.compile(r"\bjob[\-_]", re.I)) or
            soup.find_all("article", class_=re.compile(r"\bjob",      re.I)) or
            soup.find_all("li",      class_=re.compile(r"\bjob",      re.I))
        )

        if not cards:
            print(
                f"[GulfTalent] No job cards on page {page} for '{keyword}' — "
                "possibly blocked or HTML structure changed"
            )
            break

        page_count = 0
        for card in cards:
            # Title + URL
            link = (
                card.find("a", class_=re.compile(r"title|heading|name", re.I))
                or card.find("h2", recursive=True)
                and card.find("h2").find("a")
                or card.find("h3", recursive=True)
                and card.find("h3").find("a")
                or card.find("a", href=re.compile(r"/job/|/jobs/", re.I))
            )
            if not link or not isinstance(link, object):
                continue
            if hasattr(link, "name") and link.name != "a":
                link = link.find("a")
            if not link:
                continue

            title = (link.get_text(strip=True) or link.get("title", "")).strip()
            href  = link.get("href", "")
            if not title or not href or len(title) < 4:
                continue

            url    = _canonical_url(href)
            url_id = _url_id(url)
            if url_id in seen:
                continue

            # Company
            company_tag = card.find(class_=re.compile(r"company|employer|org", re.I))
            company = company_tag.get_text(strip=True) if company_tag else ""

            # Location
            loc_tag = card.find(class_=re.compile(r"location|city|country", re.I))
            loc = loc_tag.get_text(strip=True) if loc_tag else location

            # Date
            date_tag = (
                card.find("time")
                or card.find(class_=re.compile(r"date|posted|ago", re.I))
            )
            date_raw = date_tag.get_text(strip=True) if date_tag else ""
            posted_iso, posted_text = _parse_age(date_raw)

            seen.add(url_id)
            jobs.append({
                "Id":         url_id,
                "Keyword":    keyword,
                "Title":      title,
                "Company":    company,
                "Location":   loc or location,
                "Url":        url,
                "PostedDate": posted_iso,
                "PostedText": posted_text,
                "IsApplied":  False,
                "Source":     "GulfTalent",
            })
            page_count += 1

            if len(jobs) >= max_results:
                break

        print(f"[GulfTalent] Page {page}: {page_count} job(s) for '{keyword}'")
        if page_count == 0:
            break

        page += 1
        if page <= max_pages and len(jobs) < max_results:
            time.sleep(1.5)

    return jobs
