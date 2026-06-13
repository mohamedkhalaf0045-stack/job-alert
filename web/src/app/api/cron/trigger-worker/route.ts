import { NextRequest, NextResponse } from 'next/server'

const OWNER    = 'mohamedkhalaf0045-stack'
const REPO     = 'job-alert'
const WORKFLOW = 'job-alert.yml'

export async function GET(req: NextRequest) {
  // Simple secret check so random crawlers can't spam workflow dispatches
  const secret = req.nextUrl.searchParams.get('secret')
  if (secret !== process.env.CRON_SECRET) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 })
  }

  const token = process.env.GH_PAT
  if (!token) {
    return NextResponse.json({ error: 'GH_PAT not set' }, { status: 500 })
  }

  const res = await fetch(
    `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        Accept:        'application/vnd.github+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ ref: 'main' }),
    }
  )

  if (res.status === 204) {
    return NextResponse.json({ ok: true, triggered: true, ts: Date.now() })
  }
  const body = await res.text()
  return NextResponse.json({ ok: false, status: res.status, body, ts: Date.now() }, { status: 500 })
}
