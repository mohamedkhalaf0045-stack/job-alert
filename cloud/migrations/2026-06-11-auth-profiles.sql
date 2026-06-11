-- Multi-user website — Phase 1a: user profiles + auto-seed trigger
-- Run this once in Supabase SQL Editor. Idempotent: safe to re-run.
--
-- IMPORTANT: apply all 2026-06-11-*.sql migrations together (in filename
-- order) BEFORE enabling sign-ups. The handle_new_user() trigger below seeds
-- both profiles and user_preferences, so user_preferences must exist before
-- the first signup fires the trigger.
--
-- profiles holds one row per authenticated user (1:1 with auth.users). It is
-- the per-user contact + delivery-preference record. The global `jobs` pool is
-- shared by everyone; everything user-specific lives in these new tables.

create table if not exists public.profiles (
    id               uuid primary key references auth.users(id) on delete cascade,
    display_name     text,
    email            text,
    timezone         text not null default 'Asia/Dubai',   -- IANA tz, drives digest send time
    telegram_chat_id text,                                 -- null = Telegram alerts off
    alert_email      boolean not null default true,
    alert_telegram   boolean not null default false,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);

alter table public.profiles enable row level security;

-- Each user can see and edit only their own profile row.
drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own on public.profiles
    for select to authenticated using (id = auth.uid());

drop policy if exists profiles_insert_own on public.profiles;
create policy profiles_insert_own on public.profiles
    for insert to authenticated with check (id = auth.uid());

drop policy if exists profiles_update_own on public.profiles;
create policy profiles_update_own on public.profiles
    for update to authenticated using (id = auth.uid()) with check (id = auth.uid());

-- Auto-seed profile + default preferences on signup.
-- SECURITY DEFINER: the trigger runs at signup with no JWT context, so it must
-- bypass RLS to insert the seed rows.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (id, email)
        values (new.id, new.email)
        on conflict (id) do nothing;
    insert into public.user_preferences (user_id)
        values (new.id)
        on conflict (user_id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();
