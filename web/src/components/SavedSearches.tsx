'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'

interface SavedSearch {
  id: string
  name: string
  keywords: string[]
  locations: string[]
  min_score: number | null
}

export default function SavedSearches() {
  const router = useRouter()
  const [searches, setSearches] = useState<SavedSearch[]>([])
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)
  const [applying, setApplying] = useState(false)
  const [selected, setSelected] = useState('')

  function load() {
    fetch('/api/saved-searches')
      .then(r => r.json())
      .then(d => setSearches(Array.isArray(d.searches) ? d.searches : []))
      .catch(() => {})
  }

  useEffect(() => { load() }, [])

  async function saveCurrentFilters(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) return
    setSaving(true)

    try {
      const supabase = createClient()
      const { data: { user } } = await supabase.auth.getUser()
      if (!user) return

      // Saved searches capture the user's current keywords/locations/min_score
      // from their existing filter settings (user_preferences).
      const { data: prefs } = await supabase
        .from('user_preferences')
        .select('keywords, locations, min_score')
        .eq('user_id', user.id)
        .single()

      await fetch('/api/saved-searches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          keywords: prefs?.keywords ?? [],
          locations: prefs?.locations ?? [],
          min_score: prefs?.min_score ?? null,
        }),
      })
      setName('')
      setShowForm(false)
      load()
    } finally {
      setSaving(false)
    }
  }

  async function applySearch(id: string) {
    setSelected(id)
    const s = searches.find(s => s.id === id)
    if (!s) return
    setApplying(true)

    // Apply by writing the saved filters into user_preferences — the feed's
    // user_jobs_feed() RPC reads keywords/locations/min_score from there.
    const supabase = createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (user) {
      await supabase.from('user_preferences').update({
        keywords: s.keywords,
        locations: s.locations,
        min_score: s.min_score,
        updated_at: new Date().toISOString(),
      }).eq('user_id', user.id)
    }

    setApplying(false)
    router.push('/app/feed')
    router.refresh()
  }

  async function deleteSearch(id: string) {
    await fetch(`/api/saved-searches/${id}`, { method: 'DELETE' })
    if (selected === id) setSelected('')
    load()
  }

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {searches.length > 0 && (
        <select
          value={selected}
          onChange={e => applySearch(e.target.value)}
          disabled={applying}
          className="text-xs border border-[var(--border)] rounded-md px-2 py-1.5 bg-white text-[var(--fg-2)] disabled:opacity-50"
        >
          <option value="">Apply a saved search…</option>
          {searches.map(s => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
      )}

      {selected && (
        <button
          onClick={() => deleteSearch(selected)}
          className="text-xs text-[var(--danger)] hover:underline"
        >
          Delete
        </button>
      )}

      {!showForm ? (
        <button
          onClick={() => setShowForm(true)}
          className="text-xs px-2.5 py-1.5 rounded-md border border-[var(--border)] text-[var(--fg-2)] hover:border-[var(--accent)]/50 hover:bg-[var(--accent-bg)] hover:text-[var(--accent)] transition-colors duration-150 font-medium"
        >
          Save this search
        </button>
      ) : (
        <form onSubmit={saveCurrentFilters} className="flex items-center gap-1.5">
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Search name"
            className="text-xs border border-[var(--border)] rounded-md px-2 py-1.5 w-32"
            autoFocus
          />
          <button
            type="submit"
            disabled={saving || !name.trim()}
            className="text-xs px-2.5 py-1.5 rounded-md bg-[var(--accent)] text-white font-medium disabled:opacity-50"
          >
            {saving ? '…' : 'Save'}
          </button>
          <button
            type="button"
            onClick={() => setShowForm(false)}
            className="text-xs text-[var(--muted)] hover:text-[var(--fg)]"
          >
            Cancel
          </button>
        </form>
      )}
    </div>
  )
}
