"""
Active learning from the user's applied/dismissed history (Phase 4).

Every time the user marks a job 'applied' (loved it) or 'dismissed' (rejected it),
that's a labeled training signal. Instead of fine-tuning a model, we inject the
most recent 5 applied + 5 dismissed jobs as live few-shot examples into the
scoring prompt. The LLM sees the user's actual taste and aligns its scoring.

Cache lives in Supabase bot_state.preferences_few_shot_v1 with a 6h TTL.
That way:
  - Enricher runs every few minutes don't re-query Supabase for history
  - When the user changes feedback, it takes up to 6h to fully propagate
  - You can force-refresh with: preferences.invalidate_cache(url, key)

Usage:
    from preferences import get_cached_or_refresh
    block = get_cached_or_refresh(supabase_url, supabase_key)
    # block is a string ready to drop into the prompt, or '' if no history yet
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)
import db

CACHE_KEY        = "preferences_few_shot_v1"
CACHE_TS_KEY     = "preferences_few_shot_v1_ts"
DEFAULT_TTL_HRS  = 6
DEFAULT_APPLIED  = 5
DEFAULT_DISMISSED = 5


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[prefs {ts}] {msg}", flush=True)


def _truncate(s: str, n: int) -> str:
    s = (s or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[:n - 1] + "..."


def _format_example(job: dict, verdict_word: str) -> str:
    """One bullet for the few-shot block. We use the LLM's own summary if
    present (it knows why it scored that way); otherwise fall back to
    title+company+location only."""
    title    = _truncate(job.get("title", ""), 80)
    company  = _truncate(job.get("company", ""), 50)
    location = _truncate(job.get("location", ""), 50)
    summary  = _truncate(job.get("llm_summary", ""), 200)
    score    = job.get("llm_score")
    score_str = f"score {score}/10, " if score is not None else ""

    line = f"- USER {verdict_word.upper()}: {title} @ {company} ({location})."
    if summary:
        line += f" {score_str}AI reasoning at the time: {summary}"
    return line


def build_few_shot_block(applied: list[dict], dismissed: list[dict]) -> str:
    """Format the applied/dismissed lists into a prompt-ready string.

    Returns '' if there are zero examples on both sides - no block at all.
    """
    if not applied and not dismissed:
        return ""

    lines = ["PAST PREFERENCES - examples of how this user has rated jobs before:"]

    if applied:
        lines.append("")
        lines.append("Jobs the user APPLIED to (positive signal, score these similar roles HIGH):")
        for j in applied[:DEFAULT_APPLIED]:
            lines.append(_format_example(j, "applied"))

    if dismissed:
        lines.append("")
        lines.append("Jobs the user DISMISSED (negative signal, score these similar roles LOW):")
        for j in dismissed[:DEFAULT_DISMISSED]:
            lines.append(_format_example(j, "dismissed"))

    lines.append("")
    lines.append("Use these as a guide for what 'fits' versus 'doesn't fit' for this user, "
                 "in addition to the candidate profile above.")
    lines.append("")
    return "\n".join(lines)


def _is_fresh(ts_iso: str, max_age_hours: int) -> bool:
    if not ts_iso:
        return False
    try:
        ts = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - ts < timedelta(hours=max_age_hours)
    except Exception:
        return False


def refresh(supabase_url: str, supabase_key: str,
            applied_limit: int = DEFAULT_APPLIED,
            dismissed_limit: int = DEFAULT_DISMISSED) -> str:
    """Pull fresh history from Supabase, format, write to cache, return block."""
    applied   = db.get_jobs_by_status(supabase_url, supabase_key, "applied",
                                       limit=applied_limit)
    dismissed = db.get_jobs_by_status(supabase_url, supabase_key, "dismissed",
                                       limit=dismissed_limit)
    # Filter dismissed: drop the auto-dismissed-as-duplicate entries from
    # Phase 3 (their llm_summary starts with "Duplicate of ") - they aren't
    # real user feedback.
    dismissed = [j for j in dismissed if not (j.get("llm_summary") or "").startswith("Duplicate of ")]

    block = build_few_shot_block(applied, dismissed)
    db.set_config(supabase_url, supabase_key, CACHE_KEY, block)
    db.set_config(supabase_url, supabase_key, CACHE_TS_KEY,
                  datetime.now(timezone.utc).isoformat())
    _log(f"Refreshed history: {len(applied)} applied + {len(dismissed)} dismissed "
         f"({len(block)} chars in cache)")
    return block


def get_cached_or_refresh(supabase_url: str, supabase_key: str,
                           max_age_hours: int = DEFAULT_TTL_HRS) -> str:
    """Return the cached few-shot block, refreshing if older than TTL."""
    ts = db.get_config(supabase_url, supabase_key, CACHE_TS_KEY, "")
    if _is_fresh(ts, max_age_hours):
        cached = db.get_config(supabase_url, supabase_key, CACHE_KEY, "")
        return cached
    # Stale or never built: refresh
    return refresh(supabase_url, supabase_key)


def invalidate_cache(supabase_url: str, supabase_key: str) -> None:
    """Force the next get_cached_or_refresh() to rebuild from scratch.
    Call this from the GUI / mobile app after the user changes a job's status
    if you want the new feedback to take effect immediately instead of waiting
    up to 6 hours."""
    db.set_config(supabase_url, supabase_key, CACHE_TS_KEY, "")


# ─── CLI for inspection ─────────────────────────────────────────────────────

def main() -> None:
    """python cloud/preferences.py [--refresh]   prints the current block."""
    import argparse
    p = argparse.ArgumentParser(description="Inspect / refresh the active-learning cache")
    p.add_argument("--refresh", action="store_true", help="Force rebuild from history")
    p.add_argument("--invalidate", action="store_true", help="Clear cache (next read rebuilds)")
    args = p.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    sup_url = os.environ.get("SUPABASE_URL", "").strip()
    sup_key = os.environ.get("SUPABASE_KEY", "").strip()
    if not sup_url or not sup_key:
        try:
            with open(os.path.join(_DIR, "..", "settings.json"), encoding="utf-8-sig") as f:
                cfg = json.load(f)
            sup_url = sup_url or cfg.get("SupabaseUrl", "")
            sup_key = sup_key or cfg.get("SupabaseKey", "")
        except Exception:
            pass
    if not sup_url or not sup_key:
        _log("ERROR: SUPABASE_URL / SUPABASE_KEY missing")
        sys.exit(1)

    if args.invalidate:
        invalidate_cache(sup_url, sup_key)
        _log("Cache invalidated.")
        return

    block = refresh(sup_url, sup_key) if args.refresh else get_cached_or_refresh(sup_url, sup_key)
    if not block:
        _log("No applied/dismissed history yet - block is empty.")
    else:
        print()
        print(block)


if __name__ == "__main__":
    main()
