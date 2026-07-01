'use client'

import { useState, useRef, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import CVUploadCard, { CVData } from '@/components/CVUploadCard'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

type ProfileType = 'candidate' | 'employer'

export default function OnboardingChatbot({ profileType }: { profileType: ProfileType }) {
  const router = useRouter()
  const [messages,   setMessages]   = useState<Message[]>([])
  const [input,      setInput]      = useState('')
  const [isLoading,  setIsLoading]  = useState(false)
  const [isComplete, setIsComplete] = useState(false)
  const [error,      setError]      = useState('')
  const [showCVUpload, setShowCVUpload] = useState(profileType === 'candidate')
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef  = useRef<HTMLInputElement>(null)
  const started   = useRef(false)

  const continueHref = profileType === 'employer' ? '/employer/profile' : '/app/feed'

  async function send(nextMessages: Message[]) {
    setIsLoading(true)
    setError('')
    try {
      const res = await fetch('/api/onboarding/chat', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ messages: nextMessages, profile_type: profileType }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || 'Failed')

      setMessages(prev => [...prev, { role: 'assistant', content: data.reply }])
      if (data.isComplete) setIsComplete(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong')
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Sorry, something went wrong. Please try again.',
      }])
    } finally {
      setIsLoading(false)
    }
  }

  // Kick off the conversation once the CV step is resolved (or immediately
  // for employers, who have no CV step).
  useEffect(() => {
    if (started.current || showCVUpload) return
    started.current = true
    send([])
  }, [showCVUpload])

  function handleCVAnalyzed(_data: CVData) {
    setShowCVUpload(false)
  }

  function handleSkipCV() {
    setShowCVUpload(false)
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  useEffect(() => {
    if (!isComplete) inputRef.current?.focus()
  }, [isComplete])

  function handleSend() {
    const text = input.trim()
    if (!text || isLoading || isComplete) return
    const userMsg: Message = { role: 'user', content: text }
    const nextMessages = [...messages, userMsg]
    setMessages(nextMessages)
    setInput('')
    send(nextMessages)
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="w-full max-w-lg bg-white rounded-2xl shadow-sm border border-[var(--border)] flex flex-col overflow-hidden h-[560px]">
      {/* Header */}
      <div className="bg-[var(--accent)] px-4 py-3 flex items-center gap-2">
        <div className="w-8 h-8 bg-white/20 rounded-full flex items-center justify-center">
          <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
          </svg>
        </div>
        <div>
          <p className="text-white text-sm font-semibold">
            {profileType === 'employer' ? 'Company setup assistant' : 'Onboarding assistant'}
          </p>
          <p className="text-white/70 text-xs">Powered by AI</p>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {showCVUpload && (
          <div className="space-y-3">
            <div className="flex justify-start">
              <div className="max-w-[95%] px-3 py-2 rounded-2xl rounded-bl-sm text-sm leading-relaxed bg-[var(--border-soft)] text-[var(--fg)]">
                Upload your CV so I can suggest roles based on your experience and skip questions I can already answer myself.
              </div>
            </div>
            <CVUploadCard onAnalysisComplete={handleCVAnalyzed} />
            <button
              onClick={handleSkipCV}
              className="text-xs text-[var(--muted)] hover:text-[var(--fg)] underline underline-offset-2"
            >
              Skip — I&apos;ll answer questions instead
            </button>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] px-3 py-2 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
                msg.role === 'user'
                  ? 'bg-[var(--accent)] text-white rounded-br-sm'
                  : 'bg-[var(--border-soft)] text-[var(--fg)] rounded-bl-sm'
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-[var(--border-soft)] px-3 py-2 rounded-2xl rounded-bl-sm">
              <div className="flex gap-1 items-center h-4">
                <span className="w-1.5 h-1.5 bg-[var(--muted)] rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1.5 h-1.5 bg-[var(--muted)] rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1.5 h-1.5 bg-[var(--muted)] rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}

        {isComplete && (
          <div className="mt-2 bg-[var(--success-bg,#ecfdf5)] border border-[var(--success,#10b981)]/30 rounded-xl p-4 text-center">
            <p className="text-sm font-semibold text-[var(--success,#10b981)] mb-3">
              ✓ Profile updated!
            </p>
            <button
              onClick={() => router.push(continueHref)}
              className="bg-[var(--accent)] text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-[var(--accent-hover)] transition-colors"
            >
              Continue →
            </button>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      {!isComplete && !showCVUpload && (
        <div className="border-t border-[var(--border)] px-3 py-3 flex gap-2 items-center">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type your answer..."
            disabled={isLoading}
            className="flex-1 text-sm px-3 py-2 rounded-full border border-[var(--border)] focus:outline-none focus:border-[var(--accent)] disabled:opacity-50"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="w-8 h-8 bg-[var(--accent)] rounded-full flex items-center justify-center hover:bg-[var(--accent-hover)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex-shrink-0"
          >
            <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </button>
        </div>
      )}

      {error && !isComplete && (
        <p className="px-4 pb-2 text-xs text-red-500">{error}</p>
      )}
    </div>
  )
}
