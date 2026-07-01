import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'

// PATCH /api/jobs/posting/[id] — update a job posting (only draft/published)
export async function PATCH(
  req: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const postingId = params.id
    const body = await req.json()

    // Verify user owns this posting
    const { data: posting, error: fetchErr } = await supabase
      .from('job_postings')
      .select('employer_id, status')
      .eq('id', postingId)
      .single()

    if (fetchErr || !posting) {
      return NextResponse.json(
        { error: 'Job posting not found' },
        { status: 404 }
      )
    }

    // Verify user is the employer
    const { data: employer } = await supabase
      .from('employers')
      .select('owner_user_id')
      .eq('id', posting.employer_id)
      .single()

    if (employer?.owner_user_id !== user.id) {
      return NextResponse.json(
        { error: 'Unauthorized to update this posting' },
        { status: 403 }
      )
    }

    // Closed postings cannot be edited
    if (posting.status === 'closed') {
      return NextResponse.json(
        { error: 'Cannot edit a closed job posting' },
        { status: 400 }
      )
    }

    // Build update object with allowed fields
    const updates: any = {}
    const allowedFields = [
      'title',
      'description',
      'requirements',
      'location',
      'salary_min',
      'salary_max',
      'employment_type',
      'expires_at',
    ]

    for (const field of allowedFields) {
      if (field in body) {
        updates[field] = body[field] || null
      }
    }

    // Allow status update: draft → published, published → draft, any → closed
    if ('status' in body) {
      const validStatuses = ['draft', 'published', 'closed']
      if (!validStatuses.includes(body.status)) {
        return NextResponse.json(
          { error: `Invalid status. Must be one of: ${validStatuses.join(', ')}` },
          { status: 400 }
        )
      }
      updates.status = body.status
    }

    if (Object.keys(updates).length === 0) {
      return NextResponse.json(
        { error: 'No valid fields to update' },
        { status: 400 }
      )
    }

    updates.updated_at = new Date().toISOString()

    const { data: updated, error } = await supabase
      .from('job_postings')
      .update(updates)
      .eq('id', postingId)
      .select()
      .single()

    if (error) throw error

    return NextResponse.json(updated)
  } catch (error) {
    console.error(`PATCH /api/jobs/posting/[id] error:`, error)
    return NextResponse.json(
      { error: 'Failed to update job posting' },
      { status: 500 }
    )
  }
}

// DELETE /api/jobs/posting/[id] — soft delete: set status='closed'
export async function DELETE(
  req: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const postingId = params.id

    // Verify user owns this posting
    const { data: posting, error: fetchErr } = await supabase
      .from('job_postings')
      .select('employer_id')
      .eq('id', postingId)
      .single()

    if (fetchErr || !posting) {
      return NextResponse.json(
        { error: 'Job posting not found' },
        { status: 404 }
      )
    }

    // Verify user is the employer
    const { data: employer } = await supabase
      .from('employers')
      .select('owner_user_id')
      .eq('id', posting.employer_id)
      .single()

    if (employer?.owner_user_id !== user.id) {
      return NextResponse.json(
        { error: 'Unauthorized to delete this posting' },
        { status: 403 }
      )
    }

    // Soft delete: set status to 'closed'
    const { data: updated, error } = await supabase
      .from('job_postings')
      .update({
        status: 'closed',
        updated_at: new Date().toISOString(),
      })
      .eq('id', postingId)
      .select()
      .single()

    if (error) throw error

    return NextResponse.json(updated)
  } catch (error) {
    console.error(`DELETE /api/jobs/posting/[id] error:`, error)
    return NextResponse.json(
      { error: 'Failed to delete job posting' },
      { status: 500 }
    )
  }
}

// GET /api/jobs/posting/[id] — fetch a single job posting (public read)
export async function GET(
  req: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const supabase = await createClient()
    const postingId = params.id

    const { data: posting, error } = await supabase
      .from('job_postings')
      .select('*')
      .eq('id', postingId)
      .single()

    if (error || !posting) {
      return NextResponse.json(
        { error: 'Job posting not found' },
        { status: 404 }
      )
    }

    // Only return published postings to unauthenticated users
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) {
      if (posting.status !== 'published') {
        return NextResponse.json(
          { error: 'Job posting not found' },
          { status: 404 }
        )
      }
    } else {
      // Authenticated users can see their own postings regardless of status
      const { data: employer } = await supabase
        .from('employers')
        .select('owner_user_id')
        .eq('id', posting.employer_id)
        .single()

      if (employer?.owner_user_id !== user.id && posting.status !== 'published') {
        return NextResponse.json(
          { error: 'Job posting not found' },
          { status: 404 }
        )
      }
    }

    return NextResponse.json(posting)
  } catch (error) {
    console.error(`GET /api/jobs/posting/[id] error:`, error)
    return NextResponse.json(
      { error: 'Failed to fetch job posting' },
      { status: 500 }
    )
  }
}
