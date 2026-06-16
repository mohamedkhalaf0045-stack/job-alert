'use client'

import { useState, useEffect } from 'react'
import { createClient } from '@/lib/supabase/client'
import type { Job, JobDetail, JobStatus } from '@/lib/types'

function sourceChip(url: string): { label: string; cls: string } {
  const u = (url || '').toLowerCase()
  if (u.includes('linkedin'))  return { label: 'LinkedIn', cls: 'bg-[#0a66c2] text-white' }
  if (u.includes('indeed'))    return { label: 'Indeed',   cls: 'bg-[#2164f3] text-white' }
  if (u.includes('adzuna'))    return { label: 'Adzuna',   cls: 'bg-[#d1003f] text-white' }
  if (u.includes('gmail'))     return { label: 'Gmail',    cls: 'bg-[#ea4335] text-white' }
  return { label: 'Web', cls: 'bg-[var(--muted)] text-white' }
}

function salaryLine(job: Job | JobDetail): string | null {
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

function scoreColors(score: number | null) {
  if (score === null) return 'bg-[var(--border-soft)] text-[var(--muted)]'
  if (score >= 8)     return 'bg-[var(--success-bg)] text-[var(--success)]'
  if (score >= 6)     return 'bg-[var(--warn-bg)] text-[var(--warn)]'
  return 'bg-[var(--danger-bg)] text-[var(--danger)]'
}

interface Props {
  job: Job
  onClose: () => void
}

export default function JobDetailModal({ job, onClose }: Props) {
  const [detail,       setDetail]       = useState<JobDetail | null>(null)
  const [loading,      setLoading]      = useState(true)
  const [fetchError,   setFetchError]   = useState('')
  const [status,       setStatus]       = useState<JobStatus | null>(job.my_status)
  const [saving,       setSaving]       = useState(false)
  const [removed,      setRemoved]      = useState(false)
  const [clExpanded,   setClExpanded]   = useState(false)

  useEffect(() => {
    fetch(`/api/app/jobs/${job.job_id}`)
      .then(async r => {
        const body = await r.json()
        if (!r.ok) throw new Error(body.error ?? `HTTP ${r.status}`)
        return body
      })
      .then(data => setDetail(data.job))
      .catch(err => setFetchError(String(err?.message ?? err)))
      .finally(() => setLoading(false))
  }, [job.job_id])

  // Close on Escape
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

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
        .delete().eq('user_id', user.id).eq('job_id', job.job_id)
    }

    if (next === 'dismissed' || next === 'hidden') {
      setRemoved(true)
      onClose()
    } else {
      setStatus(next)
    }
    setSaving(false)
  }

  function openChat() {
    const d = detail ?? job
    window.dispatchEvent(new CustomEvent('open-chat', {
      detail: {
        title:          d.title,
        company:        d.company,
        location:       d.location,
        description:    detail?.description ?? undefined,
        match_score:    d.llm_score ?? undefined,
        llm_summary:    d.llm_summary ?? undefined,
        matched_skills: (d.matched_skills ?? []).length ? d.matched_skills ?? undefined : undefined,
        missing_skills: detail?.missing_skills?.length ? detail.missing_skills : undefined,
        salary:         salaryLine(d) ?? undefined,
        source:         d.source ?? undefined,
        date_posted:    d.date_posted ?? undefined,
      },
    }))
    onClose()
  }

  const src     = sourceChip(job.url || '')
  const salary  = salaryLine(detail ?? job)
  const dateRef = (detail ?? job).date_posted ?? (detail ?? job).date_collected
  const posted  = dateRef
    ? new Date(dateRef).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
    : 'Unknown'

  const missingSkills: string[] = detail?.missing_skills ?? []
  const redFlags:      string[] = detail?.red_flags       ?? []

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-2xl bg-white rounded-2xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-[var(--border)] flex items-start justify-between gap-4 shrink-0">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-[4px] ${src.cls}`}>
                {src.label}
              </span>
              {job.llm_score !== null && (
                <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded-md tabular-nums ${scoreColors(job.llm_score)}`}>
                  {job.llm_score}/10
                </span>
              )}
              {status && status !== 'dismissed' && status !== 'hidden' && (
                <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-pill ${
                  status === 'applied' ? 'bg-[var(--success-bg)] text-[var(--success)]' :
                  status === 'saved'   ? 'bg-[var(--accent-bg)] text-[var(--accent)]'   : ''
                }`}>
                  {status === 'applied' ? '✓ Applied' : '★ Saved'}
                </span>
              )}
            </div>
            <a
              href={job.url} target="_blank" rel="noopener noreferrer"
              className="font-bold text-base text-[var(--fg)] hover:text-[var(--accent)] leading-snug transition-colors"
            >
              {job.title}
            </a>
            <p className="text-sm text-[var(--muted)] mt-0.5">{job.company}</p>
          </div>
          <button
            onClick={onClose}
            className="text-[var(--muted)] hover:text-[var(--fg)] transition-colors shrink-0 mt-0.5"
            aria-label="Close"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Meta row */}
        <div className="px-6 py-3 border-b border-[var(--border-soft)] flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--muted)] shrink-0">
          {job.location && (
            <span className="flex items-center gap-1">
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
              {job.location}
            </span>
          )}
          <span className="flex items-center gap-1">
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            Posted {posted}
          </span>
          <span className={`flex items-center gap-1 font-medium ${salary ? 'text-[var(--success)]' : ''}`}>
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            {salary ?? 'Salary not listed'}
          </span>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
          {loading && (
            <div className="flex items-center justify-center gap-3 py-12 text-sm text-[var(--muted)]">
              <div className="w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin shrink-0" />
              Fetching job details…
            </div>
          )}

          {fetchError && (
            <p className="text-sm text-[var(--danger)] bg-[var(--danger-bg)] px-4 py-3 rounded-lg">{fetchError}</p>
          )}

          {/* AI Summary */}
          {(detail?.llm_summary ?? job.llm_summary) && (
            <section>
              <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wide mb-2">AI Summary</h3>
              <p className="text-sm text-[var(--fg-2)] leading-relaxed">{detail?.llm_summary ?? job.llm_summary}</p>
            </section>
          )}

          {/* Missing Skills */}
          {!loading && missingSkills.length > 0 && (
            <section>
              <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wide mb-2">Skills to Develop</h3>
              <div className="flex flex-wrap gap-1.5">
                {missingSkills.map(skill => (
                  <span
                    key={skill}
                    className="text-xs px-2 py-0.5 bg-[var(--danger-bg)] text-[var(--danger)] border border-[var(--danger)]/20 rounded-md font-medium"
                  >
                    {skill}
                  </span>
                ))}
              </div>
            </section>
          )}

          {/* Red Flags */}
          {!loading && redFlags.length > 0 && (
            <section>
              <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wide mb-2">Red Flags</h3>
              <ul className="space-y-1">
                {redFlags.map((flag, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-[var(--warn)]">
                    <svg className="w-4 h-4 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                    <span>{flag}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Description */}
          {!loading && detail?.description && (
            <section>
              <h3 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wide mb-2">Job Description</h3>
              <div className="max-h-72 overflow-y-auto rounded-lg bg-[var(--border-soft)] p-4">
                <p className="text-sm text-[var(--fg-2)] leading-relaxed whitespace-pre-wrap">{detail.description}</p>
              </div>
            </section>
          )}

          {/* Cover Letter Draft */}
          {!loading && detail?.cover_letter_draft && (
            <section>
              <button
                onClick={() => setClExpanded(v => !v)}
                className="flex items-center gap-2 text-xs font-semibold text-[var(--muted)] uppercase tracking-wide mb-2 hover:text-[var(--fg)] transition-colors"
              >
                <svg className={`w-3.5 h-3.5 transition-transform ${clExpanded ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
                Cover Letter Draft
              </button>
              {clExpanded && (
                <div className="max-h-48 overflow-y-auto rounded-lg bg-[var(--border-soft)] p-4">
                  <p className="text-sm text-[var(--fg-2)] leading-relaxed whitespace-pre-wrap">{detail.cover_letter_draft}</p>
                </div>
              )}
            </section>
          )}

          {!loading && !fetchError && !detail?.description && (
            <div className="text-sm text-[var(--meta)] text-center py-4 space-y-2">
              <p className="text-xs">Full description not yet available — view the original posting.</p>
              <a
                href={job.url} target="_blank" rel="noopener noreferrer"
                className="inline-block text-xs px-3 py-1.5 rounded-md bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] transition-colors"
              >
                View on {sourceChip(job.url || '').label} →
              </a>
            </div>
          )}
        </div>

        {/* Footer */}
        {!removed && (
          <div className="px-6 py-4 border-t border-[var(--border)] flex items-center gap-2 shrink-0 flex-wrap">
            <button
              onClick={() => interact('saved')} disabled={saving}
              className={`text-xs px-3 py-1.5 rounded-md border font-medium transition-colors duration-150 ${
                status === 'saved'
                  ? 'bg-[var(--accent)] text-[var(--accent-on)] border-[var(--accent)]'
                  : 'border-[var(--border)] text-[var(--muted)] hover:border-[#cbd5e1] hover:bg-[var(--border-soft)]'
              }`}
            >
              {status === 'saved' ? '★ Saved' : '☆ Save'}
            </button>
            <button
              onClick={() => interact('applied')} disabled={saving}
              className={`text-xs px-3 py-1.5 rounded-md border font-medium transition-colors duration-150 ${
                status === 'applied'
                  ? 'bg-[var(--success)] text-white border-[var(--success)]'
                  : 'border-[var(--border)] text-[var(--muted)] hover:border-[#cbd5e1] hover:bg-[var(--border-soft)]'
              }`}
            >
              {status === 'applied' ? '✓ Applied' : 'Applied'}
            </button>
            <button
              onClick={() => interact('dismissed')} disabled={saving}
              className="text-xs px-3 py-1.5 rounded-md border border-[var(--border)] text-[var(--meta)] hover:border-[#cbd5e1] hover:bg-[var(--border-soft)] transition-colors duration-150"
            >
              Hide
            </button>
            <div className="ml-auto">
              <button
                onClick={openChat}
                className="text-xs px-3 py-1.5 rounded-md bg-[var(--accent)] text-white font-medium hover:bg-[var(--accent-hover)] transition-colors"
              >
                Talk to Me
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
