'use client'

import { useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import type { Job, JobStatus } from '@/lib/types'

function scoreColor(score: number | null): string {
  if (score === null) return 'bg-gray-100 text-gray-500'
  if (score >= 8)     return 'bg-green-100 text-green-700'
  if (score >= 6)     return 'bg-yellow-100 text-yellow-700'
  return 'bg-red-100 text-red-500'
}

function salaryLine(job: Job): string | null {
  const { salary_min, salary_max, salary_avg, salary_currency, salary_period } = job
  if (!salary_min && !salary_max && !salary_avg) return null
  const cur = salary_currency || 'AED'
  const per = salary_period === 'year' ? '/yr' : '/mo'
  if (salary_min && salary_max) {
    return `${cur} ${salary_min.toLocaleString()}–${salary_max.toLocaleString()}${per}`
  }
  const val = salary_avg || salary_max || salary_min || 0
  return `${cur} ${val.toLocaleString()}${per}`
}

export default function JobCard({ job }: { job: Job }) {
  const [status,  setStatus]  = useState<JobStatus | null>(job.my_status)
  const [saving,  setSaving]  = useState(false)
  const [removed, setRemoved] = useState(false)

  async function interact(newStatus: JobStatus) {
    if (saving) return
    const next = status === newStatus ? null : newStatus
    setSaving(true)
    const supabase = createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) { setSaving(false); return }

    if (next) {
      await supabase.from('user_job_interactions').upsert(
        { user_id: user.id, job_id: job.job_id, status: next, updated_at: new Date().toISOString() },
        { onConflict: 'user_id,job_id' }
      )
    } else {
      await supabase.from('user_job_interactions')
        .delete()
        .eq('user_id', user.id)
        .eq('job_id', job.job_id)
    }

    if (next === 'dismissed' || next === 'hidden') {
      setRemoved(true)
    } else {
      setStatus(next)
    }
    setSaving(false)
  }

  if (removed) return null

  const salary = salaryLine(job)
  const posted = job.date_collected
    ? new Date(job.date_collected).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
    : ''

  return (
    <article
      className={`bg-white rounded-xl border p-4 transition ${
        status === 'saved'    ? 'border-blue-200 bg-blue-50/30'  :
        status === 'applied'  ? 'border-green-200 bg-green-50/30' : ''
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <a
            href={job.url} target="_blank" rel="noopener noreferrer"
            className="font-semibold text-sm hover:text-blue-600 hover:underline block truncate"
          >
            {job.title}
          </a>
          <p className="text-xs text-gray-500 mt-0.5 truncate">
            {job.company} · {job.location}
          </p>
        </div>
        {job.llm_score !== null && (
          <span className={`text-xs font-bold px-2 py-0.5 rounded-full shrink-0 ${scoreColor(job.llm_score)}`}>
            {job.llm_score}/10
          </span>
        )}
      </div>

      {job.llm_summary && (
        <p className="text-xs text-gray-600 mt-2 line-clamp-2">{job.llm_summary}</p>
      )}

      {salary && (
        <p className="text-xs text-green-700 font-medium mt-1">{salary}</p>
      )}

      <div className="flex items-center gap-2 mt-3 flex-wrap">
        <button
          onClick={() => interact('saved')} disabled={saving}
          className={`text-xs px-2.5 py-1 rounded-lg border transition ${
            status === 'saved'
              ? 'bg-blue-600 text-white border-blue-600'
              : 'border-gray-200 hover:bg-gray-50'
          }`}
        >
          {status === 'saved' ? '★ Saved' : '☆ Save'}
        </button>
        <button
          onClick={() => interact('applied')} disabled={saving}
          className={`text-xs px-2.5 py-1 rounded-lg border transition ${
            status === 'applied'
              ? 'bg-green-600 text-white border-green-600'
              : 'border-gray-200 hover:bg-gray-50'
          }`}
        >
          {status === 'applied' ? '✓ Applied' : 'Applied'}
        </button>
        <button
          onClick={() => interact('dismissed')} disabled={saving}
          className="text-xs px-2.5 py-1 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-400"
        >
          Hide
        </button>
        <span className="ml-auto text-xs text-gray-400">{posted}</span>
      </div>
    </article>
  )
}
