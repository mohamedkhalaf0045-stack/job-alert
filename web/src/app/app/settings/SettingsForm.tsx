'use client'

import { useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import type { UserPreferences, Profile } from '@/lib/types'

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
  const [saving,     setSaving]     = useState(false)
  const [saved,      setSaved]      = useState(false)
  const [error,      setError]      = useState('')

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
