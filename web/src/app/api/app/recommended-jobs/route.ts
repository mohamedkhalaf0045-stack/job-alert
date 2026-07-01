import { NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'
import type { Job } from '@/lib/types'

// GET /api/app/recommended-jobs — "Recommended for you"
// Calls the existing user_jobs_feed() RPC (same filtering as the main feed)
// then excludes any job the user has already seen/interacted with, i.e. any
// job_id present in user_job_interactions for this user (saved, applied,
// dismissed, hidden, or any HR-tracked status). Returns a small top-N slice.
export async function GET() {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const admin = createAdminClient()

    // Pull a wider slice than we need since we filter seen jobs client-side
    // (RPC already excludes dismissed/hidden, but we also want to exclude
    // anything the user has any interaction row for at all — "seen").
    const { data: jobs, error } = await admin.rpc('user_jobs_feed', {
      p_user: user.id,
      p_limit: 60,
    })

    if (error) throw error

    const { data: interactions } = await admin
      .from('user_job_interactions')
      .select('job_id')
      .eq('user_id', user.id)

    const seenIds = new Set((interactions ?? []).map(i => i.job_id))

    const recommended = ((jobs as Job[]) ?? [])
      .filter(j => !seenIds.has(j.job_id))
      .slice(0, 10)

    return NextResponse.json({ jobs: recommended })
  } catch (error) {
    console.error('GET /api/app/recommended-jobs error:', error)
    return NextResponse.json({ error: 'Failed to fetch recommended jobs' }, { status: 500 })
  }
}
