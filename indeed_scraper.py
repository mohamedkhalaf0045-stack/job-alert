"""
Indeed job scraper using Playwright.
Called by the PowerShell worker as a subprocess.
Outputs a JSON array of job objects to stdout.

Install:
    pip install playwright playwright-stealth
    playwright install chromium

Usage:
    python indeed_scraper.py --keyword "IT support" --location "United Arab Emirates" --max-hours 24
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import re

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print(json.dumps({"error": "playwright not installed. Run: pip install playwright && playwright install chromium"}))
    sys.exit(1)

try:
    from playwright_stealth import stealth_sync
    _HAS_STEALTH = True
except ImportError:
    _HAS_STEALTH = False

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


def _get_base_url(location: str) -> str:
    loc = location.lower().strip()
    for key, code in _COUNTRY_DOMAINS.items():
        if key in loc or loc == key:
            return f"https://{code}.indeed.com/jobs"
    return "https://www.indeed.com/jobs"


def _max_hours_to_fromage(max_hours: int) -> int | None:
    if max_hours <= 168:   # up to 1 week → use 1 day or 7 days
        return 1 if max_hours <= 24 else 7
    if max_hours <= 720:
        return 30
    return None


def _extract_age_from_page(page_html: str) -> dict[str, str]:
    """Return {jk: age_text} extracted from embedded JSON state."""
    age_map: dict[str, str] = {}
    for m in re.finditer(r'"jobKey"\s*:\s*"([^"]+)"', page_html):
        jk = m.group(1)
        snippet = page_html[m.start(): m.start() + 600]
        age_m = re.search(r'"age"\s*:\s*"([^"]+)"', snippet)
        if age_m:
            age_map[jk] = age_m.group(1)
    return age_map


def _clean(text: str | None) -> str:
    return (text or "").strip()


def scrape_indeed(keyword: str, location: str, max_pages: int = 2, max_hours: int = 24) -> list:
    jobs: list[dict] = []
    seen_ids: set[str] = set()

    base_url = _get_base_url(location)
    fromage  = _max_hours_to_fromage(max_hours)

    with sync_playwright() as p:
        browser = None
        for launch_kwargs in (
            {"channel": "chrome",  "headless": True},
            {"channel": "msedge",  "headless": True},
            {"headless": True},
        ):
            try:
                browser = p.chromium.launch(**launch_kwargs)
                break
            except Exception:
                continue

        if browser is None:
            raise RuntimeError("Could not launch any browser. Run: playwright install chromium")

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="Asia/Dubai",
        )

        page = context.new_page()
        if _HAS_STEALTH:
            stealth_sync(page)

        for page_num in range(max_pages):
            start = page_num * 10
            url   = f"{base_url}?q={keyword}&sort=date&start={start}"
            if fromage:
                url += f"&fromage={fromage}"

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_selector(".job_seen_beacon, [data-jk]", timeout=10_000)
            except PWTimeout:
                break
            except Exception:
                break

            time.sleep(1.5)

            page_html = page.content()
            age_map   = _extract_age_from_page(page_html)

            # .job_seen_beacon is the full card container; [data-jk] is only the <a> anchor
            cards = page.query_selector_all(".job_seen_beacon")
            if not cards:
                break

            for card in cards:
                link_el = card.query_selector("a[data-jk]")
                if not link_el:
                    continue
                jk = link_el.get_attribute("data-jk")
                if not jk or jk in seen_ids:
                    continue
                seen_ids.add(jk)

                title_el   = card.query_selector(".jobTitle span[title], .jobTitle span, a[data-jk] span")
                company_el = card.query_selector('[data-testid="company-name"]')
                loc_el     = card.query_selector('[data-testid="text-location"]')

                title   = _clean(title_el.inner_text()   if title_el   else None)
                company = _clean(company_el.inner_text() if company_el else None)
                loc     = _clean(loc_el.inner_text()     if loc_el     else location)

                if not title:
                    continue

                # Use extracted age if available, otherwise fall back to "Just posted"
                # (safe since we already filtered by fromage at the URL level)
                posted = age_map.get(jk, "Just posted")

                jobs.append({
                    "Id":         f"indeed-{jk}",
                    "Keyword":    keyword,
                    "Title":      title,
                    "Company":    company,
                    "Location":   loc,
                    "Url":        f"https://ae.indeed.com/viewjob?jk={jk}",
                    "PostedDate": "",
                    "PostedText": posted,
                    "IsApplied":  False,
                    "Source":     "Indeed",
                })

        browser.close()

    return jobs


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword",   required=True)
    parser.add_argument("--location",  required=True)
    parser.add_argument("--pages",     type=int, default=2)
    parser.add_argument("--max-hours", type=int, default=24, dest="max_hours")
    args = parser.parse_args()

    try:
        results = scrape_indeed(args.keyword, args.location, args.pages, args.max_hours)
        print(json.dumps(results, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
