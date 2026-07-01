import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'
import { calculateHRCompleteness } from '@/lib/completeness'
import CompletenessBar from '@/components/CompletenessBar'
import CompleteProfileBanner from '@/components/CompleteProfileBanner'
import EmployerProfileForm from './EmployerProfileForm'
import type { EmployerProfile } from '@/app/api/employers/profile/route'

export const dynamic = 'force-dynamic'

export default async function EmployerProfilePage() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')

  const { data: profile } = await supabase
    .from('profiles')
    .select('employer_id')
    .eq('id', user.id)
    .single()

  let employer: EmployerProfile | null = null
  if (profile?.employer_id) {
    const { data } = await supabase
      .from('employers')
      .select('*')
      .eq('id', profile.employer_id)
      .single()
    employer = data as EmployerProfile | null
  }

  let hasPublishedJob = false
  if (employer) {
    const { count } = await supabase
      .from('job_postings')
      .select('id', { count: 'exact', head: true })
      .eq('employer_id', employer.id)
      .eq('status', 'published')
    hasPublishedJob = (count ?? 0) > 0
  }

  const completeness = calculateHRCompleteness({
    hasName: !!employer?.name,
    hasLogo: !!employer?.logo_url,
    hasIndustry: !!employer?.industry,
    hasDescription: !!employer?.description,
    hasPublishedJob,
  })

  return (
    <div className="max-w-lg">
      <h1 className="text-xl font-bold mb-6">Company profile</h1>
      <CompleteProfileBanner result={completeness} href="/employer/onboarding" />
      <CompletenessBar result={completeness} title="Company profile completeness" />
      <EmployerProfileForm employer={employer} />
    </div>
  )
}
