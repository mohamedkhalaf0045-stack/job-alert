-- Multi-user website — Phase 1g: jobs RLS write-lockdown (SECURITY FIX)
-- Run once in Supabase SQL Editor. Idempotent: safe to re-run.
--
-- ⚠️ PRECONDITION — READ BEFORE RUNNING ⚠️
-- This makes the `jobs` table READ-ONLY for the anon + authenticated roles;
-- only the service_role key can write. If your scraper/enricher still use the
-- ANON key, applying this WILL STOP JOB COLLECTION (their INSERTs get denied).
--
-- Before running, confirm the pipeline uses the service_role key:
--   • GitHub Actions secret  SUPABASE_KEY  = the service_role key
--   • local settings.json    SupabaseKey   = the service_role key
-- (This is the same "switch to service_role" step noted in
--  2026-06-10-bot-state-rls-lockdown.sql.)
--
-- Verify the current key's role first (decode the JWT payload's "role" claim),
-- or run the test at the bottom of this file AFTER applying.
--
-- Also note: this intentionally breaks the Flutter mobile app's anon writes to
-- jobs.status / easy-apply rows. Those are owner-only features — update the app
-- to authenticate, or retire them, separately.

alter table public.jobs enable row level security;

-- Replace the wide-open policy (anyone with the public anon key could
-- insert/update/DELETE every job) with read-only access for everyone.
drop policy if exists anon_full_access_jobs on public.jobs;
drop policy if exists jobs_read_all          on public.jobs;

create policy jobs_read_all on public.jobs
    for select using (true);

-- No INSERT/UPDATE/DELETE policy => writes denied for anon + authenticated.
-- service_role bypasses RLS entirely, so the pipeline keeps writing.

-- ── Post-apply verification ──────────────────────────────────────────────────
-- With the ANON key (not service_role), this INSERT must now FAIL with a
-- row-level-security violation. If it SUCCEEDS, the lockdown did not take
-- effect — investigate before relying on it.
--   insert into public.jobs (job_id, title, company, url, source)
--   values ('rls_probe', 'probe', 'probe', 'https://example.com/rls_probe', 'probe');
-- And confirm the pipeline still inserts: trigger a scan and check worker logs
-- for a successful "inserted=N" line.
