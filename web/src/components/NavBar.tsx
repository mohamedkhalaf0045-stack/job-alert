'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'

export default function NavBar({ email }: { email: string }) {
  const pathname = usePathname()
  const router   = useRouter()

  async function signOut() {
    const supabase = createClient()
    await supabase.auth.signOut()
    router.push('/')
    router.refresh()
  }

  function navLink(href: string, label: string) {
    const active = pathname === href
    return (
      <Link
        href={href}
        className={`text-sm px-3 py-1.5 rounded-lg transition ${
          active ? 'bg-blue-100 text-blue-700 font-medium' : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
        }`}
      >
        {label}
      </Link>
    )
  }

  return (
    <nav className="sticky top-0 z-10 bg-white border-b px-4 py-3 flex items-center justify-between">
      <div className="flex items-center gap-1">
        <span className="font-bold tracking-tight mr-3">JobAlert</span>
        {navLink('/app/feed',     'Feed')}
        {navLink('/app/saved',    'Saved')}
        {navLink('/app/settings', 'Settings')}
      </div>
      <div className="flex items-center gap-3">
        <span className="text-xs text-gray-400 hidden sm:block truncate max-w-[160px]">{email}</span>
        <button onClick={signOut} className="text-sm text-gray-500 hover:text-gray-800">
          Sign out
        </button>
      </div>
    </nav>
  )
}
