import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'

async function assertAdmin() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user || user.email !== process.env.ADMIN_EMAIL) return null
  return user
}

// GET /api/admin/users/[id]/prefs — load a user's preferences + profile
export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const admin_user = await assertAdmin()
  if (!admin_user) return NextResponse.json({ error: 'Forbidden' }, { status: 403 })

  const { id } = await params
  const admin = createAdminClient()

  const [{ data: prefs }, { data: profile }] = await Promise.all([
    admin.from('user_preferences')
      .select('keywords, locations, exclude_keywords, min_score, alert_frequency, paused')
      .eq('user_id', id)
      .maybeSingle(),
    admin.from('profiles')
      .select('alert_email, alert_telegram, telegram_chat_id')
      .eq('id', id)
      .maybeSingle(),
  ])

  return NextResponse.json({ prefs, profile })
}

// PATCH /api/admin/users/[id]/prefs — update a user's preferences + profile
export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const admin_user = await assertAdmin()
  if (!admin_user) return NextResponse.json({ error: 'Forbidden' }, { status: 403 })

  const { id } = await params
  const body = await req.json() as {
    keywords: string[]
    locations: string[]
    exclude_keywords: string[]
    min_score: number | null
    alert_frequency: 'instant' | 'daily' | 'off'
    paused: boolean
    alert_email: boolean
    alert_telegram: boolean
    telegram_chat_id: string | null
  }

  const admin = createAdminClient()
  const now = new Date().toISOString()

  const [prefResult, profResult] = await Promise.all([
    admin.from('user_preferences').upsert(
      {
        user_id:          id,
        keywords:         body.keywords,
        locations:        body.locations,
        exclude_keywords: body.exclude_keywords,
        min_score:        body.min_score,
        alert_frequency:  body.alert_frequency,
        paused:           body.paused,
        updated_at:       now,
      },
      { onConflict: 'user_id' }
    ),
    admin.from('profiles').update({
      alert_email:      body.alert_email,
      alert_telegram:   body.alert_telegram,
      telegram_chat_id: body.telegram_chat_id,
      updated_at:       now,
    }).eq('id', id),
  ])

  if (prefResult.error) return NextResponse.json({ error: prefResult.error.message }, { status: 500 })
  if (profResult.error) return NextResponse.json({ error: profResult.error.message }, { status: 500 })

  return NextResponse.json({ ok: true })
}
