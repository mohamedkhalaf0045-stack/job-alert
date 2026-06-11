-- Multi-user website — Phase 1c: per-user job triage state
-- Run once in Supabase SQL Editor (after the jobs table exists).
-- Idempotent: safe to re-run.
--
-- This REPLACES the global jobs.status for per-user purposes. The shared `jobs`
-- pool keeps its own status column (written by the single-user pipeline), but
-- each user's saved/applied/dismissed/hidden state lives here, one row per
-- (user, job). Absence of a row == untriaged ("new") — we never store a row
-- just for "seen", so this table stays small.

create table if not exists public.user_job_interactions (
    user_id    uuid not null references auth.users(id) on delete cascade,
    job_id     text not null references public.jobs(job_id) on delete cascade,
    status     text not null check (status in ('saved', 'applied', 'dismissed', 'hidden')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (user_id, job_id)
);

create index if not exists uji_user_status_idx on public.user_job_interactions (user_id, status);
create index if not exists uji_job_idx          on public.user_job_interactions (job_id);

alter table public.user_job_interactions enable row level security;

-- Each user reads/writes only their own interaction rows.
drop policy if exists uji_all_own on public.user_job_interactions;
create policy uji_all_own on public.user_job_interactions
    for all to authenticated
    using (user_id = auth.uid())
    with check (user_id = auth.uid());
