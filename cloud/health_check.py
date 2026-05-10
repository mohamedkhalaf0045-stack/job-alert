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
import sys
import requests
from datetime import datetime, timezone, timedelta

GITHUB_API = "https://api.github.com"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


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
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
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

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
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
                    ts = created_at[:16].replace("T", " ")
                    ok_msgs.append(f"Last run: {ts} UTC ({age_h:.1f}h ago)")
            except Exception:
                pass

    # ── 3. Recent job collection ───────────────────────────────────────────
    if sb_ok:
        recent = count_recent_jobs(supabase_url, supabase_key, hours=max_run_hours + 1)
        if recent == -1:
            issues.append("Could not count recent jobs from Supabase")
        elif recent == 0:
            issues.append(
                f"<b>0 jobs</b> collected in the last {max_run_hours + 1}h — "
                f"scraper may be broken or rate-limited"
            )
        else:
            ok_msgs.append(f"Jobs collected (last {max_run_hours + 1}h): {recent}")

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
        sys.exit(1)
    else:
        print(f"[{now_str}] All checks passed:")
        for m in ok_msgs:
            print(f"  OK  {m}")


if __name__ == "__main__":
    main()
