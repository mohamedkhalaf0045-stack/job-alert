'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { createClient } from '@/lib/supabase/client'

interface Conversation {
  id: string
  job_posting_id: string | null
  candidate_id: string
  employer_id: string
  initiated_by: 'candidate' | 'employer'
  created_at: string
  updated_at: string
  otherParticipantId: string
  otherParticipantName?: string
  lastMessage?: {
    content: string
    senderName: string
    sentAt: string
  }
  isCandidate: boolean
}

export default function MessagesPage() {
  const router = useRouter()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [currentUserId, setCurrentUserId] = useState<string | null>(null)

  // Load conversations
  useEffect(() => {
    const loadData = async () => {
      setIsLoading(true)
      try {
        // Get current user
        const supabase = await createClient()
        const { data: { user } } = await supabase.auth.getUser()

        if (!user) {
          router.push('/auth/login')
          return
        }

        setCurrentUserId(user.id)

        // Fetch conversations
        const res = await fetch('/api/conversations', {
          headers: { 'Content-Type': 'application/json' },
        })

        if (!res.ok) {
          const data = await res.json()
          setError(data.error || 'Failed to load conversations')
          return
        }

        const data = await res.json()
        setConversations(data || [])
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error')
      } finally {
        setIsLoading(false)
      }
    }

    loadData()
  }, [router])

  const formatTime = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`

    return date.toLocaleDateString()
  }

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-[var(--text)]">Messages</h1>
        <p className="text-[var(--muted)] mt-1">
          Your conversations with candidates and employers
        </p>
      </div>

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg mb-6">
          <p className="text-red-800">{error}</p>
        </div>
      )}

      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <p className="text-[var(--muted)]">Loading conversations...</p>
        </div>
      ) : conversations.length === 0 ? (
        <div className="bg-white rounded-lg border border-[var(--border)] p-12 text-center">
          <h2 className="text-lg font-semibold text-[var(--text)] mb-2">
            No conversations yet
          </h2>
          <p className="text-[var(--muted)] mb-4">
            {currentUserId ? 'Start a conversation by messaging someone' : 'Load conversations'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {conversations.map((conversation) => (
            <Link key={conversation.id} href={`/app/messages/${conversation.id}`}>
              <div className="bg-white rounded-lg border border-[var(--border)] p-4 hover:shadow-md transition-shadow cursor-pointer">
                <div className="flex items-start justify-between mb-2">
                  <div className="flex-1">
                    <h3 className="font-semibold text-[var(--text)]">
                      {conversation.otherParticipantName || 'Unknown'}
                    </h3>
                    <p className="text-xs text-[var(--muted)]">
                      {conversation.isCandidate
                        ? 'Employer'
                        : 'Candidate'}
                    </p>
                  </div>
                  <span className="text-xs text-[var(--muted)]">
                    {formatTime(conversation.updated_at)}
                  </span>
                </div>

                {conversation.lastMessage ? (
                  <div className="mb-2">
                    <p className="text-sm text-[var(--text)] line-clamp-2">
                      <span className="font-medium">
                        {conversation.lastMessage.senderName}:
                      </span>{' '}
                      {conversation.lastMessage.content}
                    </p>
                  </div>
                ) : (
                  <p className="text-sm text-[var(--muted)] italic">No messages yet</p>
                )}

                {conversation.job_posting_id && (
                  <div className="mt-2 text-xs text-[var(--muted-darker)] bg-[var(--accent-bg)] px-2 py-1 rounded w-fit">
                    Discussing a job posting
                  </div>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
