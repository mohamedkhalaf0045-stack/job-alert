import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'
import Groq from 'groq-sdk'

interface KeywordExpansion {
  title_variations: string[]
  related_skills: string[]
}

async function expandKeywordsWithGroq(keyword: string): Promise<KeywordExpansion> {
  const groq = new Groq({ apiKey: process.env.GROQ_API_KEY })

  const prompt = `Generate job title variations and related skills for: "${keyword}"

Return ONLY valid JSON with this structure:
{
  "title_variations": ["Job Title 1", "Job Title 2", "Job Title 3", "Job Title 4", "Job Title 5"],
  "related_skills": ["skill1", "skill2", "skill3", "skill4", "skill5", "skill6", "skill7", "skill8", "skill9", "skill10"]
}

No markdown, just JSON.`

  // Retry up to 3x with backoff on 429
  for (let attempt = 0; attempt < 3; attempt++) {
    if (attempt > 0) await new Promise(r => setTimeout(r, attempt * 2000))
    try {
      const message = await groq.chat.completions.create({
        model: 'llama-3.3-70b-versatile',
        max_tokens: 512,
        messages: [{ role: 'user', content: prompt }],
      })
      const content = message.choices[0]?.message?.content
      if (!content) throw new Error('No response from Groq')
      const jsonMatch = content.match(/\{[\s\S]*\}/)
      if (!jsonMatch) throw new Error('Invalid JSON response')
      const parsed = JSON.parse(jsonMatch[0]) as KeywordExpansion
      return {
        title_variations: Array.isArray(parsed.title_variations) ? parsed.title_variations : [],
        related_skills:   Array.isArray(parsed.related_skills)   ? parsed.related_skills   : [],
      }
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status
      const msg    = (err as { message?: string })?.message ?? ''
      if (status !== 429 || attempt === 2) break
      if (msg.includes('per day') || msg.includes('TPD')) break  // daily cap — don't retry
    }
  }
  return { title_variations: [keyword], related_skills: [] }
}

export async function POST(req: NextRequest) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const { keyword } = await req.json() as { keyword: string }
    if (!keyword?.trim()) return NextResponse.json({ error: 'Keyword is required' }, { status: 400 })

    const expansion = await expandKeywordsWithGroq(keyword.trim())

    // Store to DB if user_preferences row already exists (non-fatal during onboarding)
    const admin = createAdminClient()
    const { data: currentPrefs } = await admin
      .from('user_preferences')
      .select('keyword_expansions')
      .eq('user_id', user.id)
      .single()

    if (currentPrefs) {
      const currentExpansions = (currentPrefs.keyword_expansions as Record<string, unknown>) ?? {}
      currentExpansions[keyword.trim().toLowerCase()] = {
        original: keyword,
        variations: expansion.title_variations,
        related_skills: expansion.related_skills,
        generated_at: new Date().toISOString(),
      }
      await admin
        .from('user_preferences')
        .update({ keyword_expansions: currentExpansions })
        .eq('user_id', user.id)
    }

    return NextResponse.json({ keyword, expansion })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
