export interface LocationGroup {
  label: string
  flag: string
  // All location strings stored in locations[] — RPC does ILIKE '%x%' on each
  locations: string[]
}

export const LOCATION_GROUPS: Record<string, LocationGroup> = {
  uae: {
    label: 'United Arab Emirates',
    flag: '🇦🇪',
    locations: [
      'United Arab Emirates',
      'UAE',
      'Dubai',
      'Abu Dhabi',
      'Sharjah',
      'Ajman',
      'Ras Al Khaimah',
      'Fujairah',
      'Umm Al Quwain',
    ],
  },
  egypt: {
    label: 'Egypt',
    flag: '🇪🇬',
    locations: ['Egypt', 'Cairo', 'Alexandria', 'Giza'],
  },
  saudi: {
    label: 'Saudi Arabia',
    flag: '🇸🇦',
    locations: ['Saudi Arabia', 'Riyadh', 'Jeddah', 'Dammam', 'Mecca', 'Medina'],
  },
  qatar: {
    label: 'Qatar',
    flag: '🇶🇦',
    locations: ['Qatar', 'Doha'],
  },
  kuwait: {
    label: 'Kuwait',
    flag: '🇰🇼',
    locations: ['Kuwait', 'Kuwait City'],
  },
  bahrain: {
    label: 'Bahrain',
    flag: '🇧🇭',
    locations: ['Bahrain', 'Manama'],
  },
  oman: {
    label: 'Oman',
    flag: '🇴🇲',
    locations: ['Oman', 'Muscat'],
  },
  jordan: {
    label: 'Jordan',
    flag: '🇯🇴',
    locations: ['Jordan', 'Amman'],
  },
}

/** Given a locations[] array, return which group keys are fully active */
export function getActiveGroups(locations: string[]): string[] {
  const locSet = new Set(locations)
  return Object.entries(LOCATION_GROUPS)
    .filter(([, g]) => g.locations.every(l => locSet.has(l)))
    .map(([k]) => k)
}

/** Toggle a group on/off in a locations array */
export function toggleLocationGroup(current: string[], groupKey: string): string[] {
  const group = LOCATION_GROUPS[groupKey]
  if (!group) return current
  const activeGroups = getActiveGroups(current)
  if (activeGroups.includes(groupKey)) {
    // Remove all group locations
    const remove = new Set(group.locations)
    return current.filter(l => !remove.has(l))
  } else {
    // Add all group locations (deduplicated)
    const existing = new Set(current)
    return [...current, ...group.locations.filter(l => !existing.has(l))]
  }
}
