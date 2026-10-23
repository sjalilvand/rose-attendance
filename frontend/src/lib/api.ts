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
  /** null برای کاربران سیستمی مثل superuser که پروندهٔ پرسنلی ندارند */
  employee: {
    id: number
    personnel_code: string
    first_name: string
    last_name: string
    full_name: string
    employment_status: string
    home_branch_id: number | null
  } | null
  roles: string[]
  branches: BranchInfo[]
}

export interface TokenResponse {
  access: string
  refresh: string
  /** null برای اکانت ادمین بدون پروندهٔ پرسنلی */
  personnel_code: string | null
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

// ---------------------------------------------------------------------------
// Requests & approvals (phase-2 step 3 — section 11 + approved decision #5)
// ---------------------------------------------------------------------------
export interface RequestSegmentInfo {
  id: number
  branch: string
  branch_name: string
  starts_at: string
  ends_at: string
  computed_minutes: number
  status: string
}

export interface MyRequest {
  kind: 'LEAVE' | 'MISSION'
  id: number
  status: string
  starts_at: string
  ends_at: string
  computed_minutes: number
  created_at: string
  segments: RequestSegmentInfo[]
  leave_type?: string
  leave_type_name?: string
  description?: string
  subject?: string
  destination?: string
}

export interface LeaveTypeInfo {
  code: string
  name: string
  is_hourly: boolean
  is_paid: boolean
  requires_attachment: boolean
}

export interface QueueItem {
  kind: 'LEAVE' | 'MISSION'
  request_id: number
  segment_id: number
  employee: { id: number; personnel_code: string; full_name: string }
  branch: string
  branch_name: string
  starts_at: string
  ends_at: string
  computed_minutes: number
  leave_type?: string
  leave_type_name?: string
  description?: string
  subject?: string
  destination?: string
}

export interface ReviewItem {
  event_uuid: string
  employee: { id: number; personnel_code: string; full_name: string }
  branch: string
  event_type: string
  device_time: string | null
  effective_time: string
  flags: string[]
  location_status: string
  connection_mode: string
}

export interface OvertimeItem {
  id: number
  employee: { id: number; personnel_code: string; full_name: string }
  branch: string
  shift_date: string
  proposed_minutes: number
  approved_minutes: number
  status: string
  reason: string
  decided_at: string | null
}

export interface BoardRow {
  employee: { id: number; personnel_code: string; full_name: string; is_home: boolean }
  branch: string
  branch_name: string
  day: DayRow | null
}

export function fetchLeaveTypes(): Promise<{ count: number; results: LeaveTypeInfo[] }> {
  return apiFetch('/leave-types/')
}

export function fetchMyRequests(): Promise<{ count: number; results: MyRequest[] }> {
  return apiFetch('/requests/')
}

export function submitLeave(payload: {
  leave_type: string
  starts_at: string
  ends_at: string
  description?: string
}): Promise<MyRequest> {
  return apiFetch('/requests/leave/', { method: 'POST', body: JSON.stringify(payload) })
}

export function submitMission(payload: {
  subject: string
  starts_at: string
  ends_at: string
  destination_text?: string
}): Promise<MyRequest> {
  return apiFetch('/requests/mission/', { method: 'POST', body: JSON.stringify(payload) })
}

export function cancelRequest(kind: 'LEAVE' | 'MISSION', id: number): Promise<MyRequest> {
  return apiFetch('/requests/cancel/', { method: 'POST', body: JSON.stringify({ kind, id }) })
}

export function fetchRequestQueue(): Promise<{ count: number; results: QueueItem[] }> {
  return apiFetch('/requests/queue/')
}

export function decideSegment(
  segment_id: number,
  action: 'APPROVE' | 'REJECT',
  comment = '',
): Promise<{ segment_id: number; segment_status: string; overall_status: string }> {
  return apiFetch('/requests/queue/decide/', {
    method: 'POST',
    body: JSON.stringify({ segment_id, action, comment }),
  })
}

export function fetchReviewQueue(): Promise<{ count: number; results: ReviewItem[] }> {
  return apiFetch('/attendance/review-queue/?page_size=100')
}

export function approveReviewPunch(
  event_uuid: string,
  corrected_time: string,
  reason: string,
): Promise<PunchResult> {
  return apiFetch('/attendance/review-queue/approve/', {
    method: 'POST',
    body: JSON.stringify({ event_uuid, corrected_time, reason }),
  })
}

export function fetchOvertime(status?: string): Promise<{ count: number; results: OvertimeItem[] }> {
  const qs = status ? `&status=${encodeURIComponent(status)}` : ''
  return apiFetch(`/attendance/overtime/?page_size=100${qs}`)
}

export function approveOvertime(id: number): Promise<{ id: number; status: string; approved_minutes: number }> {
  return apiFetch('/attendance/overtime/approve/', { method: 'POST', body: JSON.stringify({ id }) })
}

export function fetchManagerBoard(date: string): Promise<{ date: string; count: number; results: BoardRow[] }> {
  return apiFetch(`/reports/manager-board/?date=${encodeURIComponent(date)}`)
}
