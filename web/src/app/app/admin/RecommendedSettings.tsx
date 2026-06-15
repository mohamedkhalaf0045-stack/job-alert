'use client'

import { useState } from 'react'

const UAE_LOCATIONS = [
  'United Arab Emirates',
  'Dubai',
  'Abu Dhabi',
  'Sharjah',
  'Ajman',
  'Egypt',
  'Saudi Arabia',
  'Qatar',
  'Kuwait',
]

const inputCls = 'w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'

function parseList(raw: string): string[] {
  try { return JSON.parse(raw) } catch { return [] }
}

interface Props {
  initialKeywords: string[]
  initialLocations: string[]
}

export default function RecommendedSettings({ initialKeywords, initialLocations }: Props) {
  const [keywords, setKeywords] = useState<string[]>(initialKeywords)
  const [kwInput, setKwInput] = useState('')
  const [locations, setLocations] = useState<string[]>(initialLocations)
  const [locInput, setLocInput] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  function addKw(kw: string) {
    const t = kw.trim()
    if (t && !keywords.includes(t)) setKeywords(prev => [...prev, t])
  }
  function removeKw(kw: string) { setKeywords(prev => prev.filter(k => k !== kw)) }

  function kwKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      addKw(kwInput)
      setKwInput('')
    }
  }

  function toggleLoc(loc: string) {
    setLocations(prev => prev.includes(loc) ? prev.filter(l => l !== loc) : [...prev, loc])
  }

  function locKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      const t = locInput.trim()
      if (t && !locations.includes(t)) setLocations(prev => [...prev, t])
      setLocInput('')
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true); setError(''); setSaved(false)
    const res = await fetch('/api/admin/bot-state', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        recommended_keywords:  JSON.stringify(keywords),
        recommended_locations: JSON.stringify(locations),
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
      <div className="bg-amber-50 border border-amber-100 rounded-lg p-3">
        <p className="text-xs text-amber-700">
          These are shown as suggestion chips on the onboarding screen so new users can add them with one tap.
          They don&apos;t override user choices — just pre-fill suggestions.
        </p>
      </div>

      {/* Keywords */}
      <div>
        <label className="block text-sm font-medium mb-1">Recommended keywords</label>
        <input
          value={kwInput}
          onChange={e => setKwInput(e.target.value)}
          onKeyDown={kwKeyDown}
          onBlur={() => { if (kwInput.trim()) { addKw(kwInput); setKwInput('') } }}
          placeholder="e.g. IT Support, Network Engineer"
          className={inputCls}
        />
        <p className="text-xs text-gray-400 mt-1">Press Enter or comma to add</p>
        {keywords.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-3">
            {keywords.map(kw => (
              <span key={kw} className="inline-flex items-center gap-1 px-3 py-1 bg-blue-50 text-blue-700 rounded-full text-xs font-medium">
                {kw}
                <button type="button" onClick={() => removeKw(kw)} className="text-blue-400 hover:text-blue-600 ml-0.5">×</button>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Locations */}
      <div>
        <label className="block text-sm font-medium mb-2">Recommended locations</label>
        <div className="flex flex-wrap gap-2 mb-3">
          {UAE_LOCATIONS.map(loc => (
            <button
              key={loc}
              type="button"
              onClick={() => toggleLoc(loc)}
              className={`px-3 py-1.5 rounded-full text-sm font-medium border transition-colors ${
                locations.includes(loc)
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'border-gray-200 text-gray-600 hover:border-blue-300 hover:text-blue-600'
              }`}
            >
              {locations.includes(loc) ? '✓ ' : ''}{loc}
            </button>
          ))}
        </div>
        <input
          value={locInput}
          onChange={e => setLocInput(e.target.value)}
          onKeyDown={locKeyDown}
          placeholder="Other location… (press Enter)"
          className={inputCls}
        />
        {locations.filter(l => !UAE_LOCATIONS.includes(l)).length > 0 && (
          <div className="flex flex-wrap gap-2 mt-2">
            {locations.filter(l => !UAE_LOCATIONS.includes(l)).map(loc => (
              <span key={loc} className="inline-flex items-center gap-1 px-3 py-1 bg-blue-50 text-blue-700 rounded-full text-xs font-medium">
                {loc}
                <button type="button" onClick={() => toggleLoc(loc)} className="text-blue-400 hover:text-blue-600">×</button>
              </span>
            ))}
          </div>
        )}
      </div>

      {error && <p className="text-red-600 text-sm">{error}</p>}

      <button
        type="submit"
        disabled={saving}
        className="bg-blue-600 text-white px-5 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm font-medium transition"
      >
        {saving ? 'Saving…' : saved ? '✓ Saved' : 'Save recommendations'}
      </button>
    </form>
  )
}

export { parseList }
