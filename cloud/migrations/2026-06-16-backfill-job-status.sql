-- Jobs inserted before the `status` column existed (or before its default was set)
-- have status = NULL and are invisible to the enricher's get_unscored_jobs query
-- (which filters .eq("status", "new")).  Backfill them so the enricher can score them.
-- Safe to re-run: only touches rows where both status and llm_score are NULL.

UPDATE jobs
   SET status = 'new'
 WHERE status IS NULL
   AND llm_score IS NULL;
