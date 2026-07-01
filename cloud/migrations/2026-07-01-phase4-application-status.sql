-- Phase 4: Application tracking status — extend user_job_interactions.status
-- Run after 2026-06-11-user-job-interactions.sql
-- Idempotent: safe to re-run.
--
-- Adds HR-facing / pipeline statuses so employers (or future HR tooling) can
-- move a candidate's interaction through a tracked application lifecycle,
-- beyond the original candidate-only saved/applied/dismissed/hidden set.

alter table public.user_job_interactions
    drop constraint if exists user_job_interactions_status_check;

alter table public.user_job_interactions
    add constraint user_job_interactions_status_check
    check (status in (
        'saved', 'applied', 'dismissed', 'hidden',
        'viewed_by_hr', 'in_review', 'rejected', 'matched'
    ));
