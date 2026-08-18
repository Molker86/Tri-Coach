import type {
  AiExport,
  AuthResponse,
  GarminConnectResult,
  GarminDublette,
  GarminEinheitStatus,
  GarminJob,
  GarminKalender,
  GarminKalenderLeeren,
  GarminPlanUebertragung,
  GarminStatus,
  KiJob,
  KiSettings,
  KiStatus,
  Plan,
  PlanDeleteResult,
  PlanImportResult,
  PlanSummary,
  Profile,
  ProfileHistoryEntry,
  SessionLog,
  Stats,
  TrainingRequest,
  TrainingRequestInput,
  User,
  UserOption,
  WellnessDay,
} from '../types'
import { BASE_PATH } from '../basePath'

const TOKEN_KEY = 'tricoach.token'
const LAST_USER_KEY = 'tricoach.lastUser'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token === null) localStorage.removeItem(TOKEN_KEY)
  else localStorage.setItem(TOKEN_KEY, token)
}

/** Zuletzt angemeldetes Konto -- überlebt das Abmelden, damit die
 *  Anmeldeseite es wieder vorauswählen kann. */
export function getLastUserId(): number | null {
  const raw = localStorage.getItem(LAST_USER_KEY)
  const id = raw === null ? NaN : Number(raw)
  return Number.isFinite(id) ? id : null
}

