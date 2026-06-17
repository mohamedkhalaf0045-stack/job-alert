'use client'

import { useState, useEffect, useCallback } from 'react'
import type { Job } from '@/lib/types'

export default function CoverLetterModal({ job, onClose }: { job: Job; onClose: () => void }) {
  const [text,    setText]    = useState('')
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState('')
  const [copied,  setCopied]  = useState(false)

  const generate = useCallback(async () => {
    setLoading(true); setError(''); setCopied(false)
    try {
      const res  = await fetch(`/api/app/cover-letter/${job.job_id}`, { method: 'POST' })
      const body = await res.json()
      if (!res.ok) throw new Error(body.error ?? `HTTP ${res.status}`)
      setText(body.cover_letter ?? '')
    } catch (e) {
      setError(String((e as Error)?.message ?? e))
    } finally {
      setLoading(false)
    }
  }, [job.job_id])

  useEffect(() => { generate() }, [generate])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  async function copy() {
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000) } catch {}
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-xl bg-white rounded-2xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-[var(--border)] flex items-start justify-between gap-4 shrink-0">
          <div className="min-w-0">
            <h2 className="font-bold text-base text-[var(--fg)]">Cover Letter</h2>
            <p className="text-xs text-[var(--muted)] mt-0.5 truncate">{job.title} &middot; {job.company}</p>
          </div>
          <button onClick={onClose} className="text-[var(--muted)] hover:text-[var(--fg)] transition-colors shrink-0" aria-label="Close">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {loading && (
            <div className="flex items-center justify-center gap-3 py-12 text-sm text-[var(--muted)]">
              <div className="w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin shrink-0" />
              Writing your cover letter…
            </div>
          )}
          {error && (
            <p className="text-sm text-[var(--danger)] bg-[var(--danger-bg)] px-4 py-3 rounded-lg">{error}</p>
          )}
          {!loading && !error && (
            <textarea
              value={text}
              onChange={e => setText(e.target.value)}
              className="w-full h-72 text-sm text-[var(--fg-2)] leading-relaxed bg-[var(--border-soft)] rounded-lg p-4 resize-none focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30"
            />
          )}
          <p className="text-[11px] text-[var(--meta)] mt-2">
            AI-generated draft from your CV — review and edit before sending.
          </p>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-[var(--border)] flex items-center gap-2 shrink-0">
          <button
            onClick={copy} disabled={loading || !!error || !text}
            className="text-xs px-3 py-1.5 rounded-md bg-[var(--accent)] text-white font-medium hover:bg-[var(--accent-hover)] disabled:opacity-40 transition-colors"
          >
            {copied ? '✓ Copied' : 'Copy'}
          </button>
          <button
            onClick={generate} disabled={loading}
            className="text-xs px-3 py-1.5 rounded-md border border-[var(--border)] text-[var(--muted)] hover:border-[#cbd5e1] hover:bg-[var(--border-soft)] disabled:opacity-40 transition-colors"
          >
            Regenerate
          </button>
          <button
            onClick={onClose}
            className="ml-auto text-xs px-3 py-1.5 rounded-md border border-[var(--border)] text-[var(--muted)] hover:bg-[var(--border-soft)] transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
