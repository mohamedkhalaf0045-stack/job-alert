-- Phase 5: auto-generated cover-letter drafts.
-- Run this once in Supabase SQL Editor. Idempotent.

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS cover_letter_draft        text;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS cover_letter_generated_at timestamptz;
