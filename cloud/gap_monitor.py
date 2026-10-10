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
import requests
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

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


_SENIORITY = {"senior", "junior", "sr", "jr", "lead", "principal", "associate", "staff"}
_BLOCKED_WORDS = {"manager", "director", "head", "vp", "chief", "intern", "trainee",
                  "fresh", "graduate", "internship"}


_ROLE_WORDS = {"engineer", "administrator", "admin", "support", "officer", "executive",
               "specialist", "analyst", "technician", "helpdesk", "desk", "architect",
               "consultant", "infrastructure", "coordinator", "supervisor"}


def _suggest_keyword(title: str) -> str:
    """Short role phrase (<=3 words ending at the role noun), or "" if unsuitable."""
    t = re.split(r"[(/|\-–,]", title or "")[0]
    words = [w for w in re.findall(r"[A-Za-z0-9+#]+", t) if w.lower() not in _SENIORITY]
    if any(w.lower() in _BLOCKED_WORDS for w in words):
        return ""
    idx = next((i for i, w in enumerate(words) if w.lower() in _ROLE_WORDS), -1)
    if idx < 0:
        return ""
    phrase = words[max(0, idx - 2): idx + 1]
    return " ".join(phrase) if len(phrase) >= 2 else ""


def _auto_add_keywords(url: str, key: str, findings: list[dict]) -> list[str]:
    """Append safe keywords for keyword_gap findings to setting_keywords."""
    raw = db.get_config(url, key, "setting_keywords", "")
    current = [k.strip() for k in raw.split(",") if k.strip()]
    exclude = [e.strip().lower() for e in
               db.get_config(url, key, "setting_exclude_keywords", "").split(",") if e.strip()]
    have = {k.lower() for k in current}
    added: list[str] = []
    for f in findings:
        if f["verdict"] != "keyword_gap":
            continue
        kw = _suggest_keyword(f["title"])
        if not kw or kw.lower() in have or any(e in kw.lower() for e in exclude):
            continue
        added.append(kw)
        have.add(kw.lower())
    if added:
        db.set_config(url, key, "setting_keywords", ",".join(current + added))
    return added


def _open_issue(report: dict, lines: list[str]) -> str:
    """Create/update one GitHub issue for problems that need a code/config fix."""
    token, repo = _env("GITHUB_TOKEN"), _env("GITHUB_REPOSITORY")
    if not token or not repo:
        return ""
    api = f"https://api.github.com/repos/{repo}/issues"
    hdr = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    title = "Gap monitor: scan is missing jobs"
    body = ("Automated report from `cloud/gap_monitor.py`.\n\n```\n" + "\n".join(lines)
            + "\n```\n\n<details><summary>JSON</summary>\n\n```json\n"
            + json.dumps(report, indent=1)[:50000] + "\n```\n</details>\n")
    try:
        existing = requests.get(api, headers=hdr, timeout=20,
                                params={"state": "open", "labels": "gap-monitor"}).json()
        if isinstance(existing, list) and existing:
            num = existing[0]["number"]
            requests.post(f"{api}/{num}/comments", headers=hdr, json={"body": body[:65000]}, timeout=20)
            return f"{existing[0]['html_url']} (updated)"
        r = requests.post(api, headers=hdr, timeout=20,
                          json={"title": title, "body": body[:65000], "labels": ["gap-monitor"]})
        return r.json().get("html_url", "") if r.status_code < 300 else ""
    except requests.RequestException as exc:
        print(f"[Gap] issue create failed: {exc}")
        return ""


