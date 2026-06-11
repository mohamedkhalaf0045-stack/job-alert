import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'
import SettingsForm from './SettingsForm'

export const dynamic = 'force-dynamic'

export default async function SettingsPage() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')

  const [prefsRes, profileRes] = await Promise.all([
    supabase.from('user_preferences').select('*').eq('user_id', user.id).single(),
    supabase.from('profiles').select('*').eq('id', user.id).single(),
  ])

  return (
    <div>
      <h1 className="text-xl font-bold mb-6">Settings</h1>
      <SettingsForm
        prefs={prefsRes.data}
        profile={profileRes.data}
        userId={user.id}
      />
    </div>
  )
}
