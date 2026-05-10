"""
PostgreSQL (Supabase) client — replaces job-database.ps1.
Handles job upserts, Telegram-sent tracking, and deduplication.
"""

from __future__ import annotations

import hashlib
import re
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

import psycopg2
import psycopg2.extras


_CREATE_TABLE_SQL = """
create table if not exists jobs (
    job_id          text primary key,
    title           text not null,
    company         text not null,
    location        text not null,
    url             text not null unique,
    date_posted     timestamptz,
    date_collected  timestamptz not null default now(),
    source          text not null,
    status          text not null default 'new',
    telegram_sent_at timestamptz
);
create index if not exists idx_jobs_url            on jobs(url);
create index if not exists idx_jobs_date_posted    on jobs(date_posted);
create index if not exists idx_jobs_status         on jobs(status);
create index if not exists idx_jobs_title_co_loc   on jobs(title, company, location);
"""


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


def _resolve_posted_date(job: dict) -> datetime | None:
    posted_date = _normalize(str(job.get("PostedDate", "")))
    posted_text = _normalize(str(job.get("PostedText", "")))
    now = datetime.now(timezone.utc)

    if posted_date:
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(posted_date[:len(fmt)], fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue

    if posted_text:
        m = re.search(r"(\d+)\s*minute", posted_text, re.I)
        if m:
            return now.replace(second=0, microsecond=0)
        m = re.search(r"(\d+)\s*hour", posted_text, re.I)
        if m:
            from datetime import timedelta
            return now - timedelta(hours=int(m.group(1)))
        m = re.search(r"(\d+)\s*day", posted_text, re.I)
        if m:
            from datetime import timedelta
            return now - timedelta(days=int(m.group(1)))
        m = re.search(r"(\d+)\s*week", posted_text, re.I)
        if m:
            from datetime import timedelta
            return now - timedelta(weeks=int(m.group(1)))
        if re.search(r"just now|just posted|today", posted_text, re.I):
            return now

    return None


def _force_ipv4_dsn(dsn: str) -> str:
    """Replace the hostname with its IPv4 address so psycopg2 doesn't pick IPv6 first."""
    try:
        p = urlparse(dsn)
        infos = socket.getaddrinfo(p.hostname, p.port or 5432, socket.AF_INET, socket.SOCK_STREAM)
        if infos:
            ipv4 = infos[0][4][0]
            netloc = p.netloc.replace(p.hostname, ipv4)
            return urlunparse((p.scheme, netloc, p.path, p.params, p.query, p.fragment))
    except Exception:
        pass
    return dsn


def get_connection(database_url: str):
    return psycopg2.connect(_force_ipv4_dsn(database_url), cursor_factory=psycopg2.extras.RealDictCursor)


def initialize_database(database_url: str) -> None:
    with get_connection(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_TABLE_SQL)
        conn.commit()


def get_telegram_sent_urls(database_url: str) -> set[str]:
    with get_connection(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("select url from jobs where telegram_sent_at is not null")
            return {row["url"] for row in cur.fetchall()}


def mark_telegram_sent(database_url: str, url: str) -> None:
    canonical = _canonical_url(url)
    if not canonical:
        return
    with get_connection(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update jobs set telegram_sent_at = %s where url = %s",
                (datetime.now(timezone.utc), canonical),
            )
        conn.commit()


def upsert_job(cur, job: dict, source: str = "LinkedIn") -> str:
    job_id = _job_id(job)
    url = _canonical_url(str(job.get("Url", "")))
    if not job_id or not url:
        return "invalid"

    title = _normalize(str(job.get("Title", "")))
    company = _normalize(str(job.get("Company", "")))
    location = _normalize(str(job.get("Location", "")))
    if not title or not company:
        return "invalid"

    date_posted = _resolve_posted_date(job)
    date_collected = datetime.now(timezone.utc)
    status = _normalize(str(job.get("Status", "new"))) or "new"

    cur.execute(
        "select job_id, title, company, location, url, source, status from jobs where job_id = %s or url = %s limit 1",
        (job_id, url),
    )
    existing = cur.fetchone()

    if existing is None:
        cur.execute(
            """insert into jobs (job_id, title, company, location, url, date_posted, date_collected, source, status)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (url) do nothing""",
            (job_id, title, company, location, url, date_posted, date_collected, source, status),
        )
        return "inserted"

    changed = (
        existing["title"] != title
        or existing["company"] != company
        or existing["location"] != location
        or existing["source"] != source
    )
    if not changed:
        return "seen"

    cur.execute(
        """update jobs set title=%s, company=%s, location=%s, date_collected=%s, source=%s
           where job_id = %s""",
        (title, company, location, date_collected, source, existing["job_id"]),
    )
    return "updated"


def sync_jobs(database_url: str, jobs: list[dict], source: str = "LinkedIn") -> dict:
    summary = {"inserted": 0, "updated": 0, "seen": 0, "invalid": 0}
    if not jobs:
        return summary

    with get_connection(database_url) as conn:
        with conn.cursor() as cur:
            for job in jobs:
                result = upsert_job(cur, job, source)
                summary[result] = summary.get(result, 0) + 1
        conn.commit()

    return summary
