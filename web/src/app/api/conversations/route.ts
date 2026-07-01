import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'

export async function POST(req: NextRequest) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const body = await req.json() as {
      job_posting_id?: string | null
      recipient_id: string
      initiated_by: 'candidate' | 'employer'
    }

    const { job_posting_id, recipient_id, initiated_by } = body

    // Validate inputs
    if (!recipient_id) {
      return NextResponse.json(
        { error: 'recipient_id is required' },
        { status: 400 }
      )
    }

    if (initiated_by !== 'candidate' && initiated_by !== 'employer') {
      return NextResponse.json(
        { error: 'initiated_by must be "candidate" or "employer"' },
        { status: 400 }
      )
    }

    // Check if the initiator is trying to message themselves
    if (user.id === recipient_id) {
      return NextResponse.json(
        { error: 'Cannot message yourself' },
        { status: 400 }
      )
    }

    // Check if either party has blocked the other
    const admin = createAdminClient()
    const { data: blockerProfile } = await admin
      .from('profiles')
      .select('blocked_users')
      .eq('id', user.id)
      .single()

    const { data: recipientProfile } = await admin
      .from('profiles')
      .select('blocked_users')
      .eq('id', recipient_id)
      .single()

    if (
      blockerProfile?.blocked_users?.includes(recipient_id) ||
      recipientProfile?.blocked_users?.includes(user.id)
    ) {
      return NextResponse.json(
        { error: 'Cannot message this user (blocked)' },
        { status: 403 }
      )
    }

    // Determine who is candidate and who is employer based on initiated_by
    let candidate_id: string
    let employer_id: string

    if (initiated_by === 'candidate') {
      candidate_id = user.id
      employer_id = recipient_id
    } else {
      candidate_id = recipient_id
      employer_id = user.id
    }

    // Create or fetch existing conversation
    const { data: existingConversation } = await admin
      .from('conversations')
      .select('*')
      .eq('candidate_id', candidate_id)
      .eq('employer_id', employer_id)
      .eq('job_posting_id', job_posting_id || null)
      .single()

    if (existingConversation) {
      // Conversation already exists
      return NextResponse.json({
        id: existingConversation.id,
        candidate_id: existingConversation.candidate_id,
        employer_id: existingConversation.employer_id,
        job_posting_id: existingConversation.job_posting_id,
        initiated_by: existingConversation.initiated_by,
        created_at: existingConversation.created_at,
        updated_at: existingConversation.updated_at,
        isNew: false,
      })
    }

    // Create new conversation
    const { data: newConversation, error } = await admin
      .from('conversations')
      .insert({
        job_posting_id,
        candidate_id,
        employer_id,
        initiated_by,
      })
      .select()
      .single()

    if (error || !newConversation) {
      console.error('Error creating conversation:', error)
      return NextResponse.json(
        { error: 'Failed to create conversation' },
        { status: 500 }
      )
    }

    return NextResponse.json({
      id: newConversation.id,
      candidate_id: newConversation.candidate_id,
      employer_id: newConversation.employer_id,
      job_posting_id: newConversation.job_posting_id,
      initiated_by: newConversation.initiated_by,
      created_at: newConversation.created_at,
      updated_at: newConversation.updated_at,
      isNew: true,
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    console.error('POST /conversations error:', message)
    return NextResponse.json({ error: message }, { status: 500 })
  }
}

export async function GET(req: NextRequest) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const admin = createAdminClient()

    // Fetch conversations where user is either candidate or employer
    const { data: conversations, error } = await admin
      .from('conversations')
      .select(
        `
        id,
        job_posting_id,
        candidate_id,
        employer_id,
        initiated_by,
        created_at,
        updated_at,
        messages (
          id,
          content,
          sender_id,
          sent_at,
          read_at
        )
      `
      )
      .or(`candidate_id.eq.${user.id},employer_id.eq.${user.id}`)
      .order('updated_at', { ascending: false })

    if (error) {
      console.error('Error fetching conversations:', error)
      return NextResponse.json(
        { error: 'Failed to fetch conversations' },
        { status: 500 }
      )
    }

    // Fetch participant profiles for each conversation
    const conversationsWithProfiles = await Promise.all(
      conversations.map(async (conv) => {
        const { data: candidateProfile } = await admin
          .from('profiles')
          .select('id, display_name, email')
          .eq('id', conv.candidate_id)
          .single()

        const { data: employerProfile } = await admin
          .from('profiles')
          .select('id, display_name, email')
          .eq('id', conv.employer_id)
          .single()

        const otherParticipantId =
          user.id === conv.candidate_id ? conv.employer_id : conv.candidate_id
        const otherParticipantName =
          user.id === conv.candidate_id
            ? employerProfile?.display_name
            : candidateProfile?.display_name

        // Get last message
        const messages = conv.messages as any[]
        const lastMessage = messages?.[0]

        return {
          id: conv.id,
          job_posting_id: conv.job_posting_id,
          candidate_id: conv.candidate_id,
          employer_id: conv.employer_id,
          initiated_by: conv.initiated_by,
          created_at: conv.created_at,
          updated_at: conv.updated_at,
          otherParticipantId,
          otherParticipantName,
          lastMessage: lastMessage
            ? {
                content: lastMessage.content,
                senderName: lastMessage.sender_id === user.id ? 'You' : otherParticipantName,
                sentAt: lastMessage.sent_at,
              }
            : null,
          isCandidate: user.id === conv.candidate_id,
        }
      })
    )

    return NextResponse.json(conversationsWithProfiles)
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    console.error('GET /conversations error:', message)
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
