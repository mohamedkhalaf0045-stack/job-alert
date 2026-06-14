'use client'

import { useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import { useRouter } from 'next/navigation'
import CVUploadCard from '@/components/CVUploadCard'

export default function OnboardingPage() {
  const router = useRouter()
  const [keywords,  setKeywords]  = useState('')
  const [locations, setLocations] = useState('')
  const [excludes,  setExcludes]  = useState('')
  const [frequency, setFrequency] = useState<'instant' | 'daily' | 'off'>('daily')
  const [error,     setError]     = useState('')
  const [loading,   setLoading]   = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const kw  = keywords.split(',').map(s => s.trim()).filter(Boolean)
    const loc = locations.split(',').map(s => s.trim()).filter(Boolean)
    if (!kw.length && !loc.length) {
      setError('Add at least one keyword or location to continue.')
      return
    }
    setError('')
    setLoading(true)
    const supabase = createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) { router.push('/login'); return }

    const { error } = await supabase.from('user_preferences').upsert(
      {
        user_id:          user.id,
        keywords:         kw,
        locations:        loc,
        exclude_keywords: excludes.split(',').map(s => s.trim()).filter(Boolean),
        alert_frequency:  frequency,
        updated_at:       new Date().toISOString(),
      },
      { onConflict: 'user_id' }
    )
    setLoading(false)
    if (error) { setError(error.message); return }
    router.push('/app/feed')
  }

  const inputCls = 'w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'

  return (
    <div className="min-h-screen flex items-center justify-center px-4 bg-gray-50">
      <div className="w-full max-w-md bg-white rounded-xl shadow-sm p-8">
        <h1 className="text-2xl font-bold mb-1">Set up your job search</h1>
        <p className="text-gray-500 text-sm mb-6">
          You can change these any time in Settings.
        </p>
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4">
            <p className="text-sm text-blue-900 font-medium mb-3">Optional: Upload your CV</p>
            <CVUploadCard />
            <p className="text-xs text-blue-800 mt-3">
              ℹ️ Your CV skills will help us match you with more relevant jobs. You can still enter keywords below.
            </p>
          </div>

          <hr className="border-gray-100" />

          <div>
            <label className="block text-sm font-medium mb-1">
              Job keywords <span className="text-red-500">*</span>
            </label>
            <input
              value={keywords} onChange={e => setKeywords(e.target.value)}
              placeholder="IT Support, System Administrator, Help Desk"
              className={inputCls}
            />
            <p className="text-xs text-gray-400 mt-1">Comma-separated. Any match shows the job.</p>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Locations</label>
            <input
              value={locations} onChange={e => setLocations(e.target.value)}
              placeholder="United Arab Emirates, Egypt"
              className={inputCls}
            />
            <p className="text-xs text-gray-400 mt-1">Leave blank to match all locations.</p>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Exclude keywords</label>
            <input
              value={excludes} onChange={e => setExcludes(e.target.value)}
              placeholder="Senior, Lead, Manager"
              className={inputCls}
            />
            <p className="text-xs text-gray-400 mt-1">Jobs containing any of these are hidden.</p>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Alert frequency</label>
            <select
              value={frequency}
              onChange={e => setFrequency(e.target.value as 'instant' | 'daily' | 'off')}
              className={inputCls}
            >
              <option value="daily">Daily digest (8 AM your time)</option>
              <option value="instant">Instant (within 15 min of a match)</option>
              <option value="off">Off — I&apos;ll browse manually</option>
            </select>
          </div>

          {error && <p className="text-red-600 text-sm">{error}</p>}

          <button
            type="submit" disabled={loading}
            className="w-full bg-blue-600 text-white py-2.5 rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium"
          >
            {loading ? 'Saving…' : 'Go to my feed →'}
          </button>
        </form>
      </div>
    </div>
  )
}
