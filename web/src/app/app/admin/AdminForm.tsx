'use client'

import { useState } from 'react'

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

function boolVal(state: Record<string, string>, key: string, def = true): boolean {
  const v = state[key]
  if (!v) return def
  return !['false', '0', 'no', 'off'].includes(v.toLowerCase())
}

export default function AdminForm({ state }: { state: Record<string, string> }) {
  const [maxHours,     setMaxHours]     = useState(state.setting_max_hours ?? '72')
  const [minScore,     setMinScore]     = useState(state.setting_llm_min_score ?? '4')
  const [excludeKw,    setExcludeKw]    = useState(state.setting_exclude_keywords ?? '')
  const [searchLi,     setSearchLi]     = useState(boolVal(state, 'setting_search_linkedin'))
  const [searchIndeed, setSearchIndeed] = useState(boolVal(state, 'setting_search_indeed', false))
  const [searchBayt,   setSearchBayt]   = useState(boolVal(state, 'setting_search_bayt'))
  const [searchGt,     setSearchGt]     = useState(boolVal(state, 'setting_search_gulftalent'))
  const [searchNaukri, setSearchNaukri] = useState(boolVal(state, 'setting_search_naukrigulf'))
  const [searchWeb,    setSearchWeb]    = useState(boolVal(state, 'setting_search_web', false))
  const [legacyTg,     setLegacyTg]    = useState(boolVal(state, 'setting_legacy_telegram'))
  const [saving,  setSaving]  = useState(false)
  const [saved,   setSaved]   = useState(false)
  const [error,   setError]   = useState('')

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true); setSaved(false); setError('')

    const res = await fetch('/api/admin/bot-state', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        setting_max_hours:          maxHours,
        setting_llm_min_score:      minScore,
        setting_exclude_keywords:   excludeKw,
        setting_search_linkedin:    searchLi.toString(),
        setting_search_indeed:      searchIndeed.toString(),
        setting_search_bayt:        searchBayt.toString(),
        setting_search_gulftalent:  searchGt.toString(),
        setting_search_naukrigulf:  searchNaukri.toString(),
        setting_search_web:         searchWeb.toString(),
        setting_legacy_telegram:    legacyTg.toString(),
      }),
    })

    setSaving(false)
    if (!res.ok) {
      const { error: msg } = await res.json()
      setError(msg ?? 'Unknown error')
    } else {
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    }
  }

  return (
    <form onSubmit={handleSave} className="space-y-6 max-w-lg">

      {/* Read-only: auto-synced from user prefs */}
      <div className="bg-blue-50 border border-blue-100 rounded-lg p-4 space-y-3">
        <p className="text-xs font-semibold text-blue-700 uppercase tracking-wide">
          Auto-synced from all users&apos; preferences
        </p>
        <div>
          <p className="text-xs text-gray-500 mb-0.5">Active keywords</p>
          <p className="text-sm font-mono break-all">{state.setting_keywords || '—'}</p>
        </div>
        <div>
          <p className="text-xs text-gray-500 mb-0.5">Active locations</p>
          <p className="text-sm font-mono break-all">{state.setting_location || '—'}</p>
        </div>
      </div>

      <Field label="Max job age (hours)"
        hint="Jobs older than this are ignored by the scraper. Default: 72">
        <input type="number" min="1" max="720"
          value={maxHours} onChange={e => setMaxHours(e.target.value)}
          className={inputCls} />
      </Field>

      <Field label="Global min AI score (1–10)"
        hint="Telegram alerts are only sent for jobs at or above this score. Default: 4">
        <input type="number" min="1" max="10"
          value={minScore} onChange={e => setMinScore(e.target.value)}
          className={inputCls} />
      </Field>

      <Field label="Global exclude keywords"
        hint="Comma-separated words. Jobs with these are never scraped for anyone.">
        <input value={excludeKw} onChange={e => setExcludeKw(e.target.value)}
          placeholder="intern, junior, unpaid" className={inputCls} />
      </Field>

      <hr className="border-gray-100" />
      <h2 className="text-base font-semibold">Search sources</h2>

      <div className="space-y-2">
        {([
          ['LinkedIn',   searchLi,     setSearchLi],
          ['Bayt',       searchBayt,   setSearchBayt],
          ['GulfTalent', searchGt,     setSearchGt],
          ['NaukriGulf', searchNaukri, setSearchNaukri],
          ['Indeed',     searchIndeed, setSearchIndeed],
          ['Web search', searchWeb,    setSearchWeb],
        ] as [string, boolean, (v: boolean) => void][]).map(([label, val, setter]) => (
          <label key={label} className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={val}
              onChange={e => setter(e.target.checked)} className="rounded" />
            <span className="text-sm">{label}</span>
          </label>
        ))}
      </div>

      <hr className="border-gray-100" />

      <div>
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={legacyTg}
            onChange={e => setLegacyTg(e.target.checked)} className="rounded" />
          <span className="text-sm">Legacy single-user Telegram alerts</span>
        </label>
        <p className="text-xs text-gray-400 mt-1 ml-6">
          Disable once you receive alerts through the per-user alert system.
        </p>
      </div>

      {error && <p className="text-red-600 text-sm">{error}</p>}

      <button type="submit" disabled={saving}
        className="bg-blue-600 text-white px-5 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm font-medium transition">
        {saving ? 'Saving…' : saved ? '✓ Saved' : 'Save settings'}
      </button>
    </form>
  )
}
