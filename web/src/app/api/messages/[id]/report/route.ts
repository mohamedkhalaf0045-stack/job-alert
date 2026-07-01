import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'

export async function POST(
  req: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const messageId = params.id
    const body = await req.json() as { reason: string }
    const { reason } = body

    if (!reason || reason.trim().length === 0) {
      return NextResponse.json(
        { error: 'Report reason is required' },
        { status: 400 }
      )
    }

    if (reason.length > 500) {
      return NextResponse.json(
        { error: 'Reason too long (max 500 characters)' },
        { status: 400 }
      )
    }

    const admin = createAdminClient()

    // Verify message exists
    const { data: message, error: msgError } = await admin
      .from('messages')
      .select('id, conversation_id')
      .eq('id', messageId)
      .single()

    if (msgError || !message) {
      return NextResponse.json(
        { error: 'Message not found' },
        { status: 404 }
      )
    }

    // Verify user is a participant in the conversation
    const { data: conversation, error: convError } = await admin
      .from('conversations')
      .select('candidate_id, employer_id')
      .eq('id', message.conversation_id)
      .single()

    if (convError || !conversation) {
      return NextResponse.json(
        { error: 'Conversation not found' },
        { status: 404 }
      )
    }

    const isParticipant =
      user.id === conversation.candidate_id || user.id === conversation.employer_id
    if (!isParticipant) {
      return NextResponse.json(
        { error: 'Not a participant in this conversation' },
        { status: 403 }
      )
    }

    // Check if this user has already reported this message
    const { data: existingReport, error: checkError } = await admin
      .from('message_reports')
      .select('id')
      .eq('message_id', messageId)
      .eq('reporter_id', user.id)
      .single()

    if (!checkError && existingReport) {
      return NextResponse.json(
        { error: 'You have already reported this message' },
        { status: 400 }
      )
    }

    // Create the report
    const { data: report, error: createError } = await admin
      .from('message_reports')
      .insert({
        message_id: messageId,
        reporter_id: user.id,
        reason,
      })
      .select()
      .single()

    if (createError || !report) {
      console.error('Error creating report:', createError)
      return NextResponse.json(
        { error: 'Failed to create report' },
        { status: 500 }
      )
    }

    return NextResponse.json({
      id: report.id,
      message_id: report.message_id,
      reporter_id: report.reporter_id,
      reason: report.reason,
      reported_at: report.reported_at,
      resolved: report.resolved,
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    console.error('POST /messages/[id]/report error:', message)
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
