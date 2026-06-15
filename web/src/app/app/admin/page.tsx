import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'
import AdminTabs from './AdminTabs'

export const dynamic = 'force-dynamic'

const BOT_KEYS = [
  'setting_keywords',
  'setting_location',
  'setting_max_hours',
  'setting_llm_min_score',
  'setting_exclude_keywords',
  'setting_search_linkedin',
  'setting_search_indeed',
  'setting_search_bayt',
  'setting_search_gulftalent',
  'setting_search_naukrigulf',
  'setting_search_web',
  'setting_legacy_telegram',
  'recommended_keywords',
  'recommended_locations',
]

function parseList(raw: string | undefined): string[] {
  if (!raw) return []
  try { return JSON.parse(raw) } catch { return [] }
}

export default async function AdminPage() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')
  if (user.email !== process.env.ADMIN_EMAIL) redirect('/app/feed')

  const { data: rows } = await supabase
    .from('bot_state')
    .select('key, value')
    .in('key', BOT_KEYS)

  const state: Record<string, string> = {}
  for (const row of rows ?? []) {
    state[row.key] = row.value
  }

  const scraperState = Object.fromEntries(
    Object.entries(state).filter(([k]) => !k.startsWith('recommended_'))
  )

  return (
    <div>
      <h1 className="text-xl font-bold mb-1">Admin</h1>
      <p className="text-sm text-gray-500 mb-6">
        Manage scraper settings, users, and onboarding recommendations.
      </p>
      <AdminTabs
        scraperState={scraperState}
        recommendedKeywords={parseList(state.recommended_keywords)}
        recommendedLocations={parseList(state.recommended_locations)}
      />
    </div>
  )
}
