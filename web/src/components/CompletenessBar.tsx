'use client'

import type { CompletenessResult } from '@/lib/completeness'

function barColor(percent: number): string {
  if (percent >= 100) return 'bg-[var(--success)]'
  if (percent >= 50) return 'bg-[var(--accent)]'
  return 'bg-[var(--warn)]'
}

export default function CompletenessBar({
  result,
  title = 'Profile completeness',
}: {
  result: CompletenessResult
  title?: string
}) {
  const { percent, missing } = result

  return (
    <div className="bg-white rounded-xl border border-[var(--border)] p-4 mb-6">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-semibold text-[var(--fg)]">{title}</h2>
        <span className="text-sm font-bold tabular-nums text-[var(--fg)]">{percent}%</span>
      </div>

      <div className="w-full h-2 rounded-full bg-[var(--border-soft)] overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-300 ${barColor(percent)}`}
          style={{ width: `${percent}%` }}
        />
      </div>

      {percent >= 100 ? (
        <p className="text-xs text-[var(--success)] font-medium mt-2">Your profile is complete.</p>
      ) : missing.length > 0 ? (
        <div className="mt-3">
          <p className="text-xs font-medium text-[var(--muted)] mb-1.5">To complete your profile:</p>
          <ul className="space-y-1">
            {missing.map(item => (
              <li key={item} className="flex items-center gap-1.5 text-xs text-[var(--fg-2)]">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--warn)] shrink-0" />
                {item}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
