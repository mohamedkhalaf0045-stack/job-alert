import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'
import NavBar from '@/components/NavBar'

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')

  const isAdmin = user.email === process.env.ADMIN_EMAIL

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar email={user.email ?? ''} isAdmin={isAdmin} />
      <main className="max-w-3xl mx-auto px-4 py-8">{children}</main>
    </div>
  )
}
