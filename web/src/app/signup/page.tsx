'use client'

import { useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import Link from 'next/link'
import ConfirmEmailPending from '@/components/ConfirmEmailPending'

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">
      <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" fill="#4285F4"/>
      <path d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.258c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z" fill="#34A853"/>
      <path d="M3.964 10.707A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.707V4.961H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.039l3.007-2.332z" fill="#FBBC05"/>
      <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.961L3.964 7.293C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
    </svg>
  )
}

export default function SignupPage() {
  const [email,         setEmail]         = useState('')
  const [password,      setPassword]      = useState('')
  const [error,         setError]         = useState('')
  const [loading,       setLoading]       = useState(false)
  const [sent,          setSent]          = useState(false)
  const [googleLoading, setGoogleLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    const supabase = createClient()
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        emailRedirectTo: `${location.origin}/auth/callback?next=/onboarding`,
      },
    })
    setLoading(false)
    if (error) { setError(error.message); return }
    // If a session came back immediately, confirmation is disabled — no
    // need to show the "check your email" state. Otherwise (user created,
    // no session) Supabase requires email confirmation before sign-in.
    if (data.user && !data.session) {
      setSent(true)
    } else if (data.session) {
      window.location.href = '/onboarding'
    } else {
      setSent(true)
    }
  }

  async function handleGoogleSignIn() {
    setGoogleLoading(true)
    const supabase = createClient()
    await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: `${location.origin}/auth/callback` },
    })
  }

  const inputCls = [
    'w-full border border-[var(--border)] rounded-lg px-3 py-2.5 text-sm',
    'focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/25 focus:border-[var(--accent)]',
    'bg-white placeholder:text-[var(--meta)] text-[var(--fg)] transition-all',
  ].join(' ')

  if (sent) {
    return <ConfirmEmailPending email={email} />
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 bg-[var(--bg)]">
      {/* Logo */}
      <Link href="/" className="flex items-center gap-2 mb-8 select-none">
        <span className="w-8 h-8 rounded-lg bg-[var(--accent)] text-white text-sm font-bold flex items-center justify-center leading-none">
          J
        </span>
        <span className="font-semibold text-[var(--fg)] text-lg tracking-tight">JobAlert</span>
      </Link>

      <div className="w-full max-w-sm bg-white rounded-2xl border border-[var(--border)] shadow-sm p-8">
        <h1 className="text-xl font-bold mb-1 text-[var(--fg)] tracking-tight">Create account</h1>
        <p className="text-sm text-[var(--muted)] mb-6">Free — no credit card required.</p>

        <button
          onClick={handleGoogleSignIn}
          disabled={googleLoading}
          className="w-full flex items-center justify-center gap-3 border border-[var(--border)] rounded-lg px-3 py-2.5 text-sm font-medium text-[var(--fg-2)] hover:bg-[var(--border-soft)] disabled:opacity-50 transition-colors mb-4"
        >
          <GoogleIcon />
          {googleLoading ? 'Redirecting…' : 'Continue with Google'}
        </button>

        <div className="relative mb-4">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-[var(--border)]" />
          </div>
          <div className="relative flex justify-center text-xs">
            <span className="bg-white px-3 text-[var(--meta)]">or</span>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="email" placeholder="Email address" required autoFocus
            value={email} onChange={e => setEmail(e.target.value)}
            className={inputCls}
          />
          <input
            type="password" placeholder="Password (min 8 chars)" required minLength={8}
            value={password} onChange={e => setPassword(e.target.value)}
            className={inputCls}
          />
          {error && <p className="text-[var(--danger)] text-xs">{error}</p>}
          <button
            type="submit" disabled={loading}
            className="w-full bg-[var(--accent)] text-[var(--accent-on)] py-2.5 rounded-lg hover:bg-[var(--accent-hover)] disabled:opacity-50 font-medium text-sm transition-colors"
          >
            {loading ? 'Creating…' : 'Create account'}
          </button>
        </form>

        <p className="mt-5 text-sm text-center text-[var(--muted)]">
          Already have an account?{' '}
          <Link href="/login" className="text-[var(--accent)] font-medium hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
