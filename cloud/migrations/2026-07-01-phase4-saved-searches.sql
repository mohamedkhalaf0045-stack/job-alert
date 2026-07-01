-- Phase 4: Saved searches
-- Run once in Supabase SQL Editor.
-- Idempotent: safe to re-run.
--
-- Lets a candidate save a named combination of keywords/locations/min_score
-- so it can be re-applied later from the feed page without retyping filters.

create table if not exists public.saved_searches (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid not null references auth.users(id) on delete cascade,
    name       text not null,
    keywords   text[] not null default '{}',
    locations  text[] not null default '{}',
    min_score  int,
    created_at timestamptz not null default now()
);

create index if not exists saved_searches_user_id_idx on public.saved_searches(user_id);
create index if not exists saved_searches_created_at_idx on public.saved_searches(created_at desc);

alter table public.saved_searches enable row level security;

-- Each user reads/writes only their own saved searches.
drop policy if exists saved_searches_all_own on public.saved_searches;
create policy saved_searches_all_own on public.saved_searches
    for all to authenticated
    using (user_id = auth.uid())
    with check (user_id = auth.uid());
