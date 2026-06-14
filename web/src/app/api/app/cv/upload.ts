import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'
import Groq from 'groq-sdk'
// @ts-ignore - pdf-parse has no TypeScript definitions
import pdfParse from 'pdf-parse/lib/pdf-parse.js'

const MAX_FILE_SIZE = 10 * 1024 * 1024 // 10MB
const TEXT_LIMIT = 6000 // chars

async function extractTextFromPDF(buffer: Buffer): Promise<string> {
  try {
    const pdf = await pdfParse(buffer)
    return pdf.text
  } catch (err) {
    throw new Error(`PDF extraction failed: ${err instanceof Error ? err.message : 'Unknown error'}`)
  }
}

async function extractTextFromFile(buffer: Buffer, mimeType: string): Promise<string> {
  if (mimeType === 'application/pdf') {
    return extractTextFromPDF(buffer)
  } else if (mimeType === 'text/plain') {
    return buffer.toString('utf-8')
  }
  throw new Error(`Unsupported file type: ${mimeType}. Use PDF or TXT.`)
}

interface CVAnalysisResult {
  skills: string[]
  years_experience: number | null
  job_titles: string[]
  certifications: string[]
  languages: string[]
  education: string[]
  summary: string
  domain_terms: string[]
}

async function analyzeCVWithGroq(text: string): Promise<CVAnalysisResult> {
  const groq = new Groq({
    apiKey: process.env.GROQ_API_KEY,
  })

  const truncated = text.substring(0, TEXT_LIMIT)

  const prompt = `Extract structured information from this CV/resume. Return ONLY valid JSON, no markdown or extra text.

CV Content:
${truncated}

Return JSON with this exact structure:
{
  "skills": ["skill1", "skill2", "skill3"],
  "years_experience": 5,
  "job_titles": ["Job Title 1", "Job Title 2"],
  "certifications": ["Cert1", "Cert2"],
  "languages": ["English", "Arabic"],
  "education": ["Bachelor in CS from University"],
  "summary": "One sentence professional summary",
  "domain_terms": ["relevant", "keywords", "for", "job", "matching"]
}`

  try {
    const message = await groq.chat.completions.create({
      model: 'llama-3.3-70b-versatile',
      max_tokens: 1024,
      messages: [
        {
          role: 'user',
          content: prompt,
        },
      ],
    })

    const content = message.choices[0]?.message?.content
    if (!content) {
      throw new Error('No response from Groq')
    }

    // Parse JSON from response
    const jsonMatch = content.match(/\{[\s\S]*\}/)
    if (!jsonMatch) {
      throw new Error('Invalid JSON response from Groq')
    }

    const parsed = JSON.parse(jsonMatch[0]) as CVAnalysisResult
    return {
      skills: Array.isArray(parsed.skills) ? parsed.skills : [],
      years_experience: parsed.years_experience ?? null,
      job_titles: Array.isArray(parsed.job_titles) ? parsed.job_titles : [],
      certifications: Array.isArray(parsed.certifications) ? parsed.certifications : [],
      languages: Array.isArray(parsed.languages) ? parsed.languages : [],
      education: Array.isArray(parsed.education) ? parsed.education : [],
      summary: parsed.summary ?? '',
      domain_terms: Array.isArray(parsed.domain_terms) ? parsed.domain_terms : [],
    }
  } catch (err) {
    throw new Error(`Groq analysis failed: ${err instanceof Error ? err.message : 'Unknown error'}`)
  }
}

export async function POST(req: NextRequest) {
  try {
    // Check authentication
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    // Parse multipart form data
    const formData = await req.formData()
    const file = formData.get('file') as File | null

    if (!file) {
      return NextResponse.json({ error: 'No file provided' }, { status: 400 })
    }

    // Validate file size
    if (file.size > MAX_FILE_SIZE) {
      return NextResponse.json({ error: `File too large. Max ${MAX_FILE_SIZE / 1024 / 1024}MB` }, { status: 400 })
    }

    // Validate MIME type (PDF or TXT)
    const allowedTypes = ['application/pdf', 'text/plain']
    if (!allowedTypes.includes(file.type)) {
      return NextResponse.json({ error: 'Unsupported file type. Use PDF or TXT.' }, { status: 400 })
    }

    // Extract text
    const buffer = await file.arrayBuffer()
    const text = await extractTextFromFile(Buffer.from(buffer), file.type)

    // Analyze with Groq
    const analysis = await analyzeCVWithGroq(text)

    // Store in Supabase
    const admin = createAdminClient()
    const now = new Date().toISOString()

    const updates = {
      cv_skills: analysis.skills.join(','),
      cv_years_experience: analysis.years_experience?.toString() ?? '',
      cv_job_titles: analysis.job_titles.join(','),
      cv_certifications: analysis.certifications.join(','),
      cv_languages: analysis.languages.join(','),
      cv_education: analysis.education.join(','),
      cv_summary: analysis.summary,
      cv_domain_terms: analysis.domain_terms.join(','),
      cv_analyzed_at: now,
    }

    for (const [key, value] of Object.entries(updates)) {
      const { error } = await admin
        .from('bot_state')
        .upsert({ key, value }, { onConflict: 'key' })
      if (error) {
        console.error(`Failed to store ${key}:`, error)
      }
    }

    return NextResponse.json({
      ok: true,
      analysis: {
        ...analysis,
        analyzed_at: now,
      },
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    console.error('CV upload error:', message)
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
