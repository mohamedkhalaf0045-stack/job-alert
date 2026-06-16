'use client'

import { useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import type { Job, JobStatus } from '@/lib/types'
import JobDetailModal from './JobDetailModal'

function scoreColors(score: number | null) {
  if (score === null) return 'bg-[var(--border-soft)] text-[var(--muted)]'
  if (score >= 8)     return 'bg-[var(--success-bg)] text-[var(--success)]'
  if (score >= 6)     return 'bg-[var(--warn-bg)] text-[var(--warn)]'
  return 'bg-[var(--danger-bg)] text-[var(--danger)]'
}

function sourceChip(url: string): { label: string; cls: string } {
  const u = (url || '').toLowerCase()
  if (u.includes('linkedin'))  return { label: 'LinkedIn', cls: 'bg-[#0a66c2] text-white' }
  if (u.includes('indeed'))    return { label: 'Indeed',   cls: 'bg-[#2164f3] text-white' }
  if (u.includes('adzuna'))    return { label: 'Adzuna',   cls: 'bg-[#d1003f] text-white' }
  if (u.includes('gmail'))     return { label: 'Gmail',    cls: 'bg-[#ea4335] text-white' }
  return { label: 'Web', cls: 'bg-[var(--muted)] text-white' }
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

function skillMatchScore(userSkills: string[], job: Job): { matched: string[]; pct: number } {
  if (!userSkills.length) return { matched: [], pct: 0 }
  const haystack = [job.title, job.llm_summary ?? '', ...(job.matched_skills ?? [])].join(' ').toLowerCase()
  const matched = userSkills.filter(s => haystack.includes(s.toLowerCase()))
  return { matched, pct: Math.round((matched.length / userSkills.length) * 100) }
}

export default function JobCard({ job, userSkills, isNew }: { job: Job; userSkills?: string[]; isNew?: boolean }) {
  const [status,    setStatus]    = useState<JobStatus | null>(job.my_status)
  const [saving,    setSaving]    = useState(false)
  const [removed,   setRemoved]   = useState(false)
  const [showModal, setShowModal] = useState(false)

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

  function openChat() {
    window.dispatchEvent(new CustomEvent('open-chat', {
      detail: {
        title:          job.title,
        company:        job.company,
        location:       job.location,
        match_score:    job.llm_score ?? undefined,
        llm_summary:    job.llm_summary ?? undefined,
        matched_skills: job.matched_skills ?? undefined,
        salary:         salaryLine(job) ?? undefined,
        source:         job.source ?? undefined,
        date_posted:    job.date_posted ?? undefined,
      },
    }))
  }

  if (removed) return null

  const salary     = salaryLine(job)
  const skillMatch = userSkills?.length ? skillMatchScore(userSkills, job) : null
  // Use date_posted (when job was actually posted); fall back to date_collected
  const dateRef = job.date_posted ?? job.date_collected
  function relativeTime(iso: string): string {
    const diffMs = Date.now() - new Date(iso).getTime()
    const mins  = Math.floor(diffMs / 60_000)
    const hours = Math.floor(diffMs / 3_600_000)
    const days  = Math.floor(diffMs / 86_400_000)
    if (mins  < 60)  return `${mins}m ago`
    if (hours < 24)  return `${hours}h ago`
    if (days  < 7)   return `${days}d ago`
    return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
  }
  const posted = dateRef ? relativeTime(dateRef) : ''
  const src = sourceChip(job.url || '')

  return (
    <>
      <article
        className={`bg-white rounded-xl border transition-all duration-150 p-4 hover:shadow-sm ${
          status === 'saved'
            ? 'border-[var(--accent)]/30 bg-[var(--accent-bg)]'
            : status === 'applied'
              ? 'border-[#16a34a]/25 bg-[var(--success-bg)]/40'
              : 'border-[var(--border)] hover:border-[#cbd5e1]'
        }`}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <a
              href={job.url} target="_blank" rel="noopener noreferrer"
              className="font-semibold text-sm text-[var(--fg)] hover:text-[var(--accent)] block truncate leading-snug transition-colors"
            >
              {job.title}
            </a>
            <p className="text-xs text-[var(--muted)] mt-0.5 truncate">
              {job.company}
              {job.location && <> &middot; {job.location}</>}
            </p>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            {isNew && (
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-[4px] bg-[var(--success)] text-white tracking-wide">
                NEW
              </span>
            )}
            {job.llm_score !== null && (
              <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded-md tabular-nums ${scoreColors(job.llm_score)}`}>
                {job.llm_score}/10
              </span>
            )}
            <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-[4px] ${src.cls}`}>
              {src.label}
            </span>
          </div>
        </div>

        {/* AI summary */}
        {job.llm_summary && (
          <p className="text-xs text-[var(--fg-2)] mt-2 line-clamp-2 leading-relaxed">
            {job.llm_summary}
          </p>
        )}

        {/* Skill match */}
        {skillMatch && skillMatch.matched.length > 0 && (
          <div className="mt-2 flex items-center gap-1.5 flex-wrap">
            <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-pill shrink-0 ${
              skillMatch.pct >= 60 ? 'bg-[var(--success-bg)] text-[var(--success)]' :
              skillMatch.pct >= 30 ? 'bg-[var(--warn-bg)] text-[var(--warn)]'       :
              'bg-[var(--border-soft)] text-[var(--muted)]'
            }`}>
              {skillMatch.pct}% match
            </span>
            {skillMatch.matched.slice(0, 4).map(s => (
              <span key={s} className="text-[10px] px-1.5 py-0.5 bg-[var(--accent-bg)] text-[var(--accent)] rounded font-medium">
                {s}
              </span>
            ))}
            {skillMatch.matched.length > 4 && (
              <span className="text-xs text-[var(--meta)]">+{skillMatch.matched.length - 4}</span>
            )}
          </div>
        )}

        {/* Salary */}
        {salary
          ? <p className="text-xs text-[var(--success)] font-medium mt-1.5">{salary}</p>
          : <p className="text-xs text-[var(--meta)] mt-1.5">Salary not listed</p>
        }

        {/* Action row */}
        <div className="flex items-center gap-1.5 mt-3 flex-wrap">
          <button
            onClick={() => interact('saved')} disabled={saving}
            className={`text-xs px-2.5 py-1 rounded-md border font-medium transition-colors duration-150 ${
              status === 'saved'
                ? 'bg-[var(--accent)] text-[var(--accent-on)] border-[var(--accent)]'
                : 'border-[var(--border)] text-[var(--muted)] hover:border-[#cbd5e1] hover:bg-[var(--border-soft)]'
            }`}
          >
            {status === 'saved' ? '★ Saved' : '☆ Save'}
          </button>
          <button
            onClick={() => interact('applied')} disabled={saving}
            className={`text-xs px-2.5 py-1 rounded-md border font-medium transition-colors duration-150 ${
              status === 'applied'
                ? 'bg-[var(--success)] text-white border-[var(--success)]'
                : 'border-[var(--border)] text-[var(--muted)] hover:border-[#cbd5e1] hover:bg-[var(--border-soft)]'
            }`}
          >
            {status === 'applied' ? '✓ Applied' : 'Applied'}
          </button>
          <button
            onClick={() => interact('dismissed')} disabled={saving}
            className="text-xs px-2.5 py-1 rounded-md border border-[var(--border)] text-[var(--meta)] hover:border-[#cbd5e1] hover:bg-[var(--border-soft)] transition-colors duration-150"
          >
            Hide
          </button>
          <button
            onClick={() => setShowModal(true)}
            className="text-xs px-2.5 py-1 rounded-md border border-[var(--border)] text-[var(--fg-2)] hover:border-[var(--accent)]/50 hover:bg-[var(--accent-bg)] hover:text-[var(--accent)] transition-colors duration-150 font-medium"
          >
            Analyze
          </button>
          <button
            onClick={openChat}
            className="text-xs px-2.5 py-1 rounded-md bg-[var(--accent)] text-white font-medium hover:bg-[var(--accent-hover)] transition-colors duration-150"
          >
            Talk to Me
          </button>
          <span className="ml-auto text-xs text-[var(--meta)] tabular-nums">{posted}</span>
        </div>
      </article>

      {showModal && (
        <JobDetailModal job={job} onClose={() => setShowModal(false)} />
      )}
    </>
  )
}
