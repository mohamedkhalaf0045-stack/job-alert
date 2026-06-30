-- Data retention policy + pg_cron scheduled cleanup
-- Run once in Supabase SQL Editor.
--
-- Retention windows:
--   jobs (status != saved/applied)  : 60 days
--   jobs (saved or applied)         : forever
--   user_alert_log                  : 90 days (cascades from job deletes + direct cleanup)
--   telegram_claude_history         : 30 days
--
-- Also fixes the user_alert_log channel check constraint to include 'fcm'.

-- ── 1. Fix FCM channel constraint ─────────────────────────────────────────────
-- Drop the old constraint that only allows email|telegram, add fcm.
ALTER TABLE public.user_alert_log
  DROP CONSTRAINT IF EXISTS user_alert_log_channel_check;

ALTER TABLE public.user_alert_log
  ADD CONSTRAINT user_alert_log_channel_check
  CHECK (channel IN ('email', 'telegram', 'fcm'));

-- ── 2. Index to make retention deletes fast ───────────────────────────────────
CREATE INDEX IF NOT EXISTS jobs_date_status_idx
  ON public.jobs (date_collected, status)
  WHERE status NOT IN ('saved', 'applied');

-- ── 3. One-time immediate cleanup ─────────────────────────────────────────────
-- Delete old jobs (not saved/applied) older than 60 days.
-- ON DELETE CASCADE on user_alert_log.job_id cleans alert log rows automatically.
DELETE FROM public.jobs
WHERE status NOT IN ('saved', 'applied')
  AND date_collected < NOW() - INTERVAL '60 days';

-- Delete old alert log entries whose jobs were already deleted (FK cascade missed
-- nothing if above ran first, but belt-and-suspenders for any orphaned rows).
DELETE FROM public.user_alert_log
WHERE sent_at < NOW() - INTERVAL '90 days';

-- Delete old Telegram conversation history.
DELETE FROM public.telegram_claude_history
WHERE created_at < NOW() - INTERVAL '30 days';

-- ── 4. pg_cron scheduled cleanup (runs weekly — Sunday 02:00 UTC) ─────────────
-- Requires the pg_cron extension. Enable it first:
--   Supabase Dashboard → Database → Extensions → search "pg_cron" → Enable
--
-- After enabling, run this block:

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN

    -- Remove old job if it exists (idempotent re-run)
    PERFORM cron.unschedule('cleanup-old-jobs')
      WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'cleanup-old-jobs');
    PERFORM cron.unschedule('cleanup-alert-log')
      WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'cleanup-alert-log');
    PERFORM cron.unschedule('cleanup-telegram-history')
      WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'cleanup-telegram-history');

    -- Jobs cleanup — Sunday 02:00 UTC
    PERFORM cron.schedule(
      'cleanup-old-jobs',
      '0 2 * * 0',
      $$
        DELETE FROM public.jobs
        WHERE status NOT IN ('saved', 'applied')
          AND date_collected < NOW() - INTERVAL '60 days';
      $$
    );

    -- Alert log cleanup — Sunday 02:05 UTC (after jobs cleanup so cascade runs first)
    PERFORM cron.schedule(
      'cleanup-alert-log',
      '5 2 * * 0',
      $$
        DELETE FROM public.user_alert_log
        WHERE sent_at < NOW() - INTERVAL '90 days';
      $$
    );

    -- Telegram history cleanup — Sunday 02:10 UTC
    PERFORM cron.schedule(
      'cleanup-telegram-history',
      '10 2 * * 0',
      $$
        DELETE FROM public.telegram_claude_history
        WHERE created_at < NOW() - INTERVAL '30 days';
      $$
    );

    RAISE NOTICE 'pg_cron jobs scheduled successfully.';
  ELSE
    RAISE NOTICE 'pg_cron not enabled — skipping schedule setup. Enable via Dashboard → Database → Extensions → pg_cron, then re-run this block.';
  END IF;
END
$$;
