-- Add FCM device token to profiles so Python worker can push notifications
-- to the user's phone even when the app is closed.
-- Run once in Supabase SQL Editor.

ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS fcm_token TEXT;

-- Allow signed-in users to update their own FCM token.
-- (profiles table may already have a broad update policy — this is additive)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'profiles'
      AND policyname = 'profiles_own_fcm_token_update'
  ) THEN
    EXECUTE $policy$
      CREATE POLICY profiles_own_fcm_token_update
        ON public.profiles
        FOR UPDATE
        TO authenticated
        USING  (id = auth.uid())
        WITH CHECK (id = auth.uid())
    $policy$;
  END IF;
END
$$;
