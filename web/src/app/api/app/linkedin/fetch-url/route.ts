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

function extractTextFromHtml(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim()
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
  if (!match) throw new Error('Could not parse profile — try pasting the text instead')

  const p = JSON.parse(match[0]) as LinkedInAnalysis
  return {
    job_titles: Array.isArray(p.job_titles) ? p.job_titles : [],
    skills:     Array.isArray(p.skills)     ? p.skills     : [],
    locations:  Array.isArray(p.locations)  ? p.locations  : [],
    summary:    typeof p.summary === 'string' ? p.summary  : '',
  }
}

export async function POST(req: NextRequest) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const body = await req.json()
    const url  = typeof body?.url === 'string' ? body.url.trim() : ''

    if (!url || !url.includes('linkedin.com')) {
      return NextResponse.json(
        { error: 'Enter a valid LinkedIn profile URL (linkedin.com/in/…)' },
        { status: 400 }
      )
    }

    const res = await fetch(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      },
      signal: AbortSignal.timeout(10_000),
    })

    if (!res.ok) {
      return NextResponse.json(
        { error: 'LinkedIn blocked the request. Please paste your profile text instead.' },
        { status: 422 }
      )
    }

    const html = await res.text()
    const text = extractTextFromHtml(html)

    if (text.length < 50) {
      return NextResponse.json(
        { error: 'Could not extract enough text from the page. Please paste your profile text instead.' },
        { status: 422 }
      )
    }

    const analysis = await analyzeWithGroq(text)
    return NextResponse.json({ ok: true, analysis })
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    console.error('LinkedIn fetch-url error:', message)
    return NextResponse.json(
      { error: 'Could not fetch the profile. Please paste your profile text instead.' },
      { status: 500 }
    )
  }
}
