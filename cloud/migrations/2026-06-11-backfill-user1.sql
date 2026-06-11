-- Multi-user website — Phase 1f: backfill the owner as user #1
-- Run ONCE in Supabase SQL Editor, AFTER:
--   (a) all other 2026-06-11-*.sql migrations are applied, and
--   (b) the owner has signed up on the website (so an auth.users row + the
--       auto-seeded profiles/user_preferences rows exist).
--
-- Edit the two placeholders below, then run. Idempotent: safe to re-run.
--   v_owner: your auth user id — Supabase Dashboard → Authentication → Users.
--   v_tg:    your Telegram chat id (e.g. 941885724), or leave the placeholder
--            to skip enabling Telegram.

do $$
declare
    v_owner uuid := '<OWNER_UUID>';
    v_tg    text := '<TELEGRAM_CHAT_ID>';
    v_kw    text;
    v_loc   text;
    v_excl  text;
    v_min   text;
begin
    -- Pull the existing single-user settings from bot_state.
    select value into v_kw   from public.bot_state where key = 'setting_keywords';
    select value into v_loc  from public.bot_state where key = 'setting_location';
    select value into v_excl from public.bot_state where key = 'setting_exclude_keywords';
    select value into v_min  from public.bot_state where key = 'setting_llm_min_score';

    -- Map them onto the owner's preferences (comma lists -> trimmed arrays).
    update public.user_preferences set
        keywords         = coalesce(array(select trim(x) from unnest(string_to_array(v_kw,   ',')) x where trim(x) <> ''), '{}'),
        locations        = coalesce(array(select trim(x) from unnest(string_to_array(v_loc,  ',')) x where trim(x) <> ''), '{}'),
        exclude_keywords = coalesce(array(select trim(x) from unnest(string_to_array(v_excl, ',')) x where trim(x) <> ''), '{}'),
        min_score        = nullif(v_min, '')::smallint,
        alert_frequency  = 'instant',
        updated_at       = now()
    where user_id = v_owner;

    -- Enable Telegram for the owner if a chat id was provided.
    update public.profiles set
        telegram_chat_id = nullif(v_tg, '<TELEGRAM_CHAT_ID>'),
        alert_telegram   = (v_tg <> '<TELEGRAM_CHAT_ID>'),
        timezone         = 'Asia/Dubai'
    where id = v_owner;

    -- Carry over the owner's existing triage from the global jobs.status.
    insert into public.user_job_interactions (user_id, job_id, status)
        select v_owner, job_id, status
          from public.jobs
         where status in ('saved', 'applied', 'dismissed')
        on conflict (user_id, job_id) do nothing;
end $$;
