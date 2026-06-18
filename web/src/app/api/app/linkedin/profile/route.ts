import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import Groq from 'groq-sdk'

const TEXT_LIMIT = 3000

interface LinkedInAnalysis {
  job_titles: string[]
  skills:     string[]
  locations:  string[]
  summary:    string
}

async function analyzeWithGroq(text: string): Promise<LinkedInAnalysis> {
  const groq = new Groq({ apiKey: process.env.GROQ_API_KEY })

  const prompt = `Extract job search keywords from this LinkedIn profile text. Return ONLY valid JSON, no markdown.

LinkedIn profile:
${text.substring(0, TEXT_LIMIT)}

JSON:
{
  "job_titles": ["IT Support Engineer"],
  "skills": ["Windows Server", "Active Directory"],
  "locations": ["Dubai", "United Arab Emirates"],
  "summary": "One sentence about the person"
}`

  const msg = await groq.chat.completions.create({
    model:      'llama-3.3-70b-versatile',
    max_tokens: 512,
    messages:   [{ role: 'user', content: prompt }],
  })

  const content = msg.choices[0]?.message?.content ?? ''
  const match   = content.match(/\{[\s\S]*\}/)
  if (!match) throw new Error('Could not parse profile — try pasting more text')

  const p = JSON.parse(match[0]) as LinkedInAnalysis
  return {
    job_titles: Array.isArray(p.job_titles) ? p.job_titles : [],
    skills:     Array.isArray(p.skills)     ? p.skills     : [],
    locations:  Array.isArray(p.locations)  ? p.locations  : [],
    summary:    typeof p.summary === 'string' ? p.summary   : '',
  }
}

export async function POST(req: NextRequest) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const body = await req.json()
    const text = typeof body?.text === 'string' ? body.text.trim() : ''
    if (text.length < 20) {
      return NextResponse.json(
        { error: 'Paste at least a few lines from your LinkedIn profile' },
        { status: 400 }
      )
    }

    const analysis = await analyzeWithGroq(text)
    return NextResponse.json({ ok: true, analysis })
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    console.error('LinkedIn profile parse error:', message)
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
