import { NextRequest, NextResponse } from 'next/server'
import { waitUntil } from '@vercel/functions'
import Groq from 'groq-sdk'
import { createAdminClient } from '@/lib/supabase/admin'

const MAX_HISTORY = 20

async function sendTg(chatId: number, text: string) {
  const token = process.env.TELEGRAM_BOT_TOKEN!
  const chunks: string[] = []
  for (let i = 0; i < text.length; i += 4000) chunks.push(text.slice(i, i + 4000))
  for (const chunk of chunks) {
    await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: chatId, text: chunk }),
    })
  }
}

async function processMessage(chatId: number, userText: string) {
  const db = createAdminClient()
  const groq = new Groq({ apiKey: process.env.GROQ_API_KEY })

  if (userText.trim() === '/clear') {
    await db.from('telegram_claude_history').delete().eq('chat_id', chatId)
    await sendTg(chatId, 'Conversation cleared.')
    return
  }

  // Load recent history (newest first → reverse for chronological order)
  const { data: rows } = await db
    .from('telegram_claude_history')
    .select('role, content')
    .eq('chat_id', chatId)
    .order('created_at', { ascending: false })
    .limit(MAX_HISTORY)

  const history = (rows ?? []).reverse()

  const messages: Groq.Chat.ChatCompletionMessageParam[] = [
    ...history.map(r => ({
      role: r.role as 'user' | 'assistant',
      content: r.content,
    })),
    { role: 'user', content: userText },
  ]

  let reply: string
  try {
    const response = await groq.chat.completions.create({
      model: 'llama-3.3-70b-versatile',
      max_tokens: 2048,
      messages: [
        {
          role: 'system',
          content:
            'You are a job search assistant accessed via Telegram. ' +
            'The conversation history includes job alerts that were sent to the user — each alert lists job title, company, score, and URL. ' +
            'When the user asks about a job or company, refer to those alerts. ' +
            'You can help with: explaining job requirements, researching companies, writing cover letters, interview preparation, and career advice. ' +
            'Keep replies concise and clear. Use plain text — avoid markdown tables or heavy formatting.',
        },
        ...messages,
      ],
    })
    reply = response.choices[0]?.message?.content ?? '(empty response)'
  } catch (err) {
    reply = `Error: ${(err as Error).message}`
  }

  // Persist both turns
  await db.from('telegram_claude_history').insert([
    { chat_id: chatId, role: 'user',      content: userText },
    { chat_id: chatId, role: 'assistant', content: reply },
  ])

  // Trim old messages
  const { data: all } = await db
    .from('telegram_claude_history')
    .select('id')
    .eq('chat_id', chatId)
    .order('created_at', { ascending: false })
  if (all && all.length > MAX_HISTORY * 2) {
    const toDelete = all.slice(MAX_HISTORY * 2).map(r => r.id)
    await db.from('telegram_claude_history').delete().in('id', toDelete)
  }

  await sendTg(chatId, reply)
}

export async function POST(req: NextRequest) {
  const body = await req.json()
  const message = body?.message
  if (!message?.text) return NextResponse.json({ ok: true })

  const chatId: number = message.chat?.id
  const text: string   = message.text

  const allowed = process.env.TELEGRAM_ALLOWED_CHAT_ID
  if (allowed && chatId?.toString() !== allowed) {
    return NextResponse.json({ ok: true })
  }

  waitUntil(processMessage(chatId, text))
  return NextResponse.json({ ok: true })
}
