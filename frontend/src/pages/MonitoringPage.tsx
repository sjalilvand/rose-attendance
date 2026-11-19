/** مانیتورینگ وب — دید زندهٔ عملیاتی برای تیم مدیریت (نسخهٔ دسکتاپ).
 * KPI امروز، حاضرانِ الان، جریان زندهٔ ترددها، انحراف‌های GPS و غایبان؛
 * خودکار تازه‌سازی هر ۳۰ ثانیه + فیلتر شعبه. دسترسی HR/ADMIN/مدیران/حسابرس. */
import { useCallback, useEffect, useState } from 'react'
import {
  ApiError,
  fetchMonitoringDashboard,
  fetchOrgBranches,
  type MonitoringDashboard,
  type OrgBranch,
} from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { faDigits, formatTime } from '../lib/jalali'

const MONITORING_ROLES = ['HR', 'ADMIN', 'REGION_MANAGER', 'AUDITOR', 'BRANCH_MANAGER']

function errMsg(e: unknown): string {
  return e instanceof ApiError ? e.message : 'خطای شبکه'
}

function meters(value: number | null): string {
  if (value == null) return '—'
  if (value >= 1000) return `${faDigits((value / 1000).toFixed(1))} کیلومتر`
  return `${faDigits(Math.round(value))} متر`
}

function locChip(status: string): { label: string; cls: string } {
  switch (status) {
    case 'IN_RANGE':
      return { label: 'در محدوده', cls: 'chip-ok' }
    case 'OUT_OF_RANGE':
      return { label: 'خارج از محدوده', cls: 'chip-danger' }
    case 'LOW_ACCURACY':
      return { label: 'دقت پایین', cls: 'chip-warn' }
    default:
      return { label: 'بدون موقعیت', cls: 'chip-muted' }
  }
}

