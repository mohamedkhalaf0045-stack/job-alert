import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'
import Groq from 'groq-sdk'

interface JobRow {
  title: string | null
  company: string | null
  location: string | null
  description: string | null
  llm_summary: string | null
}

async function getCVContext(userId: string): Promise<string> {
  const admin = createAdminClient()
  const { data } = await admin
    .from('bot_state')
    .select('value')
    .eq('key', `cv_data:${userId}`)
    .single<{ value: string }>()

  if (!data?.value) return ''
  try {
    const cv = JSON.parse(data.value)
    const parts: string[] = []
    if (cv.summary)          parts.push(`Professional summary: ${cv.summary}`)
    if (cv.years_experience) parts.push(`Years of experience: ${cv.years_experience}`)
    if (Array.isArray(cv.job_titles)     && cv.job_titles.length)     parts.push(`Past job titles: ${cv.job_titles.join(', ')}`)
    if (Array.isArray(cv.skills)         && cv.skills.length)         parts.push(`Skills: ${cv.skills.join(', ')}`)
    if (Array.isArray(cv.certifications) && cv.certifications.length) parts.push(`Certifications: ${cv.certifications.join(', ')}`)
    return parts.join('\n')
  } catch { return '' }
}

export async function POST(
  _req: NextRequest,
  { params }: { params: Promise<{ job_id: string }> }
) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const { job_id } = await params
    const admin = createAdminClient()

    const { data: job, error } = await admin
      .from('jobs')
      .select('title, company, location, description, llm_summary')
      .eq('job_id', job_id)
      .single<JobRow>()

    if (error || !job) {
      return NextResponse.json({ error: 'Job not found' }, { status: 404 })
    }

    const cvContext = await getCVContext(user.id)

    const jobLines = [
      `Title: ${job.title ?? ''}`,
      `Company: ${job.company ?? ''}`,
      job.location ? `Location: ${job.location}` : '',
      job.description ? `\nJob description:\n${job.description.substring(0, 3000)}`
                      : (job.llm_summary ? `\nRole summary: ${job.llm_summary}` : ''),
    ].filter(Boolean).join('\n')

    const systemPrompt =
      `You are a professional career writer in the UAE. Write a concise, tailored cover ` +
      `letter (180–250 words) for the job below, drawing ONLY on the candidate's real CV ` +
      `background — never invent experience, employers, or credentials. Plain text, no ` +
      `markdown. Structure: a strong opening naming the role and company; one paragraph ` +
      `connecting the candidate's actual skills/experience to the role's needs; a brief ` +
      `closing with availability and a call to action. Professional, confident, not generic.` +
      (cvContext ? `\n\nCandidate CV / background:\n${cvContext}`
                 : `\n\n(No CV on file — keep claims generic and invite the reader to review the attached CV.)`) +
      `\n\nJob:\n${jobLines}`

    const groq = new Groq({ apiKey: process.env.GROQ_API_KEY })
    const response = await groq.chat.completions.create({
      model: 'llama-3.3-70b-versatile',
      max_tokens: 600,
      temperature: 0.6,
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user',   content: 'Write the cover letter now.' },
      ],
    })

    const coverLetter = response.choices[0]?.message?.content?.trim()
      ?? 'Could not generate a cover letter. Please try again.'

    return NextResponse.json({ cover_letter: coverLetter })
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    console.error('[cover-letter] error:', message)
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
