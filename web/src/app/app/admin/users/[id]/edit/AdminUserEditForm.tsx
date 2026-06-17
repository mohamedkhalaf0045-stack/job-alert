'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'

interface Prefs {
  keywords:         string[]
  locations:        string[]
  exclude_keywords: string[]
  min_score:        number | null
  alert_frequency:  'instant' | 'daily' | 'off'
  paused:           boolean
}

interface Profile {
  alert_email:      boolean
  alert_telegram:   boolean
  telegram_chat_id: string | null
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

export default function AdminUserEditForm({
  userId,
  userEmail,
  prefs,
  profile,
}: {
  userId:    string
  userEmail: string
  prefs:     Prefs | null
  profile:   Profile | null
}) {
  const router = useRouter()

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

    const res = await fetch(`/api/admin/users/${userId}/prefs`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        keywords:         keywords.split(',').map(s => s.trim()).filter(Boolean),
        locations:        locations.split(',').map(s => s.trim()).filter(Boolean),
        exclude_keywords: excludes.split(',').map(s => s.trim()).filter(Boolean),
        min_score:        minScore ? parseInt(minScore) : null,
        alert_frequency:  freq,
        paused,
        alert_email:      alertEmail,
        alert_telegram:   alertTg,
        telegram_chat_id: tgChatId.trim() || null,
      }),
    })

    setSaving(false)
    if (!res.ok) {
      const { error: msg } = await res.json()
      setError(msg ?? 'Save failed')
    } else {
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    }
  }

  return (
    <form onSubmit={handleSave} className="space-y-6 max-w-lg">
      <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm text-amber-800">
        Editing settings for <strong>{userEmail}</strong>
      </div>

      <h2 className="text-base font-semibold">Filter Settings</h2>

      <Field label="Job keywords" hint="Comma-separated. Any match shows the job.">
        <input value={keywords} onChange={e => setKeywords(e.target.value)}
          placeholder="IT Support, System Administrator, Help Desk" className={inputCls} />
      </Field>

      <Field label="Locations" hint="Leave blank to match all locations.">
        <input value={locations} onChange={e => setLocations(e.target.value)}
          placeholder="United Arab Emirates, Egypt" className={inputCls} />
      </Field>

      <Field label="Exclude keywords" hint="Jobs containing any of these are hidden.">
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
          <option value="daily">Daily digest (8 AM their time)</option>
          <option value="instant">Instant (within 15 min of a match)</option>
          <option value="off">Off — manual browsing only</option>
        </select>
      </Field>

      <hr className="border-gray-100" />
      <h2 className="text-base font-semibold">Notifications</h2>

      <label className="flex items-center gap-2 cursor-pointer">
        <input type="checkbox" checked={alertEmail} onChange={e => setAlertEmail(e.target.checked)} className="rounded" />
        <span className="text-sm">Email alerts</span>
      </label>

      <div className="space-y-2">
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={alertTg} onChange={e => setAlertTg(e.target.checked)} className="rounded" />
          <span className="text-sm">Telegram alerts</span>
        </label>
        {alertTg && (
          <Field label="Telegram chat ID" hint="Numeric chat ID from @userinfobot.">
            <input value={tgChatId} onChange={e => setTgChatId(e.target.value)}
              placeholder="941885724" className={inputCls} />
          </Field>
        )}
      </div>

      <hr className="border-gray-100" />

      <label className="flex items-center gap-2 cursor-pointer">
        <input type="checkbox" checked={paused} onChange={e => setPaused(e.target.checked)} className="rounded" />
        <span className="text-sm">Pause all alerts</span>
      </label>

      {error && <p className="text-red-600 text-sm">{error}</p>}

      <div className="flex items-center gap-3">
        <button type="submit" disabled={saving}
          className="bg-blue-600 text-white px-5 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm font-medium transition">
          {saving ? 'Saving…' : saved ? '✓ Saved' : 'Save settings'}
        </button>
        <button
          type="button"
          onClick={() => router.push('/app/admin')}
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          ← Back to admin
        </button>
      </div>
    </form>
  )
}
