export type JobStatus = 'saved' | 'applied' | 'dismissed' | 'hidden'

export interface Job {
  job_id: string
  title: string
  company: string
  location: string
  url: string
  source: string
  date_posted: string | null
  date_collected: string
  llm_score: number | null
  llm_summary: string | null
  matched_skills: string[] | null
  salary_min: number | null
  salary_max: number | null
  salary_avg: number | null
  salary_currency: string | null
  salary_period: string | null
  salary_source: string | null
  my_status: JobStatus | null
}

export interface JobDetail extends Job {
  description:        string | null
  missing_skills:     string[] | null
  red_flags:          string[] | null
  cover_letter_draft: string | null
}

export interface UserPreferences {
  user_id: string
  keywords: string[]
  locations: string[]
  exclude_keywords: string[]
  min_score: number | null
  alert_frequency: 'instant' | 'daily' | 'off'
  digest_hour: number
  paused: boolean
}

export interface Profile {
  id: string
  display_name: string | null
  email: string | null
  timezone: string
  telegram_chat_id: string | null
  alert_email: boolean
  alert_telegram: boolean
}
