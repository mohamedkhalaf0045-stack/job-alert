import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'
import NavBar from '@/components/NavBar'
import ChatWidget from '@/components/ChatWidget'

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')

  // Redirect to onboarding if setup is incomplete
  const { data: prefs } = await supabase
    .from('user_preferences')
    .select('keywords, locations')
    .eq('user_id', user.id)
    .single()

  const hasKeywords = Array.isArray(prefs?.keywords) && prefs.keywords.length > 0
  const hasLocations = Array.isArray(prefs?.locations) && prefs.locations.length > 0
  if (!hasKeywords || !hasLocations) redirect('/onboarding')

  const isAdmin = user.email === process.env.ADMIN_EMAIL

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar email={user.email ?? ''} isAdmin={isAdmin} />
      <main className="max-w-3xl mx-auto px-4 py-8">{children}</main>
      <ChatWidget />
    </div>
  )
}
