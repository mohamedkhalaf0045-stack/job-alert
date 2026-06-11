-- Multi-user website — Phase 1b: per-user search preferences
-- Run once in Supabase SQL Editor (after 2026-06-11-auth-profiles.sql).
-- Idempotent: safe to re-run.
--
-- user_preferences is the per-user filter spec applied to the shared global
-- `jobs` pool (see public.user_jobs_feed in 2026-06-11-jobs-rls-multiuser.sql).
-- Arrays mirror the comma-split lists the existing worker already uses
-- (setting_keywords / setting_location).

create table if not exists public.user_preferences (
    user_id          uuid primary key references auth.users(id) on delete cascade,
    keywords         text[]  not null default '{}',   -- OR-matched include terms
    locations        text[]  not null default '{}',   -- OR-matched location terms
    exclude_keywords text[]  not null default '{}',   -- any match => drop the job
    min_score        smallint,                        -- null = no AI-score floor (also shows unscored jobs)
    sources          text[],                          -- null/empty = all sources
    alert_frequency  text not null default 'daily'
                     check (alert_frequency in ('instant', 'daily', 'off')),
    digest_hour      smallint not null default 8 check (digest_hour between 0 and 23),
    paused           boolean not null default false,
    updated_at       timestamptz not null default now()
);

alter table public.user_preferences enable row level security;

-- Each user reads/writes only their own preferences row.
drop policy if exists prefs_all_own on public.user_preferences;
create policy prefs_all_own on public.user_preferences
    for all to authenticated
    using (user_id = auth.uid())
    with check (user_id = auth.uid());
