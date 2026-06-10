"""
Daily digest: send the top N best-fit jobs from the last 24 hours to Telegram.

Runs once a day from a GitHub Actions cron (.github/workflows/daily-digest.yml).
Can also be invoked manually:

    python cloud/digest.py                # send digest to Telegram
    python cloud/digest.py --hours 48     # last 2 days instead of 1
    python cloud/digest.py --top 5        # top 5 instead of 3
    python cloud/digest.py --dry-run      # build + print, don't send

Skips:
  - jobs marked as duplicates (Phase 3)
  - jobs auto-dismissed for low score
  - jobs already at status applied / saved (already on user's radar)

Includes a cover-letter availability hint if the job has one (Phase 5).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import requests

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)
import db
import telegram_notify as tg


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[digest {ts}] {msg}", flush=True)


def get_top_jobs(supabase_url: str, supabase_key: str,
                  hours: int = 24, top_n: int = 3) -> list[dict]:
    """Return the highest-scoring NEW jobs from the last `hours` hours.

    Filters:
      - llm_score IS NOT NULL              (only scored jobs)
      - status = 'new'                     (not yet triaged or auto-dismissed)
      - duplicate_of_url IS NULL           (only canonical, not dedup'd copies)
      - date_collected >= cutoff           (recent)

    Ordered by overall_score DESC, then by date_collected DESC as tiebreaker.
    """
    # Use 'Z' suffix instead of '+00:00' so PostgREST query-string parsing
    # doesn't choke on the literal '+' (matches the fix in commit 5e1d3a3).
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    h = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}
    url = (
        f"{supabase_url}/rest/v1/jobs"
        "?select=title,company,location,url,llm_score,llm_summary,"
        "matched_skills,missing_skills,cover_letter_draft"
        "&status=eq.new"
        "&llm_score=not.is.null"
        "&duplicate_of_url=is.null"
        f"&date_collected=gte.{cutoff}"
        "&order=llm_score.desc,date_collected.desc"
        f"&limit={top_n}"
    )
    try:
        r = requests.get(url, headers=h, timeout=15)
        r.raise_for_status()
        return r.json() or []
    except Exception as exc:
        _log(f"Supabase query failed: {exc}")
        return []


def format_digest(jobs: list[dict], hours: int) -> str:
    """Build the multi-line Telegram digest message."""
    if not jobs:
        return f"Daily digest ({hours}h)\n\nNo new scored jobs found in the last {hours} hours."

    parts = [f"Daily digest - top {len(jobs)} jobs from the last {hours}h", ""]
    for i, j in enumerate(jobs, 1):
        score   = j.get("llm_score")
        title   = (j.get("title")   or "")[:80]
        company = (j.get("company") or "")[:50]
        loc     = (j.get("location")or "")[:50]
        summary = (j.get("llm_summary") or "")[:160]
        matched = j.get("matched_skills") or []
        cover   = "[cover letter ready]" if (j.get("cover_letter_draft") or "").strip() else ""

        parts.append(f"{i}. {score}/10  {title}")
        if company and loc:
            parts.append(f"   {company} - {loc}")
        elif company:
            parts.append(f"   {company}")
        if matched:
            parts.append(f"   Matched: {', '.join(matched[:4])}")
        if summary:
            parts.append(f"   {summary}")
        if cover:
            parts.append(f"   {cover}")
        url = j.get("url") or ""
        if url:
            parts.append(f"   {url}")
        parts.append("")

    return "\n".join(parts).rstrip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Send daily top-jobs digest to Telegram")
    parser.add_argument("--hours",  type=int, default=24, help="Look-back window in hours")
    parser.add_argument("--top",    type=int, default=3,  help="Number of top jobs to include")
    parser.add_argument("--dry-run", action="store_true", help="Print message, don't send")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # Creds: env -> settings.json fallback (same pattern as enricher)
    sup_url = os.environ.get("SUPABASE_URL", "").strip()
    sup_key = os.environ.get("SUPABASE_KEY", "").strip()
    tg_tok  = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not (sup_url and sup_key and tg_tok and tg_chat):
        try:
            with open(os.path.join(_DIR, "..", "settings.json"), encoding="utf-8-sig") as f:
                cfg = json.load(f)
            sup_url = sup_url or cfg.get("SupabaseUrl", "")
            sup_key = sup_key or cfg.get("SupabaseKey", "")
            tg_tok  = tg_tok  or cfg.get("TelegramBotToken", "")
            tg_chat = tg_chat or cfg.get("TelegramChatId", "")
        except Exception:
            pass

    # SECURITY: Telegram credentials come from env / settings.json only —
    # never from bot_state, which is readable with the public anon key.

    if not sup_url or not sup_key:
        _log("ERROR: SUPABASE_URL / SUPABASE_KEY missing")
        sys.exit(1)
    if not tg_tok or not tg_chat:
        _log("ERROR: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing")
        sys.exit(1)

    _log(f"Building digest: window={args.hours}h, top={args.top}")
    jobs = get_top_jobs(sup_url, sup_key, hours=args.hours, top_n=args.top)
    _log(f"Found {len(jobs)} qualifying job(s)")

    msg = format_digest(jobs, args.hours)
    print()
    print(msg)
    print()

    if args.dry_run:
        _log("Dry run - not sending.")
        return

    ok = tg.send_message(tg_tok, tg_chat, msg)
    _log("Sent." if ok else "Send FAILED.")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
