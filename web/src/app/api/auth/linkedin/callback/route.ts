import { NextRequest, NextResponse } from 'next/server'

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const code  = searchParams.get('code')
  const state = searchParams.get('state')
  const error = searchParams.get('error')

  const appUrl       = `${req.nextUrl.protocol}//${req.nextUrl.host}`
  const onboardingUrl = `${appUrl}/onboarding`

  if (error) {
    return NextResponse.redirect(`${onboardingUrl}?li_error=denied`)
  }

  const storedState = req.cookies.get('li_oauth_state')?.value
  if (!state || state !== storedState) {
    return NextResponse.redirect(`${onboardingUrl}?li_error=state`)
  }

  if (!code) {
    return NextResponse.redirect(`${onboardingUrl}?li_error=no_code`)
  }

  // Exchange code for access token
  const tokenRes = await fetch('https://www.linkedin.com/oauth/v2/accessToken', {
    method:  'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body:    new URLSearchParams({
      grant_type:    'authorization_code',
      code,
      redirect_uri:  `${appUrl}/api/auth/linkedin/callback`,
      client_id:     process.env.LINKEDIN_CLIENT_ID!,
      client_secret: process.env.LINKEDIN_CLIENT_SECRET!,
    }),
  })

  if (!tokenRes.ok) {
    return NextResponse.redirect(`${onboardingUrl}?li_error=token`)
  }

  const { access_token } = await tokenRes.json() as { access_token: string }

  // Fetch OpenID Connect userinfo + try headline from /v2/me
  const [userinfoRes, meRes] = await Promise.allSettled([
    fetch('https://api.linkedin.com/v2/userinfo', {
      headers: { Authorization: `Bearer ${access_token}` },
    }),
    fetch('https://api.linkedin.com/v2/me?projection=(id,localizedHeadline)', {
      headers: {
        Authorization:              `Bearer ${access_token}`,
        'X-Restli-Protocol-Version': '2.0.0',
      },
    }),
  ])

  const userinfo = userinfoRes.status === 'fulfilled' && userinfoRes.value.ok
    ? await userinfoRes.value.json() as Record<string, string>
    : {} as Record<string, string>

  const me = meRes.status === 'fulfilled' && meRes.value.ok
    ? await meRes.value.json() as Record<string, string>
    : {} as Record<string, string>

  const name     = userinfo.name ?? `${userinfo.given_name ?? ''} ${userinfo.family_name ?? ''}`.trim()
  const headline = me.localizedHeadline ?? ''
  const jobTitle = headline ? headline.split(' at ')[0].trim() : ''

  const profile = Buffer.from(
    JSON.stringify({ name, headline, jobTitle })
  ).toString('base64')

  const res = NextResponse.redirect(`${onboardingUrl}?li_data=${encodeURIComponent(profile)}`)
  res.cookies.set('li_oauth_state', '', { maxAge: 0, path: '/' })
  return res
}
