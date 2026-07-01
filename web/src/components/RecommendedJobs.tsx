'use client'

import { useEffect, useState } from 'react'
import JobCard from './JobCard'
import type { Job } from '@/lib/types'

export default function RecommendedJobs({ userSkills }: { userSkills: string[] }) {
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => {
    fetch('/api/app/recommended-jobs')
      .then(r => r.json())
      .then(d => setJobs(Array.isArray(d.jobs) ? d.jobs : []))
      .catch(() => setJobs([]))
  }, [])

  if (jobs === null || jobs.length === 0) return null

  return (
    <div className="mb-8">
      <div className="flex items-center gap-3 mb-3">
        <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-[var(--accent-bg)] text-[var(--accent)]">
          Recommended for you
        </span>
        <span className="text-xs text-[var(--meta)]">{jobs.length} job{jobs.length !== 1 ? 's' : ''}</span>
        <div className="flex-1 h-px bg-[var(--border)]" />
        <button
          onClick={() => setCollapsed(c => !c)}
          className="text-xs text-[var(--muted)] hover:text-[var(--fg)] transition-colors"
        >
          {collapsed ? 'Show' : 'Hide'}
        </button>
      </div>
      {!collapsed && (
        <div className="space-y-3">
          {jobs.map(job => (
            <JobCard key={`rec-${job.job_id}`} job={job} userSkills={userSkills} />
          ))}
        </div>
      )}
    </div>
  )
}
