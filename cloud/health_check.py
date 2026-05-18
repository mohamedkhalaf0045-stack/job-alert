"""
Health check for the job-alert system.
Runs every 3 hours as a separate GitHub Actions workflow.
Sends a Telegram alert only when issues are detected.

Checks:
  1. Supabase connectivity (can we query the jobs table?)
  2. GitHub Actions last run — failed / cancelled?
  3. Worker timing — has it run within the expected window?
  4. Recent job collection — any jobs inserted in the last 25h?
"""

from __future__ import annotations
import os
import re
import sys
import requests
from datetime import datetime, timezone, timedelta

GITHUB_API = "https://api.github.com"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip().lstrip('﻿')


# ── individual checks ────────────────────────────────────────────────────────

def check_supabase(url: str, key: str) -> tuple[bool, str]:
    """Returns (ok, detail)."""
    if not url or not key:
        return False, "SUPABASE_URL or SUPABASE_KEY not set"
    try:
        r = requests.get(
            f"{url}/rest/v1/jobs?select=job_id&limit=1",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=10,
        )
        if r.status_code == 200:
            return True, "OK"
        return False, f"HTTP {r.status_code} — {r.text[:120]}"
    except Exception as exc:
        return False, f"Connection error: {exc}"


def get_last_run(token: str, repo: str) -> dict | None:
    """Returns the latest workflow run dict, or None on error."""
    if not token or not repo:
        return None
    try:
        r = requests.get(
            f"{GITHUB_API}/repos/{repo}/actions/runs?per_page=1",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=10,
        )
        if r.status_code != 200:
            return None
        runs = r.json().get("workflow_runs", [])
        return runs[0] if runs else None
    except Exception:
        return None


