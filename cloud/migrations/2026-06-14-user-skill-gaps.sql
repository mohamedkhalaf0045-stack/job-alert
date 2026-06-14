-- user_skill_gaps: Track skills that user is missing but appear in matching jobs
-- Used by skill gap detection feature to show learning opportunities

CREATE TABLE IF NOT EXISTS public.user_skill_gaps (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  skill TEXT NOT NULL,
  frequency INT NOT NULL DEFAULT 0, -- how many jobs require this skill
  job_count INT NOT NULL DEFAULT 0, -- number of matching jobs with this skill
  analyzed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(user_id, skill)
);

CREATE INDEX idx_user_skill_gaps_user_id ON public.user_skill_gaps(user_id);
CREATE INDEX idx_user_skill_gaps_frequency ON public.user_skill_gaps(frequency DESC);

-- RLS: Users can only see their own skill gaps
ALTER TABLE public.user_skill_gaps ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own skill gaps" ON public.user_skill_gaps
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own skill gaps" ON public.user_skill_gaps
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own skill gaps" ON public.user_skill_gaps
  FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- Allow service role to write skill gaps (from API)
CREATE POLICY "Service role can manage all skill gaps" ON public.user_skill_gaps
  FOR ALL USING (TRUE) WHEN (current_setting('role') = 'authenticated');
