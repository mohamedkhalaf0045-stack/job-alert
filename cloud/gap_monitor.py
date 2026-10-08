"""
Gap monitor: finds jobs that reached us late and explains why.

A job whose only source is a Gmail alert email (`Gmail/*`) was never seen by
the direct LinkedIn scan, otherwise it would have been stored under `LinkedIn`
first. So every late Gmail job is a discovery gap. For each one we classify:

  keyword_gap   - no configured scan keyword relates to the job title
  probe_blocked - LinkedIn returned nothing for any probe (datacenter block)
  search_miss   - searching the exact title with a 72h window did not list it
  ranking_miss  - the title search lists it, so the scan's limits/timing missed it

Also reports per-source median lag for the window. Telegram-notifies a short
report (only when gaps exist, unless --always) and stores the last report in
bot_state[gap_monitor_last].

Usage: python cloud/gap_monitor.py [--hours 26] [--min-lag 6] [--probe 8] [--always] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

import db
import linkedin
import telegram_notify


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip().lstrip("﻿")


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9+#]+", (text or "").lower()) if len(t) > 2}


def _load_keywords(url: str, key: str) -> list[str]:
    kws: list[str] = []
    raw = db.get_config(url, key, "setting_keywords", "")
    kws += [k.strip() for k in raw.split(",") if k.strip()]
    try:
        for p in db.get_active_profiles(url, key):
            kws += [k.strip() for k in (p.get("keywords") or []) if k.strip()]
    except Exception as exc:  # noqa: BLE001
        print(f"[Gap] could not load profile keywords: {exc}")
    return sorted(set(kws), key=str.lower)


def _keyword_covers(title: str, keywords: list[str]) -> str:
    """Return the keyword that genuinely covers the title, else "".

    A keyword covers a title when all of its meaningful words (3+ chars) appear
    as whole words in the title. Keywords with no meaningful words (e.g. "IT")
    never cover anything - they used to match inside words like "Specialist".
    """
    tt = _tokens(title)
    best = ""
    for kw in keywords:
        kt = _tokens(kw)
        if kt and kt <= tt and len(kt) > len(_tokens(best)):
            best = kw
    return best


def _job_id(row: dict) -> str:
    m = re.search(r"(\d{6,})", row.get("job_id") or row.get("url") or "")
    return m.group(1) if m else ""


def _probe(row: dict, cookie: str) -> tuple[str, list[str]]:
    """Return (found|absent|blocked, notes)."""
    jid = _job_id(row)
    try:
        jobs = linkedin.scrape_linkedin(
            row["title"], row.get("location") or "", cookie_header=cookie,
            max_pages=4, max_hours=72, sort_recent=True,
        )
    except Exception as exc:  # noqa: BLE001
        return "blocked", [f"probe error: {exc}"]
    if not jobs:
        return "blocked", ["probe returned 0 jobs"]
    ids = {_job_id({"url": j.get("Url", "") or j.get("url", "")}) for j in jobs}
    return ("found" if jid in ids else "absent"), [f"probe saw {len(jobs)} jobs"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=26)
    ap.add_argument("--min-lag", type=float, default=6.0)
    ap.add_argument("--probe", type=int, default=15, help="max jobs to live-probe")
    ap.add_argument("--always", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    url, key = _env("SUPABASE_URL"), _env("SUPABASE_KEY")
    if not url or not key:
        print("SUPABASE_URL / SUPABASE_KEY not set")
        return 1
    sb = db._get_client(url, key)

    since = (datetime.now(timezone.utc) - timedelta(hours=a.hours)).isoformat()
    rows = (
        sb.table("jobs")
        .select("job_id,title,company,location,url,source,date_posted,date_collected")
        .gte("date_collected", since)
        .not_.is_("date_posted", "null")
        .execute()
        .data
    )

    def lag(r: dict) -> float:
        p = datetime.fromisoformat(r["date_posted"].replace("Z", "+00:00"))
        c = datetime.fromisoformat(r["date_collected"].replace("Z", "+00:00"))
        return (c - p).total_seconds() / 3600

    by_src: dict[str, list[float]] = {}
    for r in rows:
        by_src.setdefault(r["source"], []).append(lag(r))
    lag_lines = [
        f"• {s}: {len(v)} jobs, median lag {statistics.median(v):.1f}h"
        for s, v in sorted(by_src.items(), key=lambda kv: -len(kv[1]))
    ]

    gaps = [r for r in rows if r["source"].startswith("Gmail/") and lag(r) >= a.min_lag]
    gaps.sort(key=lag, reverse=True)
    keywords = _load_keywords(url, key)
    cookie = _env("LINKEDIN_COOKIE")

    findings = []
    for i, r in enumerate(gaps):
        cov = _keyword_covers(r["title"], keywords)
        notes: list[str] = []
        if not cov:
            verdict = "keyword_gap"
        elif i < a.probe:
            state, notes = _probe(r, cookie)
            verdict = {"blocked": "probe_blocked", "absent": "search_miss",
                       "found": "ranking_miss"}[state]
        else:
            verdict = "unprobed"
        findings.append({
            "job_id": _job_id(r), "title": r["title"], "company": r["company"],
            "lag_h": round(lag(r), 1), "matched_keyword": cov, "verdict": verdict,
            "notes": notes, "url": r["url"],
        })

    counts: dict[str, int] = {}
    for f in findings:
        counts[f["verdict"]] = counts.get(f["verdict"], 0) + 1

    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "window_h": a.hours, "gaps": len(findings), "verdicts": counts, "findings": findings,
    }
    print(json.dumps(report, indent=2)[:6000])

    hints = {
        "keyword_gap": "add a keyword covering these titles",
        "probe_blocked": "LinkedIn blocked the probe (datacenter IP) — run scan from home IP/proxy",
        "search_miss": "LinkedIn search itself doesn't list them promptly (indexing delay)",
        "ranking_miss": "keyword exists but scan missed it — raise pages/frequency",
        "unprobed": "keyword exists; not probed (cap)",
    }
    lines = [f"🕳️ Gap monitor — last {a.hours}h", *lag_lines, ""]
    if findings:
        lines.append(f"{len(findings)} job(s) found only via email, ≥{a.min_lag:g}h late:")
        for v, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"• {n} × {v}: {hints.get(v, '')}")
        lines.append("")
        for f in findings[:5]:
            lines.append(f"{f['lag_h']}h · {f['title']} — {f['company']} [{f['verdict']}]")
            lines.append(f["url"])
    else:
        lines.append("No late email-only jobs. ✅")
    text = "\n".join(lines)

    if a.dry_run:
        print(text)
        return 0
    try:
        db.set_config(url, key, "gap_monitor_last", json.dumps(report)[:20000])
    except Exception as exc:  # noqa: BLE001
        print(f"[Gap] could not store report: {exc}")
    if findings or a.always:
        telegram_notify.send_message(_env("TELEGRAM_BOT_TOKEN"), _env("TELEGRAM_CHAT_ID"), text[:3900])
    return 0


if __name__ == "__main__":
    sys.exit(main())
