import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'

async function assertAdmin() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user || user.email !== process.env.ADMIN_EMAIL) return null
  return user
}

// GET /api/admin/users — list all users with their preferences
export async function GET() {
  const admin_user = await assertAdmin()
  if (!admin_user) return NextResponse.json({ error: 'Forbidden' }, { status: 403 })

  const admin = createAdminClient()

  const { data: authUsers, error: authErr } = await admin.auth.admin.listUsers({ perPage: 1000 })
  if (authErr) return NextResponse.json({ error: authErr.message }, { status: 500 })

  const userIds = authUsers.users.map(u => u.id)

  const { data: prefs } = await admin
    .from('user_preferences')
    .select('user_id, keywords, locations, alert_frequency, updated_at')
    .in('user_id', userIds)

  const cvKeys = userIds.map(id => `cv_data:${id}`)
  const { data: cvRows } = await admin
    .from('bot_state')
    .select('key')
    .in('key', cvKeys)

  const prefsMap = Object.fromEntries((prefs ?? []).map(p => [p.user_id, p]))
  const cvSet = new Set((cvRows ?? []).map(r => r.key.replace('cv_data:', '')))

  const users = authUsers.users.map(u => ({
    id: u.id,
    email: u.email ?? '',
    created_at: u.created_at,
    last_sign_in: u.last_sign_in_at ?? null,
    provider: u.app_metadata?.provider ?? 'email',
    keywords: prefsMap[u.id]?.keywords ?? [],
    locations: prefsMap[u.id]?.locations ?? [],
    alert_frequency: prefsMap[u.id]?.alert_frequency ?? null,
    onboarded: !!prefsMap[u.id],
    cv_uploaded: cvSet.has(u.id),
  }))

  return NextResponse.json({ users })
}

// DELETE /api/admin/users — delete a user by id
export async function DELETE(req: NextRequest) {
  const admin_user = await assertAdmin()
  if (!admin_user) return NextResponse.json({ error: 'Forbidden' }, { status: 403 })

  const { userId } = await req.json() as { userId: string }
  if (!userId) return NextResponse.json({ error: 'userId required' }, { status: 400 })
  if (userId === admin_user.id) return NextResponse.json({ error: 'Cannot delete your own account' }, { status: 400 })

  const admin = createAdminClient()

  // Delete user preferences and related data first
  await admin.from('user_preferences').delete().eq('user_id', userId)
  await admin.from('user_alert_log').delete().eq('user_id', userId)

  // Delete the auth user (cascades to other tables via FK)
  const { error } = await admin.auth.admin.deleteUser(userId)
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })

  return NextResponse.json({ ok: true })
}
