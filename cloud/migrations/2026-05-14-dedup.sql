-- Phase 3: cross-source deduplication
-- Run this once in Supabase SQL Editor.
-- Idempotent: safe to re-run.

-- 768-dim float vector from nomic-embed-text, stored as jsonb for portability
-- (avoids needing the pgvector extension at this scale).
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS embedding         jsonb;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS duplicate_of_url  text;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS dedup_checked_at  timestamptz;

-- Lookup index: when checking for duplicates we scan recent jobs by company
-- and date_collected; this index speeds the candidate-narrowing step.
CREATE INDEX IF NOT EXISTS jobs_company_collected_idx
    ON jobs (company, date_collected DESC);

CREATE INDEX IF NOT EXISTS jobs_duplicate_of_idx
    ON jobs (duplicate_of_url)
    WHERE duplicate_of_url IS NOT NULL;
