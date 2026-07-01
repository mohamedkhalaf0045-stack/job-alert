'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { createClient } from '@/lib/supabase/client'
import type { RealtimeChannel } from '@supabase/supabase-js'

interface Message {
  id: string
  conversation_id: string
  sender_id: string
  content: string
  sent_at: string
  read_at: string | null
  created_at: string
}

interface ChatMessagesPanelProps {
  conversationId: string
  currentUserId: string
  otherParticipantName?: string
  onError?: (error: string) => void
}

export default function ChatMessagesPanel({
  conversationId,
  currentUserId,
  otherParticipantName,
  onError,
}: ChatMessagesPanelProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const [blockMenuOpen, setBlockMenuOpen] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const channelRef = useRef<RealtimeChannel | null>(null)

  // Load initial messages
  useEffect(() => {
    const loadMessages = async () => {
      setIsLoading(true)
      try {
        const res = await fetch(
          `/api/conversations/${conversationId}/messages?limit=50&offset=0`,
          { headers: { 'Content-Type': 'application/json' } }
        )

        if (!res.ok) {
          const error = await res.json()
          onError?.(error.error || 'Failed to load messages')
          return
        }

        const data = await res.json()
        setMessages(data.messages || [])
      } catch (error) {
        onError?.(error instanceof Error ? error.message : 'Unknown error')
      } finally {
        setIsLoading(false)
      }
    }

    loadMessages()
  }, [conversationId, onError])

  // Auto-scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Focus input on load
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Set up Realtime subscription for new messages
  useEffect(() => {
    const supabase = createClient()
    const channel = supabase
      .channel(`messages:${conversationId}`)
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'messages',
          filter: `conversation_id=eq.${conversationId}`,
        },
        (payload) => {
          const newMessage = payload.new as Message
          setMessages((prev) => [...prev, newMessage])
        }
      )
      .subscribe()

    channelRef.current = channel

    return () => {
      supabase.removeChannel(channel)
    }
  }, [conversationId])

  const sendMessage = async (text: string) => {
    if (!text.trim() || isSending) return

    const trimmedText = text.trim()
    setInput('')
    setIsSending(true)

    try {
      const res = await fetch(
        `/api/conversations/${conversationId}/messages`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: trimmedText }),
        }
      )

      if (!res.ok) {
        const error = await res.json()
        onError?.(error.error || 'Failed to send message')
        setInput(trimmedText) // Restore input on error
        return
      }

      // Message will appear via Realtime subscription
    } catch (error) {
      onError?.(error instanceof Error ? error.message : 'Unknown error')
      setInput(trimmedText)
    } finally {
      setIsSending(false)
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  const blockUser = async (userId: string, isBlock: boolean) => {
    try {
      const res = await fetch(`/api/users/${userId}/block`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: isBlock ? 'block' : 'unblock' }),
      })

      if (!res.ok) {
        const error = await res.json()
        onError?.(error.error || 'Failed to update block status')
        return
      }

      onError?.(
        isBlock
          ? `User blocked. You won't see messages from this person.`
          : `User unblocked.`
      )
      setBlockMenuOpen(null)
    } catch (error) {
      onError?.(error instanceof Error ? error.message : 'Unknown error')
    }
  }

  const reportMessage = async (messageId: string) => {
    const reason = prompt('Please describe why you are reporting this message:')
    if (!reason) return

    try {
      const res = await fetch(`/api/messages/${messageId}/report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      })

      if (!res.ok) {
        const error = await res.json()
        onError?.(error.error || 'Failed to report message')
        return
      }

      onError?.('Message reported. Thank you for helping keep our platform safe.')
      setBlockMenuOpen(null)
    } catch (error) {
      onError?.(error instanceof Error ? error.message : 'Unknown error')
    }
  }

  return (
    <div className="flex flex-col h-full bg-white rounded-lg border border-[var(--border)] overflow-hidden">
      {/* Messages container */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-[var(--bg)]">
        {isLoading ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-[var(--muted)]">Loading messages...</p>
          </div>
        ) : messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-2">
            <p className="text-[var(--muted)]">No messages yet</p>
            <p className="text-xs text-[var(--muted-darker)]">
              Start the conversation below
            </p>
          </div>
        ) : (
          messages.map((msg) => {
            const isOwn = msg.sender_id === currentUserId

            return (
              <div
                key={msg.id}
                className={`flex ${isOwn ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`group relative max-w-xs lg:max-w-md px-4 py-2 rounded-lg ${
                    isOwn
                      ? 'bg-[var(--accent)] text-white'
                      : 'bg-[var(--accent-bg)] text-[var(--text)]'
                  }`}
                >
                  <p className="text-sm break-words">{msg.content}</p>
                  <div
                    className={`flex items-center justify-between gap-2 mt-1 text-xs ${
                      isOwn ? 'text-white/70' : 'text-[var(--muted)]'
                    }`}
                  >
                    <span>
                      {new Date(msg.sent_at).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </span>
                    {isOwn && msg.read_at && (
                      <span title="Read">✓✓</span>
                    )}
                  </div>

                  {/* Action menu for non-own messages */}
                  {!isOwn && (
                    <div className="absolute hidden group-hover:block top-0 right-0 transform translate-x-full ml-2 bg-white shadow-lg rounded border border-[var(--border)] z-10">
                      <button
                        onClick={() => reportMessage(msg.id)}
                        className="block w-full text-left px-3 py-2 text-sm hover:bg-[var(--accent-bg)] text-red-600 border-b border-[var(--border)]"
                      >
                        Report
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )
          })
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="border-t border-[var(--border)] p-4 bg-white">
        <div className="flex gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message... (Shift+Enter for new line)"
            disabled={isSending}
            className="flex-1 px-3 py-2 border border-[var(--border)] rounded resize-none focus:outline-none focus:ring-2 focus:ring-[var(--accent)] text-sm bg-white text-[var(--text)] placeholder-[var(--muted)] disabled:opacity-50"
            rows={3}
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={!input.trim() || isSending}
            className="px-4 py-2 bg-[var(--accent)] text-white rounded font-medium hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
          >
            {isSending ? '...' : 'Send'}
          </button>
        </div>
      </div>
    </div>
  )
}
