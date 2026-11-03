-- Enable RLS on telegram_claude_history (Supabase advisor: "RLS Disabled in Public", critical).
-- No policies on purpose: only the service_role key reads/writes this table
-- (web Telegram webhook via createAdminClient, cloud/user_alerts.py and cloud/cleanup.py
-- in GitHub Actions), and service_role bypasses RLS. anon/authenticated get no access.
-- Applied to the live project 2026-11-03.
alter table public.telegram_claude_history enable row level security;
