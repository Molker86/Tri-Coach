import type {
  AiExport,
  AuthResponse,
  Plan,
  PlanImportResult,
  PlanSummary,
  Profile,
  ProfileHistoryEntry,
  SessionLog,
  SessionLogInput,
  Stats,
  TrainingRequest,
  TrainingRequestInput,
  User,
} from '../types'
import { BASE_PATH } from '../basePath'

const TOKEN_KEY = 'tricoach.token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token === null) localStorage.removeItem(TOKEN_KEY)
  else localStorage.setItem(TOKEN_KEY, token)
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
  register: (email: string, username: string, password: string) =>
    request<AuthResponse>('/auth/register', {
      method: 'POST',
      body: { email, username, password },
    }),

  login: (identifier: string, password: string) =>
    request<AuthResponse>('/auth/login', {
      method: 'POST',
      body: { identifier, password },
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
  deletePlan: (id: number) => request<void>(`/plans/${id}`, { method: 'DELETE' }),

  listLogs: (weeks = 4) => request<SessionLog[]>(`/logs?weeks=${weeks}`),
  createLog: (data: SessionLogInput) =>
    request<SessionLog>('/logs', { method: 'POST', body: data }),
  updateLog: (id: number, data: SessionLogInput) =>
    request<SessionLog>(`/logs/${id}`, { method: 'PUT', body: data }),
  deleteLog: (id: number) => request<void>(`/logs/${id}`, { method: 'DELETE' }),
  stats: () => request<Stats>('/logs/stats'),
}