def count_recent_jobs(url: str, key: str, hours: int = 25) -> int:
    """Returns count of jobs inserted in the last `hours` hours, or -1 on error."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        r = requests.get(
            f"{url}/rest/v1/jobs?date_collected=gte.{cutoff}&select=job_id",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Prefer": "count=exact",
                "Range-Unit": "items",
                "Range": "0-0",
            },
            timeout=10,
        )
        parts = r.headers.get("content-range", "").split("/")
        return int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else -1
    except Exception:
        return -1


def get_supabase_config(url: str, key: str, config_key: str, default: str = "") -> str:
    """Read a single key from the bot_state config table."""
    try:
        r = requests.get(
            f"{url}/rest/v1/bot_state?key=eq.{config_key}&select=value&limit=1",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=10,
        )
        rows = r.json() if r.status_code == 200 else []
        return rows[0]["value"] if rows else default
    except Exception:
        return default


def parse_tz_offset(tz_str: str) -> timedelta:
    """Parse 'UTC+4', 'UTC-5:30', etc. into a timedelta. Returns UTC on failure."""
    m = re.match(r"UTC([+-])(\d{1,2})(?::(\d{2}))?$", (tz_str or "").strip())
    if not m:
        return timedelta(0)
    sign   = 1 if m.group(1) == "+" else -1
    hours  = int(m.group(2))
    mins   = int(m.group(3)) if m.group(3) else 0
    return timedelta(hours=sign * hours, minutes=sign * mins)


def fmt_local(dt: datetime, tz_offset: timedelta, label: str) -> str:
    """Format a UTC datetime as local time with a ±HH:00 label, e.g. '2026-05-12 01:28 UTC+4'."""
    local = dt.astimezone(timezone(tz_offset))
    return local.strftime("%Y-%m-%d %H:%M") + f" {label}"


def send_telegram(token: str, chat_id: str, text: str) -> None:
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    supabase_url  = _env("SUPABASE_URL")
    supabase_key  = _env("SUPABASE_KEY")
    gh_token      = _env("GH_TOKEN")
    gh_repo       = _env("GH_REPO")
    tg_token      = _env("TELEGRAM_BOT_TOKEN")
    tg_chat       = _env("TELEGRAM_CHAT_ID")
    max_run_hours = int(_env("MAX_RUN_HOURS", "2"))

    # Read display timezone from Supabase (set by mobile/Windows app)
    tz_str    = get_supabase_config(supabase_url, supabase_key, "setting_timezone", "UTC")
    tz_offset = parse_tz_offset(tz_str)
    tz_label  = tz_str if tz_str else "UTC"

    now_utc = datetime.now(timezone.utc)
    now_str = fmt_local(now_utc, tz_offset, tz_label)
    issues:  list[str] = []
    ok_msgs: list[str] = []

    # ── 1. Supabase ────────────────────────────────────────────────────────
    sb_ok, sb_detail = check_supabase(supabase_url, supabase_key)
    if sb_ok:
        ok_msgs.append(f"Supabase: {sb_detail}")
    else:
        issues.append(f"Supabase unreachable — {sb_detail}")

    # ── 2. GitHub Actions last run ─────────────────────────────────────────
    run = get_last_run(gh_token, gh_repo)
    if run is None:
        issues.append("GitHub API: could not fetch workflow runs (token missing or invalid?)")
    else:
        status      = run.get("status", "")
        conclusion  = run.get("conclusion", "") or ""
        created_at  = run.get("created_at", "")
        html_url    = run.get("html_url", "")
        run_name    = run.get("name", "workflow")

        # 2a. Did it fail?
        if conclusion in ("failure", "cancelled", "timed_out", "startup_failure"):
            issues.append(
                f'Run <b>{run_name}</b> finished with <b>{conclusion}</b>\n'
                f'   <a href="{html_url}">View logs</a>'
            )
        elif status in ("in_progress", "queued", "waiting"):
            ok_msgs.append(f"Run {run_name}: {status} (currently running)")
        elif conclusion == "success":
            ok_msgs.append(f"Run {run_name}: success")

        # 2b. Is it overdue?
        if created_at:
            try:
                run_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                age_h  = (datetime.now(timezone.utc) - run_dt).total_seconds() / 3600
                if age_h > max_run_hours and status not in ("in_progress", "queued", "waiting"):
                    issues.append(
                        f"No workflow run in <b>{age_h:.1f}h</b> "
                        f"(expected every {max_run_hours}h — schedule may be paused)"
                    )
                else:
                    ts = fmt_local(run_dt, tz_offset, tz_label)
                    ok_msgs.append(f"Last run: {ts} ({age_h:.1f}h ago)")
            except Exception:
                pass

    # ── 3. Recent job collection ───────────────────────────────────────────
    # Use a 25-hour window regardless of MAX_RUN_HOURS.  The workflow-run
    # check (step 2b) already catches "scraper hasn't run recently"; this
    # check catches "scraper runs but consistently fetches nothing at all"
    # (cookie expired, API banned, etc.).  A 3-hour window caused false
    # alarms on quiet market days when all found jobs were already in DB.
    if sb_ok:
        recent = count_recent_jobs(supabase_url, supabase_key, hours=25)
        if recent == -1:
            issues.append("Could not count recent jobs from Supabase")
        elif recent == 0:
            issues.append(
                "<b>0 jobs</b> collected in the last 25h — "
                "scraper may be broken, cookie expired, or rate-limited"
            )
        else:
            ok_msgs.append(f"Jobs collected (last 25h): {recent}")

    # ── Send Telegram ──────────────────────────────────────────────────────
    if issues:
        lines = [f"⚠️ <b>Job Alert — Health Issue</b>", f"<i>{now_str}</i>", ""]
        for msg in issues:
            lines.append(f"❌ {msg}")
        if ok_msgs:
            lines.append("")
            for msg in ok_msgs:
                lines.append(f"✅ {msg}")
        alert_text = "\n".join(lines)
        send_telegram(tg_token, tg_chat, alert_text)
        print(f"[{now_str}] ALERT sent — {len(issues)} issue(s):")
        for i in issues:
            print(f"  - {i}")
    else:
        print(f"[{now_str}] All checks passed:")
        for m in ok_msgs:
            print(f"  OK  {m}")


if __name__ == "__main__":
    main()
