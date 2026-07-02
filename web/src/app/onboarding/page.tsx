'use client'

import { useState, useEffect } from 'react'
import { createClient } from '@/lib/supabase/client'
import { useRouter } from 'next/navigation'
import CVUploadCard, { CVData } from '@/components/CVUploadCard'
import OnboardingChatbot from '@/components/OnboardingChatbot'
import LocationGroupPicker from '@/components/LocationGroupPicker'
import { ROLE_FAMILIES } from '@/config/role-families'
import { LOCATION_GROUPS } from '@/config/location-groups'

type Step   = 1 | 2 | 3
type Source = 'cv' | 'linkedin' | null

export default function OnboardingPage() {
  const router = useRouter()
  const [step, setStep] = useState<Step>(1)
  const [useChatbot, setUseChatbot] = useState(false)

  // Step 1 — source
  const [source,            setSource]            = useState<Source>(null)
  const [linkedInMode,      setLinkedInMode]      = useState<'url' | 'text'>('url')
  const [linkedInUrl,       setLinkedInUrl]       = useState('')
  const [linkedInText,      setLinkedInText]      = useState('')
  const [linkedInLoading,   setLinkedInLoading]   = useState(false)
  const [linkedInError,     setLinkedInError]     = useState('')
  const [linkedInDone,      setLinkedInDone]      = useState(false)
  const [linkedInOAuthName, setLinkedInOAuthName] = useState('')
  const [suggestedLocations, setSuggestedLocations] = useState<string[]>([])

  // Step 2 — keywords
  const [keywordInput,        setKeywordInput]        = useState('')
  const [keywords,            setKeywords]            = useState<string[]>([])
  const [suggestedKeywords,   setSuggestedKeywords]   = useState<string[]>([])
  const [recommendedKeywords, setRecommendedKeywords] = useState<string[]>([])

  // Role expansion state
  const [selectedFamily,       setSelectedFamily]       = useState<string | null>(null)
  const [expandedVariations,   setExpandedVariations]   = useState<string[]>([])
  const [expanding,            setExpanding]            = useState(false)
  const [expandedFor,          setExpandedFor]          = useState<string[]>([])
  const [keywordExpansionsData, setKeywordExpansionsData] = useState<Record<string, {
    original: string; variations: string[]; related_skills: string[]; generated_at: string
  }>>({})

  // Step 3 — locations + finish
  const [recommendedLocations, setRecommendedLocations] = useState<string[]>([])
  const [locations,    setLocations]    = useState<string[]>([])
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

  // Handle LinkedIn OAuth callback
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const raw    = params.get('li_data')
    const err    = params.get('li_error')
    if (raw) {
      try {
        const { name, headline, jobTitle } = JSON.parse(atob(raw)) as {
          name: string; headline: string; jobTitle: string
        }
        setSource('linkedin')
        if (jobTitle) {
          setSuggestedKeywords([jobTitle])
          setLinkedInDone(true)
        } else if (name) {
          setLinkedInOAuthName(name)
          setSource('linkedin')
        }
      } catch { /* ignore */ }
      router.replace('/onboarding')
    }
    if (err) {
      setLinkedInError(
        err === 'denied' ? 'LinkedIn authorization was cancelled.' : 'LinkedIn connection failed — try another method.'
      )
      setSource('linkedin')
      router.replace('/onboarding')
    }
  }, [router])

  // Auto-expand keywords in background (debounced 1s)
  useEffect(() => {
    if (keywords.length === 0) return
    const toExpand = keywords.filter(kw => !expandedFor.includes(kw))
    if (toExpand.length === 0) return

    const timer = setTimeout(async () => {
      setExpanding(true)
      try {
        const newExpData = { ...keywordExpansionsData }
        const newVariants: string[] = []
        // Sequential (not parallel) to avoid Groq 429 rate limit
        for (const kw of toExpand) {
          await new Promise(r => setTimeout(r, 300)) // 300ms gap between calls
          const r = await fetch('/api/app/cv/expand-keywords', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ keyword: kw }),
          }).then(res => res.ok ? res.json() : null).catch(() => null)
          if (!r?.expansion) continue
          const key = (r.keyword as string).toLowerCase()
          newExpData[key] = {
            original:       r.keyword as string,
            variations:     (r.expansion.title_variations as string[]) ?? [],
            related_skills: (r.expansion.related_skills   as string[]) ?? [],
            generated_at:   new Date().toISOString(),
          }
          for (const v of ((r.expansion.title_variations as string[]) ?? [])) {
            if (!keywords.includes(v) && !newVariants.includes(v)) newVariants.push(v)
          }
        }
        setExpandedFor(prev => Array.from(new Set([...prev, ...toExpand])))
        setKeywordExpansionsData(newExpData)
        setExpandedVariations(prev => {
          const existing = new Set([...prev, ...keywords])
          return [...prev, ...newVariants.filter(v => !existing.has(v))]
        })
      } finally {
        setExpanding(false)
      }
    }, 1000)

    return () => clearTimeout(timer)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keywords.join('|')])

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

  // ── Role family select ────────────────────────────────────────────────────
  function selectFamily(familyKey: string) {
    if (selectedFamily === familyKey) {
      setSelectedFamily(null)
      return
    }
    setSelectedFamily(familyKey)
    const family = ROLE_FAMILIES[familyKey]
    setKeywords(prev => {
      const existing = new Set(prev)
      return [...prev, ...family.keywords.filter(kw => !existing.has(kw))]
    })
  }

  // ── When moving to Step 3, pre-select LinkedIn-suggested locations ─────────
  function goToStep3() {
    if (suggestedLocations.length > 0 && locations.length === 0) {
      // Map LinkedIn-suggested locations to known group locations
      const allGroupLocs = new Set(
        Object.values(LOCATION_GROUPS).flatMap(g => g.locations)
      )
      setLocations(suggestedLocations.filter(l => allGroupLocs.has(l)))
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
        user_id:            user.id,
        keywords,
        locations,
        exclude_keywords:   excludes.split(',').map(s => s.trim()).filter(Boolean),
        alert_frequency:    frequency,
        keyword_expansions: keywordExpansionsData,
        updated_at:         new Date().toISOString(),
      },
      { onConflict: 'user_id' }
    )
    setLoading(false)
    if (dbErr) { setError(dbErr.message); return }
    router.push('/app/feed')
  }

  const inputCls = 'w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'
  const steps    = [{ n: 1, label: 'Profile' }, { n: 2, label: 'Keywords' }, { n: 3, label: 'Location' }]

  const step1Done = source === 'cv' || linkedInDone

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-start px-4 py-12">
      <div className="w-full max-w-lg">

        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-gray-900">Set up your job search</h1>
          <p className="text-gray-500 text-sm mt-1">Takes less than 2 minutes</p>
        </div>

        {/* Form / chatbot toggle */}
        <div className="text-center mb-6">
          <button
            onClick={() => setUseChatbot(prev => !prev)}
            className="text-sm text-blue-600 hover:text-blue-700 font-medium underline underline-offset-2"
          >
            {useChatbot ? '← Use the step-by-step form instead' : 'Prefer to chat instead?'}
          </button>
        </div>

        {useChatbot ? (
          <div className="flex justify-center">
            <OnboardingChatbot profileType="candidate" />
          </div>
        ) : (
        <>
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

                {linkedInOAuthName ? (
                  <div className="flex items-center gap-2 p-3 rounded-lg bg-green-50 border border-green-200 mb-3 text-sm text-green-800">
                    <span>✓</span>
                    <span>Connected as <strong>{linkedInOAuthName}</strong> — paste your profile text below to extract job titles.</span>
                  </div>
                ) : (
                  <a
                    href="/api/auth/linkedin"
                    className="flex items-center justify-center gap-2 w-full py-2.5 rounded-lg bg-[#0A66C2] hover:bg-[#004182] text-white text-sm font-medium transition-colors mb-3"
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M19 3a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14m-.5 15.5v-5.3a3.26 3.26 0 0 0-3.26-3.26c-.85 0-1.84.52-2.32 1.3v-1.11h-2.79v8.37h2.79v-4.93c0-.77.62-1.4 1.39-1.4a1.4 1.4 0 0 1 1.4 1.4v4.93h2.79M6.88 8.56a1.68 1.68 0 0 0 1.68-1.68c0-.93-.75-1.69-1.68-1.69a1.69 1.69 0 0 0-1.69 1.69c0 .93.76 1.68 1.69 1.68m1.39 9.94v-8.37H5.5v8.37h2.77z"/>
                    </svg>
                    Connect with LinkedIn
                  </a>
                )}

                <div className="flex items-center gap-2 mb-3">
                  <div className="flex-1 h-px bg-gray-200" />
                  <span className="text-xs text-gray-400">or</span>
                  <div className="flex-1 h-px bg-gray-200" />
                </div>

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

            {/* Role family quick-select */}
            <div className="mb-4">
              <p className="text-xs font-medium text-gray-500 mb-2">Quick start — pick your field:</p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(ROLE_FAMILIES).map(([key, family]) => (
                  <button
                    key={key}
                    onClick={() => selectFamily(key)}
                    className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${
                      selectedFamily === key
                        ? 'bg-blue-600 text-white border-blue-600'
                        : 'border-gray-200 text-gray-600 hover:border-blue-300 hover:text-blue-600'
                    }`}
                  >
                    {family.label}
                  </button>
                ))}
              </div>
            </div>

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

            {/* AI expansion results */}
            {expanding && keywords.length > 0 && (
              <div className="mt-4 flex items-center gap-2 text-xs text-gray-500">
                <svg className="animate-spin h-3 w-3 text-blue-500" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Finding related roles with AI…
              </div>
            )}

            {!expanding && expandedVariations.length > 0 && (
              <div className="mt-4 p-3 bg-blue-50 rounded-lg border border-blue-100">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-medium text-blue-700">AI found similar roles:</p>
                  <button
                    onClick={() => {
                      expandedVariations.filter(v => !keywords.includes(v)).forEach(v => addKeyword(v))
                      setExpandedVariations([])
                    }}
                    className="text-xs text-blue-600 hover:text-blue-800 font-medium"
                  >
                    Add all
                  </button>
                </div>
                <div className="flex flex-wrap gap-2">
                  {expandedVariations.map(v => (
                    <button
                      key={v}
                      onClick={() => {
                        addKeyword(v)
                        setExpandedVariations(prev => prev.filter(x => x !== v))
                      }}
                      disabled={keywords.includes(v)}
                      className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
                        keywords.includes(v)
                          ? 'bg-blue-600 text-white border-blue-600 opacity-60'
                          : 'border-blue-300 text-blue-600 hover:bg-blue-100'
                      }`}
                    >
                      {keywords.includes(v) ? '✓ ' : '+ '}{v}
                    </button>
                  ))}
                </div>
                <button
                  onClick={() => setExpandedVariations([])}
                  className="text-xs text-gray-400 hover:text-gray-600 mt-2 block"
                >
                  Dismiss suggestions
                </button>
              </div>
            )}

            <div className="mt-6 flex gap-3">
              <button onClick={() => setStep(1)}
                className="flex-1 border border-gray-200 text-gray-600 py-2.5 rounded-lg hover:bg-gray-50 text-sm">
                ← Back
              </button>
              <button
                onClick={() => { if (keywords.length > 0) goToStep3() }}
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
              Pick one or more countries — all cities are included automatically.
              <span className="text-red-500 ml-1">*</span>
            </p>

            {suggestedLocations.length > 0 && (
              <p className="text-xs text-green-700 bg-green-50 rounded px-2 py-1.5 mb-3">
                ✓ Pre-selected from your LinkedIn profile — adjust as needed
              </p>
            )}

            <LocationGroupPicker value={locations} onChange={setLocations} />

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
        </>
        )}

      </div>
    </div>
  )
}
