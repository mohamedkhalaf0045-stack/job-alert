-- Add keyword_expansions JSONB column to user_preferences
-- Stores semantic expansions of keywords for better job matching coverage

ALTER TABLE public.user_preferences
ADD COLUMN IF NOT EXISTS keyword_expansions JSONB DEFAULT '{}'::jsonb;

-- Example structure:
-- {
--   "azure administrator": {
--     "original": "Azure Administrator",
--     "variations": ["Cloud Administrator", "Infrastructure Engineer", ...],
--     "related_skills": ["Azure", "Cloud", "Windows Server", ...],
--     "generated_at": "2026-06-14T..."
--   }
-- }
