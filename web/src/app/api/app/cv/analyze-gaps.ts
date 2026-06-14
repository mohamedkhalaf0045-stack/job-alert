import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'
import Groq from 'groq-sdk'

interface JobSkillsResult {
  skills: string[]
}

async function extractJobSkillsWithGroq(jobTitle: string, jobDescription: string): Promise<string[]> {
  const groq = new Groq({
    apiKey: process.env.GROQ_API_KEY,
  })

  const prompt = `Extract the required technical and soft skills from this job posting. Return ONLY a JSON array of skill strings, no markdown or extra text.

Job Title: ${jobTitle}

Job Description:
${jobDescription.substring(0, 2000)}`

  try {
    const message = await groq.chat.completions.create({
      model: 'llama-3.3-70b-versatile',
      max_tokens: 512,
      messages: [
        {
          role: 'user',
          content: prompt,
        },
      ],
    })

    const content = message.choices[0]?.message?.content
    if (!content) return []

    // Try to extract JSON array
    const match = content.match(/\[[\s\S]*\]/)
    if (!match) return []

    const parsed = JSON.parse(match[0]) as string[]
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
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

    // Get user's CV skills
    const admin = createAdminClient()
    const { data: botState } = await admin
      .from('bot_state')
      .select('value')
      .eq('key', 'cv_skills')
      .single()

    const cvSkillsStr = botState?.value ?? ''
    const cvSkills = new Set(
      cvSkillsStr
        .split(',')
        .map((s: string) => s.trim().toLowerCase())
        .filter((s: string) => s)
    )

    // Get user's recent job feed (last 50 jobs)
    const { data: jobs } = await supabase.rpc('user_jobs_feed', { p_user: user.id, p_limit: 50 })

    if (!jobs || jobs.length === 0) {
      return NextResponse.json({
        missing_skills: [],
        message: 'No recent jobs found. View more jobs first.',
      })
    }

    // Track skill frequency
    const skillFrequency = new Map<string, number>()
    const skillJobCount = new Map<string, number>()

    // Extract skills from each job
    for (const job of jobs) {
      const jobSkills = await extractJobSkillsWithGroq(job.title || '', job.description || '')

      for (const skill of jobSkills) {
        const skillLower = skill.trim().toLowerCase()
        if (skillLower && !cvSkills.has(skillLower)) {
          skillFrequency.set(skillLower, (skillFrequency.get(skillLower) ?? 0) + 1)
          skillJobCount.set(skillLower, (skillJobCount.get(skillLower) ?? 0) + 1)
        }
      }
    }

    // Sort by frequency
    const missedSkills = Array.from(skillFrequency.entries())
      .map(([skill, frequency]) => ({
        skill,
        frequency,
        job_count: skillJobCount.get(skill) ?? 0,
      }))
      .sort((a, b) => b.frequency - a.frequency)
      .slice(0, 10) // Top 10 missing skills

    // Store in database for future reference
    for (const { skill, frequency, job_count } of missedSkills) {
      const { error } = await admin
        .from('user_skill_gaps')
        .upsert({
          user_id: user.id,
          skill,
          frequency,
          job_count,
          analyzed_at: new Date().toISOString(),
        }, { onConflict: 'user_id,skill' })

      if (error) {
        console.error(`Failed to store skill gap: ${error.message}`)
      }
    }

    return NextResponse.json({
      missing_skills: missedSkills,
      total_jobs_analyzed: jobs.length,
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    console.error('Skill gap analysis error:', message)
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
