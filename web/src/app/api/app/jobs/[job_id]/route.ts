import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'

async function fetchLinkedInDescription(jobUrl: string): Promise<string> {
  try {
    const m = jobUrl.match(/\/(?:view|jobs\/view)\/(\d+)/)
    if (!m) return ''
    const apiUrl = `https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/${m[1]}`
    const res = await fetch(apiUrl, {
      headers: { 'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1)' },
      signal: AbortSignal.timeout(8000),
    })
    if (!res.ok) return ''
    const html = await res.text()
    const descMatch = html.match(/class="show-more-less-html__markup[^"]*"[^>]*>([\s\S]*?)<\/div>/)
    const raw = descMatch ? descMatch[1] : html
    return raw.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 3000)
  } catch {
    return ''
  }
}

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ job_id: string }> }
) {
  // Auth check via user session
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const { job_id } = await params

  // Use admin client for the SELECT so column existence and RLS never block the read
  const admin = createAdminClient()
  const { data, error } = await admin
    .from('jobs')
    .select(
      'job_id, title, company, location, url, source,' +
      'date_posted, date_collected,' +
      'llm_score, llm_summary, description,' +
      'missing_skills, red_flags,' +
      'matched_skills,' +
      'salary_min, salary_max, salary_avg,' +
      'salary_currency, salary_period, salary_source,' +
      'cover_letter_draft'
    )
    .eq('job_id', job_id)
    .single()

  if (error || !data) {
    console.error('[jobs detail] db error:', error?.message)
    return NextResponse.json({ error: error?.message ?? 'Not found' }, { status: 404 })
  }

  // On-demand description fetch when not stored yet
  if (!data.description && data.url) {
    const url: string = data.url
    let fetched = ''

    if (url.toLowerCase().includes('linkedin.com')) {
      fetched = await fetchLinkedInDescription(url)
    } else if (url.toLowerCase().includes('indeed.com')) {
      try {
        const res = await fetch(url, {
          headers: { 'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1)' },
          signal: AbortSignal.timeout(8000),
        })
        if (res.ok) {
          const html = await res.text()
          const m = html.match(/id="jobDescriptionText"[^>]*>([\s\S]*?)<\/div>/)
          if (m) fetched = m[1].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 3000)
        }
      } catch { /* ignore */ }
    }

    if (fetched) {
      data.description = fetched
      // Store it for next time (fire-and-forget)
      admin.from('jobs').update({ description: fetched }).eq('job_id', job_id).then(() => {})
    }
  }

  return NextResponse.json({ job: data })
}
