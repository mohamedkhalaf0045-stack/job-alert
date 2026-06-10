"""
Market-salary lookup for a job title (Phase 24).

Primary source: Adzuna salary statistics — real market data. UAE ("ae") is a
supported Adzuna country and the project already has Adzuna API credentials
(ADZUNA_APP_ID / ADZUNA_APP_KEY GitHub Secrets, optional AdzunaAppId/Key in
settings.json for local runs).

Fallback: the enricher's scoring LLM also returns a salary estimate for the
title+location (salary_est_* fields) — used when Adzuna has no data for the
title or no credentials are configured.

Lookups are cached in Supabase bot_state (salary_mkt_v1_<country>_<slug>) for
30 days, so repeat titles cost zero API calls. Cache writes are best-effort:
after the RLS lockdown, local runs with the anon key simply skip caching.
"""

from __future__ import annotations

import json
import re
import time

import requests

import db

_API_BASE     = "https://api.adzuna.com/v1/api/jobs"
_CACHE_PREFIX = "salary_mkt_v1_"
_CACHE_TTL_S  = 30 * 24 * 3600  # salary stats move slowly
_CURRENCY     = {"ae": "AED", "gb": "GBP", "us": "USD", "in": "INR", "sg": "SGD"}


def _slug(title: str, country: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (title or "").lower()).strip("_")
    return f"{_CACHE_PREFIX}{country}_{s[:80]}"


def _cache_get(sb_url: str, sb_key: str, key: str) -> dict | None:
    """Returns the cached dict ({"none": True} = known no-data) or None on miss."""
    if not sb_url or not sb_key:
        return None
    try:
        raw = db.get_config(sb_url, sb_key, key, "")
        if not raw:
            return None
        data = json.loads(raw)
        if time.time() - float(data.get("ts", 0)) > _CACHE_TTL_S:
            return None
        value = data.get("value")
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _cache_set(sb_url: str, sb_key: str, key: str, value: dict) -> None:
    if not sb_url or not sb_key:
        return
    try:
        db.set_config(sb_url, sb_key, key,
                      json.dumps({"ts": time.time(), "value": value}))
    except Exception:
        pass  # anon key is read-only post-RLS — caching is best-effort


def _adzuna_history(title: str, app_id: str, app_key: str, country: str) -> dict | None:
    """Average advertised salary per month for the title (country-wide)."""
    r = requests.get(
        f"{_API_BASE}/{country}/history",
        params={"app_id": app_id, "app_key": app_key, "what": title,
                "content-type": "application/json"},
        timeout=15,
    )
    if r.status_code != 200:
        return None
    months = (r.json() or {}).get("month") or {}
    vals = [float(v) for _, v in sorted(months.items())[-6:] if v]
    if not vals:
        return None
    return {"avg": round(sum(vals) / len(vals)), "min": None, "max": None}


def _adzuna_histogram(title: str, app_id: str, app_key: str, country: str) -> dict | None:
    """Salary distribution for the title — used when history has no data."""
    r = requests.get(
        f"{_API_BASE}/{country}/histogram",
        params={"app_id": app_id, "app_key": app_key, "what": title,
                "content-type": "application/json"},
        timeout=15,
    )
    if r.status_code != 200:
        return None
    hist = (r.json() or {}).get("histogram") or {}
    buckets = []
    for k, v in hist.items():
        try:
            amount, count = float(k), int(v)
        except (TypeError, ValueError):
            continue
        if count > 0 and amount > 0:
            buckets.append((amount, count))
    if not buckets:
        return None
    total = sum(c for _, c in buckets)
    avg = sum(a * c for a, c in buckets) / total
    return {"avg": round(avg),
            "min": round(min(a for a, _ in buckets)),
            "max": round(max(a for a, _ in buckets))}


def get_market_salary(title: str, app_id: str, app_key: str,
                      supabase_url: str = "", supabase_key: str = "",
                      country: str = "ae") -> dict | None:
    """Average market salary for a title, as advertised on the market.

    Returns {"avg", "min", "max", "currency", "period": "year",
    "source": "adzuna_market"} or None when unavailable. Adzuna amounts are
    annualised; callers divide by 12 for the monthly figure.
    """
    title = (title or "").strip()
    if not title or not app_id or not app_key:
        return None

    key = _slug(title, country)
    cached = _cache_get(supabase_url, supabase_key, key)
    if cached is not None:
        return None if cached.get("none") else cached

    try:
        stats = (_adzuna_history(title, app_id, app_key, country)
                 or _adzuna_histogram(title, app_id, app_key, country))
    except requests.RequestException:
        return None  # transient network problem — don't cache the failure

    result = None
    if stats and stats.get("avg"):
        result = {**stats,
                  "currency": _CURRENCY.get(country, ""),
                  "period":   "year",
                  "source":   "adzuna_market"}

    _cache_set(supabase_url, supabase_key, key, result or {"none": True})
    return result


def from_ai_estimate(breakdown: dict | None) -> dict | None:
    """Build a salary dict from the scoring LLM's salary_est_* fields."""
    if not breakdown:
        return None
    mn = breakdown.get("salary_est_min_monthly")
    mx = breakdown.get("salary_est_max_monthly")
    if not (mn or mx):
        return None
    if mn and mx and mn > mx:
        mn, mx = mx, mn
    cur = (breakdown.get("salary_est_currency") or "").strip().upper()[:6]
    avg = round(((mn or mx) + (mx or mn)) / 2)
    return {"avg": avg, "min": mn, "max": mx,
            "currency": cur or "AED", "period": "month", "source": "ai_estimate"}
