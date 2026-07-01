'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'

export default function ConfirmEmailPage() {
  const router = useRouter()
  const [email, setEmail] = useState('')
  const [resending, setResending] = useState(false)
  const [resendMsg, setResendMsg] = useState('')
  const [resendErr, setResendErr] = useState('')
  const [signingOut, setSigningOut] = useState(false)

  useEffect(() => {
    const supabase = createClient()
    supabase.auth.getUser().then(({ data }) => {
      if (data.user?.email) setEmail(data.user.email)
      // Already confirmed (e.g. confirmed in another tab) — move on.
      if (data.user?.email_confirmed_at) {
        router.replace('/app/feed')
      }
    })
  }, [router])

  async function handleResend() {
    if (!email) return
    setResending(true)
    setResendMsg('')
    setResendErr('')
    const supabase = createClient()
    const { error } = await supabase.auth.resend({ type: 'signup', email })
    setResending(false)
    if (error) {
      setResendErr(error.message)
      return
    }
    setResendMsg('Confirmation email resent — check your inbox.')
  }

  async function handleSignOut() {
    setSigningOut(true)
    const supabase = createClient()
    await supabase.auth.signOut()
    router.push('/login')
    router.refresh()
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 bg-[var(--bg)]">
      <div className="text-center max-w-sm bg-white rounded-2xl border border-[var(--border)] shadow-sm p-10">
        <div className="text-4xl mb-4">📬</div>
        <h2 className="text-xl font-bold mb-2 text-[var(--fg)] tracking-tight">Confirm your email</h2>
        <p className="text-sm text-[var(--muted)] leading-relaxed">
          Please confirm your email to continue.{' '}
          {email
            ? <>Check your inbox at <strong className="text-[var(--fg-2)]">{email}</strong>.</>
            : 'Check your inbox for the confirmation link.'}
        </p>

        {resendMsg && (
          <p className="mt-4 text-sm text-[var(--success)]">{resendMsg}</p>
        )}
        {resendErr && (
          <p className="mt-4 text-sm text-[var(--danger)]">{resendErr}</p>
        )}

        <button
          onClick={handleResend}
          disabled={resending || !email}
          className="mt-6 w-full bg-[var(--accent)] text-[var(--accent-on)] py-2.5 rounded-lg hover:bg-[var(--accent-hover)] disabled:opacity-50 font-medium text-sm transition-colors"
        >
          {resending ? 'Resending…' : 'Resend confirmation email'}
        </button>

        <button
          onClick={handleSignOut}
          disabled={signingOut}
          className="mt-3 w-full border border-[var(--border)] py-2.5 rounded-lg text-sm font-medium text-[var(--fg-2)] hover:bg-[var(--border-soft)] disabled:opacity-50 transition-colors"
        >
          {signingOut ? 'Signing out…' : 'Sign out (wrong account?)'}
        </button>
      </div>
    </div>
  )
}
