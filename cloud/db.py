"""
Supabase REST API client — uses HTTPS (PostgREST) instead of direct PostgreSQL.
This avoids IPv4/IPv6 connectivity issues on GitHub Actions runners.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, urlunparse

from supabase import create_client, Client


_client: Client | None = None


# ── Blocked job-source domains ────────────────────────────────────────────────
# Jobs whose URL host matches any of these are dropped in sync_jobs() before they
# ever reach the database — so they are never alerted, never shown in the app or
# dashboard. Jobsora is a low-signal aggregator the user does not want.
# Extend at runtime via set_blocked_domains() (the worker loads the Supabase
# setting_blocked_domains list) or the BLOCKED_DOMAINS env var (comma-separated).
_BLOCKED_DOMAINS: set[str] = {"jobsora.com"}
for _d in (os.environ.get("BLOCKED_DOMAINS", "") or "").split(","):
    _d = _d.strip().lower().lstrip("www.")
    if _d:
        _BLOCKED_DOMAINS.add(_d)


def set_blocked_domains(domains) -> None:
    """Merge additional blocked domains (from Supabase settings) into the set.

    Accepts a comma-separated string or an iterable of domain strings.
    Always keeps the built-in defaults (e.g. jobsora.com).
    """
    if isinstance(domains, str):
        domains = domains.split(",")
    for d in (domains or []):
        d = str(d).strip().lower().lstrip("www.")
        if d:
            _BLOCKED_DOMAINS.add(d)


def _is_blocked_domain(url: str) -> bool:
    """True if the URL's host is (or is a subdomain of) a blocked domain."""
    try:
        host = urlparse((url or "").strip()).netloc.lower().split(":")[0].lstrip("www.")
    except Exception:
        return False
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in _BLOCKED_DOMAINS)


def _get_client(supabase_url: str, supabase_key: str) -> Client:
    global _client
    if _client is None:
        _client = create_client(supabase_url, supabase_key)
    return _client


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _canonical_url(raw: str) -> str:
    """Normalize a job URL for deduplication.

    LinkedIn job URLs come in two shapes depending on the source:
      - Guest API:   /jobs/view/4203456789
      - Web search:  /jobs/view/it-support-specialist-at-company-4203456789

    Both refer to the same job.  Extract the trailing numeric ID and build a
    stable canonical form so different sources produce the same URL string.
    """
    try:
        raw = (raw or "").strip()
        if "linkedin.com/jobs/view/" in raw.lower():
            m = re.search(r'/jobs/view/[^/?#]*?(\d{7,})(?:[/?#]|$)', raw)
            if m:
                return f"https://www.linkedin.com/jobs/view/{m.group(1)}"
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
        # Fetch more rows than requested, then re-sort by source priority so the
        # enricher always scores LinkedIn jobs first (P1), then Indeed (P2),
        # Gmail (P3), Adzuna (P4), and Web sources last (P5).
        fetch_limit = min(limit * 4, 200)
        result = (
            sb.table("jobs")
            .select("job_id,title,company,location,url,source,telegram_sent_at,date_posted,date_collected")
            .is_("llm_score", "null")
            .or_("status.eq.new,status.is.null")
            .order("date_collected", desc=True)
            .limit(fetch_limit)
            .execute()
        )
        rows = result.data or []

        # Re-sort by source priority in Python
        _SRC_RANK = {"LinkedIn": 1, "Indeed": 2, "Gmail": 3, "Adzuna": 4}

        def _rank(row: dict) -> int:
            src = row.get("source") or ""
            for prefix, rank in _SRC_RANK.items():
                if src.startswith(prefix):
                    return rank
            return 5  # Web/Tavily, Web/Brave, Web/Google, Web/Bing, etc.

        rows.sort(key=_rank)
        return rows[:limit]
    except Exception as exc:
        print(f"[DB] get_unscored_jobs error: {exc}")
        return []


