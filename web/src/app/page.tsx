import Link from 'next/link'

export default function LandingPage() {
  return (
    <main className="min-h-screen flex flex-col bg-[var(--bg)]">
      {/* Nav */}
      <nav className="px-6 py-4 flex items-center justify-between bg-white border-b border-[var(--border)]">
        <div className="flex items-center gap-2">
          <span className="w-7 h-7 rounded-md bg-[var(--accent)] text-white text-[11px] font-bold flex items-center justify-center select-none leading-none">
            J
          </span>
          <span className="font-semibold text-[var(--fg)] tracking-tight">JobAlert</span>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/login"
            className="text-sm text-[var(--muted)] hover:text-[var(--fg)] px-3 py-1.5 rounded-md hover:bg-[var(--border-soft)] transition-colors"
          >
            Sign in
          </Link>
          <Link
            href="/signup"
            className="text-sm bg-[var(--accent)] text-[var(--accent-on)] px-4 py-1.5 rounded-lg hover:bg-[var(--accent-hover)] transition-colors font-medium"
          >
            Get started →
          </Link>
        </div>
      </nav>

      {/* Hero */}
      <section className="flex-1 flex flex-col items-center justify-center px-4 py-24 text-center">
        <div className="inline-flex items-center gap-2 text-xs font-medium text-[var(--accent)] bg-[var(--accent-bg)] rounded-pill px-3 py-1 mb-6">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)] animate-pulse" />
          Scraped every 5 minutes
        </div>

        <h1 className="text-5xl font-bold mb-5 max-w-xl leading-[1.1] tracking-tight text-[var(--fg)]">
          Job alerts tailored to{' '}
          <span className="text-[var(--accent)]">your skills</span>
        </h1>

        <p className="text-[var(--muted)] mb-10 max-w-md text-base leading-relaxed">
          Set your keywords and locations once. Get daily or instant alerts for matching jobs
          scraped from LinkedIn, Indeed, and more — completely free.
        </p>

        <div className="flex items-center gap-3">
          <Link
            href="/signup"
            className="bg-[var(--accent)] text-[var(--accent-on)] px-6 py-3 rounded-lg text-sm font-semibold hover:bg-[var(--accent-hover)] transition-colors shadow-sm"
          >
            Create free account
          </Link>
          <Link
            href="/login"
            className="px-6 py-3 rounded-lg text-sm font-semibold text-[var(--fg-2)] border border-[var(--border)] bg-white hover:bg-[var(--border-soft)] transition-colors"
          >
            Sign in
          </Link>
        </div>
      </section>

      {/* Features */}
      <section className="bg-white border-t border-[var(--border)] py-14 px-4">
        <div className="max-w-2xl mx-auto grid grid-cols-1 sm:grid-cols-3 gap-10 text-center">
          {[
            ['🔍', 'Smart matching', 'Keyword + location filters over a live job pool scraped every 5 minutes.'],
            ['📬', 'Daily or instant', 'Get a digest at 8 AM or an alert within 15 minutes of a new match.'],
            ['💼', 'Track applications', 'Save, apply, and dismiss jobs from your personal feed.'],
          ].map(([icon, title, desc]) => (
            <div key={title as string}>
              <div className="text-2xl mb-3">{icon}</div>
              <h3 className="font-semibold text-[var(--fg)] mb-1.5 text-sm">{title}</h3>
              <p className="text-xs text-[var(--muted)] leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      <footer className="py-5 text-center text-xs text-[var(--meta)] border-t border-[var(--border)]">
        JobAlert — free for job seekers
      </footer>
    </main>
  )
}
