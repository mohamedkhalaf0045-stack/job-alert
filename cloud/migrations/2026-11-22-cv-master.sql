-- 2026-11-22 — private master CV for tailored CVs (cloud/cv_builder.py)
--
-- One row per CV (id 'default' for the owner). `data` holds the structured
-- CV JSON described in cloud/cv_builder.py.
--
-- RLS is enabled with NO policies, so the public anon key (shipped in the
-- apps) can neither read nor write it. Only the service_role key (GitHub
-- secret SUPABASE_SERVICE_ROLE_KEY) can, which the Easy Apply workflow uses.
-- Never store the CV in bot_state: that table is readable with the anon key.

create table if not exists public.cv_master (
  id          text primary key,
  data        jsonb not null,
  updated_at  timestamptz not null default now()
);

alter table public.cv_master enable row level security;

revoke all on public.cv_master from anon, authenticated;
