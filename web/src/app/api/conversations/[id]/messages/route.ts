import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'
import { createAdminClient } from '@/lib/supabase/admin'
import { checkMessageRateLimit } from '@/lib/redis'

export async function POST(
  req: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const conversationId = params.id
    const body = await req.json() as { content: string }
    const { content } = body

    if (!content || content.trim().length === 0) {
      return NextResponse.json(
        { error: 'Message content is required' },
        { status: 400 }
      )
    }

    if (content.length > 5000) {
      return NextResponse.json(
        { error: 'Message too long (max 5000 characters)' },
        { status: 400 }
      )
    }

    // Rate limit check
    const rateLimitResult = await checkMessageRateLimit(user.id)
    if (!rateLimitResult.allowed) {
      return NextResponse.json(
        {
          error: 'Rate limit exceeded. Please wait before sending another message.',
          retryAfter: Math.ceil((rateLimitResult.resetAt - Date.now()) / 1000),
        },
        { status: 429 }
      )
    }

    const admin = createAdminClient()

    // Verify user is a participant in this conversation
    const { data: conversation, error: convError } = await admin
      .from('conversations')
      .select('id, candidate_id, employer_id')
      .eq('id', conversationId)
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

    // Check if the recipient has blocked the sender
    const otherParticipantId =
      user.id === conversation.candidate_id
        ? conversation.employer_id
        : conversation.candidate_id

    const { data: recipientProfile } = await admin
      .from('profiles')
      .select('blocked_users')
      .eq('id', otherParticipantId)
      .single()

    if (recipientProfile?.blocked_users?.includes(user.id)) {
      return NextResponse.json(
        { error: 'You cannot message this user (you are blocked)' },
        { status: 403 }
      )
    }

    // Create the message
    const { data: message, error: msgError } = await admin
      .from('messages')
      .insert({
        conversation_id: conversationId,
        sender_id: user.id,
        content,
      })
      .select()
      .single()

    if (msgError || !message) {
      console.error('Error creating message:', msgError)
      return NextResponse.json(
        { error: 'Failed to create message' },
        { status: 500 }
      )
    }

    // Update conversation updated_at timestamp
    await admin
      .from('conversations')
      .update({ updated_at: new Date().toISOString() })
      .eq('id', conversationId)

    return NextResponse.json({
      id: message.id,
      conversation_id: message.conversation_id,
      sender_id: message.sender_id,
      content: message.content,
      sent_at: message.sent_at,
      read_at: message.read_at,
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    console.error('POST /conversations/[id]/messages error:', message)
    return NextResponse.json({ error: message }, { status: 500 })
  }
}

export async function GET(
  req: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const conversationId = params.id
    const url = new URL(req.url)
    const limit = parseInt(url.searchParams.get('limit') || '50')
    const offset = parseInt(url.searchParams.get('offset') || '0')

    const admin = createAdminClient()

    // Verify user is a participant in this conversation
    const { data: conversation, error: convError } = await admin
      .from('conversations')
      .select('id, candidate_id, employer_id')
      .eq('id', conversationId)
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

    // Fetch messages (paginated, most recent first)
    const { data: messages, error: msgError } = await admin
      .from('messages')
      .select('*')
      .eq('conversation_id', conversationId)
      .order('sent_at', { ascending: false })
      .range(offset, offset + limit - 1)

    if (msgError) {
      console.error('Error fetching messages:', msgError)
      return NextResponse.json(
        { error: 'Failed to fetch messages' },
        { status: 500 }
      )
    }

    // Mark unread messages from the other participant as read
    const otherParticipantId =
      user.id === conversation.candidate_id
        ? conversation.employer_id
        : conversation.candidate_id

    const unreadMessages = (messages || []).filter(
      (m) => m.sender_id !== user.id && !m.read_at
    )

    if (unreadMessages.length > 0) {
      await admin
        .from('messages')
        .update({ read_at: new Date().toISOString() })
        .in('id', unreadMessages.map((m) => m.id))
    }

    // Return messages in chronological order (flip the reversed list)
    const reversedMessages = (messages || []).reverse()

    return NextResponse.json({
      messages: reversedMessages,
      hasMore: reversedMessages.length === limit,
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    console.error('GET /conversations/[id]/messages error:', message)
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
