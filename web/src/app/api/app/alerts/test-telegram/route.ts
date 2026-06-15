import { NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'

export async function POST() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { data: profile } = await supabase
    .from('profiles')
    .select('telegram_chat_id, alert_telegram')
    .eq('id', user.id)
    .single()

  if (!profile?.alert_telegram) {
    return NextResponse.json(
      { error: 'Telegram alerts are not enabled. Check the box and save settings first.' },
      { status: 400 }
    )
  }
  if (!profile.telegram_chat_id) {
    return NextResponse.json(
      { error: 'No Telegram chat ID saved. Enter your numeric chat ID and save first.' },
      { status: 400 }
    )
  }

  const botToken = process.env.TELEGRAM_BOT_TOKEN
  if (!botToken) {
    return NextResponse.json(
      { error: 'TELEGRAM_BOT_TOKEN is not set on this server. Add it to your Vercel environment variables.' },
      { status: 500 }
    )
  }

  const resp = await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      chat_id: profile.telegram_chat_id,
      text: '✅ JobAlert test message — your Telegram alerts are working correctly.',
    }),
  })

  const tgData = await resp.json() as { ok: boolean; description?: string }

  if (!tgData.ok) {
    return NextResponse.json(
      { error: `Telegram API error: ${tgData.description ?? 'Unknown'}. Check your chat ID is correct.` },
      { status: 400 }
    )
  }

  return NextResponse.json({ ok: true })
}
