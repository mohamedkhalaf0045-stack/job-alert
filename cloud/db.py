"""
Supabase REST API client — uses HTTPS (PostgREST) instead of direct PostgreSQL.
This avoids IPv4/IPv6 connectivity issues on GitHub Actions runners.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, urlunparse

from supabase import create_client, Client


_client: Client | None = None


def _get_client(supabase_url: str, supabase_key: str) -> Client:
    global _client
    if _client is None:
        _client = create_client(supabase_url, supabase_key)
    return _client


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _canonical_url(raw: str) -> str:
    try:
        p = urlparse(raw)
        return urlunparse((p.scheme, p.netloc, p.path, "", "", "")).rstrip("/")
    except Exception:
        return raw


def _job_id(job: dict) -> str:
    raw_id = _normalize(str(job.get("Id", "")))
    if raw_id:
        return raw_id
    combo = f"{_normalize(job.get('Title',''))}|{_normalize(job.get('Company',''))}|{_normalize(job.get('Location',''))}"
    if combo.replace("|", "").strip():
        return hashlib.sha256(combo.lower().encode()).hexdigest()
    return ""


def _resolve_posted_date(job: dict) -> str | None:
    posted_date = _normalize(str(job.get("PostedDate", "")))
    posted_text = _normalize(str(job.get("PostedText", "")))
    now = datetime.now(timezone.utc)

    if posted_date:
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                dt = datetime.strptime(posted_date[:len(fmt)], fmt).replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except ValueError:
                continue

    if posted_text:
        from datetime import timedelta
        m = re.search(r"(\d+)\s*minute", posted_text, re.I)
        if m:
            return now.isoformat()
        m = re.search(r"(\d+)\s*hour", posted_text, re.I)
        if m:
            return (now - timedelta(hours=int(m.group(1)))).isoformat()
        m = re.search(r"(\d+)\s*day", posted_text, re.I)
        if m:
            return (now - timedelta(days=int(m.group(1)))).isoformat()
        m = re.search(r"(\d+)\s*week", posted_text, re.I)
        if m:
            return (now - timedelta(weeks=int(m.group(1)))).isoformat()
        if re.search(r"just now|just posted|today", posted_text, re.I):
            return now.isoformat()

    return None


def initialize_database(supabase_url: str, supabase_key: str) -> None:
    """Verify we can reach the jobs table. Table must be created manually in Supabase SQL Editor."""
    sb = _get_client(supabase_url, supabase_key)
    try:
        sb.table("jobs").select("job_id", count="exact").limit(1).execute()
    except Exception as exc:
        raise RuntimeError(
            "Cannot reach 'jobs' table in Supabase. "
            "Run the CREATE TABLE SQL in the Supabase SQL Editor first. "
            f"Details: {exc}"
        )
    # Ensure bot_state table exists (best-effort — ignore if missing)
    try:
        sb.table("bot_state").select("key").limit(1).execute()
    except Exception:
        pass


def get_config(supabase_url: str, supabase_key: str, key: str, default: str = "") -> str:
    sb = _get_client(supabase_url, supabase_key)
    try:
        result = sb.table("bot_state").select("value").eq("key", key).execute()
        rows = result.data or []
        return rows[0]["value"] if rows else default
    except Exception:
        return default


def set_config(supabase_url: str, supabase_key: str, key: str, value: str) -> None:
    sb = _get_client(supabase_url, supabase_key)
    try:
        sb.table("bot_state").upsert({"key": key, "value": value}).execute()
    except Exception:
        pass


def get_job_count(supabase_url: str, supabase_key: str) -> int:
    sb = _get_client(supabase_url, supabase_key)
    try:
        result = sb.table("jobs").select("job_id", count="exact").limit(1).execute()
        return result.count or 0
    except Exception:
        return 0


def get_telegram_sent_urls(supabase_url: str, supabase_key: str) -> set[str]:
    sb = _get_client(supabase_url, supabase_key)
    result = sb.table("jobs").select("url").not_.is_("telegram_sent_at", "null").execute()
    return {row["url"] for row in (result.data or [])}


def mark_telegram_sent(supabase_url: str, supabase_key: str, url: str) -> None:
    canonical = _canonical_url(url)
    if not canonical:
        return
    sb = _get_client(supabase_url, supabase_key)
    sb.table("jobs").update({"telegram_sent_at": datetime.now(timezone.utc).isoformat()}).eq("url", canonical).execute()


def get_unscored_jobs(supabase_url: str, supabase_key: str, limit: int = 20) -> list[dict]:
    sb = _get_client(supabase_url, supabase_key)
    try:
        result = (
            sb.table("jobs")
            .select("job_id,title,company,location,url,source")
            .is_("llm_score", "null")
            .eq("status", "new")
            .order("date_collected", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        print(f"[DB] get_unscored_jobs error: {exc}")
        return []


# ─── Phase 3: dedup helpers ────────────────────────────────────────────────

def get_recent_with_embeddings(supabase_url: str, supabase_key: str,
                                company: str = "", window_days: int = 7,
                                exclude_url: str = "") -> list[dict]:
    """Recent jobs with embeddings (for cosine-similarity dedup).

    Filters by company (case-insensitive ILIKE) when provided, since
    duplicates almost always share the same company name.
    """
    sb = _get_client(supabase_url, supabase_key)
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        q = (
            sb.table("jobs")
            .select("url,title,company,embedding,date_collected")
            .not_.is_("embedding", "null")
            .gte("date_collected", cutoff)
        )
        if company.strip():
            q = q.ilike("company", company.strip())
        result = q.limit(200).execute()
        rows = result.data or []
        if exclude_url:
            rows = [r for r in rows if r.get("url") != exclude_url]
        return rows
    except Exception as exc:
        print(f"[DB] get_recent_with_embeddings error: {exc}")
        return []


def get_jobs_without_embedding(supabase_url: str, supabase_key: str,
                                 limit: int = 500) -> list[dict]:
    """Jobs that haven't had a dedup pass yet (embedding IS NULL)."""
    sb = _get_client(supabase_url, supabase_key)
    try:
        result = (
            sb.table("jobs")
            .select("job_id,title,company,location,url,description,date_collected")
            .is_("embedding", "null")
            .order("date_collected", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        print(f"[DB] get_jobs_without_embedding error: {exc}")
        return []


def get_all_jobs_for_dedup(supabase_url: str, supabase_key: str,
                            limit: int = 500) -> list[dict]:
    """Every job, oldest first - for full --reprocess-all backfill so that
    canonical (oldest) jobs are processed before their duplicates."""
    sb = _get_client(supabase_url, supabase_key)
    try:
        result = (
            sb.table("jobs")
            .select("job_id,title,company,location,url,description,date_collected")
            .order("date_collected", desc=False)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        print(f"[DB] get_all_jobs_for_dedup error: {exc}")
        return []


def mark_embedding(supabase_url: str, supabase_key: str, url: str,
                   embedding: list[float],
                   duplicate_of_url: str | None = None) -> None:
    """Persist embedding + (optional) duplicate link for a job.

    Always updates dedup_checked_at to now so we can tell processed-but-canonical
    rows from never-processed rows.
    """
    if not url:
        return
    sb = _get_client(supabase_url, supabase_key)
    update = {
        "embedding": embedding,
        "duplicate_of_url": duplicate_of_url,
        "dedup_checked_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        sb.table("jobs").update(update).eq("url", url).execute()
    except Exception as exc:
        msg = str(exc).lower()
        if "could not find" in msg or "does not exist" in msg or "pgrst204" in msg:
            print("[DB] dedup columns missing - run cloud/migrations/2026-05-14-dedup.sql")
        else:
            print(f"[DB] mark_embedding error for {url}: {exc}")


def update_job_enrichment(
    supabase_url: str,
    supabase_key: str,
    job_id: str,
    description: str,
    score: int,
    summary: str,
    min_score: int = 4,
    breakdown: dict | None = None,
) -> None:
    """Persist LLM enrichment for a job.

    If `breakdown` is provided (multi-criteria scoring, Phase 2+) the extra
    columns are included in the update. If those columns don't exist in the
    Supabase schema yet, the update is retried once without them so legacy
    deployments keep working. Run the SQL in `cloud/migrations/2026-05-13-multi-criteria.sql`
    once in Supabase to enable the full breakdown.
    """
    # Postgres text/jsonb columns cannot store the NUL byte ().
    # LinkedIn/Indeed scraped HTML sometimes contains stray NULs. Strip them.
    def _strip_nul(s):
        return s.replace("\x00", "") if isinstance(s, str) else s
    def _strip_nul_list(lst):
        return [_strip_nul(x) for x in lst] if isinstance(lst, list) else lst

    sb = _get_client(supabase_url, supabase_key)
    update: dict = {
        "description": (_strip_nul(description)[:4000] if description else None),
        "llm_score":   score,
        "llm_summary": _strip_nul(summary),
    }
    if score < min_score:
        update["status"] = "dismissed"

    if breakdown:
        update.update({
            "skills_match":     int(breakdown.get("skills_match", 0)),
            "experience_match": int(breakdown.get("experience_match", 0)),
            "location_match":   int(breakdown.get("location_match", 0)),
            "seniority_match":  int(breakdown.get("seniority_match", 0)),
            "matched_skills":   _strip_nul_list(breakdown.get("matched_skills") or []),
            "missing_skills":   _strip_nul_list(breakdown.get("missing_skills") or []),
            "red_flags":        _strip_nul_list(breakdown.get("red_flags")      or []),
        })

    try:
        sb.table("jobs").update(update).eq("job_id", job_id).execute()
        return
    except Exception as exc:
        msg = str(exc).lower()
        # PostgREST returns PGRST204 / "column ... does not exist" when the schema is older
        if breakdown and ("could not find" in msg or "does not exist" in msg or "schema cache" in msg or "pgrst204" in msg):
            print(f"[DB] Phase-2 columns missing in Supabase - falling back to llm_score/llm_summary only. "
                  f"Run cloud/migrations/2026-05-13-multi-criteria.sql to enable the breakdown.")
            legacy_update = {k: v for k, v in update.items()
                             if k in ("description", "llm_score", "llm_summary", "status")}
            try:
                sb.table("jobs").update(legacy_update).eq("job_id", job_id).execute()
                return
            except Exception as exc2:
                print(f"[DB] update_job_enrichment (legacy retry) error for {job_id}: {exc2}")
        else:
            print(f"[DB] update_job_enrichment error for {job_id}: {exc}")


def get_scores_for_urls(supabase_url: str, supabase_key: str, urls: list[str]) -> dict[str, dict]:
    """Return {url: {llm_score, llm_summary}} for already-enriched jobs."""
    if not urls:
        return {}
    sb = _get_client(supabase_url, supabase_key)
    try:
        canonical_urls = [_canonical_url(u) for u in urls]
        result = (
            sb.table("jobs")
            .select("url,llm_score,llm_summary")
            .in_("url", canonical_urls)
            .not_.is_("llm_score", "null")
            .execute()
        )
        return {row["url"]: row for row in (result.data or [])}
    except Exception:
        return {}


def sync_jobs(supabase_url: str, supabase_key: str, jobs: list[dict], source: str = "LinkedIn") -> dict:
    summary: dict = {"inserted": 0, "updated": 0, "seen": 0, "invalid": 0, "new_jobs": []}
    if not jobs:
        return summary

    sb = _get_client(supabase_url, supabase_key)

    # Fetch existing URLs in one query for dedup
    all_urls = [_canonical_url(str(j.get("Url", ""))) for j in jobs]
    existing_resp = sb.table("jobs").select("job_id,url,title,company,location,source").in_("url", all_urls).execute()
    existing_by_url = {row["url"]: row for row in (existing_resp.data or [])}

    for job in jobs:
        job_id = _job_id(job)
        url = _canonical_url(str(job.get("Url", "")))
        if not job_id or not url:
            summary["invalid"] += 1
            continue

        title = _normalize(str(job.get("Title", "")))
        company = _normalize(str(job.get("Company", "")))
        if not title or not company:
            summary["invalid"] += 1
            continue

        record = {
            "job_id": job_id,
            "title": title,
            "company": company,
            "location": _normalize(str(job.get("Location", ""))),
            "url": url,
            "date_posted": _resolve_posted_date(job),
            "date_collected": datetime.now(timezone.utc).isoformat(),
            "source": _normalize(source),
            "status": _normalize(str(job.get("Status", "new"))) or "new",
        }

        existing = existing_by_url.get(url)
        if existing is None:
            try:
                sb.table("jobs").insert(record).execute()
                summary["inserted"] += 1
                summary["new_jobs"].append(job)
            except Exception:
                # May fail if job_id conflict — treat as seen
                summary["seen"] += 1
        else:
            changed = (
                existing.get("title") != record["title"]
                or existing.get("company") != record["company"]
                or existing.get("location") != record["location"]
                or existing.get("source") != record["source"]
            )
            if changed:
                sb.table("jobs").update({
                    "title": record["title"],
                    "company": record["company"],
                    "location": record["location"],
                    "date_collected": record["date_collected"],
                    "source": record["source"],
                }).eq("url", url).execute()
                summary["updated"] += 1
            else:
                summary["seen"] += 1

    return summary
