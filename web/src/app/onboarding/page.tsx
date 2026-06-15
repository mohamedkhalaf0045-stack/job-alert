'use client'

import { useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import { useRouter } from 'next/navigation'
import CVUploadCard, { CVData } from '@/components/CVUploadCard'

type Step = 1 | 2 | 3

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

export default function OnboardingPage() {
  const router = useRouter()
  const [step, setStep] = useState<Step>(1)

  // Step 1 — CV
  const [cvUploaded, setCvUploaded] = useState(false)
  const [cvSkipped, setCvSkipped] = useState(false)

  // Step 2 — Keywords
  const [keywordInput, setKeywordInput] = useState('')
  const [keywords, setKeywords] = useState<string[]>([])
  const [suggestedKeywords, setSuggestedKeywords] = useState<string[]>([])

  // Step 3 — Locations + finish
  const [locations, setLocations] = useState<string[]>([])
  const [locationInput, setLocationInput] = useState('')
  const [excludes, setExcludes] = useState('')
  const [frequency, setFrequency] = useState<'instant' | 'daily' | 'off'>('daily')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // ── CV step handlers ─────────────────────────────────────────────────────
  function handleCVAnalyzed(data: CVData) {
    setCvUploaded(true)
    const titles = (data.job_titles ?? []).slice(0, 5)
    setSuggestedKeywords(titles)
  }

  // ── Keywords step helpers ────────────────────────────────────────────────
  function addKeyword(kw: string) {
    const trimmed = kw.trim()
    if (trimmed && !keywords.includes(trimmed)) {
      setKeywords(prev => [...prev, trimmed])
    }
  }

  function removeKeyword(kw: string) {
    setKeywords(prev => prev.filter(k => k !== kw))
  }

  function handleKeywordKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      addKeyword(keywordInput)
      setKeywordInput('')
    }
  }

  // ── Location helpers ─────────────────────────────────────────────────────
  function toggleLocation(loc: string) {
    setLocations(prev =>
      prev.includes(loc) ? prev.filter(l => l !== loc) : [...prev, loc]
    )
  }

  function handleLocationKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      const trimmed = locationInput.trim()
      if (trimmed && !locations.includes(trimmed)) {
        setLocations(prev => [...prev, trimmed])
      }
      setLocationInput('')
    }
  }

  // ── Final submit ─────────────────────────────────────────────────────────
  async function handleFinish() {
    if (keywords.length === 0) { setError('Add at least one keyword.'); return }
    if (locations.length === 0) { setError('Select at least one location.'); return }
    setError('')
    setLoading(true)
    const supabase = createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) { router.push('/login'); return }

    const { error: dbErr } = await supabase.from('user_preferences').upsert(
      {
        user_id:          user.id,
        keywords,
        locations,
        exclude_keywords: excludes.split(',').map(s => s.trim()).filter(Boolean),
        alert_frequency:  frequency,
        updated_at:       new Date().toISOString(),
      },
      { onConflict: 'user_id' }
    )
    setLoading(false)
    if (dbErr) { setError(dbErr.message); return }
    router.push('/app/feed')
  }

  const inputCls = 'w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'

  // ── Step indicators ──────────────────────────────────────────────────────
  const steps = [
    { n: 1, label: 'Your CV' },
    { n: 2, label: 'Keywords' },
    { n: 3, label: 'Location' },
  ]

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-start px-4 py-12">
      <div className="w-full max-w-lg">

        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-gray-900">Set up your job search</h1>
          <p className="text-gray-500 text-sm mt-1">Takes less than 2 minutes</p>
        </div>

        {/* Step progress */}
        <div className="flex items-center justify-center mb-8 gap-0">
          {steps.map((s, i) => (
            <div key={s.n} className="flex items-center">
              <div className="flex flex-col items-center">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold transition-colors ${
                  step > s.n ? 'bg-green-500 text-white' :
                  step === s.n ? 'bg-blue-600 text-white' :
                  'bg-gray-200 text-gray-500'
                }`}>
                  {step > s.n ? '✓' : s.n}
                </div>
                <span className={`text-xs mt-1 font-medium ${step === s.n ? 'text-blue-600' : 'text-gray-400'}`}>
                  {s.label}
                </span>
              </div>
              {i < steps.length - 1 && (
                <div className={`w-16 h-0.5 mb-5 mx-1 transition-colors ${step > s.n ? 'bg-green-400' : 'bg-gray-200'}`} />
              )}
            </div>
          ))}
        </div>

        {/* ── STEP 1: CV ─────────────────────────────────────────────── */}
        {step === 1 && (
          <div className="bg-white rounded-xl shadow-sm p-6">
            <h2 className="text-lg font-semibold mb-1">Upload your CV</h2>
            <p className="text-sm text-gray-500 mb-5">
              We extract your skills and job titles to find you better matches automatically.
            </p>

            <CVUploadCard onAnalysisComplete={handleCVAnalyzed} />

            <div className="mt-6 flex flex-col gap-3">
              {cvUploaded ? (
                <button
                  onClick={() => setStep(2)}
                  className="w-full bg-blue-600 text-white py-2.5 rounded-lg hover:bg-blue-700 font-medium text-sm"
                >
                  Continue →
                </button>
              ) : (
                <>
                  <p className="text-xs text-gray-400 text-center">
                    Upload your CV above to continue, or skip if you don&apos;t have one handy.
                  </p>
                  <button
                    onClick={() => { setCvSkipped(true); setStep(2) }}
                    className="w-full border border-gray-200 text-gray-500 py-2.5 rounded-lg hover:bg-gray-50 text-sm font-medium"
                  >
                    Skip for now
                  </button>
                </>
              )}
            </div>
          </div>
        )}

        {/* ── STEP 2: Keywords ───────────────────────────────────────── */}
        {step === 2 && (
          <div className="bg-white rounded-xl shadow-sm p-6">
            <h2 className="text-lg font-semibold mb-1">What jobs are you looking for?</h2>
            <p className="text-sm text-gray-500 mb-5">
              Add job titles you want to find. Press Enter or comma to add each one.
            </p>

            {/* CV suggestions */}
            {suggestedKeywords.length > 0 && (
              <div className="mb-4">
                <p className="text-xs font-medium text-gray-500 mb-2">From your CV:</p>
                <div className="flex flex-wrap gap-2">
                  {suggestedKeywords.map(kw => (
                    <button
                      key={kw}
                      onClick={() => addKeyword(kw)}
                      disabled={keywords.includes(kw)}
                      className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                        keywords.includes(kw)
                          ? 'bg-blue-600 text-white border-blue-600'
                          : 'border-blue-300 text-blue-600 hover:bg-blue-50'
                      }`}
                    >
                      {keywords.includes(kw) ? '✓ ' : '+ '}{kw}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Keyword input */}
            <input
              value={keywordInput}
              onChange={e => setKeywordInput(e.target.value)}
              onKeyDown={handleKeywordKeyDown}
              onBlur={() => { if (keywordInput.trim()) { addKeyword(keywordInput); setKeywordInput('') } }}
              placeholder="e.g. IT Support, System Administrator"
              className={inputCls}
              autoFocus
            />
            <p className="text-xs text-gray-400 mt-1">Press Enter or comma after each keyword</p>

            {/* Added keywords */}
            {keywords.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-3">
                {keywords.map(kw => (
                  <span key={kw} className="inline-flex items-center gap-1 px-3 py-1 bg-blue-50 text-blue-700 rounded-full text-xs font-medium">
                    {kw}
                    <button onClick={() => removeKeyword(kw)} className="text-blue-400 hover:text-blue-600 ml-0.5">×</button>
                  </span>
                ))}
              </div>
            )}

            {keywords.length === 0 && (
              <p className="text-xs text-red-500 mt-2">At least one keyword is required</p>
            )}

            <div className="mt-6 flex gap-3">
              <button
                onClick={() => setStep(1)}
                className="flex-1 border border-gray-200 text-gray-600 py-2.5 rounded-lg hover:bg-gray-50 text-sm"
              >
                ← Back
              </button>
              <button
                onClick={() => { if (keywords.length > 0) setStep(3) }}
                disabled={keywords.length === 0}
                className="flex-1 bg-blue-600 text-white py-2.5 rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed font-medium text-sm"
              >
                Continue →
              </button>
            </div>
          </div>
        )}

        {/* ── STEP 3: Location + finish ──────────────────────────────── */}
        {step === 3 && (
          <div className="bg-white rounded-xl shadow-sm p-6">
            <h2 className="text-lg font-semibold mb-1">Where are you looking?</h2>
            <p className="text-sm text-gray-500 mb-5">
              Select all countries or cities that apply.
            </p>

            {/* Location chips */}
            <div className="flex flex-wrap gap-2 mb-4">
              {UAE_LOCATIONS.map(loc => (
                <button
                  key={loc}
                  onClick={() => toggleLocation(loc)}
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

            {/* Custom location input */}
            <input
              value={locationInput}
              onChange={e => setLocationInput(e.target.value)}
              onKeyDown={handleLocationKeyDown}
              placeholder="Other location... (press Enter to add)"
              className={inputCls}
            />

            {/* Added custom locations */}
            {locations.filter(l => !UAE_LOCATIONS.includes(l)).length > 0 && (
              <div className="flex flex-wrap gap-2 mt-3">
                {locations.filter(l => !UAE_LOCATIONS.includes(l)).map(loc => (
                  <span key={loc} className="inline-flex items-center gap-1 px-3 py-1 bg-blue-50 text-blue-700 rounded-full text-xs font-medium">
                    {loc}
                    <button onClick={() => toggleLocation(loc)} className="text-blue-400 hover:text-blue-600">×</button>
                  </span>
                ))}
              </div>
            )}

            {locations.length === 0 && (
              <p className="text-xs text-red-500 mt-2">Select at least one location</p>
            )}

            <hr className="my-5 border-gray-100" />

            {/* Alert frequency */}
            <div className="mb-4">
              <label className="block text-sm font-medium mb-1">Alert frequency</label>
              <select
                value={frequency}
                onChange={e => setFrequency(e.target.value as 'instant' | 'daily' | 'off')}
                className={inputCls}
              >
                <option value="daily">Daily digest (8 AM)</option>
                <option value="instant">Instant (within 15 min of a match)</option>
                <option value="off">Off — I&apos;ll browse manually</option>
              </select>
            </div>

            {/* Exclude keywords (optional) */}
            <div>
              <label className="block text-sm font-medium mb-1">
                Exclude keywords <span className="text-gray-400 font-normal">(optional)</span>
              </label>
              <input
                value={excludes}
                onChange={e => setExcludes(e.target.value)}
                placeholder="Senior, Manager, Intern"
                className={inputCls}
              />
              <p className="text-xs text-gray-400 mt-1">Jobs containing these words will be hidden</p>
            </div>

            {error && <p className="text-red-600 text-sm mt-3">{error}</p>}

            <div className="mt-6 flex gap-3">
              <button
                onClick={() => setStep(2)}
                className="flex-1 border border-gray-200 text-gray-600 py-2.5 rounded-lg hover:bg-gray-50 text-sm"
              >
                ← Back
              </button>
              <button
                onClick={handleFinish}
                disabled={loading || locations.length === 0}
                className="flex-1 bg-blue-600 text-white py-2.5 rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed font-medium text-sm"
              >
                {loading ? 'Saving…' : 'Go to my feed →'}
              </button>
            </div>
          </div>
        )}

      </div>
    </div>
  )
}
