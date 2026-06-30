import { NextRequest, NextResponse } from 'next/server'
import { createAdminClient } from '@/lib/supabase/admin'
import Groq from 'groq-sdk'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

interface JobContext {
  title?:          string
  company?:        string
  location?:       string
  description?:    string
  match_score?:    number
  llm_summary?:    string
  matched_skills?: string[]
  missing_skills?: string[]
}

async function getCVContext(userId: string): Promise<string> {
  const admin = createAdminClient()
  const { data } = await admin
    .from('bot_state')
    .select('value')
    .eq('key', `cv_data:${userId}`)
    .single()

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

function buildSystemPrompt(cvContext: string, job?: JobContext): string {
  const cvSection = cvContext ? `\n\nUser CV:\n${cvContext}` : ''
  let jobSection  = ''
  if (job) {
    const lines = ['\n\nJob being discussed:']
    if (job.title)    lines.push(`Title: ${job.title}`)
    if (job.company)  lines.push(`Company: ${job.company}`)
    if (job.location) lines.push(`Location: ${job.location}`)
    if (job.match_score != null) lines.push(`AI match score: ${job.match_score}/10`)
    if (job.llm_summary) lines.push(`AI summary: ${job.llm_summary}`)
    if (Array.isArray(job.matched_skills) && job.matched_skills.length) lines.push(`Matched skills: ${job.matched_skills.join(', ')}`)
    if (Array.isArray(job.missing_skills) && job.missing_skills.length) lines.push(`Missing skills: ${job.missing_skills.join(', ')}`)
    if (job.description) lines.push(`\nJob description:\n${job.description.substring(0, 3000)}`)
    jobSection = lines.join('\n')
  }

  return `You are a professional career assistant helping a job seeker in the UAE. You help with interview prep, CV advice, salary negotiation for the UAE market, cover letter tips, and whether the user is a good fit for a role. Be concise and practical. Respond in the same language the user writes in (Arabic or English). Keep responses under 300 words unless asked for more.${cvSection}${jobSection}`
}

export async function POST(req: NextRequest) {
  // Accept Bearer token from the Flutter app (Supabase JWT)
  const authHeader = req.headers.get('Authorization') ?? ''
  const token = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : ''
  if (!token) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const admin = createAdminClient()
  const { data: { user }, error: authError } = await admin.auth.getUser(token)
  if (authError || !user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  try {
    const body = await req.json() as { messages: unknown; job?: JobContext }
    const { messages: rawMessages, job } = body

    // Validate messages array before touching Groq — prevents cost-exhaustion abuse.
    if (!Array.isArray(rawMessages) || rawMessages.length === 0) {
      return NextResponse.json({ error: 'No messages' }, { status: 400 })
    }
    if (rawMessages.length > 50) {
      return NextResponse.json({ error: 'Too many messages' }, { status: 400 })
    }
    const messages: Message[] = rawMessages.map((m: unknown) => {
      const msg = m as Record<string, unknown>
      const role = (msg.role === 'user' || msg.role === 'assistant' ? msg.role : 'user') as 'user' | 'assistant'
      const content = typeof msg.content === 'string'
        ? msg.content.slice(0, 4000)   // cap per-message length
        : ''
      return { role, content }
    }).filter(m => m.content.length > 0)

    if (messages.length === 0) {
      return NextResponse.json({ error: 'No valid messages' }, { status: 400 })
    }

    const cvContext    = await getCVContext(user.id)
    const systemPrompt = buildSystemPrompt(cvContext, job)
    const groq         = new Groq({ apiKey: process.env.GROQ_API_KEY })

    const response = await groq.chat.completions.create({
      model:      'llama-3.3-70b-versatile',
      max_tokens: 512,
      messages: [
        { role: 'system', content: systemPrompt },
        ...messages.map(m => ({ role: m.role, content: m.content })),
      ],
    })

    const reply = response.choices[0]?.message?.content ?? 'Sorry, could not generate a response.'
    return NextResponse.json({ reply })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
