import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'

export interface EmployerProfile {
  id: string
  name: string
  logo_url: string | null
  industry: string | null
  size: string | null
  location: string | null
  description: string | null
  verified: boolean
  owner_user_id: string
  created_at: string
  updated_at: string
}

// GET /api/employers/profile — fetch current user's employer profile
export async function GET() {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    // Check if user is an employer (has user_type='employer' in profiles)
    const { data: profile } = await supabase
      .from('profiles')
      .select('user_type, employer_id')
      .eq('id', user.id)
      .single()

    if (profile?.user_type !== 'employer') {
      return NextResponse.json(
        { error: 'User is not an employer' },
        { status: 403 }
      )
    }

    // Fetch the employer profile
    const { data: employer, error } = await supabase
      .from('employers')
      .select('*')
      .eq('owner_user_id', user.id)
      .single()

    if (error && error.code === 'PGRST116') {
      // No employer profile yet
      return NextResponse.json(null)
    }

    if (error) throw error

    return NextResponse.json(employer as EmployerProfile)
  } catch (error) {
    console.error('GET /api/employers/profile error:', error)
    return NextResponse.json(
      { error: 'Failed to fetch employer profile' },
      { status: 500 }
    )
  }
}

// POST /api/employers/profile — create or update employer profile
export async function POST(req: NextRequest) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const body = await req.json()
    const { name, logo_url, industry, size, location, description } = body

    if (!name || typeof name !== 'string' || name.trim().length === 0) {
      return NextResponse.json(
        { error: 'Company name is required' },
        { status: 400 }
      )
    }

    // Ensure user has employer user_type
    const { data: profile } = await supabase
      .from('profiles')
      .select('user_type')
      .eq('id', user.id)
      .single()

    if (profile?.user_type !== 'employer') {
      // Auto-upgrade to employer
      const { error: updateErr } = await supabase
        .from('profiles')
        .update({ user_type: 'employer' })
        .eq('id', user.id)

      if (updateErr) throw updateErr
    }

    // Check if employer profile already exists
    const { data: existing } = await supabase
      .from('employers')
      .select('id')
      .eq('owner_user_id', user.id)
      .single()

    if (existing) {
      // Update
      const { data: updated, error } = await supabase
        .from('employers')
        .update({
          name: name.trim(),
          logo_url: logo_url || null,
          industry: industry || null,
          size: size || null,
          location: location || null,
          description: description || null,
          updated_at: new Date().toISOString(),
        })
        .eq('owner_user_id', user.id)
        .select()
        .single()

      if (error) throw error

      // Link employer to profile if not already linked
      const { error: linkErr } = await supabase
        .from('profiles')
        .update({ employer_id: updated.id })
        .eq('id', user.id)

      if (linkErr) throw linkErr

      return NextResponse.json(updated as EmployerProfile)
    } else {
      // Create
      const admin = createAdminClient() // Use service role to create (bypasses RLS)
      const { data: created, error } = await admin
        .from('employers')
        .insert({
          owner_user_id: user.id,
          name: name.trim(),
          logo_url: logo_url || null,
          industry: industry || null,
          size: size || null,
          location: location || null,
          description: description || null,
        })
        .select()
        .single()

      if (error) throw error

      // Link employer to profile
      const { error: linkErr } = await supabase
        .from('profiles')
        .update({ employer_id: created.id })
        .eq('id', user.id)

      if (linkErr) throw linkErr

      return NextResponse.json(created as EmployerProfile, { status: 201 })
    }
  } catch (error) {
    console.error('POST /api/employers/profile error:', error)
    return NextResponse.json(
      { error: 'Failed to create/update employer profile' },
      { status: 500 }
    )
  }
}

// PATCH /api/employers/profile — partial update to employer profile
export async function PATCH(req: NextRequest) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const body = await req.json()

    // Only allow updating specific fields
    const updates: any = {}
    const allowedFields = ['name', 'logo_url', 'industry', 'size', 'location', 'description']

    for (const field of allowedFields) {
      if (field in body) {
        updates[field] = body[field] || null
      }
    }

    if (Object.keys(updates).length === 0) {
      return NextResponse.json(
        { error: 'No valid fields to update' },
        { status: 400 }
      )
    }

    updates.updated_at = new Date().toISOString()

    const { data: updated, error } = await supabase
      .from('employers')
      .update(updates)
      .eq('owner_user_id', user.id)
      .select()
      .single()

    if (error && error.code === 'PGRST116') {
      return NextResponse.json(
        { error: 'Employer profile not found' },
        { status: 404 }
      )
    }

    if (error) throw error

    return NextResponse.json(updated as EmployerProfile)
  } catch (error) {
    console.error('PATCH /api/employers/profile error:', error)
    return NextResponse.json(
      { error: 'Failed to update employer profile' },
      { status: 500 }
    )
  }
}

// DELETE /api/employers/profile — soft delete (optional, not in Phase 1 spec)
export async function DELETE(req: NextRequest) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    // Unlink employer from profile
    const { error: unlinkErr } = await supabase
      .from('profiles')
      .update({ employer_id: null, user_type: 'candidate' })
      .eq('id', user.id)

    if (unlinkErr) throw unlinkErr

    // Delete employer profile (cascades to job_postings)
    const { error } = await supabase
      .from('employers')
      .delete()
      .eq('owner_user_id', user.id)

    if (error && error.code !== 'PGRST116') throw error

    return NextResponse.json({ success: true })
  } catch (error) {
    console.error('DELETE /api/employers/profile error:', error)
    return NextResponse.json(
      { error: 'Failed to delete employer profile' },
      { status: 500 }
    )
  }
}
