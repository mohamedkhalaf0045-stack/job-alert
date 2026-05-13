"""
Cross-source deduplication using local Ollama embeddings.

A "duplicate" is the same job posting that appears on multiple sources
(e.g. LinkedIn AND Indeed AND Adzuna). We don't want to score it 3 times
nor send 3 Telegram alerts.

Approach (Phase 3 of the smart-tool plan):
  1. For each new job, compute a 768-dim embedding of (title + company +
     first 200 chars of description) via Ollama's nomic-embed-text model.
  2. Compare against embeddings of jobs from the last 7 days that share
     the same company (case-insensitive) - narrows candidates massively.
  3. If cosine similarity >= 0.92 with any prior job, mark the new one
     as a duplicate: set jobs.duplicate_of_url to the canonical row.
  4. The canonical (first-seen) row keeps `duplicate_of_url IS NULL` and
     is the only one that gets scored / alerted on.

Run standalone:
    python cloud/dedup.py                          # process unprocessed only
    python cloud/dedup.py --reprocess-all --dry-run
    python cloud/dedup.py --reprocess-all

Imported by enricher.py to run dedup BEFORE scoring each job.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone, timedelta

import requests

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)
import db

DEFAULT_OLLAMA       = "http://localhost:11434"
DEFAULT_EMBED_MODEL  = "nomic-embed-text"
DEFAULT_THRESHOLD    = 0.92
DEFAULT_WINDOW_DAYS  = 7


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[dedup {ts}] {msg}", flush=True)


# ─── Embedding ──────────────────────────────────────────────────────────────

def _build_signature(job: dict) -> str:
    """The text we embed. Keep it concise + load-bearing fields only."""
    title   = (job.get("title")   or "").strip()
    company = (job.get("company") or "").strip()
    desc    = (job.get("description") or "").strip()[:200]
    return f"{title}\n{company}\n{desc}"


def compute_embedding(text: str, ollama_url: str = DEFAULT_OLLAMA,
                      model: str = DEFAULT_EMBED_MODEL) -> list[float] | None:
    """POST to Ollama /api/embeddings. Returns None on failure."""
    if not text or not text.strip():
        return None
    try:
        r = requests.post(
            f"{ollama_url}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=60,
        )
        r.raise_for_status()
        emb = r.json().get("embedding") or []
        return emb if emb else None
    except Exception as exc:
        _log(f"Embedding error: {exc}")
        return None


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity. Returns 0.0 on dimension mismatch or zero vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot   = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# ─── Duplicate detection ────────────────────────────────────────────────────

def find_canonical_match(
    job: dict,
    job_embedding: list[float],
    candidates: list[dict],
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[str | None, float]:
    """Among `candidates` (recent jobs with embeddings, same company),
    find the highest cosine match >= threshold.

    Returns (duplicate_of_url, best_similarity). duplicate_of_url is None
    if no match exceeds the threshold. The chosen canonical is the OLDEST
    matching job, so later duplicates always point at the original.
    """
    if not job_embedding:
        return None, 0.0

    company = (job.get("company") or "").strip().lower()
    if not company:
        return None, 0.0

    best_url, best_sim = None, 0.0
    for cand in candidates:
        cand_company = (cand.get("company") or "").strip().lower()
        if cand_company != company:
            continue
        if cand.get("url") == job.get("url"):
            continue  # same row, skip
        cand_emb = cand.get("embedding") or []
        if isinstance(cand_emb, str):
            try:
                cand_emb = json.loads(cand_emb)
            except Exception:
                continue
        sim = cosine(job_embedding, cand_emb)
        if sim >= threshold and sim > best_sim:
            best_url, best_sim = cand.get("url"), sim
    return best_url, best_sim


def process_one_job(
    supabase_url: str,
    supabase_key: str,
    job: dict,
    ollama_url: str = DEFAULT_OLLAMA,
    threshold: float = DEFAULT_THRESHOLD,
    window_days: int = DEFAULT_WINDOW_DAYS,
    dry_run: bool = False,
) -> dict:
    """Compute embedding + check for duplicates + persist.

    Returns: {action: 'canonical' | 'duplicate' | 'no_embedding',
              similarity: float, duplicate_of_url: str | None}
    """
    text = _build_signature(job)
    emb  = compute_embedding(text, ollama_url=ollama_url)

    if not emb:
        return {"action": "no_embedding", "similarity": 0.0, "duplicate_of_url": None}

    # Fetch recent same-company jobs WITH embeddings
    candidates = db.get_recent_with_embeddings(
        supabase_url, supabase_key,
        company=(job.get("company") or ""),
        window_days=window_days,
        exclude_url=(job.get("url") or ""),
    )

    dup_url, sim = find_canonical_match(job, emb, candidates, threshold=threshold)

    if dry_run:
        return {
            "action": "duplicate" if dup_url else "canonical",
            "similarity": sim,
            "duplicate_of_url": dup_url,
        }

    db.mark_embedding(supabase_url, supabase_key, job.get("url", ""), emb,
                      duplicate_of_url=dup_url)
    return {
        "action": "duplicate" if dup_url else "canonical",
        "similarity": sim,
        "duplicate_of_url": dup_url,
    }


# ─── CLI: backfill mode ─────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-source dedup via Ollama embeddings")
    parser.add_argument("--ollama",     default=DEFAULT_OLLAMA,    help="Ollama base URL")
    parser.add_argument("--model",      default=DEFAULT_EMBED_MODEL, help="Embedding model name")
    parser.add_argument("--threshold",  type=float, default=DEFAULT_THRESHOLD,
                        help="Cosine similarity threshold for duplicates (default 0.92)")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS,
                        help="Only compare against jobs collected within N days")
    parser.add_argument("--reprocess-all", action="store_true",
                        help="Re-embed every job (otherwise: only jobs missing embedding)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute + compare but don't write to Supabase")
    parser.add_argument("--limit",     type=int, default=500, help="Max jobs to process")
    args = parser.parse_args()

    # Force UTF-8 stdout/stderr on Windows
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # Load Supabase creds (env → settings.json fallback)
    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    supabase_key = os.environ.get("SUPABASE_KEY", "").strip()
    if not supabase_url or not supabase_key:
        try:
            with open(os.path.join(_DIR, "..", "settings.json"), encoding="utf-8-sig") as f:
                cfg = json.load(f)
            supabase_url = supabase_url or cfg.get("SupabaseUrl", "")
            supabase_key = supabase_key or cfg.get("SupabaseKey", "")
        except Exception:
            pass

    if not supabase_url or not supabase_key:
        _log("ERROR: SUPABASE_URL / SUPABASE_KEY missing")
        sys.exit(1)

    if args.reprocess_all:
        jobs = db.get_all_jobs_for_dedup(supabase_url, supabase_key, limit=args.limit)
    else:
        jobs = db.get_jobs_without_embedding(supabase_url, supabase_key, limit=args.limit)

    _log(f"Processing {len(jobs)} job(s). threshold={args.threshold} window_days={args.window_days} dry_run={args.dry_run}")

    canonical = duplicate = failed = 0
    for i, job in enumerate(jobs, 1):
        title   = (job.get("title")   or "?")[:50]
        company = (job.get("company") or "?")[:25]
        result  = process_one_job(supabase_url, supabase_key, job,
                                  ollama_url=args.ollama, threshold=args.threshold,
                                  window_days=args.window_days, dry_run=args.dry_run)
        if result["action"] == "no_embedding":
            failed += 1
            _log(f"[{i}/{len(jobs)}] NO_EMB  {title} @ {company}")
        elif result["action"] == "duplicate":
            duplicate += 1
            _log(f"[{i}/{len(jobs)}] DUP({result['similarity']:.3f})  {title} @ {company}  -> {result['duplicate_of_url'][:60]}")
        else:
            canonical += 1
            _log(f"[{i}/{len(jobs)}] OK     {title} @ {company}")

    _log(f"Done. canonical={canonical}, duplicate={duplicate}, failed={failed}")


if __name__ == "__main__":
    main()
