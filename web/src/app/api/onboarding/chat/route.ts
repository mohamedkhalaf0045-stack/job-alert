import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'
import Groq from 'groq-sdk'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

type ProfileType = 'candidate' | 'employer'

const CANDIDATE_SYSTEM_PROMPT = `You are an onboarding assistant. Ask ONE question at a time to fill in profile fields: skills (list), years_experience (number), certifications (list), target_roles (list), desired_locations (list). After the user answers a question, acknowledge briefly and ask the next missing field. When all fields are collected, respond with exactly the marker: ONBOARDING_COMPLETE followed by a JSON object of all collected fields.`

const EMPLOYER_SYSTEM_PROMPT = `You are an onboarding assistant for a company profile. Ask ONE question at a time to fill in: company_name, industry, size (e.g. '1-10', '11-50', '51-200', '200+'), location, description (1-2 sentences about what the company does). When all fields are collected, respond with exactly the marker: ONBOARDING_COMPLETE followed by a JSON object of all collected fields.`

function systemPromptFor(profileType: ProfileType): string {
  return profileType === 'employer' ? EMPLOYER_SYSTEM_PROMPT : CANDIDATE_SYSTEM_PROMPT
}

// Extract the JSON payload that follows the ONBOARDING_COMPLETE marker.
function extractCompletionData(reply: string): Record<string, unknown> | null {
  const idx = reply.indexOf('ONBOARDING_COMPLETE')
  if (idx === -1) return null

  const after = reply.slice(idx + 'ONBOARDING_COMPLETE'.length)
  const start = after.indexOf('{')
  if (start === -1) return null

  // Find the matching closing brace by tracking depth, so trailing prose
  // after the JSON object doesn't break parsing.
  let depth = 0
  let end = -1
  for (let i = start; i < after.length; i++) {
    if (after[i] === '{') depth++
    else if (after[i] === '}') {
      depth--
      if (depth === 0) { end = i; break }
    }
  }
  if (end === -1) return null

  try {
    return JSON.parse(after.slice(start, end + 1))
  } catch {
    return null
  }
}

function toStringArray(v: unknown): string[] {
  if (Array.isArray(v)) return v.map(x => String(x).trim()).filter(Boolean)
  if (typeof v === 'string') return v.split(',').map(s => s.trim()).filter(Boolean)
  return []
}

async function persistCandidateData(userId: string, data: Record<string, unknown>) {
  const admin = createAdminClient()

  // Merge with any existing cv_data:{user_id} bot_state entry.
  const { data: existing } = await admin
    .from('bot_state')
    .select('value')
    .eq('key', `cv_data:${userId}`)
    .single()

  let existingCv: Record<string, unknown> = {}
  if (existing?.value) {
    try { existingCv = JSON.parse(existing.value) } catch { existingCv = {} }
  }

  const skills           = toStringArray(data.skills)
  const certifications   = toStringArray(data.certifications)
  const targetRoles      = toStringArray(data.target_roles)
  const desiredLocations = toStringArray(data.desired_locations)
  const yearsExperience  = typeof data.years_experience === 'number'
    ? data.years_experience
    : parseFloat(String(data.years_experience ?? '')) || existingCv.years_experience || null

  const mergedCv = {
    ...existingCv,
    skills:           skills.length ? skills : (existingCv.skills ?? []),
    years_experience: yearsExperience,
    certifications:   certifications.length ? certifications : (existingCv.certifications ?? []),
    job_titles:       targetRoles.length ? targetRoles : (existingCv.job_titles ?? []),
    analyzed_at:      new Date().toISOString(),
  }

  await admin.from('bot_state').upsert(
    { key: `cv_data:${userId}`, value: JSON.stringify(mergedCv) },
    { onConflict: 'key' }
  )

  // Update user_preferences: keywords from target_roles, locations from desired_locations.
  const { data: existingPrefs } = await admin
    .from('user_preferences')
    .select('keywords, locations')
    .eq('user_id', userId)
    .single()

  const mergedKeywords = Array.from(new Set([...(existingPrefs?.keywords ?? []), ...targetRoles]))
  const mergedLocations = Array.from(new Set([...(existingPrefs?.locations ?? []), ...desiredLocations]))

  await admin.from('user_preferences').upsert(
    {
      user_id:    userId,
      keywords:   mergedKeywords.length ? mergedKeywords : (existingPrefs?.keywords ?? []),
      locations:  mergedLocations.length ? mergedLocations : (existingPrefs?.locations ?? []),
      updated_at: new Date().toISOString(),
    },
    { onConflict: 'user_id' }
  )
}

