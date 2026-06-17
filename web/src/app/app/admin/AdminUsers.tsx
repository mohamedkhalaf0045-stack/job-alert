'use client'

import { useState, useEffect, useCallback } from 'react'

interface UserRow {
  id: string
  email: string
  created_at: string
  last_sign_in: string | null
  provider: string
  keywords: string[]
  locations: string[]
  alert_frequency: string | null
  onboarded: boolean
  cv_uploaded: boolean
}

function timeAgo(iso: string | null): string {
  if (!iso) return 'Never'
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

export default function AdminUsers() {
  const [users, setUsers] = useState<UserRow[]>([])
  const [loading, setLoading] = useState(true)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [error, setError] = useState('')

  const loadUsers = useCallback(async () => {
    setLoading(true)
    const res = await fetch('/api/admin/users')
    const data = await res.json()
    setUsers(data.users ?? [])
    setLoading(false)
  }, [])

  useEffect(() => { loadUsers() }, [loadUsers])

  async function deleteUser(user: UserRow) {
    if (!confirm(`Delete ${user.email}? This is permanent and removes all their data.`)) return
    setDeletingId(user.id)
    setError('')
    const res = await fetch('/api/admin/users', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ userId: user.id }),
    })
    if (!res.ok) {
      const { error: msg } = await res.json()
      setError(msg ?? 'Delete failed')
    } else {
      setUsers(prev => prev.filter(u => u.id !== user.id))
    }
    setDeletingId(null)
  }

  if (loading) {
    return <div className="text-sm text-gray-500 py-8 text-center">Loading users…</div>
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-gray-500">{users.length} registered user{users.length !== 1 ? 's' : ''}</p>
        <button onClick={loadUsers} className="text-xs text-blue-600 hover:underline">Refresh</button>
      </div>

      {error && <p className="text-red-600 text-sm mb-3">{error}</p>}

      <div className="space-y-3">
        {users.map(u => (
          <div key={u.id} className="bg-white border border-gray-200 rounded-xl p-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-sm text-gray-900 truncate">{u.email}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    u.provider === 'google' ? 'bg-red-50 text-red-600' : 'bg-gray-100 text-gray-500'
                  }`}>
                    {u.provider}
                  </span>
                  {u.onboarded ? (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-green-50 text-green-600 font-medium">Onboarded</span>
                  ) : (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-yellow-50 text-yellow-600 font-medium">Not set up</span>
                  )}
                  {u.cv_uploaded && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-600 font-medium">CV uploaded</span>
                  )}
                </div>

                <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-500">
                  <span>Joined: {new Date(u.created_at).toLocaleDateString()}</span>
                  <span>Last login: {timeAgo(u.last_sign_in)}</span>
                  {u.onboarded && (
                    <>
                      <span>Keywords: {u.keywords.length}</span>
                      <span>Locations: {u.locations.join(', ') || '—'}</span>
                    </>
                  )}
                  {u.alert_frequency && (
                    <span>Alerts: {u.alert_frequency}</span>
                  )}
                </div>

                {u.keywords.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {u.keywords.slice(0, 6).map(kw => (
                      <span key={kw} className="text-xs px-2 py-0.5 bg-blue-50 text-blue-700 rounded-full">{kw}</span>
                    ))}
                    {u.keywords.length > 6 && (
                      <span className="text-xs text-gray-400">+{u.keywords.length - 6} more</span>
                    )}
                  </div>
                )}
              </div>

              <div className="flex flex-col gap-1.5 shrink-0">
                <a
                  href={`/app/feed?as=${u.id}`}
                  className="text-xs px-3 py-1.5 border border-blue-200 text-blue-600 rounded-lg hover:bg-blue-50 transition-colors text-center"
                >
                  View as
                </a>
                <a
                  href={`/app/admin/users/${u.id}/edit`}
                  className="text-xs px-3 py-1.5 border border-gray-200 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors text-center"
                >
                  Edit
                </a>
                <button
                  onClick={() => deleteUser(u)}
                  disabled={deletingId === u.id}
                  className="text-xs px-3 py-1.5 border border-red-200 text-red-600 rounded-lg hover:bg-red-50 disabled:opacity-40 transition-colors"
                >
                  {deletingId === u.id ? 'Deleting…' : 'Delete'}
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {users.length === 0 && (
        <p className="text-sm text-gray-400 text-center py-8">No users yet.</p>
      )}
    </div>
  )
}
