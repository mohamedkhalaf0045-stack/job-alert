import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'
import Groq from 'groq-sdk'

const MAX_FILE_SIZE = 10 * 1024 * 1024
const TEXT_LIMIT = 6000

async function extractText(buffer: Buffer, mimeType: string): Promise<string> {
  if (mimeType === 'application/pdf') {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const pdfParse = require('pdf-parse') as (buf: Buffer) => Promise<{ text: string }>
    const pdf = await pdfParse(buffer)
    return pdf.text
  }
  if (mimeType === 'text/plain') return buffer.toString('utf-8')
  throw new Error('Unsupported file type. Use PDF or TXT.')
}

interface CVAnalysis {
  skills: string[]
  years_experience: number | null
  job_titles: string[]
  certifications: string[]
  languages: string[]
  education: string[]
  summary: string
  domain_terms: string[]
}

async function analyzeWithGroq(text: string): Promise<CVAnalysis> {
  const groq = new Groq({ apiKey: process.env.GROQ_API_KEY })
  const truncated = text.substring(0, TEXT_LIMIT)

  const prompt = `Extract structured information from this CV/resume. Return ONLY valid JSON, no markdown.

CV:
${truncated}

JSON structure:
{
  "skills": ["skill1"],
  "years_experience": 5,
  "job_titles": ["Title 1"],
  "certifications": ["Cert1"],
  "languages": ["English"],
  "education": ["Bachelor in CS"],
  "summary": "One sentence summary",
  "domain_terms": ["keyword1"]
}`

  const msg = await groq.chat.completions.create({
    model: 'llama-3.3-70b-versatile',
    max_tokens: 1024,
    messages: [{ role: 'user', content: prompt }],
  })

  const content = msg.choices[0]?.message?.content ?? ''
  const match = content.match(/\{[\s\S]*\}/)
  if (!match) throw new Error('Invalid JSON from Groq')

  const p = JSON.parse(match[0]) as CVAnalysis
  return {
    skills:           Array.isArray(p.skills)         ? p.skills         : [],
    years_experience: p.years_experience              ?? null,
    job_titles:       Array.isArray(p.job_titles)      ? p.job_titles      : [],
    certifications:   Array.isArray(p.certifications)  ? p.certifications  : [],
    languages:        Array.isArray(p.languages)       ? p.languages       : [],
    education:        Array.isArray(p.education)       ? p.education       : [],
    summary:          p.summary                        ?? '',
    domain_terms:     Array.isArray(p.domain_terms)    ? p.domain_terms    : [],
  }
}

export async function POST(req: NextRequest) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const formData = await req.formData()
    const file = formData.get('file') as File | null
    if (!file) return NextResponse.json({ error: 'No file provided' }, { status: 400 })
    if (file.size > MAX_FILE_SIZE) return NextResponse.json({ error: 'File too large (max 10MB)' }, { status: 400 })
    if (!['application/pdf', 'text/plain'].includes(file.type)) {
      return NextResponse.json({ error: 'Unsupported file type. Use PDF or TXT.' }, { status: 400 })
    }

    const buffer = Buffer.from(await file.arrayBuffer())
    const text = await extractText(buffer, file.type)
    const analysis = await analyzeWithGroq(text)
    const now = new Date().toISOString()

    // Store per-user as a single JSON key: cv_data:{user_id}
    const admin = createAdminClient()
    const { error: storeErr } = await admin
      .from('bot_state')
      .upsert(
        { key: `cv_data:${user.id}`, value: JSON.stringify({ ...analysis, analyzed_at: now }) },
        { onConflict: 'key' }
      )
    if (storeErr) console.error('Failed to store CV:', storeErr)

    return NextResponse.json({ ok: true, analysis: { ...analysis, analyzed_at: now } })
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    console.error('CV upload error:', message)
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
