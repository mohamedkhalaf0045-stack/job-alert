'use client'

import { useState, useEffect } from 'react'
import { useRouter, useParams } from 'next/navigation'
import Link from 'next/link'
import ChatMessagesPanel from '@/components/ChatMessagesPanel'
import { createClient } from '@/lib/supabase/client'

interface ConversationDetails {
  id: string
  job_posting_id: string | null
  candidate_id: string
  employer_id: string
  initiated_by: 'candidate' | 'employer'
  created_at: string
  updated_at: string
  otherParticipantId: string
  otherParticipantName?: string
  isCandidate: boolean
}

export default function ConversationPage() {
  const router = useRouter()
  const params = useParams()
  const conversationId = params?.id as string
  const [conversation, setConversation] = useState<ConversationDetails | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [currentUserId, setCurrentUserId] = useState<string | null>(null)
  const [notificationMessage, setNotificationMessage] = useState<string | null>(null)

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

        // Fetch conversation
        const res = await fetch('/api/conversations', {
          headers: { 'Content-Type': 'application/json' },
        })

        if (!res.ok) {
          setError('Failed to load conversation')
          return
        }

        const conversations = await res.json()
        const conv = conversations.find(
          (c: ConversationDetails) => c.id === conversationId
        )

        if (!conv) {
          setError('Conversation not found')
          return
        }

        setConversation(conv)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error')
      } finally {
        setIsLoading(false)
      }
    }

    loadData()
  }, [router, conversationId])

  const handleError = (message: string) => {
    setNotificationMessage(message)
    setTimeout(() => setNotificationMessage(null), 4000)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <p className="text-[var(--muted)]">Loading conversation...</p>
      </div>
    )
  }

  if (error || !conversation || !currentUserId) {
    return (
      <div className="max-w-4xl mx-auto">
        <Link
          href="/app/messages"
          className="text-[var(--accent)] hover:underline mb-4 inline-block"
        >
          ← Back to Messages
        </Link>
        <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
          <p className="text-red-800 font-medium">
            {error || 'Conversation not found'}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto h-screen flex flex-col">
      {/* Header */}
      <div className="border-b border-[var(--border)] p-4 bg-white sticky top-0">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-[var(--text)]">
              {conversation.otherParticipantName || 'Unknown'}
            </h1>
            <p className="text-sm text-[var(--muted)] mt-1">
              {conversation.isCandidate ? 'Employer' : 'Candidate'}
            </p>
            {conversation.job_posting_id && (
              <p className="text-xs text-[var(--muted-darker)] mt-2 bg-[var(--accent-bg)] px-2 py-1 rounded w-fit">
                Discussing a job posting
              </p>
            )}
          </div>
          <Link
            href="/app/messages"
            className="text-[var(--muted)] hover:text-[var(--text)]"
          >
            ✕
          </Link>
        </div>
      </div>

      {/* Notification */}
      {notificationMessage && (
        <div className="bg-blue-50 border-b border-blue-200 px-4 py-3">
          <p className="text-blue-800 text-sm">{notificationMessage}</p>
        </div>
      )}

      {/* Chat area */}
      <div className="flex-1 overflow-hidden">
        <ChatMessagesPanel
          conversationId={conversationId}
          currentUserId={currentUserId}
          otherParticipantName={conversation.otherParticipantName}
          onError={handleError}
        />
      </div>
    </div>
  )
}
