import { createServerClient, type CookieOptions } from '@supabase/ssr'
import { NextResponse, type NextRequest } from 'next/server'

export async function middleware(request: NextRequest) {
  let supabaseResponse = NextResponse.next({ request })

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() { return request.cookies.getAll() },
        setAll(cookiesToSet: { name: string; value: string; options?: CookieOptions }[]) {
          cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value))
          supabaseResponse = NextResponse.next({ request })
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options as Parameters<typeof supabaseResponse.cookies.set>[2])
          )
        },
      },
    }
  )

  // Refresh session — required by @supabase/ssr
  const { data: { user } } = await supabase.auth.getUser()

  const path = request.nextUrl.pathname

  // Unauthenticated users trying to reach /app/** → login
  if (!user && path.startsWith('/app')) {
    return NextResponse.redirect(new URL('/login', request.url))
  }

  // Already logged-in users hitting /login or /signup → feed
  if (user && (path === '/login' || path === '/signup')) {
    return NextResponse.redirect(new URL('/app/feed', request.url))
  }

  // Logged-in but unconfirmed users trying to reach onboarding or the app →
  // block until they confirm their email (mirrors mobile app enforcement).
  const isProtected = path.startsWith('/app') || path === '/onboarding'
  if (user && !user.email_confirmed_at && isProtected) {
    return NextResponse.redirect(new URL('/confirm-email', request.url))
  }

  return supabaseResponse
}

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
}
