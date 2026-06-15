import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'
import Groq from 'groq-sdk'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

interface JobContext {
  title?: string
  company?: string
  location?: string
  description?: string
  match_score?: number
}

async function getCVContext(userId: string): Promise<string> {
  const admin = createAdminClient()
  const keys = ['cv_skills', 'cv_job_titles', 'cv_years_experience', 'cv_summary', 'cv_certifications']

  const { data } = await admin
    .from('bot_state')
    .select('key, value')
    .in('key', keys)

  if (!data || data.length === 0) return ''

  const map = Object.fromEntries(data.map(r => [r.key, r.value]))
  const parts: string[] = []

  if (map.cv_summary) parts.push(`Professional summary: ${map.cv_summary}`)
  if (map.cv_years_experience) parts.push(`Years of experience: ${map.cv_years_experience}`)
  if (map.cv_job_titles) parts.push(`Past job titles: ${map.cv_job_titles}`)
  if (map.cv_skills) parts.push(`Skills: ${map.cv_skills}`)
  if (map.cv_certifications) parts.push(`Certifications: ${map.cv_certifications}`)

  return parts.join('\n')
}

function buildSystemPrompt(cvContext: string, job?: JobContext): string {
  const jobSection = job
    ? `\n\nCurrent job the user is asking about:\nTitle: ${job.title ?? 'Unknown'}\nCompany: ${job.company ?? 'Unknown'}\nLocation: ${job.location ?? 'Unknown'}\nMatch score: ${job.match_score != null ? job.match_score + '%' : 'N/A'}\nDescription:\n${(job.description ?? '').substring(0, 2000)}`
    : ''

  const cvSection = cvContext
    ? `\n\nUser's CV / background:\n${cvContext}`
    : ''

  return `You are a professional career assistant helping a job seeker in the UAE. You help with:
- Interview preparation (likely questions, how to answer them, what to research)
- CV / resume advice specific to the job
- Salary negotiation guidance for UAE market
- Whether the user is a good fit for a specific role
- Cover letter tips
- Application strategy (should they apply, how to stand out)
- General career advice

Be concise, practical, and specific to the UAE job market. Respond in the same language the user writes in (Arabic or English).${cvSection}${jobSection}

Important: If you don't have enough context to answer, ask one clarifying question. Keep responses under 250 words unless the user asks for detail.`
}

export async function POST(req: NextRequest) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const body = await req.json() as { messages: Message[]; job?: JobContext }
    const { messages, job } = body

    if (!messages || messages.length === 0) {
      return NextResponse.json({ error: 'No messages provided' }, { status: 400 })
    }

    const cvContext = await getCVContext(user.id)
    const systemPrompt = buildSystemPrompt(cvContext, job)

    const groq = new Groq({ apiKey: process.env.GROQ_API_KEY })

    const response = await groq.chat.completions.create({
      model: 'llama-3.3-70b-versatile',
      max_tokens: 512,
      messages: [
        { role: 'system', content: systemPrompt },
        ...messages.map(m => ({ role: m.role, content: m.content })),
      ],
    })

    const reply = response.choices[0]?.message?.content ?? 'Sorry, I could not generate a response.'

    return NextResponse.json({ reply })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    console.error('Chat error:', message)
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
