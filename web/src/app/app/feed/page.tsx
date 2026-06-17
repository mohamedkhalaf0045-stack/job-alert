import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'
import JobCard from '@/components/JobCard'
import type { Job } from '@/lib/types'
import Link from 'next/link'

async function getUserCVSkills(userId: string): Promise<string[]> {
  const admin = createAdminClient()

  // Try per-user web upload first
  const { data: perUser } = await admin
    .from('bot_state').select('value').eq('key', `cv_data:${userId}`).single()
  if (perUser?.value) {
    try {
      const cv = JSON.parse(perUser.value)
      if (Array.isArray(cv.skills) && cv.skills.length) return cv.skills
    } catch { /* fall through */ }
  }

  // Fall back to Windows desktop app global keys
  const { data } = await admin
    .from('bot_state').select('value').eq('key', 'cv_skills').single()
  if (data?.value) return data.value.split(',').map((s: string) => s.trim()).filter(Boolean)

  return []
}

export const dynamic = 'force-dynamic'

export default async function FeedPage({
  searchParams,
}: {
  searchParams: Promise<{ before?: string; as?: string }>
}) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')

  const { before, as: viewAsId } = await searchParams

  // Admin impersonation: if ?as=UUID is set and the requester is the admin,
  // show the feed as that user. Otherwise fall back to the logged-in user.
  const isAdmin = user.email === process.env.ADMIN_EMAIL
  const targetUserId = (isAdmin && viewAsId) ? viewAsId : user.id
  const isImpersonating = isAdmin && viewAsId && viewAsId !== user.id

  // Fetch the impersonated user's email for the banner (admin client, server-side only)
  let impersonatedEmail = ''
  if (isImpersonating) {
    const admin = createAdminClient()
    const { data: authUser } = await admin.auth.admin.getUserById(targetUserId)
    impersonatedEmail = authUser?.user?.email ?? targetUserId
  }

  // Gate: force onboarding if user has no keywords or locations set
  // Skip the gate when admin is impersonating (target may not have prefs yet)
  if (!isImpersonating) {
    const { data: prefs } = await supabase
      .from('user_preferences')
      .select('keywords, locations')
      .eq('user_id', user.id)
      .single()

    const hasKeywords = Array.isArray(prefs?.keywords) && prefs.keywords.length > 0
    const hasLocations = Array.isArray(prefs?.locations) && prefs.locations.length > 0
    if (!hasKeywords || !hasLocations) redirect('/onboarding')
  }

  const admin = createAdminClient()
  const { data: jobs, error } = await admin.rpc('user_jobs_feed', {
    p_user:  targetUserId,
    p_limit: 20,
    ...(before ? { p_before: before } : {}),
  })

  if (error) {
    return (
      <div>
        <h1 className="text-xl font-bold mb-4">Your feed</h1>
        <div className="bg-white rounded-xl border p-6 text-sm">
          <p className="text-red-600 font-medium">Could not load feed</p>
          <p className="text-gray-500 mt-1">{error.message}</p>
          <p className="text-gray-400 mt-2 text-xs">
            Make sure the Phase 1 migrations (2026-06-11-*.sql) have been applied in Supabase.
          </p>
        </div>
      </div>
    )
  }

  // Sort newest-first; jobs in the same scrape batch can share near-identical
  // date_collected values so Postgres order is non-deterministic without a tiebreaker.
  const jobList = ((jobs as Job[]) ?? [])
    .sort((a, b) => new Date(b.date_collected).getTime() - new Date(a.date_collected).getTime())
  const nextCursor = jobList.length === 20 ? jobList[jobList.length - 1].date_collected : null
  const userSkills = await getUserCVSkills(targetUserId)

  // Group jobs by recency using server-side time (UTC, consistent with date_collected)
  const now = Date.now()
  const H24 = 24 * 60 * 60 * 1000
  const H48 = 48 * 60 * 60 * 1000

  function ageGroup(job: Job): 'today' | 'yesterday' | 'older' {
    const age = now - new Date(job.date_collected).getTime()
    if (age < H24)  return 'today'
    if (age < H48)  return 'yesterday'
    return 'older'
  }

  const sections: { label: string; key: string; jobs: Job[] }[] = [
    { label: 'Today',     key: 'today',     jobs: jobList.filter(j => ageGroup(j) === 'today') },
    { label: 'Yesterday', key: 'yesterday', jobs: jobList.filter(j => ageGroup(j) === 'yesterday') },
    { label: 'Older',     key: 'older',     jobs: jobList.filter(j => ageGroup(j) === 'older') },
  ].filter(s => s.jobs.length > 0)

  if (!jobList.length && !before) {
    return (
      <div>
        <h1 className="text-xl font-bold mb-4">Your feed</h1>
        <div className="bg-white rounded-xl border p-8 text-center text-gray-500">
          <p className="font-medium mb-2">No matching jobs yet</p>
          <p className="text-sm">
            Either no jobs matching your preferences have been scraped yet, or your
            keywords/locations don&apos;t match the current job pool.
          </p>
          <p className="text-sm mt-3">
            Check your{' '}
            <Link href="/app/settings" className="text-blue-600 underline">
              settings
            </Link>{' '}
            or wait for the next scrape run (every 5 min).
          </p>
        </div>
      </div>
    )
  }

  return (
    <div>
      {isImpersonating && (
        <div className="mb-4 flex items-center justify-between gap-3 px-4 py-2.5 bg-amber-50 border border-amber-200 rounded-xl text-sm">
          <span className="text-amber-800">
            Viewing feed as <strong>{impersonatedEmail}</strong>
          </span>
          <Link href="/app/feed" className="text-xs font-medium text-amber-700 hover:underline shrink-0">
            Exit
          </Link>
        </div>
      )}
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold">Your feed</h1>
        {before && (
          <Link href={isImpersonating ? `/app/feed?as=${viewAsId}` : '/app/feed'} className="text-xs text-blue-600 hover:underline">
            ← Back to latest
          </Link>
        )}
      </div>

      <div className="space-y-6">
        {sections.map(section => (
          <div key={section.key}>
            <div className="flex items-center gap-3 mb-3">
              <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full ${
                section.key === 'today'
                  ? 'bg-[var(--success-bg)] text-[var(--success)]'
                  : section.key === 'yesterday'
                    ? 'bg-[var(--warn-bg)] text-[var(--warn)]'
                    : 'bg-[var(--border-soft)] text-[var(--muted)]'
              }`}>
                {section.label}
              </span>
              <span className="text-xs text-[var(--meta)]">{section.jobs.length} job{section.jobs.length !== 1 ? 's' : ''}</span>
              <div className="flex-1 h-px bg-[var(--border)]" />
            </div>
            <div className="space-y-3">
              {section.jobs.map(job => (
                <JobCard
                  key={job.job_id}
                  job={job}
                  userSkills={userSkills}
                  isNew={section.key === 'today'}
                />
              ))}
            </div>
          </div>
        ))}
      </div>

      {nextCursor ? (
        <div className="mt-6 text-center">
          <Link
            href={`/app/feed?before=${encodeURIComponent(nextCursor)}${isImpersonating ? `&as=${viewAsId}` : ''}`}
            className="inline-block px-5 py-2 bg-white border rounded-lg text-sm hover:bg-gray-50 transition"
          >
            Load older jobs →
          </Link>
        </div>
      ) : (
        jobList.length > 0 && (
          <p className="mt-6 text-center text-sm text-gray-400">
            That&apos;s all for now — check back after the next scrape.
          </p>
        )
      )}
    </div>
  )
}
