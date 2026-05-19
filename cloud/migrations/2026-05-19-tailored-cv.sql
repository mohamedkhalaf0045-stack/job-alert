-- Tailored CV per job: store an AI-generated CV draft customised for each role.
-- Run once in Supabase SQL Editor.  Idempotent.

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS tailored_cv_draft        text;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS tailored_cv_generated_at timestamptz;
