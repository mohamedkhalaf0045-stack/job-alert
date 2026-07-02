import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'
import { callAI } from '@/lib/ai-chat'

interface KeywordExpansion {
  title_variations: string[]
  related_skills: string[]
}

async function expandKeywords(keyword: string): Promise<KeywordExpansion> {
  const prompt = `Generate job title variations and related skills for: "${keyword}"

Return ONLY valid JSON with this structure:
{
  "title_variations": ["Job Title 1", "Job Title 2", "Job Title 3", "Job Title 4", "Job Title 5"],
  "related_skills": ["skill1", "skill2", "skill3", "skill4", "skill5", "skill6", "skill7", "skill8", "skill9", "skill10"]
}

No markdown, just JSON.`

  const content = await callAI([{ role: 'user', content: prompt }], 512)
  const jsonMatch = content.match(/\{[\s\S]*\}/)
  if (!jsonMatch) throw new Error('Invalid JSON response from AI')
  const parsed = JSON.parse(jsonMatch[0]) as KeywordExpansion
  return {
    title_variations: Array.isArray(parsed.title_variations) ? parsed.title_variations : [],
    related_skills:   Array.isArray(parsed.related_skills)   ? parsed.related_skills   : [],
  }
}

export async function POST(req: NextRequest) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const { keyword } = await req.json() as { keyword: string }
    if (!keyword?.trim()) return NextResponse.json({ error: 'Keyword is required' }, { status: 400 })

    const expansion = await expandKeywords(keyword.trim())

    // Store to DB if user_preferences row exists (non-fatal during onboarding)
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