def get_unnotified_jobs(
    supabase_url: str,
    supabase_key: str,
    min_age_minutes: int = 30,
    max_age_hours: int = 48,
    limit: int = 20,
) -> list[dict]:
    """Return new, unnotified jobs inserted between (max_age_hours ago) and (min_age_minutes ago).

    These fell through the main notification path — Telegram was flaky, the
    worker crashed after the DB write but before sending, or the job appeared
    as 'seen' on every subsequent run.  Re-alerting them ensures every job that
    made it into the DB is eventually surfaced to the user.
    Sorted by source priority so LinkedIn catch-ups arrive first.
    """
    sb = _get_client(supabase_url, supabase_key)
    try:
        now           = datetime.now(timezone.utc)
        cutoff_old    = (now - timedelta(hours=max_age_hours)).isoformat()
        cutoff_recent = (now - timedelta(minutes=min_age_minutes)).isoformat()
        result = (
            sb.table("jobs")
            .select(
                "job_id,title,company,location,url,source,"
                "date_posted,date_collected,llm_score,llm_summary"
            )
            .eq("status", "new")
            .is_("telegram_sent_at", "null")
            .gt("date_collected", cutoff_old)
            .lt("date_collected", cutoff_recent)
            .order("date_collected", desc=False)   # oldest first
            .limit(limit)
            .execute()
        )
        rows = result.data or []
        _SRC_RANK = {"LinkedIn": 1, "Indeed": 2, "Gmail": 3, "Adzuna": 4}

        def _rank(row: dict) -> int:
            src = row.get("source") or ""
            for prefix, rank in _SRC_RANK.items():
                if src.startswith(prefix):
                    return rank
            return 5

        rows.sort(key=_rank)
        return rows
    except Exception as exc:
        print(f"[DB] get_unnotified_jobs error: {exc}")
        return []


