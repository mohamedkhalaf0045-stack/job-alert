-- 2026-06-10 — Phase 24: salary insights
--
-- Adds salary columns to the jobs table:
--   * posted salary captured by scrapers (Adzuna provides salary_min/max),
--   * average market salary for the title, looked up by the enricher
--     (Adzuna salary statistics first, scoring-LLM estimate as fallback)
--     and shown in Telegram alerts.
--
-- HOW TO RUN: Supabase -> SQL Editor -> paste this file -> Run.
-- The code degrades gracefully until this runs (salary is simply skipped),
-- but nothing is persisted or shown from DB rows without these columns.
--
-- salary_period: 'year' (Adzuna annualised) or 'month' (AI estimate).
-- salary_source: 'posted' | 'adzuna_est' | 'adzuna_market' | 'ai_estimate'.

alter table public.jobs
  add column if not exists salary_min      numeric,
  add column if not exists salary_max      numeric,
  add column if not exists salary_avg      numeric,
  add column if not exists salary_currency text,
  add column if not exists salary_period   text,
  add column if not exists salary_source   text;
