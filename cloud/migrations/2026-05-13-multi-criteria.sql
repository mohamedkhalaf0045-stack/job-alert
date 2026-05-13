-- Phase 2: multi-criteria LLM scoring
-- Run this once in Supabase SQL Editor.
-- Idempotent: safe to re-run.

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS skills_match     smallint;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS experience_match smallint;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS location_match   smallint;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS seniority_match  smallint;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS matched_skills   jsonb DEFAULT '[]'::jsonb;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS missing_skills   jsonb DEFAULT '[]'::jsonb;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS red_flags        jsonb DEFAULT '[]'::jsonb;

-- Helpful index for the mobile/PowerShell UI sort-by-best-fit queries
CREATE INDEX IF NOT EXISTS jobs_skills_match_idx ON jobs (skills_match DESC);
