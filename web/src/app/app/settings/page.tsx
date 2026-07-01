import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'
import { calculateCandidateCompleteness } from '@/lib/completeness'
import CompletenessBar from '@/components/CompletenessBar'
import CompleteProfileBanner from '@/components/CompleteProfileBanner'
import SettingsForm from './SettingsForm'

export const dynamic = 'force-dynamic'

async function hasCV(userId: string): Promise<boolean> {
  const admin = createAdminClient()
  const { data } = await admin
    .from('bot_state').select('value').eq('key', `cv_data:${userId}`).single()
  return !!data?.value
}

export default async function SettingsPage() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')

  const [prefsRes, profileRes, cvUploaded] = await Promise.all([
    supabase.from('user_preferences').select('*').eq('user_id', user.id).single(),
    supabase.from('profiles').select('*').eq('id', user.id).single(),
    hasCV(user.id),
  ])

  const prefs = prefsRes.data
  const profile = profileRes.data

  const completeness = calculateCandidateCompleteness({
    hasCV: cvUploaded,
    hasKeywords: Array.isArray(prefs?.keywords) && prefs.keywords.length > 0,
    hasLocations: Array.isArray(prefs?.locations) && prefs.locations.length > 0,
    hasDisplayName: !!profile?.display_name,
  })

  return (
    <div>
      <h1 className="text-xl font-bold mb-6">Settings</h1>
      <div className="max-w-lg">
        <CompleteProfileBanner result={completeness} href="/onboarding" />
        <CompletenessBar result={completeness} />
      </div>
      <SettingsForm
        prefs={prefs}
        profile={profile}
        userId={user.id}
      />
    </div>
  )
}
