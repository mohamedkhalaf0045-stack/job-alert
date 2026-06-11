import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'
import Link from 'next/link'

export const dynamic = 'force-dynamic'

export default async function SavedPage() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')

  const { data: interactions } = await supabase
    .from('user_job_interactions')
    .select('job_id, status, updated_at, jobs(job_id, title, company, location, url, llm_score, date_collected)')
    .eq('user_id', user.id)
    .in('status', ['saved', 'applied'])
    .order('updated_at', { ascending: false })
    .limit(100)

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const rows = (interactions ?? []) as unknown as {
    job_id: string
    status: string
    updated_at: string
    jobs: { job_id: string; title: string; company: string; location: string; url: string; llm_score: number | null; date_collected: string } | null
  }[]

  return (
    <div>
      <h1 className="text-xl font-bold mb-4">Saved &amp; applied</h1>
      {rows.length === 0 ? (
        <div className="bg-white rounded-xl border p-8 text-center text-gray-500">
          <p className="font-medium mb-2">Nothing saved yet</p>
          <p className="text-sm">
            Hit <strong>Save</strong> or <strong>Applied</strong> on jobs in your{' '}
            <Link href="/app/feed" className="text-blue-600 underline">feed</Link>.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {rows.map(row => {
            const job = row.jobs
            if (!job) return null
            const posted = job.date_collected
              ? new Date(job.date_collected).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
              : ''
            return (
              <div
                key={row.job_id}
                className={`bg-white rounded-xl border p-4 flex items-start justify-between gap-3 ${
                  row.status === 'applied' ? 'border-green-200' : 'border-blue-200'
                }`}
              >
                <div className="flex-1 min-w-0">
                  <a
                    href={job.url} target="_blank" rel="noopener noreferrer"
                    className="font-semibold text-sm hover:text-blue-600 hover:underline block truncate"
                  >
                    {job.title}
                  </a>
                  <p className="text-xs text-gray-500 mt-0.5">{job.company} · {job.location}</p>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                    row.status === 'applied' ? 'bg-green-100 text-green-700' : 'bg-blue-100 text-blue-700'
                  }`}>
                    {row.status}
                  </span>
                  <span className="text-xs text-gray-400">{posted}</span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
