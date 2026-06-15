import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'
import JobCard from '@/components/JobCard'
import type { Job } from '@/lib/types'
import Link from 'next/link'

export const dynamic = 'force-dynamic'

export default async function FeedPage({
  searchParams,
}: {
  searchParams: Promise<{ before?: string }>
}) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')

  // Gate: force onboarding if user has no keywords or locations set
  const { data: prefs } = await supabase
    .from('user_preferences')
    .select('keywords, locations')
    .eq('user_id', user.id)
    .single()

  const hasKeywords = Array.isArray(prefs?.keywords) && prefs.keywords.length > 0
  const hasLocations = Array.isArray(prefs?.locations) && prefs.locations.length > 0
  if (!hasKeywords || !hasLocations) redirect('/onboarding')

  const { before } = await searchParams

  const { data: jobs, error } = await supabase.rpc('user_jobs_feed', {
    p_user:  user.id,
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

  const jobList = (jobs as Job[]) ?? []
  const nextCursor = jobList.length === 20 ? jobList[jobList.length - 1].date_collected : null

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
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold">Your feed</h1>
        {before && (
          <Link href="/app/feed" className="text-xs text-blue-600 hover:underline">
            ← Back to latest
          </Link>
        )}
      </div>

      <div className="space-y-3">
        {jobList.map(job => (
          <JobCard key={job.job_id} job={job} />
        ))}
      </div>

      {nextCursor ? (
        <div className="mt-6 text-center">
          <Link
            href={`/app/feed?before=${encodeURIComponent(nextCursor)}`}
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
