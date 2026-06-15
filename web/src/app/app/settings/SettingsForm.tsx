'use client'

import { useState, useEffect } from 'react'
import { createClient } from '@/lib/supabase/client'
import CVUploadCard, { CVData } from '@/components/CVUploadCard'
import type { UserPreferences, Profile } from '@/lib/types'

interface CVProfile {
  skills: string[]
  job_titles: string[]
  years_experience: number | null
  certifications: string[]
  summary: string
  analyzed_at: string | null
  source: 'web' | 'desktop' | null
}

function timeAgo(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000)
  if (days === 0) return 'today'
  if (days === 1) return 'yesterday'
  return `${days} days ago`
}

const inputCls = 'w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-sm font-medium mb-1">{label}</label>
      {children}
      {hint && <p className="text-xs text-gray-400 mt-1">{hint}</p>}
    </div>
  )
}

export default function SettingsForm({
  prefs,
  profile,
  userId,
}: {
  prefs:   UserPreferences | null
  profile: Profile | null
  userId:  string
}) {
  const [keywords,   setKeywords]   = useState((prefs?.keywords         ?? []).join(', '))
  const [locations,  setLocations]  = useState((prefs?.locations        ?? []).join(', '))
  const [excludes,   setExcludes]   = useState((prefs?.exclude_keywords ?? []).join(', '))
  const [minScore,   setMinScore]   = useState(prefs?.min_score?.toString() ?? '')
  const [freq,       setFreq]       = useState<'instant' | 'daily' | 'off'>(prefs?.alert_frequency ?? 'daily')
  const [paused,     setPaused]     = useState(prefs?.paused ?? false)
  const [alertEmail, setAlertEmail] = useState(profile?.alert_email    ?? true)
  const [alertTg,    setAlertTg]    = useState(profile?.alert_telegram  ?? false)
  const [tgChatId,   setTgChatId]   = useState(profile?.telegram_chat_id ?? '')
  const [cvProfile,  setCvProfile]  = useState<CVProfile | null>(null)
  const [cvSuggested, setCvSuggested] = useState<string[]>([])
  const [saving,     setSaving]     = useState(false)

  useEffect(() => {
    fetch('/api/app/cv/profile')
      .then(r => r.json())
      .then((d: CVProfile) => { if (d.skills?.length || d.job_titles?.length) setCvProfile(d) })
      .catch(() => {})
  }, [])
  const [saved,      setSaved]      = useState(false)
  const [error,      setError]      = useState('')

  function handleCVAnalyzed(data: CVData) {
    const titles = (data.job_titles ?? []).filter(Boolean)
    if (titles.length > 0) setCvSuggested(titles)
  }

  function applyCVTitles() {
    const current = keywords.split(',').map(s => s.trim()).filter(Boolean)
    const merged = Array.from(new Set([...current, ...cvSuggested]))
    setKeywords(merged.join(', '))
    setCvSuggested([])
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true); setSaved(false); setError('')
    const supabase = createClient()

    const [prefErr, profErr] = await Promise.all([
      supabase.from('user_preferences').upsert(
        {
          user_id:          userId,
          keywords:         keywords.split(',').map(s => s.trim()).filter(Boolean),
          locations:        locations.split(',').map(s => s.trim()).filter(Boolean),
          exclude_keywords: excludes.split(',').map(s => s.trim()).filter(Boolean),
          min_score:        minScore ? parseInt(minScore) : null,
          alert_frequency:  freq,
          paused,
          updated_at:       new Date().toISOString(),
        },
        { onConflict: 'user_id' }
      ).then(r => r.error),
      supabase.from('profiles').update({
        telegram_chat_id: tgChatId.trim() || null,
        alert_telegram:   alertTg,
        alert_email:      alertEmail,
        updated_at:       new Date().toISOString(),
      }).eq('id', userId).then(r => r.error),
    ])

    setSaving(false)
    if (prefErr || profErr) {
      setError((prefErr || profErr)!.message)
    } else {
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    }
  }

  return (
    <form onSubmit={handleSave} className="space-y-6 max-w-lg">
      {/* Existing CV summary (loaded from bot_state) */}
      {cvProfile && !cvSuggested.length && (
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <p className="text-sm font-semibold text-gray-800">
                CV on file — {cvProfile.skills.length} skills
                {cvProfile.years_experience ? `, ${cvProfile.years_experience} yrs exp` : ''}
              </p>
              {cvProfile.analyzed_at && (
                <p className="text-xs text-gray-400 mt-0.5">
                  {cvProfile.source === 'desktop' ? 'From desktop app · ' : ''}
                  Analyzed {timeAgo(cvProfile.analyzed_at)}
                </p>
              )}
            </div>
          </div>

          {cvProfile.job_titles.length > 0 && (
            <div className="mb-3">
              <p className="text-xs font-medium text-gray-500 mb-1.5">Job titles</p>
              <div className="flex flex-wrap gap-1.5">
                {cvProfile.job_titles.map(t => (
                  <span key={t} className="text-xs px-2 py-0.5 bg-blue-50 text-blue-700 rounded-full font-medium">{t}</span>
                ))}
              </div>
            </div>
          )}

          {cvProfile.skills.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-500 mb-1.5">Skills used for job matching</p>
              <div className="flex flex-wrap gap-1.5">
                {cvProfile.skills.slice(0, 30).map(s => (
                  <span key={s} className="text-xs px-2 py-0.5 bg-white border border-gray-200 text-gray-600 rounded-full">{s}</span>
                ))}
                {cvProfile.skills.length > 30 && (
                  <span className="text-xs text-gray-400">+{cvProfile.skills.length - 30} more</span>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      <CVUploadCard onAnalysisComplete={handleCVAnalyzed} />

      {cvSuggested.length > 0 && (
        <div className="bg-blue-50 border border-blue-100 rounded-lg p-4">
          <p className="text-sm font-medium text-blue-800 mb-2">
            CV detected these job titles:
          </p>
          <div className="flex flex-wrap gap-2 mb-3">
            {cvSuggested.map(t => (
              <span key={t} className="px-2 py-1 bg-white border border-blue-200 text-blue-700 rounded-full text-xs font-medium">
                {t}
              </span>
            ))}
          </div>
          <button
            type="button"
            onClick={applyCVTitles}
            className="text-sm bg-blue-600 text-white px-4 py-1.5 rounded-lg hover:bg-blue-700 font-medium"
          >
            Add to my keywords →
          </button>
        </div>
      )}

      <hr className="border-gray-100" />
      <h2 className="text-base font-semibold">Filter Settings</h2>

      <Field label="Job keywords" hint="Comma-separated. Any match shows the job.">
        <input value={keywords} onChange={e => setKeywords(e.target.value)}
          placeholder="IT Support, System Administrator, Help Desk" className={inputCls} />
      </Field>

      <Field label="Locations" hint="Leave blank to match all locations.">
        <input value={locations} onChange={e => setLocations(e.target.value)}
          placeholder="United Arab Emirates, Egypt" className={inputCls} />
      </Field>

      <Field label="Exclude keywords" hint="Jobs containing any of these are hidden from your feed.">
        <input value={excludes} onChange={e => setExcludes(e.target.value)}
          placeholder="Senior, Lead, Manager" className={inputCls} />
      </Field>

      <Field label="Min AI score (1–10)" hint="Hide jobs scored below this. Leave blank to show all.">
        <input type="number" min="1" max="10" value={minScore}
          onChange={e => setMinScore(e.target.value)}
          placeholder="e.g. 5" className={inputCls} />
      </Field>

      <Field label="Alert frequency">
        <select value={freq} onChange={e => setFreq(e.target.value as 'instant' | 'daily' | 'off')}
          className={inputCls}>
          <option value="daily">Daily digest (8 AM your time)</option>
          <option value="instant">Instant (within 15 min of a match)</option>
          <option value="off">Off — I&apos;ll browse manually</option>
        </select>
      </Field>

      <hr className="border-gray-100" />
      <h2 className="text-base font-semibold">Notifications</h2>

      <label className="flex items-center gap-2 cursor-pointer">
        <input type="checkbox" checked={alertEmail} onChange={e => setAlertEmail(e.target.checked)} className="rounded" />
        <span className="text-sm">Email alerts (to your account email)</span>
      </label>

      <div className="space-y-2">
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={alertTg} onChange={e => setAlertTg(e.target.checked)} className="rounded" />
          <span className="text-sm">Telegram alerts</span>
        </label>
        {alertTg && (
          <Field
            label="Telegram chat ID"
            hint="Your numeric chat ID — message @userinfobot on Telegram to get it."
          >
            <input value={tgChatId} onChange={e => setTgChatId(e.target.value)}
              placeholder="941885724" className={inputCls} />
          </Field>
        )}
      </div>

      <hr className="border-gray-100" />

      <label className="flex items-center gap-2 cursor-pointer">
        <input type="checkbox" checked={paused} onChange={e => setPaused(e.target.checked)} className="rounded" />
        <span className="text-sm">Pause all alerts (still update feed)</span>
      </label>

      {error && <p className="text-red-600 text-sm">{error}</p>}

      <button type="submit" disabled={saving}
        className="bg-blue-600 text-white px-5 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm font-medium transition">
        {saving ? 'Saving…' : saved ? '✓ Saved' : 'Save settings'}
      </button>
    </form>
  )
}
