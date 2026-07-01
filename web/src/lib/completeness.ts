// Phase 4: Profile completeness meter
// Calculates a % complete score + list of missing items for both
// candidate and HR (employer) profiles.

export interface CompletenessResult {
  percent: number
  completed: string[]
  missing: string[]
}

export interface CandidateCompletenessInput {
  hasCV: boolean
  hasKeywords: boolean
  hasLocations: boolean
  hasDisplayName: boolean
}

export interface HRCompletenessInput {
  hasName: boolean
  hasLogo: boolean
  hasIndustry: boolean
  hasDescription: boolean
  hasPublishedJob: boolean
}

function build(checks: { label: string; done: boolean }[]): CompletenessResult {
  const completed = checks.filter(c => c.done).map(c => c.label)
  const missing = checks.filter(c => !c.done).map(c => c.label)
  const percent = checks.length
    ? Math.round((completed.length / checks.length) * 100)
    : 0
  return { percent, completed, missing }
}

// Candidate: CV, keywords, locations, display name — 4 checks, 25% each.
export function calculateCandidateCompleteness(
  input: CandidateCompletenessInput
): CompletenessResult {
  return build([
    { label: 'Upload your CV', done: input.hasCV },
    { label: 'Add job keywords', done: input.hasKeywords },
    { label: 'Add preferred locations', done: input.hasLocations },
    { label: 'Set your display name', done: input.hasDisplayName },
  ])
}

// HR: company name, logo, industry, description, at least one published job — 5 checks, 20% each.
export function calculateHRCompleteness(
  input: HRCompletenessInput
): CompletenessResult {
  return build([
    { label: 'Add company name', done: input.hasName },
    { label: 'Upload a company logo', done: input.hasLogo },
    { label: 'Select an industry', done: input.hasIndustry },
    { label: 'Write a company description', done: input.hasDescription },
    { label: 'Publish at least one job posting', done: input.hasPublishedJob },
  ])
}

// Phase 5: trigger helper for the "Complete your profile" chatbot banner.
// Returns true when the profile is under the given threshold (default 50%),
// meaning the banner linking to the onboarding chatbot should be shown.
export function shouldShowOnboardingPrompt(
  result: CompletenessResult,
  thresholdPercent = 50
): boolean {
  return result.percent < thresholdPercent
}
