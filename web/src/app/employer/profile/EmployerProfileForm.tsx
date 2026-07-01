'use client'

import { useState } from 'react'
import type { EmployerProfile } from '@/app/api/employers/profile/route'

const inputCls = 'w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)]'

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-sm font-medium mb-1">{label}</label>
      {children}
      {hint && <p className="text-xs text-gray-400 mt-1">{hint}</p>}
    </div>
  )
}

export default function EmployerProfileForm({ employer }: { employer: EmployerProfile | null }) {
  const [name, setName] = useState(employer?.name ?? '')
  const [logoUrl, setLogoUrl] = useState(employer?.logo_url ?? '')
  const [industry, setIndustry] = useState(employer?.industry ?? '')
  const [size, setSize] = useState(employer?.size ?? '')
  const [location, setLocation] = useState(employer?.location ?? '')
  const [description, setDescription] = useState(employer?.description ?? '')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true); setSaved(false); setError('')

    try {
      const res = await fetch('/api/employers/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          logo_url: logoUrl.trim() || null,
          industry: industry.trim() || null,
          size: size.trim() || null,
          location: location.trim() || null,
          description: description.trim() || null,
        }),
      })

      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        throw new Error(d.error || 'Failed to save company profile')
      }

      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSave} className="space-y-5 bg-white rounded-xl border border-[var(--border)] p-5">
      <Field label="Company name">
        <input value={name} onChange={e => setName(e.target.value)}
          placeholder="Acme Inc." className={inputCls} required />
      </Field>

      <Field label="Logo URL" hint="Link to your company logo image.">
        <input value={logoUrl} onChange={e => setLogoUrl(e.target.value)}
          placeholder="https://example.com/logo.png" className={inputCls} />
      </Field>

      <Field label="Industry">
        <input value={industry} onChange={e => setIndustry(e.target.value)}
          placeholder="Software / Fintech / Retail…" className={inputCls} />
      </Field>

      <Field label="Company size">
        <input value={size} onChange={e => setSize(e.target.value)}
          placeholder="1-10, 11-50, 51-200…" className={inputCls} />
      </Field>

      <Field label="Location">
        <input value={location} onChange={e => setLocation(e.target.value)}
          placeholder="Dubai, UAE" className={inputCls} />
      </Field>

      <Field label="Description" hint="Shown to candidates on your job postings.">
        <textarea value={description} onChange={e => setDescription(e.target.value)}
          rows={4} placeholder="What your company does…" className={inputCls} />
      </Field>

      {error && <p className="text-red-600 text-sm">{error}</p>}

      <button type="submit" disabled={saving}
        className="bg-[var(--accent)] text-[var(--accent-on)] px-5 py-2 rounded-lg hover:bg-[var(--accent-hover)] disabled:opacity-50 text-sm font-medium transition">
        {saving ? 'Saving…' : saved ? '✓ Saved' : 'Save company profile'}
      </button>
    </form>
  )
}