def update_cover_letter(supabase_url: str, supabase_key: str,
                          job_id: str, draft: str) -> None:
    """Phase 5: persist a generated cover-letter draft. Strips NUL bytes.

    Silently falls through if the cover_letter_draft column doesn't exist
    (i.e. the user hasn't run the Phase 5 migration yet) - the rest of the
    enrichment flow still works.
    """
    if not job_id or not draft:
        return
    sb = _get_client(supabase_url, supabase_key)
    clean = draft.replace("\x00", "")
    update = {
        "cover_letter_draft":        clean[:6000],   # hard cap
        "cover_letter_generated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        sb.table("jobs").update(update).eq("job_id", job_id).execute()
    except Exception as exc:
        msg = str(exc).lower()
        if "could not find" in msg or "does not exist" in msg or "pgrst204" in msg:
            print("[DB] cover_letter_draft column missing - run cloud/migrations/2026-05-15-cover-letter.sql")
        else:
            print(f"[DB] update_cover_letter error for {job_id}: {exc}")


def update_tailored_cv(supabase_url: str, supabase_key: str,
                        job_id: str, draft: str) -> None:
    """Persist a tailored CV draft for a specific job. Strips NUL bytes."""
    if not job_id or not draft:
        return
    sb    = _get_client(supabase_url, supabase_key)
    clean = draft.replace("\x00", "")
    try:
        sb.table("jobs").update({
            "tailored_cv_draft":        clean[:8000],
            "tailored_cv_generated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("job_id", job_id).execute()
    except Exception as exc:
        msg = str(exc).lower()
        if "could not find" in msg or "does not exist" in msg or "pgrst204" in msg:
            print("[DB] tailored_cv_draft column missing — run cloud/migrations/2026-05-19-tailored-cv.sql")
        else:
            print(f"[DB] update_tailored_cv error for {job_id}: {exc}")


def get_tailored_cv(supabase_url: str, supabase_key: str, job_id: str) -> str:
    """Return the stored tailored_cv_draft for a job, or '' if not yet generated."""
    if not job_id:
        return ""
    try:
        sb     = _get_client(supabase_url, supabase_key)
        result = (
            sb.table("jobs")
            .select("tailored_cv_draft,title,company")
            .eq("job_id", job_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if rows:
            return (rows[0].get("tailored_cv_draft") or "").strip()
    except Exception as exc:
        print(f"[DB] get_tailored_cv error for {job_id}: {exc}")
    return ""


def get_cover_letter(supabase_url: str, supabase_key: str, job_id: str) -> str:
    """Return the stored cover_letter_draft for a job, or '' if not yet generated."""
    if not job_id:
        return ""
    try:
        sb     = _get_client(supabase_url, supabase_key)
        result = (
            sb.table("jobs")
            .select("cover_letter_draft,title,company")
            .eq("job_id", job_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if rows:
            return (rows[0].get("cover_letter_draft") or "").strip()
    except Exception as exc:
        print(f"[DB] get_cover_letter error for {job_id}: {exc}")
    return ""


def get_jobs_by_status(supabase_url: str, supabase_key: str, status: str,
                        limit: int = 5) -> list[dict]:
    """Recent jobs for a given status (applied/dismissed/saved/new).

    Used by Phase 4 active learning to build dynamic few-shot examples
    from the user's most recent feedback. Returns most-recent first.
    """
    sb = _get_client(supabase_url, supabase_key)
    try:
        result = (
            sb.table("jobs")
            .select("title,company,location,url,llm_score,llm_summary,status,date_collected")
            .eq("status", status)
            .order("date_collected", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        print(f"[DB] get_jobs_by_status({status}) error: {exc}")
        return []


def set_job_status(supabase_url: str, supabase_key: str, job_id: str, status: str) -> bool:
    """Update a single job's status (applied/dismissed/saved/new) by job_id.

    Used by the Telegram 👍/👎 feedback buttons — the new status feeds the
    Phase 4 active-learning loop (preferences.py reads applied + dismissed).
    """
    if not job_id or not status:
        return False
    sb = _get_client(supabase_url, supabase_key)
    try:
        sb.table("jobs").update({"status": status}).eq("job_id", job_id).execute()
        return True
    except Exception as exc:
        print(f"[DB] set_job_status({job_id}, {status}) error: {exc}")
        return False


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
    salary: dict | None = None,
) -> bool:
    """Persist LLM enrichment for a job. Returns True on success, False on failure.

    If `breakdown` is provided (multi-criteria scoring, Phase 2+) the extra
    columns are included in the update. If those columns don't exist in the
    Supabase schema yet, the update is retried once without them so legacy
    deployments keep working. Run the SQL in `cloud/migrations/2026-05-13-multi-criteria.sql`
    once in Supabase to enable the full breakdown.

    Callers must check the return value before sending Telegram alerts — if False,
    llm_score was NOT saved and the job stays in get_unscored_jobs, meaning it
    will be retried next enricher run.  Alerting on a failed save causes duplicates.
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

    if salary:
        # Phase 24: market-salary snapshot (run 2026-06-10-salary-insights.sql)
        update.update({
            "salary_min":      salary.get("min"),
            "salary_max":      salary.get("max"),
            "salary_avg":      salary.get("avg"),
            "salary_currency": salary.get("currency"),
            "salary_period":   salary.get("period"),
            "salary_source":   salary.get("source"),
        })

    try:
        sb.table("jobs").update(update).eq("job_id", job_id).execute()
        return True
    except Exception as exc:
        msg = str(exc).lower()
        # PostgREST returns PGRST204 / "column ... does not exist" when the schema is older
        if (breakdown or salary) and ("could not find" in msg or "does not exist" in msg or "schema cache" in msg or "pgrst204" in msg):
            print(f"[DB] Phase-2/salary columns missing in Supabase - falling back to llm_score/llm_summary only. "
                  f"Run cloud/migrations/2026-05-13-multi-criteria.sql and "
                  f"cloud/migrations/2026-06-10-salary-insights.sql to enable them.")
            legacy_update = {k: v for k, v in update.items()
                             if k in ("description", "llm_score", "llm_summary", "status")}
            try:
                sb.table("jobs").update(legacy_update).eq("job_id", job_id).execute()
                return True
            except Exception as exc2:
                print(f"[DB] update_job_enrichment (legacy retry) error for {job_id}: {exc2}")
                return False
        else:
            print(f"[DB] update_job_enrichment error for {job_id}: {exc}")
            return False


def update_job_description(supabase_url: str, supabase_key: str, job_id: str, description: str) -> bool:
    """Store a fetched description for a single job. Returns True on success."""
    if not description or not job_id:
        return False
    sb = _get_client(supabase_url, supabase_key)
    try:
        sb.table("jobs").update({"description": description.replace("\x00", "")[:4000]}).eq("job_id", job_id).execute()
        return True
    except Exception as exc:
        print(f"[DB] update_job_description({job_id}) error: {exc}")
        return False


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
    summary: dict = {"inserted": 0, "updated": 0, "seen": 0, "invalid": 0, "blocked": 0, "new_jobs": []}
    if not jobs:
        return summary

    sb = _get_client(supabase_url, supabase_key)

    # ── Layer 1: dedup by canonical URL ──────────────────────────────────────
    all_urls = [_canonical_url(str(j.get("Url", ""))) for j in jobs]
    existing_resp = sb.table("jobs").select("job_id,url,title,company,location,source").in_("url", all_urls).execute()
    existing_by_url: dict[str, dict] = {row["url"]: row for row in (existing_resp.data or [])}

    # ── Layer 2: dedup by job_id ─────────────────────────────────────────────
    # Catches the same LinkedIn job stored under two URL formats
    # (e.g. /jobs/view/12345 vs /jobs/view/slug-name-12345).
    known_job_ids = {row["job_id"] for row in (existing_resp.data or [])}
    candidate_ids = [_job_id(j) for j in jobs]
    lookup_ids = [jid for jid in candidate_ids if jid and jid not in known_job_ids]
    existing_by_id: dict[str, dict] = {}
    if lookup_ids:
        id_resp = sb.table("jobs").select("job_id,url,title,company,location,source").in_("job_id", lookup_ids).execute()
        existing_by_id = {row["job_id"]: row for row in (id_resp.data or [])}

    for job in jobs:
        job_id = _job_id(job)
        raw_url = str(job.get("Url", ""))
        url = _canonical_url(raw_url)
        if not job_id or not url:
            summary["invalid"] += 1
            continue

        # Blocked source domain (e.g. Jobsora) — drop before it ever hits the DB,
        # so it is never alerted, scored, or shown in the app/dashboard.
        if _is_blocked_domain(raw_url) or _is_blocked_domain(url):
            summary["blocked"] = summary.get("blocked", 0) + 1
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

        # Phase 24: posted salary (Adzuna provides it). Only included when
        # present so inserts keep working on schemas without the salary
        # migration (2026-06-10-salary-insights.sql).
        if job.get("SalaryMin") or job.get("SalaryMax"):
            record.update({
                "salary_min":      job.get("SalaryMin"),
                "salary_max":      job.get("SalaryMax"),
                "salary_currency": job.get("SalaryCurrency") or "",
                "salary_period":   job.get("SalaryPeriod") or "year",
                "salary_source":   job.get("SalarySource") or "posted",
            })

        # Prefer URL match; fall back to job_id match (URL format changed)
        existing = existing_by_url.get(url) or existing_by_id.get(job_id)
        if existing is None:
            try:
                sb.table("jobs").insert(record).execute()
                summary["inserted"] += 1
                summary["new_jobs"].append(job)
            except Exception as exc:
                msg = str(exc).lower()
                has_salary = any(k.startswith("salary_") for k in record)
                if has_salary and ("could not find" in msg or "does not exist" in msg
                                   or "schema cache" in msg or "pgrst204" in msg):
                    # Salary columns missing — retry without them so new jobs
                    # are never dropped on a pre-migration schema.
                    slim = {k: v for k, v in record.items() if not k.startswith("salary_")}
                    try:
                        sb.table("jobs").insert(slim).execute()
                        summary["inserted"] += 1
                        summary["new_jobs"].append(job)
                        print("[DB] salary columns missing - run "
                              "cloud/migrations/2026-06-10-salary-insights.sql")
                    except Exception:
                        summary["seen"] += 1
                else:
                    # Unique-constraint violation (race condition or stale cache) — treat as seen
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
                }).eq("url", existing["url"]).execute()  # use stored URL (may differ from canonical)
                summary["updated"] += 1
            else:
                summary["seen"] += 1

    return summary


# ─── Multi-user per-user helpers (Phase 2+) ──────────────────────────────────

def get_active_profiles(
    supabase_url: str,
    supabase_key: str,
    channel: str | None = None,
) -> list[dict]:
    """Return merged profile + preferences for every non-paused user.

    Each dict has: user_id, email, display_name, telegram_chat_id, alert_email,
    alert_telegram, timezone, keywords, locations, exclude_keywords, min_score,
    alert_frequency, digest_hour.

    channel='email'|'telegram' narrows to users who have that channel enabled.
    Only returns users with at least one keyword or location set.
    """
    sb = _get_client(supabase_url, supabase_key)
    try:
        prefs_resp = sb.table("user_preferences").select("*").eq("paused", False).execute()
        prefs_by_user = {row["user_id"]: row for row in (prefs_resp.data or [])}
        if not prefs_by_user:
            return []

        profiles_resp = (
            sb.table("profiles")
            .select("id,email,display_name,telegram_chat_id,alert_email,alert_telegram,timezone")
            .in_("id", list(prefs_by_user.keys()))
            .execute()
        )

        combined: list[dict] = []
        for prof in (profiles_resp.data or []):
            uid   = prof["id"]
            prefs = prefs_by_user.get(uid, {})

            if channel == "email"    and not prof.get("alert_email"):
                continue
            if channel == "telegram" and not prof.get("alert_telegram"):
                continue

            kw  = prefs.get("keywords")  or []
            loc = prefs.get("locations") or []
            if not kw and not loc:
                continue

            combined.append({
                "user_id":          uid,
                "email":            prof.get("email"),
                "display_name":     prof.get("display_name"),
                "telegram_chat_id": prof.get("telegram_chat_id"),
                "alert_email":      prof.get("alert_email", True),
                "alert_telegram":   prof.get("alert_telegram", False),
                "timezone":         prof.get("timezone", "Asia/Dubai"),
                "keywords":         kw,
                "locations":        loc,
                "exclude_keywords": prefs.get("exclude_keywords") or [],
                "min_score":        prefs.get("min_score"),
                "alert_frequency":  prefs.get("alert_frequency", "daily"),
                "digest_hour":      prefs.get("digest_hour", 8),
            })
        return combined
    except Exception as exc:
        print(f"[DB] get_active_profiles error: {exc}")
        return []


def get_user_preferences(supabase_url: str, supabase_key: str, user_id: str) -> dict:
    """Return the user_preferences row for user_id as a dict, or {} if not found."""
    sb = _get_client(supabase_url, supabase_key)
    try:
        result = (
            sb.table("user_preferences")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else {}
    except Exception as exc:
        print(f"[DB] get_user_preferences error for {user_id}: {exc}")
        return {}


def get_user_matches(
    supabase_url: str,
    supabase_key: str,
    user_id: str,
    limit: int = 50,
    before: str | None = None,
) -> list[dict]:
    """Call the user_jobs_feed SQL function for a user.

    Returns matching jobs (filtered by the user's prefs, no dismissed/hidden)
    ordered by date_collected desc. Each row includes `my_status`.
    Pass `before` (ISO timestamptz) for keyset pagination.
    """
    sb = _get_client(supabase_url, supabase_key)
    try:
        params: dict = {"p_user": str(user_id), "p_limit": min(limit, 100)}
        if before:
            params["p_before"] = before
        result = sb.rpc("user_jobs_feed", params).execute()
        return result.data or []
    except Exception as exc:
        print(f"[DB] get_user_matches error for {user_id}: {exc}")
        return []


def get_last_alert_at(
    supabase_url: str,
    supabase_key: str,
    user_id: str,
    channel: str,
) -> str | None:
    """Return the most recent sent_at (ISO string) for a (user, channel), or None."""
    sb = _get_client(supabase_url, supabase_key)
    try:
        result = (
            sb.table("user_alert_log")
            .select("sent_at")
            .eq("user_id", user_id)
            .eq("channel", channel)
            .order("sent_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return rows[0]["sent_at"] if rows else None
    except Exception as exc:
        print(f"[DB] get_last_alert_at error for {user_id}/{channel}: {exc}")
        return None


def get_alerted_job_ids(
    supabase_url: str,
    supabase_key: str,
    user_id: str,
    channel: str,
) -> set[str]:
    """Return all job_ids already sent to a user on a channel (for dedup)."""
    sb = _get_client(supabase_url, supabase_key)
    try:
        result = (
            sb.table("user_alert_log")
            .select("job_id")
            .eq("user_id", user_id)
            .eq("channel", channel)
            .execute()
        )
        return {row["job_id"] for row in (result.data or [])}
    except Exception as exc:
        print(f"[DB] get_alerted_job_ids error for {user_id}/{channel}: {exc}")
        return set()


def log_user_alert(
    supabase_url: str,
    supabase_key: str,
    user_id: str,
    job_ids: list[str],
    channel: str,
) -> None:
    """Insert user_alert_log rows for each job_id. Idempotent (PK conflict = skip)."""
    if not job_ids:
        return
    sb  = _get_client(supabase_url, supabase_key)
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {"user_id": user_id, "job_id": jid, "channel": channel, "sent_at": now}
        for jid in job_ids
    ]
    try:
        sb.table("user_alert_log").upsert(rows, on_conflict="user_id,job_id,channel").execute()
    except Exception as exc:
        print(f"[DB] log_user_alert error for {user_id}/{channel}: {exc}")



def save_telegram_history(
    supabase_url: str,
    supabase_key: str,
    chat_id: int,
    role: str,
    content: str,
) -> None:
    """Insert a message into telegram_claude_history so the AI bot has context."""
    sb = _get_client(supabase_url, supabase_key)
    try:
        sb.table("telegram_claude_history").insert(
            {"chat_id": chat_id, "role": role, "content": content}
        ).execute()
    except Exception as exc:
        print(f"[DB] save_telegram_history error for chat {chat_id}: {exc}")


def upsert_user_interaction(
    supabase_url: str,
    supabase_key: str,
    user_id: str,
    job_id: str,
    status: str,
) -> bool:
    """Upsert a row in user_job_interactions (saved/applied/dismissed/hidden).

    Returns True on success, False on failure.
    """
    if not user_id or not job_id or not status:
        return False
    sb  = _get_client(supabase_url, supabase_key)
    now = datetime.now(timezone.utc).isoformat()
    try:
        sb.table("user_job_interactions").upsert(
            {"user_id": user_id, "job_id": job_id, "status": status, "updated_at": now},
            on_conflict="user_id,job_id",
        ).execute()
        return True
    except Exception as exc:
        print(f"[DB] upsert_user_interaction error for {user_id}/{job_id}: {exc}")
        return False
