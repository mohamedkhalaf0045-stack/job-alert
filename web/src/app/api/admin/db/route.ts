import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'

async function assertAdmin() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user || user.email !== process.env.ADMIN_EMAIL) return null
  return user
}

const ALLOWED_TABLES = ['jobs', 'bot_state', 'user_preferences', 'user_alert_log'] as const
type AllowedTable = typeof ALLOWED_TABLES[number]

const TABLE_COLUMNS: Record<AllowedTable, string> = {
  jobs:             'job_id, title, company, location, source, overall_score, skills_match, scraped_at, url',
  bot_state:        'key, value',
  user_preferences: 'user_id, keywords, locations, exclude_keywords, alert_frequency, paused, updated_at',
  user_alert_log:   'user_id, job_id, channel, sent_at',
}

export async function GET(req: NextRequest) {
  const admin_user = await assertAdmin()
  if (!admin_user) return NextResponse.json({ error: 'Forbidden' }, { status: 403 })

  const { searchParams } = new URL(req.url)
  const table = searchParams.get('table') as AllowedTable | null
  const search = searchParams.get('search') ?? ''
  const page = Math.max(1, parseInt(searchParams.get('page') ?? '1'))
  const pageSize = 50

  if (!table || !ALLOWED_TABLES.includes(table)) {
    return NextResponse.json({ error: 'Invalid table' }, { status: 400 })
  }

  const admin = createAdminClient()
  const from = (page - 1) * pageSize
  const to = from + pageSize - 1

  let query = admin
    .from(table)
    .select(TABLE_COLUMNS[table], { count: 'exact' })
    .range(from, to)

  // Apply search filters per table
  if (search) {
    if (table === 'jobs') {
      query = query.or(`title.ilike.%${search}%,company.ilike.%${search}%,location.ilike.%${search}%`)
    } else if (table === 'bot_state') {
      query = query.or(`key.ilike.%${search}%,value.ilike.%${search}%`)
    }
  }

  // Default sort
  if (table === 'jobs')          query = query.order('scraped_at', { ascending: false })
  if (table === 'bot_state')     query = query.order('key')
  if (table === 'user_alert_log') query = query.order('sent_at', { ascending: false })
  if (table === 'user_preferences') query = query.order('updated_at', { ascending: false })

  const { data, error, count } = await query

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })

  return NextResponse.json({ rows: data ?? [], total: count ?? 0, page, pageSize })
}
