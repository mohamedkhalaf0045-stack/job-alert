'use client'

import { useState, useEffect } from 'react'
import { createClient } from '@/lib/supabase/client'
import { useRouter } from 'next/navigation'
import CVUploadCard, { CVData } from '@/components/CVUploadCard'

type Step   = 1 | 2 | 3
type Source = 'cv' | 'linkedin' | null

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

  // Step 1 — source
  const [source,            setSource]            = useState<Source>(null)
  const [linkedInMode,      setLinkedInMode]      = useState<'url' | 'text'>('url')
  const [linkedInUrl,       setLinkedInUrl]       = useState('')
  const [linkedInText,      setLinkedInText]      = useState('')
  const [linkedInLoading,   setLinkedInLoading]   = useState(false)
  const [linkedInError,     setLinkedInError]     = useState('')
  const [linkedInDone,      setLinkedInDone]      = useState(false)
  const [suggestedLocations, setSuggestedLocations] = useState<string[]>([])

  // Step 2 — keywords
  const [keywordInput,       setKeywordInput]       = useState('')
  const [keywords,           setKeywords]           = useState<string[]>([])
  const [suggestedKeywords,  setSuggestedKeywords]  = useState<string[]>([])
  const [recommendedKeywords, setRecommendedKeywords] = useState<string[]>([])

  // Step 3 — locations + finish
  const [recommendedLocations, setRecommendedLocations] = useState<string[]>([])
  const [locations,    setLocations]    = useState<string[]>([])
  const [locationInput, setLocationInput] = useState('')
  const [excludes,     setExcludes]     = useState('')
  const [frequency,    setFrequency]    = useState<'instant' | 'daily' | 'off'>('daily')
  const [loading,      setLoading]      = useState(false)
  const [error,        setError]        = useState('')

  useEffect(() => {
    fetch('/api/app/recommended-settings')
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data.keywords)  && data.keywords.length  > 0) setRecommendedKeywords(data.keywords)
        if (Array.isArray(data.locations) && data.locations.length > 0) setRecommendedLocations(data.locations)
      })
      .catch(() => {})
  }, [])

  // ── CV handler ────────────────────────────────────────────────────────────
  function handleCVAnalyzed(data: CVData) {
    const titles = (data.job_titles ?? []).slice(0, 5)
    setSuggestedKeywords(titles)
    setSource('cv')
  }

  // ── LinkedIn handler ──────────────────────────────────────────────────────
  async function handleLinkedInExtract() {
    setLinkedInLoading(true)
    setLinkedInError('')
    try {
      let res: Response
      if (linkedInMode === 'url') {
        if (!linkedInUrl.trim().includes('linkedin.com')) {
          setLinkedInError('Enter a valid LinkedIn profile URL (e.g. linkedin.com/in/yourname)')
          return
        }
        res = await fetch('/api/app/linkedin/fetch-url', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ url: linkedInUrl.trim() }),
        })
      } else {
        if (linkedInText.trim().length < 20) {
          setLinkedInError('Paste at least a few lines from your LinkedIn profile.')
          return
        }
        res = await fetch('/api/app/linkedin/profile', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ text: linkedInText }),
        })
      }
      const json = await res.json()
      if (res.status === 401) throw new Error('Please sign in to use this feature.')
      if (!res.ok) throw new Error(json.error ?? 'Failed to parse profile')
      const { analysis } = json
      setSuggestedKeywords((analysis.job_titles ?? []).slice(0, 6))
      setSuggestedLocations(analysis.locations ?? [])
      setLinkedInDone(true)
    } catch (e) {
      setLinkedInError(e instanceof Error ? e.message : 'Unknown error')
    } finally {
      setLinkedInLoading(false)
    }
  }

  // ── Keywords helpers ──────────────────────────────────────────────────────
  function addKeyword(kw: string) {
    const t = kw.trim()
    if (t && !keywords.includes(t)) setKeywords(prev => [...prev, t])
  }
  function removeKeyword(kw: string) { setKeywords(prev => prev.filter(k => k !== kw)) }
  function handleKeywordKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      addKeyword(keywordInput)
      setKeywordInput('')
    }
  }

  // ── Location helpers ──────────────────────────────────────────────────────
  function toggleLocation(loc: string) {
    setLocations(prev => prev.includes(loc) ? prev.filter(l => l !== loc) : [...prev, loc])
  }
  function handleLocationKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      const t = locationInput.trim()
      if (t && !locations.includes(t)) setLocations(prev => [...prev, t])
      setLocationInput('')
    }
  }

  // ── When moving to Step 3, pre-select LinkedIn-suggested locations ─────────
  function goToStep3() {
    if (suggestedLocations.length > 0 && locations.length === 0) {
      setLocations(suggestedLocations.filter(l => UAE_LOCATIONS.includes(l)))
    }
    setStep(3)
  }

  // ── Final submit ──────────────────────────────────────────────────────────
  async function handleFinish() {
    if (keywords.length  === 0) { setError('Add at least one keyword.');    return }
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
  const steps    = [{ n: 1, label: 'Profile' }, { n: 2, label: 'Keywords' }, { n: 3, label: 'Location' }]

  // Whether Step 1 is "done" (CV uploaded, LinkedIn extracted, or skipped)
  const step1Done = source === 'cv' || linkedInDone

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
                  step > s.n  ? 'bg-green-500 text-white' :
                  step === s.n ? 'bg-blue-600 text-white'  :
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

        {/* ── STEP 1: Profile source ─────────────────────────────────── */}
        {step === 1 && (
          <div className="bg-white rounded-xl shadow-sm p-6">
            <h2 className="text-lg font-semibold mb-1">Import your profile</h2>
            <p className="text-sm text-gray-500 mb-5">
              We extract your job titles and skills to find better matches automatically.
            </p>

            {/* Source selector */}
            <div className="grid grid-cols-2 gap-3 mb-5">
              <button
                onClick={() => setSource('cv')}
                className={`flex flex-col items-center gap-2 p-4 rounded-xl border-2 transition-colors text-sm font-medium ${
                  source === 'cv'
                    ? 'border-blue-600 bg-blue-50 text-blue-700'
                    : 'border-gray-200 text-gray-600 hover:border-blue-300'
                }`}
              >
                <span className="text-2xl">📄</span>
                Upload CV
                <span className="text-xs font-normal text-gray-400">PDF or TXT</span>
              </button>
              <button
                onClick={() => { setSource('linkedin'); setLinkedInDone(false); setLinkedInError('') }}
                className={`flex flex-col items-center gap-2 p-4 rounded-xl border-2 transition-colors text-sm font-medium ${
                  source === 'linkedin'
                    ? 'border-blue-600 bg-blue-50 text-blue-700'
                    : 'border-gray-200 text-gray-600 hover:border-blue-300'
                }`}
              >
                <span className="text-2xl">💼</span>
                LinkedIn
                <span className="text-xs font-normal text-gray-400">URL or paste text</span>
              </button>
            </div>

            {/* CV panel */}
            {source === 'cv' && (
              <div className="mb-4">
                <CVUploadCard onAnalysisComplete={handleCVAnalyzed} />
              </div>
            )}

            {/* LinkedIn panel */}
            {source === 'linkedin' && !linkedInDone && (
              <div className="mb-4">
                {/* URL / Text toggle */}
                <div className="flex rounded-lg border border-gray-200 overflow-hidden mb-3 text-xs font-medium">
                  <button
                    onClick={() => { setLinkedInMode('url'); setLinkedInError('') }}
                    className={`flex-1 py-2 transition-colors ${linkedInMode === 'url' ? 'bg-blue-600 text-white' : 'text-gray-500 hover:bg-gray-50'}`}
                  >
                    Profile URL
                  </button>
                  <button
                    onClick={() => { setLinkedInMode('text'); setLinkedInError('') }}
                    className={`flex-1 py-2 transition-colors ${linkedInMode === 'text' ? 'bg-blue-600 text-white' : 'text-gray-500 hover:bg-gray-50'}`}
                  >
                    Paste text
                  </button>
                </div>

                {linkedInMode === 'url' ? (
                  <>
                    <p className="text-xs text-gray-500 mb-2">
                      Paste your LinkedIn profile URL and we&apos;ll extract your job titles automatically.
                    </p>
                    <input
                      value={linkedInUrl}
                      onChange={e => setLinkedInUrl(e.target.value)}
                      placeholder="https://www.linkedin.com/in/yourname"
                      className={inputCls}
                    />
                  </>
                ) : (
                  <>
                    <p className="text-xs text-gray-500 mb-2">
                      Open your LinkedIn profile → copy your <strong>About</strong> section and/or
                      recent job titles, then paste below.
                    </p>
                    <textarea
                      value={linkedInText}
                      onChange={e => setLinkedInText(e.target.value)}
                      placeholder="IT Support Engineer at Acme Corp · Dubai, UAE&#10;Skills: Windows Server, Active Directory, Azure AD…"
                      rows={5}
                      className={`${inputCls} resize-none`}
                    />
                  </>
                )}

                {linkedInError && (
                  <p className="text-xs text-red-500 mt-1">{linkedInError}</p>
                )}
                <button
                  onClick={handleLinkedInExtract}
                  disabled={
                    linkedInLoading ||
                    (linkedInMode === 'url'  && !linkedInUrl.trim().includes('linkedin.com')) ||
                    (linkedInMode === 'text' && linkedInText.trim().length < 20)
                  }
                  className="mt-3 w-full bg-blue-600 text-white py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {linkedInLoading ? 'Fetching…' : 'Extract keywords →'}
                </button>
              </div>
            )}

            {/* LinkedIn done */}
            {source === 'linkedin' && linkedInDone && (
              <div className="mb-4 flex items-center gap-2 text-green-700 bg-green-50 rounded-lg px-3 py-2 text-sm">
                <span>✓</span>
                <span>Profile analysed — keywords extracted successfully</span>
              </div>
            )}

            <div className="mt-4 flex flex-col gap-3">
              {step1Done ? (
                <button
                  onClick={() => setStep(2)}
                  className="w-full bg-blue-600 text-white py-2.5 rounded-lg hover:bg-blue-700 font-medium text-sm"
                >
                  Continue →
                </button>
              ) : (
                <>
                  <p className="text-xs text-gray-400 text-center">
                    {source ? 'Complete the step above, or' : "Don't have your CV or LinkedIn handy?"}
                  </p>
                  <button
                    onClick={() => setStep(2)}
                    className="w-full border border-gray-200 text-gray-500 py-2.5 rounded-lg hover:bg-gray-50 text-sm font-medium"
                  >
                    Skip — I&apos;ll enter keywords manually
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
              <span className="text-red-500 ml-1">*</span>
            </p>

            {/* Admin recommended */}
            {recommendedKeywords.length > 0 && (
              <div className="mb-4">
                <p className="text-xs font-medium text-gray-500 mb-2">Popular searches:</p>
                <div className="flex flex-wrap gap-2">
                  {recommendedKeywords.map(kw => (
                    <button key={kw} onClick={() => addKeyword(kw)} disabled={keywords.includes(kw)}
                      className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                        keywords.includes(kw) ? 'bg-blue-600 text-white border-blue-600' : 'border-blue-300 text-blue-600 hover:bg-blue-50'
                      }`}>
                      {keywords.includes(kw) ? '✓ ' : '+ '}{kw}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* From CV / LinkedIn */}
            {suggestedKeywords.length > 0 && (
              <div className="mb-4">
                <p className="text-xs font-medium text-gray-500 mb-2">
                  {source === 'linkedin' ? 'From your LinkedIn:' : 'From your CV:'}
                </p>
                <div className="flex flex-wrap gap-2">
                  {suggestedKeywords.map(kw => (
                    <button key={kw} onClick={() => addKeyword(kw)} disabled={keywords.includes(kw)}
                      className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                        keywords.includes(kw) ? 'bg-blue-600 text-white border-blue-600' : 'border-green-300 text-green-700 hover:bg-green-50'
                      }`}>
                      {keywords.includes(kw) ? '✓ ' : '+ '}{kw}
                    </button>
                  ))}
                </div>
              </div>
            )}

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
              <p className="text-xs text-red-500 mt-2">At least one keyword is required to continue</p>
            )}

            <div className="mt-6 flex gap-3">
              <button onClick={() => setStep(1)}
                className="flex-1 border border-gray-200 text-gray-600 py-2.5 rounded-lg hover:bg-gray-50 text-sm">
                ← Back
              </button>
              <button onClick={() => { if (keywords.length > 0) goToStep3() }}
                disabled={keywords.length === 0}
                className="flex-1 bg-blue-600 text-white py-2.5 rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed font-medium text-sm">
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
              <span className="text-red-500 ml-1">*</span>
            </p>

            {suggestedLocations.length > 0 && (
              <p className="text-xs text-green-700 bg-green-50 rounded px-2 py-1.5 mb-3">
                ✓ Pre-selected from your LinkedIn profile — adjust as needed
              </p>
            )}

            <div className="flex flex-wrap gap-2 mb-4">
              {UAE_LOCATIONS.map(loc => {
                const isSelected    = locations.includes(loc)
                const isRecommended = recommendedLocations.includes(loc)
                const isSuggested   = suggestedLocations.includes(loc)
                return (
                  <button key={loc} onClick={() => toggleLocation(loc)}
                    className={`px-3 py-1.5 rounded-full text-sm font-medium border transition-colors ${
                      isSelected
                        ? 'bg-blue-600 text-white border-blue-600'
                        : isSuggested
                          ? 'border-green-400 text-green-700 hover:bg-green-50'
                          : isRecommended
                            ? 'border-blue-300 text-blue-600 hover:bg-blue-50'
                            : 'border-gray-200 text-gray-600 hover:border-blue-300 hover:text-blue-600'
                    }`}>
                    {isSelected ? '✓ ' : ''}{loc}
                  </button>
                )
              })}
            </div>

            {recommendedLocations.filter(l => !UAE_LOCATIONS.includes(l)).length > 0 && (
              <div className="flex flex-wrap gap-2 mb-3">
                {recommendedLocations.filter(l => !UAE_LOCATIONS.includes(l)).map(loc => (
                  <button key={loc} onClick={() => toggleLocation(loc)}
                    className={`px-3 py-1.5 rounded-full text-sm font-medium border transition-colors ${
                      locations.includes(loc) ? 'bg-blue-600 text-white border-blue-600' : 'border-blue-300 text-blue-600 hover:bg-blue-50'
                    }`}>
                    {locations.includes(loc) ? '✓ ' : ''}{loc}
                  </button>
                ))}
              </div>
            )}

            <input
              value={locationInput}
              onChange={e => setLocationInput(e.target.value)}
              onKeyDown={handleLocationKeyDown}
              placeholder="Other location… (press Enter to add)"
              className={inputCls}
            />

            {locations.filter(l => !UAE_LOCATIONS.includes(l) && !recommendedLocations.includes(l)).length > 0 && (
              <div className="flex flex-wrap gap-2 mt-3">
                {locations.filter(l => !UAE_LOCATIONS.includes(l) && !recommendedLocations.includes(l)).map(loc => (
                  <span key={loc} className="inline-flex items-center gap-1 px-3 py-1 bg-blue-50 text-blue-700 rounded-full text-xs font-medium">
                    {loc}
                    <button onClick={() => toggleLocation(loc)} className="text-blue-400 hover:text-blue-600">×</button>
                  </span>
                ))}
              </div>
            )}

            {locations.length === 0 && (
              <p className="text-xs text-red-500 mt-2">Select at least one location to continue</p>
            )}

            <hr className="my-5 border-gray-100" />

            <div className="mb-4">
              <label className="block text-sm font-medium mb-1">Alert frequency</label>
              <select value={frequency} onChange={e => setFrequency(e.target.value as 'instant' | 'daily' | 'off')}
                className={inputCls}>
                <option value="daily">Daily digest (8 AM)</option>
                <option value="instant">Instant (within 15 min of a match)</option>
                <option value="off">Off — I&apos;ll browse manually</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">
                Exclude keywords <span className="text-gray-400 font-normal">(optional)</span>
              </label>
              <input value={excludes} onChange={e => setExcludes(e.target.value)}
                placeholder="Senior, Manager, Intern" className={inputCls} />
              <p className="text-xs text-gray-400 mt-1">Jobs containing these words will be hidden</p>
            </div>

            {error && <p className="text-red-600 text-sm mt-3">{error}</p>}

            <div className="mt-6 flex gap-3">
              <button onClick={() => setStep(2)}
                className="flex-1 border border-gray-200 text-gray-600 py-2.5 rounded-lg hover:bg-gray-50 text-sm">
                ← Back
              </button>
              <button onClick={handleFinish} disabled={loading || locations.length === 0}
                className="flex-1 bg-blue-600 text-white py-2.5 rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed font-medium text-sm">
                {loading ? 'Saving…' : 'Go to my feed →'}
              </button>
            </div>
          </div>
        )}

      </div>
    </div>
  )
}