def _scan_runs(hours: int) -> list[dict]:
    """Recent 'Job Alert Scan' workflow runs (needs GITHUB_TOKEN, actions: read)."""
    token, repo = _env("GITHUB_TOKEN"), _env("GITHUB_REPOSITORY")
    if not token or not repo:
        return []
    since = (datetime.now(timezone.utc) - timedelta(hours=hours + 6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        r = requests.get(
            f"https://api.github.com/repos/{repo}/actions/workflows/job-alert.yml/runs",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            params={"per_page": 100, "created": f">={since}"}, timeout=20,
        )
        runs = r.json().get("workflow_runs", []) if r.status_code == 200 else []
    except requests.RequestException:
        return []
    out = []
    for w in runs:
        out.append({
            "start": datetime.fromisoformat(w["run_started_at"].replace("Z", "+00:00")),
            "end": datetime.fromisoformat(w["updated_at"].replace("Z", "+00:00")),
            "conclusion": w.get("conclusion") or w.get("status"),
        })
    return out


def _scan_coverage(posted: datetime, collected: datetime, runs: list[dict]) -> tuple[int, str]:
    """Successful scans that finished after posting and before we got the job.

    The run that collected the job ends after `collected`, so it is excluded:
    it found the job on its first chance and is not a missed pass.
    """
    window = [x for x in runs if posted <= x["end"] < collected]
    ok = [x for x in window if x["conclusion"] == "success"]
    bad: dict[str, int] = {}
    for x in window:
        if x["conclusion"] != "success":
            bad[str(x["conclusion"])] = bad.get(str(x["conclusion"]), 0) + 1
    note = (f"{len(ok)} successful GitHub scan(s) between posting and collection"
            + (f"; others: {bad}" if bad else ""))
    return len(ok), note


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


def _linkedin_health(url: str, key: str) -> dict:
    """One LinkedIn guest search; records whether we get real results (proxy check)."""
    t0 = datetime.now(timezone.utc)
    html_text = linkedin._fetch(
        linkedin._guest_url("System Administrator", "United Arab Emirates", 0, 24),
        _env("LINKEDIN_COOKIE"), referer="https://www.linkedin.com/jobs/") or ""
    cards = len(re.findall(r"/jobs/view/", html_text))
    parsed = urlparse(linkedin._PROXY) if linkedin._PROXY else None
    proxy_info = {
        "env_len": len(linkedin._PROXY_RAW),          # 0 => secret not reaching the job
        "host": parsed.hostname if parsed else "",
        "port": parsed.port if parsed else None,
        "has_auth": bool(parsed and parsed.username),
        "egress_ip": "", "error": "",
    }
    if linkedin._PROXY:
        try:
            r = linkedin._SESSION.get("https://api.ipify.org?format=json", timeout=20)
            proxy_info["egress_ip"] = r.json().get("ip", "")
        except Exception as exc:  # noqa: BLE001
            proxy_info["error"] = type(exc).__name__ + ": " + str(exc).split("@")[-1][:200]
    res = {"at": t0.isoformat(), "proxy": bool(linkedin._PROXY), "proxy_info": proxy_info,
           "chars": len(html_text),
           "job_links": cards, "ok": cards > 0,
           "secs": round((datetime.now(timezone.utc) - t0).total_seconds(), 1)}
    try:
        db.set_config(url, key, "linkedin_health", json.dumps(res))
    except Exception as exc:  # noqa: BLE001
        print(f"[Gap] could not store linkedin_health: {exc}")
    print(f"[Gap] LinkedIn health: {res}")
    return res


def _load_handled(url: str, key: str) -> set[str]:
    try:
        return set(json.loads(db.get_config(url, key, "gap_monitor_handled", "[]")))
    except Exception:  # noqa: BLE001
        return set()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=26)
    ap.add_argument("--min-lag", type=float, default=1.0,
                    help="flag LinkedIn jobs collected more than this many hours after posting")
    ap.add_argument("--max-lag", type=float, default=72.0,
                    help="ignore LinkedIn jobs older than this at collection (re-listed old postings)")
    ap.add_argument("--probe", type=int, default=15, help="max jobs to live-probe")
    ap.add_argument("--always", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--auto-fix", action="store_true",
                    help="append safe keywords for keyword gaps; open a GitHub issue for the rest")
    a = ap.parse_args()

    url, key = _env("SUPABASE_URL"), _env("SUPABASE_KEY")
    if not url or not key:
        print("SUPABASE_URL / SUPABASE_KEY not set")
        return 1
    sb = db._get_client(url, key)
    health = _linkedin_health(url, key) if not a.dry_run else {}

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

    # Rule: any LinkedIn job we collected more than --min-lag hours after it was
    # posted is a detection failure to diagnose (direct scan or email-only).
    gaps = [r for r in rows
            if r["source"] in ("LinkedIn", "Gmail/LinkedIn")
            and a.min_lag < lag(r) <= a.max_lag]
    gaps.sort(key=lag, reverse=True)
    keywords = _load_keywords(url, key)
    cookie = _env("LINKEDIN_COOKIE")

    runs = _scan_runs(a.hours)
    findings = []
    for i, r in enumerate(gaps):
        cov = _keyword_covers(r["title"], keywords)
        notes: list[str] = []
        scans_ok = -1
        if runs:
            scans_ok, scan_note = _scan_coverage(
                datetime.fromisoformat(r["date_posted"].replace("Z", "+00:00")),
                datetime.fromisoformat(r["date_collected"].replace("Z", "+00:00")), runs)
            notes.append(scan_note)
        if r["source"] == "LinkedIn":
            # Found by our own scan, just late: either no scan ran in the window,
            # or scans ran but only caught it on a later pass.
            verdict = "scan_gap" if scans_ok == 0 else "late_pickup"
        elif not cov:
            verdict = "keyword_gap"
        elif scans_ok == 0:
            verdict = "scan_gap"   # no scan completed in the window: schedule/timeouts
        elif i < a.probe:
            state, pnotes = _probe(r, cookie)
            notes += pnotes
            verdict = {"blocked": "probe_blocked", "absent": "search_miss",
                       "found": "ranking_miss"}[state]
        else:
            verdict = "unprobed"
        findings.append({
            "job_id": _job_id(r), "title": r["title"], "company": r["company"],
            "lag_h": round(lag(r), 1), "matched_keyword": cov, "verdict": verdict,
            "notes": notes, "url": r["url"],
        })

    handled = _load_handled(url, key)
    for f in findings:
        f["new"] = f["job_id"] not in handled
    new_findings = [f for f in findings if f["new"]]

    counts: dict[str, int] = {}
    for f in new_findings:
        counts[f["verdict"]] = counts.get(f["verdict"], 0) + 1

    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "window_h": a.hours, "gaps": len(findings), "new_gaps": len(new_findings), "verdicts": counts, "findings": findings,
    }
    print(json.dumps(report, indent=2)[:6000])

    hints = {
        "keyword_gap": "add a keyword covering these titles",
        "probe_blocked": "LinkedIn blocked the probe (datacenter IP) — run scan from home IP/proxy",
        "search_miss": "LinkedIn search itself doesn't list them promptly (indexing delay)",
        "ranking_miss": "keyword exists but scan missed it — raise pages/frequency",
        "late_pickup": "our scan found it, but only on a later pass (cadence / ordering)",
        "scan_gap": "no GitHub scan completed between posting and collection (schedule throttled / timeouts)",
        "unprobed": "keyword exists; not probed (cap)",
    }
    lines = [f"🕳️ Gap monitor — last {a.hours}h", *lag_lines, ""]
    if health and not health.get("ok"):
        lines.insert(1, f"⚠️ LinkedIn returned no jobs to the cloud (proxy={health.get('proxy')}, "
                        f"{health.get('chars')} chars) — scans from GitHub are blind")
    if new_findings:
        lines.append(f"{len(new_findings)} NEW job(s) LinkedIn job(s) detected >{a.min_lag:g}h after posting:")
        for v, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"• {n} × {v}: {hints.get(v, '')}")
        lines.append("")
        for f in new_findings[:5]:
            lines.append(f"{f['lag_h']}h · {f['title']} — {f['company']} [{f['verdict']}]")
            lines.append(f["url"])
    else:
        lines.append("No new late email-only jobs. ✅")
    if a.auto_fix and not a.dry_run:
        added = _auto_add_keywords(url, key, new_findings)
        report["keywords_added"] = added
        if added:
            lines.append("")
            lines.append("✅ Auto-added keywords: " + ", ".join(added))
        needs_code = [f for f in new_findings if f["verdict"] in ("ranking_miss", "scan_gap", "late_pickup")]
        if needs_code:
            issue = _open_issue(report, lines)
            if issue:
                lines.append("")
                lines.append(f"🛠️ Fix requested (issue): {issue}")
    text = "\n".join(lines)

    if a.dry_run:
        print(text)
        return 0
    try:
        db.set_config(url, key, "gap_monitor_last", json.dumps(report)[:20000])
    except Exception as exc:  # noqa: BLE001
        print(f"[Gap] could not store report: {exc}")
    if a.auto_fix:
        try:
            db.set_config(url, key, "gap_monitor_handled",
                          json.dumps(sorted(handled | {f["job_id"] for f in findings})[-500:]))
        except Exception as exc:  # noqa: BLE001
            print(f"[Gap] could not store handled ids: {exc}")
    if new_findings or a.always:
        telegram_notify.send_message(_env("TELEGRAM_BOT_TOKEN"), _env("TELEGRAM_CHAT_ID"), text[:3900])
    return 0


if __name__ == "__main__":
    sys.exit(main())