async function persistEmployerData(userId: string, data: Record<string, unknown>) {
  const admin = createAdminClient()

  const name        = typeof data.company_name === 'string' ? data.company_name.trim() : null
  const industry    = typeof data.industry === 'string' ? data.industry.trim() : null
  const size        = typeof data.size === 'string' ? data.size.trim() : null
  const location    = typeof data.location === 'string' ? data.location.trim() : null
  const description = typeof data.description === 'string' ? data.description.trim() : null

  const { data: existing } = await admin
    .from('employers')
    .select('id')
    .eq('owner_user_id', userId)
    .single()

  let employerId: string

  if (existing) {
    const { data: updated, error } = await admin
      .from('employers')
      .update({
        ...(name        ? { name } : {}),
        ...(industry    ? { industry } : {}),
        ...(size        ? { size } : {}),
        ...(location    ? { location } : {}),
        ...(description ? { description } : {}),
        updated_at: new Date().toISOString(),
      })
      .eq('owner_user_id', userId)
      .select('id')
      .single()
    if (error) throw error
    employerId = updated.id
  } else {
    const { data: created, error } = await admin
      .from('employers')
      .insert({
        owner_user_id: userId,
        name:          name ?? 'Unnamed company',
        industry,
        size,
        location,
        description,
      })
      .select('id')
      .single()
    if (error) throw error
    employerId = created.id
  }

  // Ensure profiles.employer_id + user_type are set after creation.
  await admin
    .from('profiles')
    .update({ employer_id: employerId, user_type: 'employer' })
    .eq('id', userId)
}

export async function POST(req: NextRequest) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const body = await req.json() as { messages: Message[]; profile_type: ProfileType }
    const { messages, profile_type } = body

    if (!profile_type || (profile_type !== 'candidate' && profile_type !== 'employer')) {
      return NextResponse.json({ error: 'profile_type must be "candidate" or "employer"' }, { status: 400 })
    }
    if (!Array.isArray(messages)) {
      return NextResponse.json({ error: 'messages must be an array' }, { status: 400 })
    }

    const groq = new Groq({ apiKey: process.env.GROQ_API_KEY })

    const chatMessages: Groq.Chat.Completions.ChatCompletionMessageParam[] = [
      { role: 'system', content: systemPromptFor(profile_type) },
      ...messages.map(m => ({ role: m.role, content: m.content }) as Groq.Chat.Completions.ChatCompletionMessageParam),
    ]

    // If there are no user-facing messages yet, kick off with the first question.
    if (messages.length === 0) {
      chatMessages.push({
        role: 'user',
        content: 'Begin the onboarding — ask me the first question.',
      })
    }

    const completion = await groq.chat.completions.create({
      model:      'llama-3.3-70b-versatile',
      max_tokens: 500,
      messages:   chatMessages,
    })

    const reply = completion.choices[0]?.message?.content ?? 'Sorry, could not generate a response.'

    const extractedData = extractCompletionData(reply)
    let isComplete = false

    if (extractedData) {
      isComplete = true
      try {
        if (profile_type === 'candidate') {
          await persistCandidateData(user.id, extractedData)
        } else {
          await persistEmployerData(user.id, extractedData)
        }
      } catch (persistError) {
        console.error('Onboarding chat persist error:', persistError)
        // Still report completion to the client — the reply already committed
        // to being done; surface the extracted data even if the write failed.
      }
    }

    return NextResponse.json({
      reply,
      isComplete,
      ...(extractedData ? { extractedData } : {}),
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    console.error('Onboarding chat error:', message)
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
