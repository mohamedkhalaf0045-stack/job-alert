'use client'

import Link from 'next/link'
import { shouldShowOnboardingPrompt, type CompletenessResult } from '@/lib/completeness'

// Phase 5: banner shown on /app/settings (candidate) and /employer/profile (HR)
// when profile completeness is below 50%. Links to the AI onboarding chatbot.
export default function CompleteProfileBanner({
  result,
  href,
}: {
  result: CompletenessResult
  href: string
}) {
  if (!shouldShowOnboardingPrompt(result)) return null

  return (
    <div className="flex items-center justify-between gap-4 bg-[var(--accent-bg)] border border-[var(--accent)]/20 rounded-xl px-4 py-3 mb-6">
      <div>
        <p className="text-sm font-semibold text-[var(--accent)]">Complete your profile</p>
        <p className="text-xs text-[var(--muted)] mt-0.5">
          Your profile is only {result.percent}% complete — chat with our assistant to finish it in a couple of minutes.
        </p>
      </div>
      <Link
        href={href}
        className="shrink-0 bg-[var(--accent)] text-white text-xs font-medium px-3 py-1.5 rounded-lg hover:bg-[var(--accent-hover)] transition-colors"
      >
        Chat now →
      </Link>
    </div>
  )
}
