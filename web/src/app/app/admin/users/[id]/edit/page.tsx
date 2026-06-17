import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'
import AdminUserEditForm from './AdminUserEditForm'

export const dynamic = 'force-dynamic'

export default async function AdminUserEditPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')
  if (user.email !== process.env.ADMIN_EMAIL) redirect('/app/feed')

  const { id } = await params
  const admin = createAdminClient()

  const [
    { data: authUser },
    { data: prefs },
    { data: profile },
  ] = await Promise.all([
    admin.auth.admin.getUserById(id),
    admin.from('user_preferences')
      .select('keywords, locations, exclude_keywords, min_score, alert_frequency, paused')
      .eq('user_id', id)
      .maybeSingle(),
    admin.from('profiles')
      .select('alert_email, alert_telegram, telegram_chat_id')
      .eq('id', id)
      .maybeSingle(),
  ])

  const userEmail = authUser?.user?.email ?? id

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-bold">Edit user settings</h1>
        <p className="text-sm text-gray-500 mt-1">
          Changes take effect immediately — the user sees them on next feed load.
        </p>
      </div>
      <AdminUserEditForm
        userId={id}
        userEmail={userEmail}
        prefs={prefs ?? null}
        profile={profile ?? null}
      />
    </div>
  )
}
