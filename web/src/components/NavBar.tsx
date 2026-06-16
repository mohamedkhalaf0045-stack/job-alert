'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'

export default function NavBar({ email, isAdmin }: { email: string; isAdmin?: boolean }) {
  const pathname = usePathname()
  const router   = useRouter()

  async function signOut() {
    const supabase = createClient()
    await supabase.auth.signOut()
    router.push('/')
    router.refresh()
  }

  function navLink(href: string, label: string) {
    const active = pathname === href || pathname.startsWith(href + '/')
    return (
      <Link
        href={href}
        className={`text-sm px-3 py-1.5 rounded-md transition-colors duration-150 ${
          active
            ? 'bg-[var(--accent-bg)] text-[var(--accent)] font-medium'
            : 'text-[var(--muted)] hover:text-[var(--fg)] hover:bg-[var(--border-soft)]'
        }`}
      >
        {label}
      </Link>
    )
  }

  return (
    <nav className="sticky top-0 z-10 bg-white/90 backdrop-blur-sm border-b border-[var(--border)] px-4 py-2.5 flex items-center justify-between">
      <div className="flex items-center gap-0.5">
        <Link href="/app/feed" className="flex items-center gap-2 mr-3 select-none">
          <span className="w-6 h-6 rounded-md bg-[var(--accent)] text-white text-[11px] font-bold flex items-center justify-center leading-none">
            J
          </span>
          <span className="font-semibold text-[var(--fg)] tracking-tight text-sm">JobAlert</span>
        </Link>
        {navLink('/app/feed',     'Feed')}
        {navLink('/app/saved',    'Saved')}
        {navLink('/app/settings', 'Settings')}
        {isAdmin && navLink('/app/admin', 'Admin')}
      </div>
      <div className="flex items-center gap-3">
        <span className="text-xs text-[var(--meta)] hidden sm:block truncate max-w-[160px]">{email}</span>
        <button
          onClick={signOut}
          className="text-xs px-3 py-1.5 rounded-md text-[var(--muted)] hover:text-[var(--fg)] hover:bg-[var(--border-soft)] transition-colors duration-150"
        >
          Sign out
        </button>
      </div>
    </nav>
  )
}