export default function MonitoringPage() {
  const { me } = useAuth()
  const allowed = Boolean(me && me.roles.some((r) => MONITORING_ROLES.includes(r)))
  const [data, setData] = useState<MonitoringDashboard | null>(null)
  const [branches, setBranches] = useState<OrgBranch[]>([])
  const [branch, setBranch] = useState('')
  const [auto, setAuto] = useState(true)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(async (code: string) => {
    setBusy(true)
    setErr(null)
    try {
      const d = await fetchMonitoringDashboard({ branch: code || undefined })
      setData(d)
    } catch (e) {
      setErr(errMsg(e))
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    if (!allowed) return
    void load(branch)
    fetchOrgBranches({ page_size: 200 })
      .then((r) => setBranches(r.results))
      .catch(() => setBranches([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allowed])

  useEffect(() => {
    if (!auto || !allowed) return
    const id = window.setInterval(() => void load(branch), 30000)
    return () => window.clearInterval(id)
  }, [auto, branch, load, allowed])

  if (!allowed) {
    return (
      <div className="page">
        <section className="card">
          <div className="h">مانیتورینگ</div>
          <p className="hint">این صفحه مخصوص تیم مدیریت است.</p>
        </section>
      </div>
    )
  }

  const k = data?.kpis
  return (
    <div className="page wide">
      <section className="card">
        <div className="row between">
          <div className="h">مانیتورینگ حضور — {faDigits(data?.today ?? '')}</div>
          <div className="row-inline">
            <label className="check-label compact-label">
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
              تازه‌سازی خودکار (۳۰ث)
            </label>
            <button className="btn ghost" disabled={busy} onClick={() => void load(branch)}>
              {busy ? '…' : 'به‌روزرسانی'}
            </button>
          </div>
        </div>
        <div className="row-inline">
          <label className="compact-label grow">
            شعبه
            <select
              value={branch}
              onChange={(e) => {
                setBranch(e.target.value)
                void load(e.target.value)
              }}
            >
              <option value="">همهٔ شعب ({data ? faDigits(data.branches_in_scope) : '…'})</option>
              {branches.map((b) => (
                <option key={b.id} value={b.code}>
                  {b.code} — {b.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        {err && <div className="banner danger">{err}</div>}
        {k && (
          <div className="stat-chips kpi-chips">
            <span className="chip chip-info">پرسنل فعال: {faDigits(k.employees_active)}</span>
            <span className="chip chip-ok">حاضر الان: {faDigits(k.present_now)}</span>
            <span className="chip">تردد امروز: {faDigits(k.events_today)}</span>
            <span className="chip">افراد با تردد: {faDigits(k.with_events_today)}</span>
            <span className="chip chip-danger">خارج از محدوده: {faDigits(k.out_of_range_today)}</span>
            <span className="chip chip-warn">دقت پایین: {faDigits(k.low_accuracy_today)}</span>
            <span className="chip chip-muted">بدون GPS: {faDigits(k.no_gps_today)}</span>
            <span className="chip chip-warn">نیازمند رسیدگی: {faDigits(k.needs_review_today)}</span>
            <span className="chip chip-muted">غایب: {faDigits(data?.absent_total ?? 0)}</span>
          </div>
        )}
      </section>

      <section className="card">
        <div className="h">حاضرانِ الان ({faDigits(data?.present_now.length ?? 0)})</div>
        {data && data.present_now.length === 0 && <div className="muted">کسی در بازهٔ باز نیست.</div>}
        {data && data.present_now.length > 0 && (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>پرسنل</th>
                  <th>کد</th>
                  <th>شعبه</th>
                  <th>ورود</th>
                  <th>کارکرد تا الان</th>
                </tr>
              </thead>
              <tbody>
                {data.present_now.map((p) => (
                  <tr key={`${p.personnel_code}-${p.branch}`}>
                    <td>{p.employee}</td>
                    <td className="mono">{p.personnel_code}</td>
                    <td>
                      <span className="chip chip-info">{p.branch}</span> {p.branch_name}
                    </td>
                    <td className="mono">{p.check_in_at ? formatTime(p.check_in_at) : '—'}</td>
                    <td className="mono">
                      {p.minutes_so_far != null ? `${faDigits(p.minutes_so_far)} دقیقه` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <div className="h">انحراف‌های GPS امروز ({faDigits(data?.deviations_today.length ?? 0)})</div>
        <p className="hint">
          ترددهای «خارج از محدوده» یا «دقت پایین» — فاصله تا مرکز اداره با متر مشخص است؛ ثبت رد
          نمی‌شود و برای تصمیم مدیریت می‌ماند (تصمیم مصوب ۳).
        </p>
        {data && data.deviations_today.length === 0 && <div className="muted">انحرافی ثبت نشده است.</div>}
        {data && data.deviations_today.length > 0 && (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>زمان</th>
                  <th>پرسنل</th>
                  <th>کد</th>
                  <th>شعبه</th>
                  <th>نوع</th>
                  <th>وضعیت</th>
                  <th>فاصله</th>
                  <th>دقت GPS</th>
                </tr>
              </thead>
              <tbody>
                {data.deviations_today.map((e) => {
                  const chip = locChip(e.location_status)
                  return (
                    <tr key={e.event_uuid}>
                      <td className="mono">{formatTime(e.effective_time)}</td>
                      <td>{e.employee}</td>
                      <td className="mono">{e.personnel_code}</td>
                      <td>
                        <span className="chip chip-info">{e.branch}</span> {e.branch_name}
                      </td>
                      <td>{e.event_type === 'CHECK_IN' ? 'ورود' : 'خروج'}</td>
                      <td>
                        <span className={`chip ${chip.cls}`}>{chip.label}</span>
                      </td>
                      <td className="mono">{meters(e.location_distance_m)}</td>
                      <td className="mono">{meters(e.location_accuracy_m)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <div className="h">جریان زندهٔ ترددها (آخرین ۵۰ رویداد)</div>
        {data && data.live_events.length === 0 && <div className="muted">ترددی ثبت نشده است.</div>}
        {data && data.live_events.length > 0 && (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>زمان</th>
                  <th>پرسنل</th>
                  <th>کد</th>
                  <th>شعبه</th>
                  <th>نوع</th>
                  <th>موقعیت</th>
                  <th>فاصله</th>
                  <th>وضعیت ردیف</th>
                </tr>
              </thead>
              <tbody>
                {data.live_events.map((e) => {
                  const chip = locChip(e.location_status)
                  return (
                    <tr key={e.event_uuid}>
                      <td className="mono">{formatTime(e.effective_time)}</td>
                      <td>{e.employee}</td>
                      <td className="mono">{e.personnel_code}</td>
                      <td>
                        <span className="chip chip-info">{e.branch}</span> {e.branch_name}
                      </td>
                      <td>{e.event_type === 'CHECK_IN' ? 'ورود' : 'خروج'}</td>
                      <td>
                        <span className={`chip ${chip.cls}`}>{chip.label}</span>
                      </td>
                      <td className="mono">{meters(e.location_distance_m)}</td>
                      <td>
                        <span className={`chip ${e.event_status === 'ACCEPTED' ? 'chip-ok' : 'chip-warn'}`}>
                          {e.event_status === 'ACCEPTED' ? 'پذیرفته' : 'رسیدگی'}
                        </span>
                        {e.connection_mode === 'OFFLINE_SYNC' && (
                          <span className="chip chip-muted">آفلاین</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <div className="h">
          غایب امروز — بدون هیچ ترددی ({faDigits(data?.absent_today.length ?? 0)}
          {data && data.absent_total > data.absent_today.length
            ? ` از ${faDigits(data.absent_total)}`
            : ''}
          )
        </div>
        {data && data.absent_today.length === 0 && <div className="muted">غایبی نیست.</div>}
        {data && data.absent_today.length > 0 && (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>پرسنل</th>
                  <th>کد</th>
                  <th>شعبهٔ اصلی</th>
                </tr>
              </thead>
              <tbody>
                {data.absent_today.map((a) => (
                  <tr key={a.personnel_code}>
                    <td>{a.employee}</td>
                    <td className="mono">{a.personnel_code}</td>
                    <td>
                      <span className="chip chip-info">{a.home_branch}</span> {a.home_branch_name}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="hint">
          «غایب» فقط یعنی امروز هیچ ترددی ثبت نکرده؛ مرخصی/مأموریت باید جداگانه دیده شود.
        </p>
      </section>
    </div>
  )
}
