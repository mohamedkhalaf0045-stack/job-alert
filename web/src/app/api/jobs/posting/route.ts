import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'

export interface JobPosting {
  id: string
  employer_id: string
  title: string
  description: string | null
  requirements: string | null
  location: string | null
  salary_min: number | null
  salary_max: number | null
  employment_type: string | null
  status: 'draft' | 'published' | 'closed'
  created_at: string
  updated_at: string
  expires_at: string | null
}

// POST /api/jobs/posting — create a new job posting
export async function POST(req: NextRequest) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const body = await req.json()
    const {
      title,
      description,
      requirements,
      location,
      salary_min,
      salary_max,
      employment_type,
      expires_at,
    } = body

    if (!title || typeof title !== 'string' || title.trim().length === 0) {
      return NextResponse.json(
        { error: 'Job title is required' },
        { status: 400 }
      )
    }

    // Verify user has an employer profile
    const { data: profile } = await supabase
      .from('profiles')
      .select('employer_id')
      .eq('id', user.id)
      .single()

    if (!profile?.employer_id) {
      return NextResponse.json(
        { error: 'User does not have an employer profile' },
        { status: 403 }
      )
    }

    // Create job posting
    const { data: posting, error } = await supabase
      .from('job_postings')
      .insert({
        employer_id: profile.employer_id,
        title: title.trim(),
        description: description || null,
        requirements: requirements || null,
        location: location || null,
        salary_min: salary_min || null,
        salary_max: salary_max || null,
        employment_type: employment_type || null,
        status: 'draft',
        expires_at: expires_at || null,
      })
      .select()
      .single()

    if (error) throw error

    return NextResponse.json(posting as JobPosting, { status: 201 })
  } catch (error) {
    console.error('POST /api/jobs/posting error:', error)
    return NextResponse.json(
      { error: 'Failed to create job posting' },
      { status: 500 }
    )
  }
}

// GET /api/jobs/posting — list all postings for the authenticated employer
export async function GET(req: NextRequest) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    // Get query params for filtering
    const { searchParams } = new URL(req.url)
    const statusFilter = searchParams.get('status') || 'all'
    const limit = parseInt(searchParams.get('limit') || '50', 10)
    const offset = parseInt(searchParams.get('offset') || '0', 10)

    // Verify user has an employer profile
    const { data: profile } = await supabase
      .from('profiles')
      .select('employer_id')
      .eq('id', user.id)
      .single()

    if (!profile?.employer_id) {
      return NextResponse.json(
        { error: 'User does not have an employer profile' },
        { status: 403 }
      )
    }

    let query = supabase
      .from('job_postings')
      .select('*', { count: 'exact' })
      .eq('employer_id', profile.employer_id)
      .order('created_at', { ascending: false })

    if (statusFilter !== 'all') {
      query = query.eq('status', statusFilter)
    }

    const { data: postings, count, error } = await query
      .range(offset, offset + limit - 1)

    if (error) throw error

    return NextResponse.json({
      postings: postings as JobPosting[],
      total: count,
      limit,
      offset,
    })
  } catch (error) {
    console.error('GET /api/jobs/posting error:', error)
    return NextResponse.json(
      { error: 'Failed to fetch job postings' },
      { status: 500 }
    )
  }
}
