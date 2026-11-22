-- 2026-11-22 — security phase 1 (does not break the PC worker or the apps)
--
-- Findings (2026-11-22 audit): anyone holding the public anon key (it is in
-- the APK and this repo) could read and change every bot_state row,
-- including apply requests (name, email, phone, salary) and per-user CV data
-- (cv_data:<user_id>), and could repoint the app's update download
-- (update_apk_url). Any account that signed up could do the same.
--
-- This phase:
--   * private keys (apply_req_*, cv_data:*) — only the admin and service_role
--   * update_* keys (app update link) — write: admin and service_role only
--   * every other key keeps anon read/write for now, because the PC worker and
--     desktop GUI still use the anon key (phase 2 moves them to service_role)
--   * SECURITY DEFINER trigger functions are no longer callable over the API
--
-- The admin is whoever is listed in public.app_admins (user ids only; the
-- owner's id is inserted directly in Supabase, never committed here).

create table if not exists public.app_admins (
  user_id uuid primary key
);
alter table public.app_admins enable row level security;   -- no policies: service_role only
revoke all on public.app_admins from anon, authenticated;

create or replace function public.is_app_admin()
returns boolean
language sql stable security definer set search_path = ''
as $$
  select exists (
    select 1 from public.app_admins a
    join auth.users u on u.id = a.user_id
    where a.user_id = auth.uid() and u.email_confirmed_at is not null
  );
$$;
revoke all on function public.is_app_admin() from public;
grant execute on function public.is_app_admin() to anon, authenticated;

create or replace function public.bot_state_private_key(k text)
returns boolean language sql immutable set search_path = ''
as $$ select k like 'apply\_req\_%' or k like 'cv\_data:%' $$;

create or replace function public.bot_state_admin_write_key(k text)
returns boolean language sql immutable set search_path = ''
as $$ select public.bot_state_private_key(k) or k like 'update\_%' $$;

drop policy if exists anon_full_access_bot_state on public.bot_state;
drop policy if exists authenticated_full_access_bot_state on public.bot_state;

create policy bot_state_anon_select on public.bot_state for select to anon
  using (not public.bot_state_private_key(key));
create policy bot_state_anon_insert on public.bot_state for insert to anon
  with check (not public.bot_state_admin_write_key(key));
create policy bot_state_anon_update on public.bot_state for update to anon
  using (not public.bot_state_admin_write_key(key))
  with check (not public.bot_state_admin_write_key(key));
create policy bot_state_anon_delete on public.bot_state for delete to anon
  using (not public.bot_state_admin_write_key(key));

create policy bot_state_auth_select on public.bot_state for select to authenticated
  using (not public.bot_state_private_key(key) or public.is_app_admin());
create policy bot_state_auth_insert on public.bot_state for insert to authenticated
  with check (not public.bot_state_admin_write_key(key) or public.is_app_admin());
create policy bot_state_auth_update on public.bot_state for update to authenticated
  using (not public.bot_state_admin_write_key(key) or public.is_app_admin())
  with check (not public.bot_state_admin_write_key(key) or public.is_app_admin());
create policy bot_state_auth_delete on public.bot_state for delete to authenticated
  using (not public.bot_state_admin_write_key(key) or public.is_app_admin());

-- Trigger functions run as triggers without EXECUTE; nobody should call them
-- over /rest/v1/rpc.
revoke execute on function public.handle_new_user() from public, anon, authenticated;
revoke execute on function public.sync_job_posting_to_jobs() from public, anon, authenticated;
-- Only the web server (service_role) calls this.
revoke execute on function public.check_message_rate_limit(uuid, integer) from public, anon, authenticated;
