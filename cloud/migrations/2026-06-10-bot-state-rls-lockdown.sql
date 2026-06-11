-- 2026-06-10 — bot_state RLS lockdown (security-incident remediation)
--
-- WHY: the anon key ships inside the mobile APK and is committed in the
-- public repo (mobile/lib/config.dart), so it is effectively public. Until
-- now anon could both READ and WRITE every bot_state row — that is how the
-- secrets leaked. The apps no longer store secrets in bot_state; this
-- migration makes anon READ-ONLY so an attacker with the public key can
-- no longer corrupt settings or plant data.
--
-- HOW TO RUN: Supabase -> SQL Editor -> paste this file -> Run.
--
-- REQUIRED FOLLOW-UPS (writes now need the service_role key):
--   1. GitHub repo -> Settings -> Secrets and variables -> Actions:
--      set SUPABASE_KEY to the *service_role* key (Supabase -> Project
--      Settings -> API). The cloud worker writes worker_last_run,
--      telegram_offset, apply_req_* updates, etc., so it needs write access.
--      service_role lives only in GitHub Secrets — never in any app.
--   2. Local desktop GUI/worker: switch SupabaseKey in settings.json to the
--      service_role key so "Save settings" keeps syncing non-secret settings
--      and the dashboard keeps writing state. settings.json is gitignored,
--      so the key stays on your machine.
--   3. Mobile app: keeps the anon key and becomes READ-ONLY for bot_state.
--      Consequences until the Edge Function refactor lands:
--        - "Save settings" from the phone will not persist
--        - Easy Apply requests from the phone (apply_req_* rows) will fail
--      Job browsing and the GitHub scan/cancel buttons are unaffected
--      (jobs-table policies and the GitHub API are separate).
--
-- VERIFY AFTER RUNNING (should return HTTP 401/403, NOT 200/201):
--   curl -X POST "https://<project>.supabase.co/rest/v1/bot_state" \
--     -H "apikey: <ANON_KEY>" -H "Authorization: Bearer <ANON_KEY>" \
--     -H "Content-Type: application/json" \
--     -d '[{"key":"rls_probe","value":"x"}]'

-- Drop every existing bot_state policy (names varied across setups),
-- then grant anon SELECT only.
do $$
declare p record;
begin
  for p in
    select policyname from pg_policies
    where schemaname = 'public' and tablename = 'bot_state'
  loop
    execute format('drop policy %I on public.bot_state', p.policyname);
  end loop;
end $$;

alter table public.bot_state enable row level security;

create policy anon_read_bot_state
  on public.bot_state for select
  to anon
  using (true);

-- No INSERT/UPDATE/DELETE policies for anon = all anon writes are denied.
-- service_role bypasses RLS entirely, so workers using it are unaffected.
