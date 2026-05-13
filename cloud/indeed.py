"""
Indeed job scraper — uses Indeed's public RSS feed.
RSS is freely available, not blocked by Cloudflare, and returns clean job data.
Returns a list of job dicts in the same shape as linkedin.py.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse

import requests

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
})

_COUNTRY_DOMAINS: dict[str, str] = {
    "united arab emirates": "ae",
    "uae": "ae",
    "dubai": "ae",
    "abu dhabi": "ae",
    "sharjah": "ae",
    "ajman": "ae",
    "saudi arabia": "sa",
    "egypt": "eg",
    "qatar": "qa",
    "kuwait": "kw",
    "bahrain": "bh",
    "oman": "om",
    "jordan": "jo",
    "united kingdom": "uk",
    "uk": "uk",
    "canada": "ca",
    "australia": "au",
    "india": "in",
    "germany": "de",
    "france": "fr",
    "singapore": "sg",
    "malaysia": "my",
}


def _get_domain(location: str) -> str:
    loc = location.lower().strip()
    for key, code in _COUNTRY_DOMAINS.items():
        if key in loc or loc == key:
            return f"{code}.indeed.com"
    return "www.indeed.com"


def _rss_url(keyword: str, location: str, fromage: int) -> str:
    domain = _get_domain(location)
    q = quote(keyword)
    l = quote(location)
    return f"https://{domain}/rss?q={q}&l={l}&fromage={fromage}&sort=date"


def _plain_text(value: str) -> str:
    import html
    decoded = html.unescape(value or "")
    stripped = re.sub(r"<.*?>", " ", decoded, flags=re.DOTALL)
    return re.sub(r"\s+", " ", stripped).strip()


def _fetch(url: str) -> str | None:
    try:
        resp = _SESSION.get(url, timeout=20)
        if resp.status_code == 429:
            print(f"[Indeed] Rate limited: {url}")
            return None
        if resp.status_code != 200:
            print(f"[Indeed] HTTP {resp.status_code}: {url}")
            return None
        return resp.text
    except requests.RequestException as exc:
        print(f"[Indeed] Request error: {exc}")
        return None


def _get_age_hours(job: dict) -> float:
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
        try:
            dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)
        except ValueError:
            pass
    return float("inf")


def _parse_rss(xml_text: str, keyword: str) -> list[dict]:
    print(f"[Indeed] RSS response: {len(xml_text)} chars")
    jobs = []

    for item in re.finditer(r"<item>(.*?)</item>", xml_text, re.DOTALL):
        chunk = item.group(1)

        # Title — may be CDATA-wrapped
        title_m = (
            re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>", chunk, re.DOTALL) or
            re.search(r"<title>(.*?)</title>", chunk, re.DOTALL)
        )
        # Link — try <link> then <guid>
        link_m = (
            re.search(r"<link>\s*(https?://[^\s<]+)", chunk) or
            re.search(r"<guid[^>]*>\s*(https?://[^\s<]+)", chunk, re.DOTALL)
        )
        pub_m = re.search(r"<pubDate>(.*?)</pubDate>", chunk, re.DOTALL)

        if not title_m or not link_m:
            continue

        raw_title = (title_m.group(1) or "").strip()
        raw_link  = (link_m.group(1) or "").strip()

        if not raw_link:
            continue

        # Job key from URL (jk=abc123)
        jk_m = re.search(r"[?&]jk=([a-zA-Z0-9]+)", raw_link)
        job_id = f"indeed-{jk_m.group(1)}" if jk_m else raw_link

        # Company: last " - Company Name" segment of the title
        company = ""
        title    = raw_title
        if " - " in raw_title:
            parts = raw_title.rsplit(" - ", 1)
            title   = parts[0].strip()
            company = _plain_text(parts[1])

        # Clean URL — keep only the essential jk parameter to normalize across campaigns
        if jk_m:
            domain = _get_domain("")  # fallback; use URL's own domain
            try:
                p = urlparse(raw_link)
                clean_url = f"{p.scheme}://{p.netloc}/viewjob?jk={jk_m.group(1)}"
            except Exception:
                clean_url = raw_link
        else:
            clean_url = raw_link

        # Posted date from pubDate (RFC 2822 format)
        posted_date = ""
        posted_text = ""
        if pub_m:
            try:
                dt = parsedate_to_datetime(pub_m.group(1).strip())
                posted_date = dt.strftime("%Y-%m-%d")
                delta = datetime.now(timezone.utc) - dt
                hours = delta.total_seconds() / 3600
                days  = int(hours / 24)
                if hours < 2:
                    posted_text = "Just posted"
                elif hours < 24:
                    h = int(hours)
                    posted_text = f"{h} hour{'s' if h != 1 else ''} ago"
                elif days == 1:
                    posted_text = "1 day ago"
                else:
                    posted_text = f"{days} days ago"
            except Exception:
                pass

        jobs.append({
            "Id":         job_id,
            "Keyword":    keyword,
            "Title":      _plain_text(title),
            "Company":    company,
            "Location":   "",
            "Url":        clean_url,
            "PostedDate": posted_date,
            "PostedText": posted_text,
            "IsApplied":  False,
            "Source":     "Indeed",
        })

    return jobs


def scrape_indeed(keyword: str, location: str, max_hours: int = 24) -> list[dict]:
    """
    Scrape Indeed via RSS feed (no browser, no Cloudflare bot detection).
    Returns job dicts filtered to max_hours age.
    """
    # fromage=3 covers 3 days; we filter by actual age ourselves
    fromage = 7 if max_hours > 48 else 3
    url = _rss_url(keyword, location, fromage)
    print(f"[Indeed] Fetching RSS: {url}")

    xml_text = _fetch(url)
    if xml_text is None:
        return []

    jobs = _parse_rss(xml_text, keyword)

    filtered = [j for j in jobs if _get_age_hours(j) <= max_hours]
    print(f"[Indeed] '{keyword}': {len(jobs)} total, {len(filtered)} within {max_hours}h")
    return filtered
