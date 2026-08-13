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

/** Eintrag der Kontoauswahl auf der Anmeldeseite. */
export interface UserOption {
  id: number
  username: string
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

  /** Herkunft des Eintrags. Garmin-Einträge werden in der Oberfläche markiert. */
  source: 'manual' | 'garmin'
  garmin_activity_id: string | null
  garmin_activity_type: string | null
  garmin_training_load: number | null
  garmin_aerobic_te: number | null
  garmin_anaerobic_te: number | null
  /** Woher `rpe` stammt — bei Garmin-Einheiten ist es geschätzt. */
  rpe_source: 'manual' | 'hf_zonen' | 'trainingseffekt' | 'hf_schnitt'
}

/** Was ein Formular schicken darf.
 *
 * Die Garmin-Felder fehlen bewusst: Das Backend nimmt sie beim Speichern nicht
 * entgegen (`SessionLogIn`), damit ein Bearbeiten die Herkunft nicht löscht.
 */
export type SessionLogInput = Omit<
  SessionLog,
  | 'id' | 'created_at' | 'trimp'
  | 'source' | 'garmin_activity_id' | 'garmin_activity_type'
  | 'garmin_training_load' | 'garmin_aerobic_te' | 'garmin_anaerobic_te'
  | 'rpe_source'
>

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

// --------------------------------------------------------------------------
// Garmin Connect
// --------------------------------------------------------------------------

export type GarminStatusName = 'connected' | 'token_expired' | 'rate_limited' | 'error'

export interface GarminAccount {
  email: string
  status: GarminStatusName
  status_message: string | null
  connected_at: string
  last_sync_at: string | null
  backfill_from: string | null
  rate_limited_until: string | null
  auto_sync_enabled: boolean
  profile_sync_enabled: boolean
}

export type GarminJobState =
  | 'queued' | 'running' | 'done' | 'failed'
  | 'cancelled' | 'rate_limited' | 'interrupted'

export interface GarminJob {
  id: number
  kind: 'backfill' | 'incremental' | 'auto' | 'workout_push' | 'workout_remove'
  state: GarminJobState
  started_at: string
  finished_at: string | null
  range_start: string | null
  range_end: string | null
  cursor_date: string | null
  step: string | null
  step_index: number
  step_total: number
  progress_pct: number
  activities_new: number
  activities_updated: number
  wellness_days: number
  workouts_pushed: number
  workouts_removed: number
  message: string | null
  error: string | null
}

export interface GarminStatus {
  konto: GarminAccount | null
  aktiver_job: GarminJob | null
  letzter_job: GarminJob | null
  trainings_gesamt: number
  fitness_tage_gesamt: number
}

/** Antwort auf den Anmeldeversuch — bei aktivem MFA fehlt noch der Code. */
export interface GarminConnectResult {
  status: 'verbunden' | 'mfa_erforderlich'
  pending_id?: string
  hinweis?: string
}

/** Ein Tag Fitnessdaten. Alle Werte optional — jede Quelle füllt nur ihre eigenen. */
export interface WellnessDay {
  date: string
  sleep_seconds: number | null
  sleep_deep_seconds: number | null
  sleep_light_seconds: number | null
  sleep_rem_seconds: number | null
  sleep_awake_seconds: number | null
  sleep_score: number | null
  sleep_stress_avg: number | null
  sleep_body_battery_change: number | null
  hrv_last_night_ms: number | null
  hrv_weekly_avg_ms: number | null
  hrv_status: string | null
  hrv_baseline_low: number | null
  hrv_baseline_high: number | null
  resting_hr: number | null
  weight_kg: number | null
  body_fat_pct: number | null
  vo2max_run: number | null
  vo2max_bike: number | null
  readiness_score: number | null
  readiness_level: string | null
  readiness_feedback: string | null
  recovery_time_h: number | null
  training_status: string | null
  training_status_feedback: string | null
  weekly_training_load: number | null
  garmin_acwr: number | null
  garmin_acwr_status: string | null
  body_battery_high: number | null
  body_battery_low: number | null
  stress_avg: number | null
  stress_max: number | null
}

// --------------------------------------------------------------------------
// Trainings nach Garmin übertragen
// --------------------------------------------------------------------------

/** Was aus einer geplanten Einheit in Garmin geworden ist.
 *
 * `geaendert` heißt: Sie steht dort, aber mit einem anderen Inhalt als dem,
 * den der Plan heute vorsieht — ein erneutes Übertragen ersetzt sie.
 */
export type GarminUebertragungsZustand = 'offen' | 'aktuell' | 'geaendert' | 'fehler'

export interface GarminEinheitStatus {
  plan_session_id: number
  date: string
  title: string
  sport: Sport
  zustand: GarminUebertragungsZustand
  garmin_workout_id: string | null
  garmin_schedule_id: string | null
  last_error: string | null
}

export interface GarminPlanUebertragung {
  plan_id: number
  plan_title: string
  /** Ohne verbundenes Konto gibt es nichts zu übertragen. */
  garmin_verbunden: boolean
  einheiten: GarminEinheitStatus[]
  offen: number
  aktuell: number
  geaendert: number
  fehler: number
  /** Einheiten des Plans, die vor heute liegen und übersprungen werden. */
  vergangen: number
}

/** Ein Eintrag aus dem Garmin-Kalender — geplant oder bereits absolviert. */
export interface GarminKalenderEintrag {
  datum: string
  art: 'workout' | 'aktivitaet' | 'sonstiges'
  /** Der Termin. Über ihn wird ein Workout aus dem Kalender genommen. */
  schedule_id: string | null
  /** Die Vorlage in der Workout-Bibliothek. */
  workout_id: string | null
  activity_id: string | null
  titel: string
  sportart: Sport | null
  garmin_typ: string | null
  dauer_min: number | null
  distanz_km: number | null
  abgeschlossen: boolean
  aus_tri_coach: boolean
  plan_session_id: number | null
}

export interface GarminKalender {
  jahr: number
  monat: number
  eintraege: GarminKalenderEintrag[]
}

/** Ein manueller Eintrag, den es nun auch aus Garmin gibt. */
export interface GarminDublette {
  manual_log_id: number
  garmin_log_id: number
  date: string
  sport: Sport
  manual_duration_min: number | null
  garmin_duration_min: number | null
}
