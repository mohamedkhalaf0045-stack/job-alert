'use client'

import { useState } from 'react'
import AdminForm from './AdminForm'
import AdminUsers from './AdminUsers'
import RecommendedSettings from './RecommendedSettings'

type Tab = 'scraper' | 'users' | 'recommended'

interface Props {
  scraperState: Record<string, string>
  recommendedKeywords: string[]
  recommendedLocations: string[]
}

const TAB_LABELS: { key: Tab; label: string }[] = [
  { key: 'scraper',     label: 'Scraper Settings' },
  { key: 'users',       label: 'Users' },
  { key: 'recommended', label: 'Recommended Settings' },
]

export default function AdminTabs({ scraperState, recommendedKeywords, recommendedLocations }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('scraper')

  return (
    <div>
      {/* Tab bar */}
      <div className="flex gap-1 border-b border-gray-200 mb-6">
        {TAB_LABELS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              activeTab === key
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {activeTab === 'scraper' && <AdminForm state={scraperState} />}
      {activeTab === 'users' && <AdminUsers />}
      {activeTab === 'recommended' && (
        <RecommendedSettings
          initialKeywords={recommendedKeywords}
          initialLocations={recommendedLocations}
        />
      )}
    </div>
  )
}
