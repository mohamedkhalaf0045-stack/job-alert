-- Ensure the description column exists on jobs.
-- The enricher has been writing to it since Phase 1, but it was never added
-- via a tracked migration. Safe to re-run (IF NOT EXISTS).

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS description text;
