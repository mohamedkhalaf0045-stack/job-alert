-- Phase 4: Skill-based matching — structured skills on employer job postings
-- Run after 2026-07-01-phase1-employers.sql
-- Idempotent: safe to re-run.
--
-- Jobs already carry matched_skills / missing_skills (Groq enrichment, existing
-- columns on public.jobs). This migration lets employers declare structured
-- required skills on their own postings, independent of the scraped-job pipeline.

alter table public.job_postings
    add column if not exists requirements_skills text[] default '{}';

comment on column public.job_postings.requirements_skills is
    'Employer-declared list of required/desired skills for this posting (structured, distinct from the free-text requirements column).';
