import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'

export async function PUT(
  req: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const userIdToBlock = params.id
    const body = await req.json() as { action: 'block' | 'unblock' }
    const { action } = body

    if (!action || !['block', 'unblock'].includes(action)) {
      return NextResponse.json(
        { error: 'action must be "block" or "unblock"' },
        { status: 400 }
      )
    }

    if (user.id === userIdToBlock) {
      return NextResponse.json(
        { error: 'Cannot block yourself' },
        { status: 400 }
      )
    }

    const admin = createAdminClient()

    // Get current profile
    const { data: profile, error: fetchError } = await admin
      .from('profiles')
      .select('blocked_users')
      .eq('id', user.id)
      .single()

    if (fetchError || !profile) {
      return NextResponse.json(
        { error: 'Profile not found' },
        { status: 404 }
      )
    }

    const blockedUsers = (profile.blocked_users || []) as string[]

    let updatedBlockedUsers: string[]

    if (action === 'block') {
      // Add to blocked list if not already there
      if (!blockedUsers.includes(userIdToBlock)) {
        updatedBlockedUsers = [...blockedUsers, userIdToBlock]
      } else {
        updatedBlockedUsers = blockedUsers
      }
    } else {
      // Remove from blocked list
      updatedBlockedUsers = blockedUsers.filter((id: string) => id !== userIdToBlock)
    }

    // Update profile
    const { error: updateError } = await admin
      .from('profiles')
      .update({ blocked_users: updatedBlockedUsers })
      .eq('id', user.id)

    if (updateError) {
      console.error('Error updating blocked_users:', updateError)
      return NextResponse.json(
        { error: 'Failed to update blocked users list' },
        { status: 500 }
      )
    }

    return NextResponse.json({
      success: true,
      action,
      blocked_users: updatedBlockedUsers,
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    console.error('PUT /users/[id]/block error:', message)
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
