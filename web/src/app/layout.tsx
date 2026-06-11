import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'JobAlert — Personalised job matches',
  description: 'Set your keywords and locations once. Get alerted for every matching job.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  )
}
