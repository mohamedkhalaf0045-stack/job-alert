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
  const { data } = await admin
    .from('bot_state')
    .select('value')
    .eq('key', `cv_data:${userId}`)
    .single()

  if (!data?.value) return ''

  try {
    const cv = JSON.parse(data.value)
    const parts: string[] = []
    if (cv.summary) parts.push(`Professional summary: ${cv.summary}`)
    if (cv.years_experience) parts.push(`Years of experience: ${cv.years_experience}`)
    if (Array.isArray(cv.job_titles) && cv.job_titles.length) parts.push(`Past job titles: ${cv.job_titles.join(', ')}`)
    if (Array.isArray(cv.skills) && cv.skills.length) parts.push(`Skills: ${cv.skills.join(', ')}`)
    if (Array.isArray(cv.certifications) && cv.certifications.length) parts.push(`Certifications: ${cv.certifications.join(', ')}`)
    return parts.join('\n')
  } catch { return '' }
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
