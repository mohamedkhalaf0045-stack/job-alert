-- Multi-user website — Phase 1d: per-user alert delivery log
-- Run once in Supabase SQL Editor (after the jobs table exists).
-- Idempotent: safe to re-run.
--
-- One row per (user, job, channel) that has been alerted. This is the
-- "alert each job at most once per channel" guarantee and the watermark for
-- "new since last digest". Replaces the global jobs.telegram_sent_at for the
-- multi-user senders (cloud/user_alerts.py).

create table if not exists public.user_alert_log (
    user_id  uuid not null references auth.users(id) on delete cascade,
    job_id   text not null references public.jobs(job_id) on delete cascade,
    channel  text not null check (channel in ('email', 'telegram')),
    sent_at  timestamptz not null default now(),
    primary key (user_id, job_id, channel)
);

create index if not exists ual_user_sent_idx on public.user_alert_log (user_id, sent_at desc);

alter table public.user_alert_log enable row level security;

-- Users may READ their own delivery history (for an in-app "alerts sent" view).
drop policy if exists ual_select_own on public.user_alert_log;
create policy ual_select_own on public.user_alert_log
    for select to authenticated using (user_id = auth.uid());

-- NOTE: deliberately NO insert/update/delete policy. Only the service_role
-- alert sender writes this table, so a client cannot fake "already alerted"
-- (which would suppress real alerts).
