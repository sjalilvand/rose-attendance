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
  /** فاز ۶۵ — مشخصات کامل همگام‌شده از رز هاب (در هر ورود SSO بروزرسانی می‌شود) */
  full_name?: string
  mobile?: string
  national_id?: string
  province?: string
  province_code?: string
  clinic?: string
  /** null برای کاربران سیستمی مثل superuser که پروندهٔ پرسنلی ندارند */
  employee: {
    id: number
    personnel_code: string
    first_name: string
    last_name: string
    full_name: string
    employment_status: string
    home_branch_id: number | null
    home_branch_name?: string | null
    job_title?: string
    mobile?: string
  } | null
  roles: string[]
  /** روش ورود — SSO یا گذرواژه محلی (فیلد جدید؛ در نسخه‌های قبلی ارسال نمی‌شد) */
  auth_method?: 'SSO' | 'PASSWORD'
  last_login_at?: string | null
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

// ---------------------------------------------------------------------------
// SSO (ورود یکپارچه) + پروفایل
// ---------------------------------------------------------------------------
export interface SsoStatus {
  enabled: boolean
  label: string
}

export function fetchSsoStatus(): Promise<SsoStatus> {
  return apiFetch<SsoStatus>('/auth/sso/status/')
}

/** آدرس شروع ورود یکپارچه — مرورگر مستقیم به سرور می‌رود تا به ارائه‌دهنده ریدایرکت شود. */
export function ssoLoginUrl(): string {
  const redirect = encodeURIComponent(window.location.origin)
  return `${BASE}/auth/sso/login/?redirect=${redirect}`
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<string> {
  const res = await apiFetch<{ detail: string }>('/auth/password/change/', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  })
  return res.detail
}

