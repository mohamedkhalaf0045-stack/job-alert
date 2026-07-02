'use client'

import { useState } from 'react'
import { LOCATION_GROUPS, getActiveGroups, toggleLocationGroup } from '@/config/location-groups'

interface Props {
  value: string[]
  onChange: (locs: string[]) => void
  /** Extra plain-text location input placeholder */
  placeholder?: string
}

export default function LocationGroupPicker({ value, onChange, placeholder }: Props) {
  const [customInput, setCustomInput] = useState('')
  const [expanded,    setExpanded]    = useState<string | null>(null)

  const activeGroups = getActiveGroups(value)

  function handleGroupClick(key: string) {
    onChange(toggleLocationGroup(value, key))
  }

  function handleCustomKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      const t = customInput.trim()
      if (t && !value.includes(t)) onChange([...value, t])
      setCustomInput('')
    }
  }

  function removeCustom(loc: string) {
    onChange(value.filter(l => l !== loc))
  }

  // Locations not belonging to any group (manually typed)
  const groupedLocs = new Set(
    Object.values(LOCATION_GROUPS).flatMap(g => g.locations)
  )
  const customLocs = value.filter(l => !groupedLocs.has(l))

  return (
    <div className="space-y-3">
      {/* Country group pills */}
      <div className="flex flex-wrap gap-2">
        {Object.entries(LOCATION_GROUPS).map(([key, group]) => {
          const active = activeGroups.includes(key)
          return (
            <div key={key} className="relative">
              <button
                type="button"
                onClick={() => handleGroupClick(key)}
                onMouseEnter={() => setExpanded(key)}
                onMouseLeave={() => setExpanded(null)}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium border transition-colors ${
                  active
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'border-gray-200 text-gray-600 hover:border-blue-300 hover:text-blue-600'
                }`}
              >
                <span>{group.flag}</span>
                <span>{group.label}</span>
                {active && <span className="ml-0.5 text-xs opacity-80">✓</span>}
              </button>

              {/* Hover tooltip showing included cities */}
              {expanded === key && (
                <div className="absolute z-10 top-full left-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-md p-2 min-w-max">
                  <p className="text-xs font-medium text-gray-500 mb-1">Includes:</p>
                  <div className="flex flex-wrap gap-1">
                    {group.locations.map(loc => (
                      <span key={loc} className="text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded-full">
                        {loc}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Active group breakdown */}
      {activeGroups.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {activeGroups.flatMap(key => LOCATION_GROUPS[key].locations).map(loc => (
            <span key={loc} className="text-xs px-2 py-0.5 bg-blue-50 text-blue-600 rounded-full border border-blue-100">
              {loc}
            </span>
          ))}
        </div>
      )}

      {/* Custom location input */}
      <div>
        <input
          value={customInput}
          onChange={e => setCustomInput(e.target.value)}
          onKeyDown={handleCustomKeyDown}
          placeholder={placeholder ?? 'Other city or country… (press Enter to add)'}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <p className="text-xs text-gray-400 mt-1">Or type any city / country and press Enter</p>
      </div>

      {/* Custom (non-group) locations */}
      {customLocs.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {customLocs.map(loc => (
            <span key={loc} className="inline-flex items-center gap-1 px-3 py-1 bg-gray-100 text-gray-700 rounded-full text-xs font-medium">
              {loc}
              <button type="button" onClick={() => removeCustom(loc)} className="text-gray-400 hover:text-gray-600 ml-0.5">×</button>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
