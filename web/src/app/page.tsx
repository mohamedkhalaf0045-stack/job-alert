import Link from 'next/link'

export default function LandingPage() {
  return (
    <main className="min-h-screen flex flex-col">
      <nav className="px-6 py-4 flex items-center justify-between border-b bg-white">
        <span className="font-bold text-lg tracking-tight">JobAlert</span>
        <div className="flex items-center gap-3">
          <Link href="/login" className="text-sm text-gray-600 hover:text-gray-900">
            Sign in
          </Link>
          <Link
            href="/signup"
            className="text-sm bg-blue-600 text-white px-4 py-1.5 rounded-lg hover:bg-blue-700 transition"
          >
            Get started
          </Link>
        </div>
      </nav>

      <section className="flex-1 flex flex-col items-center justify-center px-4 py-20 text-center">
        <h1 className="text-4xl font-bold mb-4 max-w-xl leading-tight">
          Job alerts tailored to{' '}
          <span className="text-blue-600">your skills</span>
        </h1>
        <p className="text-gray-500 mb-8 max-w-md">
          Set your keywords and locations once. Get daily or instant alerts for matching jobs scraped
          from LinkedIn, Indeed, and more — completely free.
        </p>
        <Link
          href="/signup"
          className="bg-blue-600 text-white px-6 py-3 rounded-lg text-base font-medium hover:bg-blue-700 transition"
        >
          Create free account →
        </Link>
      </section>

      <section className="bg-white border-t py-12 px-4">
        <div className="max-w-2xl mx-auto grid grid-cols-1 sm:grid-cols-3 gap-8 text-center">
          {[
            ['🔍', 'Smart matching', 'Keyword + location filters over a live job pool scraped every 5 minutes.'],
            ['📬', 'Daily or instant', 'Get a digest at 8 AM or an alert within 15 minutes of a new match.'],
            ['💼', 'Track applications', 'Save, apply, and dismiss jobs from your personal feed.'],
          ].map(([icon, title, desc]) => (
            <div key={title}>
              <div className="text-3xl mb-2">{icon}</div>
              <h3 className="font-semibold mb-1">{title}</h3>
              <p className="text-sm text-gray-500">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      <footer className="py-6 text-center text-xs text-gray-400 border-t">
        JobAlert — free for job seekers
      </footer>
    </main>
  )
}