export function setLastUserId(id: number): void {
  localStorage.setItem(LAST_USER_KEY, String(id))
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/** Wird bei 401 ausgelöst, damit der AuthContext ausloggen kann. */
export const onUnauthorized = { handler: null as (() => void) | null }

async function request<T>(
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'

  const response = await fetch(`${BASE_PATH}/api${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  })

  if (response.status === 401) {
    onUnauthorized.handler?.()
    throw new ApiError('Sitzung abgelaufen. Bitte erneut anmelden.', 401)
  }

  if (!response.ok) {
    throw new ApiError(await extractError(response), response.status)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

async function extractError(response: Response): Promise<string> {
  try {
    const data = await response.json()
    const detail = data?.detail
    if (typeof detail === 'string') return detail
    // FastAPI-Validierungsfehler kommen als Liste
    if (Array.isArray(detail)) {
      return detail
        .map((e: { loc?: unknown[]; msg?: string }) => {
          const field = Array.isArray(e.loc) ? e.loc.slice(1).join('.') : ''
          return field ? `${field}: ${e.msg}` : e.msg
        })
        .join('\n')
    }
  } catch {
    // Antwort war kein JSON
  }
  return `Serverfehler (${response.status})`
}

export const api = {
  register: (email: string, username: string) =>
    request<AuthResponse>('/auth/register', {
      method: 'POST',
      body: { email, username },
    }),

  listUsers: () => request<UserOption[]>('/auth/users'),

  login: (userId: number) =>
    request<AuthResponse>('/auth/login', {
      method: 'POST',
      body: { user_id: userId },
    }),

  me: () => request<User>('/auth/me'),

  getProfile: () => request<Profile>('/profile'),
  updateProfile: (data: Partial<Profile>) =>
    request<Profile>('/profile', { method: 'PUT', body: data }),
  getProfileHistory: () => request<ProfileHistoryEntry[]>('/profile/history'),

  createRequest: (data: TrainingRequestInput) =>
    request<TrainingRequest>('/requests', { method: 'POST', body: data }),
  listRequests: () => request<TrainingRequest[]>('/requests'),
  latestRequest: () => request<TrainingRequest | null>('/requests/latest'),

  exportForAi: (requestId?: number, startDate?: string, days?: number) => {
    const params = new URLSearchParams()
    if (requestId !== undefined) params.set('request_id', String(requestId))
    if (startDate) params.set('start_date', startDate)
    if (days !== undefined) params.set('days', String(days))
    const query = params.toString()
    return request<AiExport>(`/plans/export${query ? `?${query}` : ''}`)
  },

  validatePlan: (raw: string, requestId?: number, days?: number) =>
    request<PlanImportResult>('/plans/validate', {
      method: 'POST',
      body: { raw, request_id: requestId ?? null, days: days ?? null },
    }),

  importPlan: (raw: string, requestId?: number, days?: number) =>
    request<PlanImportResult>('/plans/import', {
      method: 'POST',
      body: { raw, request_id: requestId ?? null, days: days ?? null },
    }),

  listPlans: () => request<PlanSummary[]>('/plans'),
  activePlan: () => request<Plan | null>('/plans/active'),
  getPlan: (id: number) => request<Plan>(`/plans/${id}`),
  activatePlan: (id: number) => request<Plan>(`/plans/${id}/activate`, { method: 'POST' }),
  // Löscht den Plan **und** nimmt seine Einheiten aus dem Garmin-Kalender —
  // danach käme der Server nicht mehr an sie heran. Klappt das nicht, wird gar
  // nicht gelöscht; `garminUebergehen` ist der ausdrückliche Weg daran vorbei.
  deletePlan: (id: number, opt?: { garminUebergehen?: boolean }) =>
    request<PlanDeleteResult>(
      `/plans/${id}${opt?.garminUebergehen ? '?garmin_uebergehen=true' : ''}`,
      { method: 'DELETE' },
    ),

  // Absolvierte Trainings kommen ausschließlich aus dem Garmin-Abgleich; es
  // gibt kein Anlegen und kein Bearbeiten mehr. Löschen bleibt, damit ein
  // falsch importierter Eintrag wieder verschwinden kann.
  listLogs: (weeks = 4) => request<SessionLog[]>(`/logs?weeks=${weeks}`),
  deleteLog: (id: number) => request<void>(`/logs/${id}`, { method: 'DELETE' }),
  stats: () => request<Stats>('/logs/stats'),

  garminStatus: () => request<GarminStatus>('/garmin/status'),
  garminConnect: (email: string, password: string) =>
    request<GarminConnectResult>('/garmin/connect', {
      method: 'POST',
      body: { email, password },
    }),
  garminMfa: (pendingId: string, code: string) =>
    request<GarminConnectResult>('/garmin/connect/mfa', {
      method: 'POST',
      body: { pending_id: pendingId, code },
    }),
  garminDisconnect: () => request<void>('/garmin/connection', { method: 'DELETE' }),
  garminSettings: (data: {
    auto_sync_enabled?: boolean
    profile_sync_enabled?: boolean
    auto_push_enabled?: boolean
  }) =>
    request<GarminStatus['konto']>('/garmin/settings', { method: 'PUT', body: data }),
  garminSync: () => request<GarminJob>('/garmin/sync', { method: 'POST' }),
  garminBackfill: (von?: string, tagesschleifeVoll = false) =>
    request<GarminJob>('/garmin/backfill', {
      method: 'POST',
      body: { von: von ?? null, tagesschleife_voll: tagesschleifeVoll },
    }),
  garminJob: (id: number) => request<GarminJob>(`/garmin/jobs/${id}`),
  garminAbbrechen: (id: number) =>
    request<GarminJob>(`/garmin/jobs/${id}/abbrechen`, { method: 'POST' }),
  garminWellness: (weeks = 4) => request<WellnessDay[]>(`/garmin/wellness?weeks=${weeks}`),
  garminDubletten: () => request<GarminDublette[]>('/garmin/dubletten'),

  // Gegenrichtung: geplante Einheiten auf die Uhr legen.
  garminWorkoutStatus: (planId?: number) =>
    request<GarminPlanUebertragung>(
      `/garmin/workouts/status${planId !== undefined ? `?plan_id=${planId}` : ''}`,
    ),
  garminWorkoutsUebertragen: (planId?: number) =>
    request<GarminJob>('/garmin/workouts/uebertragen', {
      method: 'POST',
      body: { plan_id: planId ?? null },
    }),
  garminWorkoutsEntfernen: (planId?: number) =>
    request<GarminJob>('/garmin/workouts/entfernen', {
      method: 'POST',
      body: { plan_id: planId ?? null },
    }),
  garminEinheitUebertragen: (planSessionId: number) =>
    request<GarminEinheitStatus>(`/garmin/workouts/einheit/${planSessionId}`, {
      method: 'POST',
    }),
  garminEinheitEntfernen: (planSessionId: number) =>
    request<void>(`/garmin/workouts/einheit/${planSessionId}`, { method: 'DELETE' }),

  garminKalender: (jahr: number, monat: number) =>
    request<GarminKalender>(`/garmin/kalender?jahr=${jahr}&monat=${monat}`),
  /** Poolvorlagen bleiben serverseitig auch mit `workoutId` erhalten. */
  garminKalenderLoeschen: (scheduleId: string, workoutId?: string | null) =>
    request<void>(
      `/garmin/kalender/${scheduleId}${workoutId ? `?workout_id=${workoutId}` : ''}`,
      { method: 'DELETE' },
    ),
  /**
   * Nimmt alle Tri-Coach-Termine eines Monats aus dem Kalender. Die Vorlagen
   * bleiben — gelöscht wird nur der Eintrag im Zeitplan.
   */
  garminKalenderLeeren: (jahr: number, monat: number) =>
    request<GarminKalenderLeeren>('/garmin/kalender/leeren', {
      method: 'POST',
      body: { jahr, monat },
    }),
  garminKalenderVerschieben: (scheduleId: string, workoutId: string, datum: string) =>
    request<void>(`/garmin/kalender/${scheduleId}/verschieben`, {
      method: 'POST',
      body: { workout_id: workoutId, datum },
    }),

  // KI-Planung im Server — der Weg ohne Zwischenablage.
  kiStatus: () => request<KiStatus>('/ki/status'),
  // Modell und Denktiefe je Nutzer. Ohne Oberfläche — wer sie von der Vorgabe
  // wegstellen will, ruft die API selbst auf.
  kiSettings: (data: Partial<KiSettings>) =>
    request<KiSettings>('/ki/settings', { method: 'PUT', body: data }),
  kiPlanen: (startDate?: string, days?: number, requestId?: number) =>
    request<KiJob>('/ki/planen', {
      method: 'POST',
      body: {
        start_date: startDate ?? null,
        days: days ?? 7,
        request_id: requestId ?? null,
      },
    }),
  kiJob: (id: number) => request<KiJob>(`/ki/jobs/${id}`),
  kiAbbrechen: (id: number) =>
    request<KiJob>(`/ki/jobs/${id}/abbrechen`, { method: 'POST' }),
}

/** Zustände, in denen ein Abgleich beendet ist. */
const JOB_ENDZUSTAENDE = new Set([
  'done', 'failed', 'cancelled', 'rate_limited', 'interrupted',
])

/** Das Wenige, was jeder Job gemeinsam hat. */
export type JobBasis = { id: number; state: string }

export function jobLaeuft(job: JobBasis | null | undefined): boolean {
  return job != null && !JOB_ENDZUSTAENDE.has(job.state)
}

/** Fragt einen laufenden Job ab, bis er beendet ist.
 *
 * Das erste Muster dieser Art in der App: Ein Backfill läuft Minuten und hat
 * deshalb seinen Zustand in der Datenbank statt in einer langen Antwort. Der
 * Planungslauf der KI dauert ähnlich lange und wird genauso abgefragt —
 * deshalb kommt der Abruf als Parameter herein, statt dass es einen zweiten,
 * gleich gebauten Poller gäbe.
 *
 * Das Intervall ist bewusst träge — ein Abgleich macht ohnehin nur alle paar
 * Sekunden einen Schritt, häufigeres Fragen erzeugt nur Last auf einem
 * Raspberry Pi. Nach zwei Minuten wird es noch weiter gestreckt, weil ein
 * Jahresrückblick lange läuft und niemand solange zusieht.
 *
 * Gibt eine Abbruchfunktion zurück, die direkt in ein useEffect-Cleanup passt.
 */
export function pollJob<T extends JobBasis>(
  jobId: number,
  hole: (id: number) => Promise<T>,
  onUpdate: (job: T) => void,
  onError?: (message: string) => void,
): () => void {
  let gestoppt = false
  let timer: ReturnType<typeof setTimeout> | undefined
  let fehlversuche = 0
  const beginn = Date.now()

  function intervall(): number {
    return Date.now() - beginn > 120_000 ? 5000 : 2500
  }

  async function frage() {
    if (gestoppt) return
    try {
      const job = await hole(jobId)
      fehlversuche = 0
      if (gestoppt) return
      onUpdate(job)
      if (!jobLaeuft(job)) return
    } catch (err) {
      // Ein Aussetzer im Netz ist kein Ende des Laufs — der geht im Server
      // weiter. Erst nach mehreren Fehlschlägen aufgeben.
      fehlversuche += 1
      if (fehlversuche >= 3) {
        onError?.(err instanceof Error ? err.message : 'Verbindung unterbrochen.')
        return
      }
    }
    timer = setTimeout(frage, intervall())
  }

  // Telefone drosseln Zeitgeber im Hintergrund. Ohne das Nachfragen beim
  // Zurückwechseln wirkte der Fortschrittsbalken eingefroren.
  function beiSichtbarkeit() {
    if (document.visibilityState === 'visible' && !gestoppt) {
      clearTimeout(timer)
      void frage()
    }
  }
  document.addEventListener('visibilitychange', beiSichtbarkeit)

  void frage()

  return () => {
    gestoppt = true
    clearTimeout(timer)
    document.removeEventListener('visibilitychange', beiSichtbarkeit)
  }
}
