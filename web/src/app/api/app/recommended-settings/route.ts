import { NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'

function parseList(raw: string | null): string[] {
  if (!raw) return []
  try { return JSON.parse(raw) } catch { return [] }
}

export async function GET() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { data: rows } = await supabase
    .from('bot_state')
    .select('key, value')
    .in('key', ['recommended_keywords', 'recommended_locations'])

  const map: Record<string, string> = {}
  for (const row of rows ?? []) map[row.key] = row.value

  return NextResponse.json({
    keywords:  parseList(map.recommended_keywords),
    locations: parseList(map.recommended_locations),
  })
}
