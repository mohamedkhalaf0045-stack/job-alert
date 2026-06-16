import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ job_id: string }> }
) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const { job_id } = await params

  const { data, error } = await supabase
    .from('jobs')
    .select([
      'job_id', 'title', 'company', 'location', 'url', 'source',
      'date_posted', 'date_collected',
      'llm_score', 'llm_summary', 'description',
      'missing_skills', 'red_flags',
      'matched_skills',
      'salary_min', 'salary_max', 'salary_avg',
      'salary_currency', 'salary_period', 'salary_source',
      'cover_letter_draft',
    ].join(', '))
    .eq('job_id', job_id)
    .single()

  if (error || !data) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 })
  }

  return NextResponse.json({ job: data })
}
