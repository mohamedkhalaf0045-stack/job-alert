"""
Indeed job scraper — Playwright HTML scraper.

Indeed's RSS feed returns 403 on all domains as of 2024 (Cloudflare Bot
Management blocks plain requests).  This module uses a headless Chromium
browser (via Playwright) to render the /jobs search page and extracts job
data from the DOM.

No API key required.  Playwright + Chromium is the only extra dependency:
    pip install playwright
    python -m playwright install chromium

Returns a list of job dicts in the same shape as linkedin.py / bayt.py.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

# ---------------------------------------------------------------------------
# Country → Indeed subdomain map (same as old RSS scraper)
# ---------------------------------------------------------------------------

_COUNTRY_DOMAINS: dict[str, str] = {
    "united arab emirates": "ae",
    "uae":                  "ae",
    "dubai":                "ae",
    "abu dhabi":            "ae",
    "sharjah":              "ae",
    "ajman":                "ae",
    "saudi arabia":         "sa",
    "egypt":                "eg",
    "qatar":                "qa",
    "kuwait":               "kw",
    "bahrain":              "bh",
    "oman":                 "om",
    "jordan":               "jo",
    "united kingdom":       "uk",
    "uk":                   "uk",
    "canada":               "ca",
    "australia":            "au",
    "india":                "in",
    "germany":              "de",
    "france":               "fr",
    "singapore":            "sg",
    "malaysia":             "my",
}


def _get_domain(location: str) -> str:
    loc = location.lower().strip()
    for key, code in _COUNTRY_DOMAINS.items():
        if key in loc or loc == key:
            return f"{code}.indeed.com"
    return "www.indeed.com"


def _search_url(keyword: str, location: str, start: int = 0, fromage: int = 3) -> str:
    domain = _get_domain(location)
    params: dict[str, str] = {
        "q":       keyword,
        "l":       location,
        "sort":    "date",
        "fromage": str(fromage),
    }
    if start:
        params["start"] = str(start)
    return f"https://{domain}/jobs?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Age parsing
# ---------------------------------------------------------------------------

def _hours_ago(text: str) -> float:
    """Convert Indeed relative time strings to hours.

    Examples: "Just posted" → 0.5, "3 hours ago" → 3.0, "2 days ago" → 48.0
    """
    if not text:
        return float("inf")
    t = text.lower().strip()
    if any(k in t for k in ("just posted", "just now", "active today", "today")):
        return 0.5
    m = re.search(r"(\d+)\s*minute", t)
    if m:
        return float(m.group(1)) / 60
    m = re.search(r"(\d+)\s*hour", t)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+)\s*day", t)
    if m:
        return float(m.group(1)) * 24
    m = re.search(r"(\d+)\s*week", t)
    if m:
        return float(m.group(1)) * 168
    return float("inf")


# ---------------------------------------------------------------------------
# Playwright page scraper
# ---------------------------------------------------------------------------

# JavaScript that runs inside the browser to extract job card data from the DOM.
# Indeed's rendered HTML has:
#   - [data-jk]              → job key on the title anchor
#   - aria-label             → "full details of TITLE"
#   - [data-testid=company-name]  → company name
#   - [data-testid=text-location] → location
#   - date text (days/hours ago)  → closest span with age text
_EXTRACT_JS = """
() => {
    const results = [];
    const seen = new Set();

    document.querySelectorAll("[data-jk]").forEach(el => {
        const jk = el.getAttribute("data-jk");
        if (!jk || seen.has(jk)) return;
        seen.add(jk);

        // Title: prefer aria-label, strip "full details of " prefix
        const ariaLabel  = el.getAttribute("aria-label") || "";
        const title      = ariaLabel.replace(/^full details of /i, "").trim()
                        || (el.querySelector("span[title]") || {}).title
                        || (el.querySelector("span")        || {}).innerText
                        || "";

        // Walk up to find the card <li> or beacon div
        const card = el.closest("li")
                  || el.closest("div.job_seen_beacon")
                  || el.closest("[class*=cardOutline]")
                  || el.parentElement;

        let company  = "";
        let location = "";
        let dateText = "";

        if (card) {
            const compEl = card.querySelector("[data-testid=company-name]");
            const locEl  = card.querySelector("[data-testid=text-location]");
            company  = compEl ? compEl.innerText.trim() : "";
            location = locEl  ? locEl.innerText.trim()  : "";

            // Date: look for elements whose text matches age patterns
            card.querySelectorAll("span, div").forEach(span => {
                const txt = span.innerText || "";
                if (/just posted|\\d+\\s*(minute|hour|day|week)s?\\s*ago/i.test(txt) && !dateText) {
                    dateText = txt.trim();
                }
            });
        }

        results.push({ jk, title, company, location, dateText });
    });

    return results;
}
"""


def _scrape_page(keyword: str, location: str, domain: str,
                 page, max_hours: int) -> list[dict]:
    """Extract job dicts from an already-loaded Playwright page."""
    raw: list[dict] = page.evaluate(_EXTRACT_JS)

    now = datetime.now(timezone.utc)
    jobs: list[dict] = []

    for r in raw:
        jk       = (r.get("jk") or "").strip()
        title    = (r.get("title") or "").strip()
        company  = (r.get("company") or "").strip()
        loc_str  = (r.get("location") or "").strip()
        age_text = (r.get("dateText") or "").strip()

        if not jk or not title:
            continue

        age = _hours_ago(age_text)
        # Indeed cards don't always surface the posting date in the DOM;
        # the `fromage` URL parameter already pre-filters by age at Indeed's
        # end.  Only hard-reject when we have an explicit age AND it's stale.
        if age != float("inf") and age > max_hours:
            continue

        if age != float("inf"):
            posted_dt = now - timedelta(hours=max(age, 0))
        else:
            posted_dt = now   # unknown age — treat as today (fromage covers this)
        posted_date = posted_dt.strftime("%Y-%m-%d")
        job_url     = f"https://{domain}/viewjob?jk={jk}"

        jobs.append({
            "Id":         f"indeed-{jk}",
            "Keyword":    keyword,
            "Title":      title,
            "Company":    company,
            "Location":   loc_str,
            "Url":        job_url,
            "PostedDate": posted_date,
            "PostedText": age_text,
            "IsApplied":  False,
            "Source":     "Indeed",
        })

    return jobs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scrape_indeed(keyword: str, location: str, max_hours: int = 72) -> list[dict]:
    """Scrape Indeed for jobs matching *keyword* in *location*.

    Launches a headless Chromium browser via Playwright on first call (cold
    start ~3 s).  Re-uses the same browser process across keywords when called
    multiple times within the same Python process via the module-level
    ``_browser`` cache.

    Returns job dicts filtered to ``max_hours`` age.
    """
    # Indeed's Cloudflare protection blocks datacenter IPs (GitHub Actions,
    # most cloud hosts) while allowing residential IPs.  Scraping from CI just
    # burns ~20s/keyword on a block page that yields nothing.  Skip it there —
    # Indeed is collected by the local (residential) worker instead.
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        print("[Indeed] Skipped on GitHub Actions (datacenter IPs are blocked by "
              "Cloudflare). Indeed is scraped by the local residential worker.")
        return []

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "[Indeed] Playwright not installed — run: "
            "pip install playwright && python -m playwright install chromium"
        )
        return []

    fromage = 7 if max_hours > 48 else 3
    domain  = _get_domain(location)
    url     = _search_url(keyword, location, fromage=fromage)
    print(f"[Indeed] Fetching: {url}")

    all_jobs: list[dict] = []

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                viewport={"width": 1280, "height": 800},
                java_script_enabled=True,
            )
            page = ctx.new_page()

            # ── Page 1 ───────────────────────────────────────────────────────
            try:
                # Wait for DOM, not network-idle: Indeed keeps long-lived
                # analytics/websocket connections open, so "networkidle" never
                # settles on datacenter IPs (GitHub Actions) and times out.
                page.goto(url, timeout=45_000, wait_until="domcontentloaded")
                # Wait for actual job cards to render (or time out gracefully if
                # the result set is empty or the page is a block/captcha screen).
                try:
                    page.wait_for_selector("[data-jk]", timeout=20_000)
                except Exception:
                    print("[Indeed] No job cards appeared (empty results or blocked)")
            except Exception as exc:
                print(f"[Indeed] Page load error: {exc}")
                browser.close()
                return []

            page1_jobs = _scrape_page(keyword, location, domain, page, max_hours)
            all_jobs.extend(page1_jobs)
            print(f"[Indeed] Page 1: {len(page1_jobs)} job(s) within {max_hours}h")

            # ── Page 2 (optional — only if page 1 was full and we need more) ─
            # Indeed shows 15 results per page.  A second fetch keeps latency
            # reasonable while doubling coverage for active keyword periods.
            if len(page1_jobs) >= 14:
                url2 = _search_url(keyword, location, start=10, fromage=fromage)
                try:
                    time.sleep(2.0)   # polite inter-page delay
                    page.goto(url2, timeout=45_000, wait_until="domcontentloaded")
                    try:
                        page.wait_for_selector("[data-jk]", timeout=20_000)
                    except Exception:
                        pass
                    page2_jobs = _scrape_page(keyword, location, domain, page, max_hours)
                    # Deduplicate against page 1
                    seen_ids = {j["Id"] for j in all_jobs}
                    new_p2   = [j for j in page2_jobs if j["Id"] not in seen_ids]
                    all_jobs.extend(new_p2)
                    print(f"[Indeed] Page 2: {len(new_p2)} new job(s)")
                except Exception as exc:
                    print(f"[Indeed] Page 2 error (non-fatal): {exc}")

            browser.close()

    except Exception as exc:
        print(f"[Indeed] Playwright error: {exc}")
        return []

    print(f"[Indeed] '{keyword}': {len(all_jobs)} job(s) total within {max_hours}h")
    return all_jobs
