'use client'

import { useState } from 'react'
import { createClient } from '@/lib/supabase/client'

/**
 * Shared "check your email" state — shown after signup (when confirmation
 * is required) and when a sign-in attempt hits Supabase's
 * "Email not confirmed" error. Mirrors mobile's _buildConfirmationWaiting().
 */
export default function ConfirmEmailPending({
  email,
  onBack,
}: {
  email: string
  onBack?: () => void
}) {
  const [resending, setResending] = useState(false)
  const [resendMsg, setResendMsg] = useState('')
  const [resendErr, setResendErr] = useState('')

  async function handleResend() {
    setResending(true)
    setResendMsg('')
    setResendErr('')
    const supabase = createClient()
    const { error } = await supabase.auth.resend({
      type: 'signup',
      email,
    })
    setResending(false)
    if (error) {
      setResendErr(error.message)
      return
    }
    setResendMsg('Confirmation email resent — check your inbox.')
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 bg-[var(--bg)]">
      <div className="text-center max-w-sm bg-white rounded-2xl border border-[var(--border)] shadow-sm p-10">
        <div className="text-4xl mb-4">📬</div>
        <h2 className="text-xl font-bold mb-2 text-[var(--fg)] tracking-tight">Check your email</h2>
        <p className="text-sm text-[var(--muted)] leading-relaxed">
          We sent a confirmation link to{' '}
          <strong className="text-[var(--fg-2)]">{email}</strong>.
          Click it to activate your account and set up your preferences.
        </p>

        {resendMsg && (
          <p className="mt-4 text-sm text-[var(--success)]">{resendMsg}</p>
        )}
        {resendErr && (
          <p className="mt-4 text-sm text-[var(--danger)]">{resendErr}</p>
        )}

        <button
          onClick={handleResend}
          disabled={resending}
          className="mt-6 w-full bg-[var(--accent)] text-[var(--accent-on)] py-2.5 rounded-lg hover:bg-[var(--accent-hover)] disabled:opacity-50 font-medium text-sm transition-colors"
        >
          {resending ? 'Resending…' : 'Resend confirmation email'}
        </button>

        {onBack && (
          <button
            onClick={onBack}
            className="mt-3 w-full border border-[var(--border)] py-2.5 rounded-lg text-sm font-medium text-[var(--fg-2)] hover:bg-[var(--border-soft)] transition-colors"
          >
            Back to sign in
          </button>
        )}
      </div>
    </div>
  )
}
