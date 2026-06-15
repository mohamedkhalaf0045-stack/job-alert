import { NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'

export interface CVProfile {
  skills: string[]
  job_titles: string[]
  years_experience: number | null
  certifications: string[]
  summary: string
  analyzed_at: string | null
  source: 'web' | 'desktop' | null
}

function splitCsv(v: string | undefined): string[] {
  return v ? v.split(',').map(s => s.trim()).filter(Boolean) : []
}

export async function GET() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const admin = createAdminClient()

  // Try per-user key first (web upload)
  const { data: perUser } = await admin
    .from('bot_state')
    .select('value')
    .eq('key', `cv_data:${user.id}`)
    .single()

  if (perUser?.value) {
    try {
      const cv = JSON.parse(perUser.value)
      return NextResponse.json({
        skills:           Array.isArray(cv.skills)       ? cv.skills       : [],
        job_titles:       Array.isArray(cv.job_titles)   ? cv.job_titles   : [],
        years_experience: cv.years_experience            ?? null,
        certifications:   Array.isArray(cv.certifications) ? cv.certifications : [],
        summary:          cv.summary                     ?? '',
        analyzed_at:      cv.analyzed_at                 ?? null,
        source:           'web',
      } satisfies CVProfile)
    } catch { /* fall through to desktop format */ }
  }

  // Fall back to global keys written by the Windows desktop app
  const { data: rows } = await admin
    .from('bot_state')
    .select('key, value')
    .in('key', ['cv_skills', 'cv_job_titles', 'cv_years_experience', 'cv_certifications', 'cv_summary', 'cv_analyzed_at'])

  if (!rows || rows.length === 0) {
    return NextResponse.json({ skills: [], job_titles: [], years_experience: null, certifications: [], summary: '', analyzed_at: null, source: null } satisfies CVProfile)
  }

  const map = Object.fromEntries(rows.map(r => [r.key, r.value]))
  return NextResponse.json({
    skills:           splitCsv(map.cv_skills),
    job_titles:       splitCsv(map.cv_job_titles),
    years_experience: map.cv_years_experience ? parseFloat(map.cv_years_experience) : null,
    certifications:   splitCsv(map.cv_certifications),
    summary:          map.cv_summary ?? '',
    analyzed_at:      map.cv_analyzed_at ?? null,
    source:           'desktop',
  } satisfies CVProfile)
}
