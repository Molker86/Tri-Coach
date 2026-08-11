export type Discipline = 'run' | 'swim' | 'bike' | 'triathlon'
export type Sport = 'run' | 'bike' | 'swim' | 'strength' | 'mobility' | 'brick' | 'rest'
export type Weekday =
  | 'monday' | 'tuesday' | 'wednesday' | 'thursday'
  | 'friday' | 'saturday' | 'sunday'

export interface User {
  id: number
  email: string
  username: string
  created_at: string
}

export interface AuthResponse {
  access_token: string
  token_type: string
  user: User
}

export interface HrZone {
  zone: string
  label: string
  low_bpm: number
  high_bpm: number
  basis: string
  estimated_max_hr: boolean
}

export interface Profile {
  birth_date: string | null
  sex: 'female' | 'male' | 'diverse' | 'none' | null
  height_cm: number | null
  weight_kg: number | null
  body_fat_pct: number | null

  resting_hr: number | null
  max_hr: number | null
  lthr: number | null
  vo2max: number | null
  hrv_rmssd: number | null

  ftp_watts: number | null
  threshold_pace_run: string | null
  css_swim: string | null

  experience_years: number | null
  current_weekly_hours: number | null
  sleep_hours: number | null
  stress_level: number | null
  injuries: string | null
  personal_bests: string | null
  notes: string | null

  updated_at: string | null
  age: number | null
  bmi: number | null
  hr_zones: HrZone[]
}

export interface ProfileHistoryEntry {
  recorded_at: string
  weight_kg: number | null
  resting_hr: number | null
  hrv_rmssd: number | null
  vo2max: number | null
  max_hr: number | null
  ftp_watts: number | null
}

export interface TrainingRequest {
  id: number
  created_at: string
  discipline: Discipline
  goal_type: string | null
  goal_text: string | null
  race_date: string | null
  race_distance: string | null
  available_days: Weekday[]
  day_sport_map: Record<string, Sport[]>
  day_time_budget: Record<string, number>
  long_session_day: string | null
  weekly_hours_target: number | null
  supplemental: string[]
  equipment: string[]
  free_text: Record<string, string>
}

export type TrainingRequestInput = Omit<TrainingRequest, 'id' | 'created_at'>

export interface PlanSession {
  id: number
  date: string
  week_number: number
  order_in_day: number
  sport: Sport
  session_type: string
  title: string
  description: string | null
  structure: string | null
  purpose: string | null
  duration_min: number | null
  distance_km: number | null
  intensity_zone: string | null
  target_hr_low: number | null
  target_hr_high: number | null
  target_pace: string | null
  target_power: string | null
  rpe_target: number | null
  logged: boolean
}

export interface Plan {
  id: number
  title: string
  summary: string | null
  coaching_notes: string | null
  start_date: string
  end_date: string
  is_active: boolean
  created_at: string
  sessions: PlanSession[]
}

export interface PlanSummary {
  id: number
  title: string
  start_date: string
  end_date: string
  is_active: boolean
  created_at: string
  session_count: number
}

export interface PlanImportResult {
  plan: Plan
  warnings: string[]
}

export interface SessionLog {
  id: number
  created_at: string
  plan_session_id: number | null
  date: string
  sport: Sport
  status: 'completed' | 'partial' | 'skipped'

  duration_min: number | null
  distance_km: number | null
  avg_hr: number | null
  max_hr: number | null
  avg_pace: string | null
  avg_power: number | null
  avg_cadence: number | null
  elevation_gain_m: number | null
  calories: number | null

  rpe: number | null
  feeling: number | null
  soreness: number | null
  sleep_hours: number | null
  sleep_quality: number | null
  morning_hr: number | null
  morning_hrv: number | null

  conditions: string | null
  notes: string | null
  trimp: number | null
}

export type SessionLogInput = Omit<SessionLog, 'id' | 'created_at' | 'trimp'>

export interface WeeklyBucket {
  week_start: string
  week_end: string
  sessions: number
  total_minutes: number
  total_km: number
  avg_rpe: number | null
  total_srpe_load: number | null
  skipped: number
  by_sport: Record<string, { sessions: number; minutes: number; km: number }>
}

export interface Stats {
  weekly: WeeklyBucket[]
  acwr: number | null
  compliance: { planned_past: number; logged: number; rate_pct: number | null } | null
  total_sessions: number
  total_minutes: number
  total_km: number
}

export interface AiExport {
  prompt: string
  payload: Record<string, unknown>
  combined: string
}