export async function updateMobile(mobile: string): Promise<string> {
  const res = await apiFetch<{ detail: string }>('/auth/profile/', {
    method: 'POST',
    body: JSON.stringify({ mobile }),
  })
  return res.detail
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
  /** ماندهٔ ردیابی‌شدهٔ پرسنل برای همین نوع مرخصی؛ null یعنی ردیابی‌نشده */
  employee_balance_minutes?: number | null
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

export function rejectReviewPunch(event_uuid: string, reason: string): Promise<PunchResult> {
  return apiFetch('/attendance/review-queue/reject/', {
    method: 'POST',
    body: JSON.stringify({ event_uuid, reason }),
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

// ---------------------------------------------------------------------------
// Personnel bulk import (HR/ADMIN) — multipart xlsx upload + template
// ---------------------------------------------------------------------------
export interface ImportReport {
  total: number
  created: number
  updated: number
  skipped: number
  errors: { row: number; personnel_code: string; message: string }[]
  dry_run: boolean
}

export async function importPersonnel(file: File, dryRun: boolean): Promise<ImportReport> {
  const token = getAccessToken()
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  const form = new FormData()
  form.append('file', file)
  form.append('dry_run', dryRun ? 'true' : 'false')
  let res: Response
  try {
    res = await fetch(`${BASE}/people/import/`, { method: 'POST', headers, body: form })
  } catch {
    throw new ApiError(0, 'network-unreachable')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const data = (await res.json()) as { detail?: string }
      detail = data.detail ?? detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as ImportReport
}

export async function downloadImportTemplate(): Promise<void> {
  return downloadXlsx('/people/import/template/', 'personnel-import-template.xlsx')
}

/** Authenticated xlsx download → save via a temporary anchor. */
async function downloadXlsx(path: string, filename: string): Promise<void> {
  const token = getAccessToken()
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, { headers })
  } catch {
    throw new ApiError(0, 'network-unreachable')
  }
  if (!res.ok) {
    let detail = 'دانلود فایل ناموفق بود.'
    try {
      const data = (await res.json()) as { detail?: string }
      detail = data.detail ?? detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail)
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// ---------------------------------------------------------------------------
// HR monthly Excel report (phase-2 step 6) — preview + workbook download
// ---------------------------------------------------------------------------
export interface MonthlyPreview {
  period: { jy: number; jm: number }
  branch: string | null
  rows: number
  totals: {
    employees: number
    required_minutes: number
    accepted_work_minutes: number
    late_minutes: number
    late_days: number
    early_leave_minutes: number
    absence_minutes: number
    absence_days: number
    shortage_minutes: number
    overtime_minutes: number
    mission_minutes: number
    leave_minutes: number
    final_count: number
  }
  by_branch: {
    branch: string
    employees: number
    required_minutes: number
    accepted_work_minutes: number
    late_minutes: number
    absence_minutes: number
    shortage_minutes: number
    overtime_minutes: number
    leave_minutes: number
  }[]
}

export interface YearTrendMonth {
  jm: number
  month_name: string
  employees: number
  required_minutes: number
  accepted_work_minutes: number
  late_minutes: number
  late_days: number
  absence_minutes: number
  absence_days: number
  shortage_minutes: number
  overtime_minutes: number
  leave_minutes: number
}

export interface YearTrend {
  period_year: number
  branch: string | null
  rows: number
  totals: {
    employees: number
    required_minutes: number
    accepted_work_minutes: number
    late_minutes: number
    late_days: number
    absence_minutes: number
    absence_days: number
    shortage_minutes: number
    overtime_minutes: number
  }
  months: YearTrendMonth[]
}

export function fetchYearTrend(jy: number, branch?: string, refresh = false): Promise<YearTrend> {
  const q = new URLSearchParams({ year: String(jy), refresh: refresh ? '1' : '0' })
  if (branch) q.set('branch', branch)
  return apiFetch(`/reports/annual/preview/?${q.toString()}`)
}

export function downloadAnnualReport(jy: number, branch?: string, refresh = false): Promise<void> {
  const q = new URLSearchParams({ year: String(jy), refresh: refresh ? '1' : '0' })
  if (branch) q.set('branch', branch)
  return downloadXlsx(`/reports/annual/excel/?${q.toString()}`, `rose-annual-report-${jy}.xlsx`)
}

export function downloadDisciplinaryReport(jy: number, jm: number, branch?: string): Promise<void> {
  const q = new URLSearchParams({ year: String(jy), month: String(jm) })
  if (branch) q.set('branch', branch)
  return downloadXlsx(`/reports/disciplinary/excel/?${q.toString()}`, `rose-disciplinary-${jy}-${String(jm).padStart(2, '0')}.xlsx`)
}

export function fetchMonthlyPreview(jy: number, jm: number, branch?: string): Promise<MonthlyPreview> {
  const q = new URLSearchParams({ year: String(jy), month: String(jm) })
  if (branch) q.set('branch', branch)
  return apiFetch(`/reports/monthly/preview/?${q.toString()}`)
}

export function downloadMonthlyReport(jy: number, jm: number, branch?: string): Promise<void> {
  const q = new URLSearchParams({ year: String(jy), month: String(jm) })
  if (branch) q.set('branch', branch)
  return downloadXlsx(`/reports/monthly/excel/?${q.toString()}`, `rose-monthly-report-${jy}-${String(jm).padStart(2, '0')}.xlsx`)
}

// ---------------------------------------------------------------------------
// Leave balance xlsx — dedicated template + import (phase-2 step 6)
// ---------------------------------------------------------------------------
export function downloadLedgerTemplate(): Promise<void> {
  return downloadXlsx('/leaves/ledger/template/', 'leave-balance-template.xlsx')
}

export async function importLedgerBalances(file: File, dryRun: boolean): Promise<ImportReport> {
  const token = getAccessToken()
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  const form = new FormData()
  form.append('file', file)
  form.append('dry_run', dryRun ? 'true' : 'false')
  let res: Response
  try {
    res = await fetch(`${BASE}/leaves/ledger/import/`, { method: 'POST', headers, body: form })
  } catch {
    throw new ApiError(0, 'network-unreachable')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const data = (await res.json()) as { detail?: string }
      detail = data.detail ?? detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as ImportReport
}

// ---------------------------------------------------------------------------
// Org management — regions / branches / shifts (HR/ADMIN), phase-2 step 5
// ---------------------------------------------------------------------------
export interface OrgRegion {
  id: number
  code: string
  name: string
  is_active: boolean
  branches_count: number
}

export interface OrgBranch {
  id: number
  code: string
  name: string
  region_code: string
  region_name: string
  province: string
  city: string
  address: string
  phone: string
  geo_latitude: number | null
  geo_longitude: number | null
  geo_radius_m: number
  is_active: boolean
  employee_count: number
}

export interface OrgShift {
  id: number
  code: string
  name: string
  starts_at: string
  ends_at: string
  crosses_midnight: boolean
  rest_minutes: number
  rest_mode: string
  grace_minutes: number
  scope_branch: string | null
  scope_branch_name: string | null
}

export interface ListResp<T> {
  count: number
  page: number
  page_size: number
  results: T[]
}

export interface BulkReport {
  total: number
  created: number
  updated: number
  skipped: number
  errors: { row: number; code?: string; personnel_code?: string; message: string }[]
  dry_run: boolean
}

export function fetchOrgRegions(): Promise<ListResp<OrgRegion>> {
  return apiFetch('/org/regions/?page_size=200')
}

export function createRegion(payload: { code: string; name: string }): Promise<OrgRegion> {
  return apiFetch('/org/regions/', { method: 'POST', body: JSON.stringify(payload) })
}

export function fetchOrgBranches(params: {
  page?: number
  page_size?: number
  region?: string
  search?: string
  is_active?: string
}): Promise<ListResp<OrgBranch>> {
  const q = new URLSearchParams()
  if (params.page) q.set('page', String(params.page))
  if (params.page_size) q.set('page_size', String(params.page_size))
  if (params.region) q.set('region', params.region)
  if (params.search) q.set('search', params.search)
  if (params.is_active) q.set('is_active', params.is_active)
  return apiFetch(`/org/branches/?${q.toString()}`)
}

export function createBranch(payload: Record<string, unknown>): Promise<OrgBranch> {
  return apiFetch('/org/branches/', { method: 'POST', body: JSON.stringify(payload) })
}

export function fetchOrgShifts(params: {
  page?: number
  page_size?: number
  search?: string
  branch?: string
}): Promise<ListResp<OrgShift>> {
  const q = new URLSearchParams()
  if (params.page) q.set('page', String(params.page))
  if (params.page_size) q.set('page_size', String(params.page_size))
  if (params.search) q.set('search', params.search)
  if (params.branch) q.set('branch', params.branch)
  return apiFetch(`/scheduling/shifts/?${q.toString()}`)
}

export function createShift(payload: Record<string, unknown>): Promise<OrgShift> {
  return apiFetch('/scheduling/shifts/', { method: 'POST', body: JSON.stringify(payload) })
}

export function bulkUpsertBranches(items: Record<string, unknown>[], dryRun: boolean): Promise<BulkReport> {
  return apiFetch('/org/branches/bulk/', {
    method: 'POST',
    body: JSON.stringify({ items, dry_run: dryRun }),
  })
}

export function bulkUpsertShifts(items: Record<string, unknown>[], dryRun: boolean): Promise<BulkReport> {
  return apiFetch('/scheduling/shifts/bulk/', {
    method: 'POST',
    body: JSON.stringify({ items, dry_run: dryRun }),
  })
}

// ---------------------------------------------------------------------------
// LeaveLedger — tracked balances per (employee, leave_type), section 11
// ---------------------------------------------------------------------------
export interface LeaveBalanceRow {
  leave_type: string
  leave_type_name: string
  is_hourly: boolean
  tracked: boolean
  balance_minutes: number | null
  entries: number
  last_basis_date: string | null
}

export interface BalancesResp {
  employee: { id: number; personnel_code: string; full_name: string } | null
  balances: LeaveBalanceRow[]
}

export interface LedgerEntry {
  id: number
  leave_type: string
  leave_type_name: string
  entry_kind: string
  minutes: number
  balance_after_minutes: number
  basis_date: string
  source_type: string
}

export function fetchLeaveBalances(employeePc?: string): Promise<BalancesResp> {
  return apiFetch(`/leaves/ledger/balances/${employeePc ? `?employee=${encodeURIComponent(employeePc)}` : ''}`)
}

export function fetchLedger(employeePc: string): Promise<{ count: number; results: LedgerEntry[] }> {
  return apiFetch(`/leaves/ledger/?employee=${encodeURIComponent(employeePc)}`)
}

export function seedLedger(
  items: { personnel_code: string; leave_type: string; minutes: number; basis_date?: string; entry_kind?: string }[],
  dryRun: boolean,
): Promise<BulkReport> {
  return apiFetch('/leaves/ledger/seed/', {
    method: 'POST',
    body: JSON.stringify({ items, dry_run: dryRun }),
  })
}

export function adjustLedger(payload: {
  personnel_code: string
  leave_type: string
  minutes: number
  basis_date?: string
}): Promise<LedgerEntry> {
  return apiFetch('/leaves/ledger/adjust/', { method: 'POST', body: JSON.stringify(payload) })
}

// ---------------------------------------------------------------------------
// Messaging — direct conversations, chat, notification inbox (§12 v1)
// ---------------------------------------------------------------------------
export interface PartnerRow {
  id: number
  personnel_code: string
  full_name: string
  job_title: string
  branch_name: string
}

export interface ConvPartner {
  id: number
  personnel_code: string
  full_name: string
  branch_name: string
}

export interface ConvLastMessage {
  body: string
  sender_id: number
  mine: boolean
  created_at: string
}

export interface ConversationRow {
  id: number
  kind: string
  partner: ConvPartner | null
  last_message: ConvLastMessage | null
  unread_count: number
}

export interface ChatMessage {
  id: number
  body: string
  sender_id: number
  mine: boolean
  created_at: string
  read_at: string | null
}

export interface ThreadResp {
  conversation: ConversationRow
  results: ChatMessage[]
}

export interface NotificationRow {
  id: number
  kind: string
  title: string
  payload: Record<string, unknown>
  read: boolean
  created_at: string
}

export interface UnreadBadge {
  messages: number
  notifications: number
}

export function fetchPartners(): Promise<{ count: number; results: PartnerRow[] }> {
  return apiFetch('/messages/partners/')
}

export function fetchConversations(): Promise<{ count: number; results: ConversationRow[] }> {
  return apiFetch('/messages/conversations/')
}

export function openConversation(partnerId: number): Promise<ConversationRow> {
  return apiFetch('/messages/conversations/', {
    method: 'POST',
    body: JSON.stringify({ partner_id: partnerId }),
  })
}

export function fetchThread(convId: number): Promise<ThreadResp> {
  return apiFetch(`/messages/conversations/${convId}/messages/`)
}

export function sendMessage(convId: number, body: string, clientUuid?: string): Promise<ChatMessage> {
  return apiFetch(`/messages/conversations/${convId}/send/`, {
    method: 'POST',
    body: JSON.stringify({ body, ...(clientUuid ? { client_uuid: clientUuid } : {}) }),
  })
}

export function fetchNotifications(): Promise<{ count: number; unread: number; results: NotificationRow[] }> {
  return apiFetch('/messages/notifications/')
}

export function markAllNotificationsRead(): Promise<{ marked: number }> {
  return apiFetch('/messages/notifications/read-all/', { method: 'POST' })
}

export function fetchUnreadBadge(): Promise<UnreadBadge> {
  return apiFetch('/messages/notifications/unread/')
}

/** Ask the Layout to refresh the unread badge immediately (after read). */
export function pokeBadge(): void {
  window.dispatchEvent(new Event('rose:refresh-badge'))
}


// ---------------------------------------------------------------------------
// مدیریت پرسنل و کاربران (خارج از پنل ادمین) — فقط HR/ADMIN/superuser
// ---------------------------------------------------------------------------
export interface MgmtUserRef {
  id: number
  username: string
  is_active: boolean
  is_staff: boolean
  last_login: string | null
}

export interface MgmtPersonnelRow {
  id: number
  personnel_code: string
  first_name: string
  last_name: string
  full_name: string
  mobile: string
  national_id: string
  job_title: string
  employment_status: string
  hired_on: string | null
  home_branch_id: number
  home_branch_code: string
  home_branch_name: string
  user: MgmtUserRef | null
}

export interface MgmtUserRow {
  id: number
  username: string
  is_active: boolean
  is_staff: boolean
  is_superuser: boolean
  last_login: string | null
  failed_attempts: number
  is_locked: boolean
  employee: { id: number; personnel_code: string; full_name: string } | null
}

export interface SeedDemoReport {
  created: number
  skipped: number
  password: string
  branch: { code: string; name: string }
  first_username: string | null
  last_username: string | null
  note: string
}

export interface MgmtPersonnelPayload {
  personnel_code: string
  first_name: string
  last_name: string
  mobile?: string
  national_id?: string
  job_title?: string
  employment_status?: string
  hired_on?: string | null
  home_branch_id?: number | null
  username?: string
  password?: string
  is_staff?: boolean
}

export function fetchMgmtPersonnel(q: string): Promise<{ count: number; results: MgmtPersonnelRow[] }> {
  return apiFetch(`/management/personnel/?q=${encodeURIComponent(q)}`)
}

export function createMgmtPersonnel(payload: MgmtPersonnelPayload): Promise<MgmtPersonnelRow> {
  return apiFetch('/management/personnel/', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateMgmtPersonnel(
  id: number,
  payload: Partial<MgmtPersonnelPayload> & { user_id?: number | null },
): Promise<MgmtPersonnelRow> {
  return apiFetch(`/management/personnel/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) })
}

export function createPersonnelUser(
  id: number,
  payload: { username: string; password: string; is_staff?: boolean },
): Promise<MgmtUserRef> {
  return apiFetch(`/management/personnel/${id}/create-user/`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchMgmtUsers(q: string): Promise<{ count: number; results: MgmtUserRow[] }> {
  return apiFetch(`/management/users/?q=${encodeURIComponent(q)}`)
}

export function updateMgmtUser(
  id: number,
  payload: { is_active?: boolean; is_staff?: boolean; username?: string },
): Promise<MgmtUserRow> {
  return apiFetch(`/management/users/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) })
}

export function setMgmtUserPassword(id: number, password: string): Promise<{ detail: string }> {
  return apiFetch(`/management/users/${id}/set-password/`, {
    method: 'POST',
    body: JSON.stringify({ password }),
  })
}

export function seedDemoPersonnel(count: number, password: string): Promise<SeedDemoReport> {
  return apiFetch('/management/seed-demo/', {
    method: 'POST',
    body: JSON.stringify({ count, password }),
  })
}
