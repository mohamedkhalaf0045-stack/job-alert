import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'
import AdminForm from './AdminForm'

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
]

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

  return (
    <div>
      <h1 className="text-xl font-bold mb-1">Admin — Scraper settings</h1>
      <p className="text-sm text-gray-500 mb-6">
        Controls the scraper that runs every 15 min on GitHub Actions.
      </p>
      <AdminForm state={state} />
    </div>
  )
}
