/** API client — JWT (access 15m / refresh 30d), auto-refresh on 401,
 * server-clock offset measurement for the CLOCK_SKEW decision (#4 of §34). */

const BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api/v1'
const ACCESS_KEY = 'rose.access'
const REFRESH_KEY = 'rose.refresh'
const OFFSET_KEY = 'rose.clockOffsetMs'

export class ApiError extends Error {
  status: number
  code?: string
  constructor(status: number, message: string, code?: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_KEY)
}

export function hasSession(): boolean {
  return Boolean(localStorage.getItem(ACCESS_KEY) || localStorage.getItem(REFRESH_KEY))
}

export function setTokens(access: string, refresh: string): void {
  localStorage.setItem(ACCESS_KEY, access)
  localStorage.setItem(REFRESH_KEY, refresh)
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

export function clockOffsetMinutes(): number {
  const raw = Number(localStorage.getItem(OFFSET_KEY) ?? '0')
  return Number.isFinite(raw) ? Math.round(raw / 60000) : 0
}

function storeOffset(ms: number): void {
  localStorage.setItem(OFFSET_KEY, String(Math.round(ms)))
}

let refreshing: Promise<boolean> | null = null

async function refreshTokens(): Promise<boolean> {
  const refresh = localStorage.getItem(REFRESH_KEY)
  if (!refresh) return false
  try {
    const res = await fetch(`${BASE}/auth/token/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh }),
    })
    if (!res.ok) return false
    const data = (await res.json()) as { access?: string; refresh?: string }
    if (!data.access) return false
    localStorage.setItem(ACCESS_KEY, data.access)
    if (data.refresh) localStorage.setItem(REFRESH_KEY, data.refresh)
    return true
  } catch {
    return false
  }
}

function ensureRefreshed(): Promise<boolean> {
  if (!refreshing) {
    refreshing = refreshTokens().finally(() => {
      refreshing = null
    })
  }
  return refreshing
}

export async function apiFetch<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const token = getAccessToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  let res: Response
  try {
    res = await fetch(BASE + path, { ...init, headers })
  } catch (err) {
    throw new ApiError(0, 'network-unreachable')
  }
  if (res.status === 401 && retry) {
    const ok = await ensureRefreshed()
    if (ok) return apiFetch<T>(path, init, false)
    clearTokens()
    throw new ApiError(401, 'نشست منقضی شد؛ دوباره وارد شوید.')
  }
  if (!res.ok) {
    let detail = res.statusText
    let code: string | undefined
    try {
      const data = (await res.json()) as { detail?: string; code?: string }
      detail = data.detail ?? JSON.stringify(data)
      code = data.code
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail, code)
  }
  return (await res.json()) as T
}

// ---------------------------------------------------------------------------
// Domain types (contract of /api/v1)
// ---------------------------------------------------------------------------
export interface BranchInfo {
  code: string
  name: string
  geo_latitude: number | null
  geo_longitude: number | null
  geo_radius_m: number
  is_home: boolean
}

export interface MeInfo {
  username: string
  server_time: string
  employee: {
    id: number
    personnel_code: string
    first_name: string
    last_name: string
    full_name: string
    employment_status: string
    home_branch_id: number | null
  }
  roles: string[]
  branches: BranchInfo[]
}

export interface TokenResponse {
  access: string
  refresh: string
  personnel_code: string
  full_name: string
  roles: string[]
}

export interface PunchResult {
  event_uuid: string
  created: boolean
  event_type: 'CHECK_IN' | 'CHECK_OUT'
  event_status: string
  location_status: string
  location_reason: string
  flags: string[]
  effective_time: string
}

export interface DayRow {
  shift_date: string
  shift_code: string | null
  is_workday: boolean
  is_holiday: boolean
  required_minutes: number
  valid_presence_minutes: number
  accepted_work_minutes: number
  rest_minutes: number
  late_minutes: number
  early_leave_minutes: number
  overtime_proposed_minutes: number
  overtime_approved_minutes: number
  absence_minutes: number
  leave_minutes_by_type: Record<string, number>
  mission_minutes: number
  session_count: number
  incomplete_sessions: number
  flags: string[]
  first_in: string | null
  last_out: string | null
}

export interface TodayCard {
  today: DayRow | null
  events: {
    event_uuid: string
    event_type: string
    branch: string
    effective_time: string
    location_status: string
    location_reason: string
    event_status: string
    flags: string[]
    connection_mode: string
  }[]
  open_session: { id: number; branch: string; check_in_at: string | null; shift_date: string } | null
}

export interface SummaryRow {
  id: number
  branch: string
  period_year: number
  period_month: number
  required_minutes: number
  accepted_work_minutes: number
  late_minutes: number
  early_leave_minutes: number
  absence_minutes: number
  shortage_minutes: number
  overtime_minutes: number
  mission_minutes: number
  leave_minutes_by_type: Record<string, number>
  incomplete_session_count: number
  no_location_count: number
  out_of_range_count: number
  summary_state: string
  finalized_at: string | null
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------
export async function login(username: string, password: string): Promise<TokenResponse> {
  const data = await apiFetch<TokenResponse>('/auth/token/', {
    method: 'POST',
    body: JSON.stringify({ username, password, platform: 'PWA' }),
  })
  setTokens(data.access, data.refresh)
  return data
}

export async function logout(): Promise<void> {
  clearTokens()
}

export function fetchMe(): Promise<MeInfo> {
  return apiFetch<MeInfo>('/me/')
}

/** Measures client−server clock offset (ms); used for CLOCK_SKEW labelling. */
export async function measureClockOffset(): Promise<number> {
  const t0 = Date.now()
  const me = await apiFetch<MeInfo>('/me/')
  const rtt = Date.now() - t0
  const offset = t0 + rtt / 2 - Date.parse(me.server_time)
  storeOffset(offset)
  return offset
}

export function punch(payload: {
  event_uuid: string
  event_type: 'CHECK_IN' | 'CHECK_OUT'
  branch_code: string
  channel: 'PWA'
  device_time?: string
  clock_offset_minutes?: number
  latitude?: number | null
  longitude?: number | null
  location_accuracy_m?: number | null
}): Promise<PunchResult> {
  return apiFetch<PunchResult>('/attendance/events/punch/', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function syncBatch(events: Record<string, unknown>[]): Promise<{
  processed: number
  needs_review: number
  results: PunchResult[]
}> {
  return apiFetch('/attendance/events/sync/', {
    method: 'POST',
    body: JSON.stringify({ events }),
  })
}

export function fetchToday(): Promise<TodayCard> {
  return apiFetch<TodayCard>('/attendance/daily/today/')
}

export function fetchDaily(from: string, to: string): Promise<{ count: number; results: DayRow[] }> {
  return apiFetch(`/attendance/daily/?from=${from}&to=${to}`)
}

export function fetchSummaries(): Promise<{ count: number; results: SummaryRow[] }> {
  return apiFetch('/reports/monthly-summaries/?page_size=24')
}
