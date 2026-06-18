import { NextRequest, NextResponse } from 'next/server'
import { randomBytes } from 'crypto'

export async function GET(req: NextRequest) {
  const state  = randomBytes(16).toString('hex')
  const appUrl = `${req.nextUrl.protocol}//${req.nextUrl.host}`

  const params = new URLSearchParams({
    response_type: 'code',
    client_id:     process.env.LINKEDIN_CLIENT_ID!,
    redirect_uri:  `${appUrl}/api/auth/linkedin/callback`,
    scope:         'openid profile email',
    state,
  })

  const res = NextResponse.redirect(
    `https://www.linkedin.com/oauth/v2/authorization?${params}`
  )
  res.cookies.set('li_oauth_state', state, {
    httpOnly: true,
    secure:   process.env.NODE_ENV === 'production',
    maxAge:   600,
    path:     '/',
    sameSite: 'lax',
  })
  return res
}
