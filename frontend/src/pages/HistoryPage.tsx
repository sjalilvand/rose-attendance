import { useCallback, useEffect, useState } from 'react'
import Chip from '../components/Chip'
import { ApiError, fetchDaily, type DayRow } from '../lib/api'
import {
  faDigits,
  formatJalaliDate,
  formatTime,
  jalaliMonthName,
  jalaliToday,
  jalaliMonthRange,
  minutesToHM,
} from '../lib/jalali'

/** کارکرد روزانه — ماه شمسی جاری و دو ماه قبل (پنجره سه‌ماهه مصوب). */
export default function HistoryPage() {
  const today = jalaliToday()
  const [cursor, setCursor] = useState({ jy: today.jy, jm: today.jm })
  const [rows, setRows] = useState<DayRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setRows(null)
    setError(null)
    const { from, to } = jalaliMonthRange(cursor.jy, cursor.jm)
    try {
      const data = await fetchDaily(from, to)
      setRows(data.results)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'خطای شبکه')
      setRows([])
    }
  }, [cursor])

  useEffect(() => {
    void load()
  }, [load])

  function shiftMonth(delta: number) {
    setCursor((c) => {
      let jm = c.jm + delta
      let jy = c.jy
      if (jm === 0) {
        jm = 12
        jy -= 1
      }
      if (jm === 13) {
        jm = 1
        jy += 1
      }
      return { jy, jm }
    })
  }

  const isCurrentMonth = cursor.jy === today.jy && cursor.jm === today.jm

  return (
    <div className="page">
      <section className="card">
        <div className="row between">
          <button className="btn ghost" onClick={() => shiftMonth(-1)} aria-label="ماه قبل">
            › ماه قبل
          </button>
          <div className="h2">
            {jalaliMonthName(cursor.jm)} {faDigits(cursor.jy)}
          </div>
          <button className="btn ghost" onClick={() => shiftMonth(1)} disabled={isCurrentMonth}>
            ماه بعد ‹
          </button>
        </div>
        <p className="hint">جزئیات روزها تا سه ماه شمسی نگهداری می‌شود (تصمیم مصوب ۲).</p>
        {error && <div className="banner danger">{error}</div>}
      </section>

      {rows === null && <div className="card page-loading">در حال محاسبه روزها…</div>}

      {rows !== null && rows.length === 0 && (
        <div className="card muted">در این ماه رکوردی یافت نشد.</div>
      )}

      {rows?.map((row) => (
        <section className="card day-card" key={`${row.shift_date}-${row.shift_code ?? 'x'}`}>
          <div className="row between">
            <div className="h3">{formatJalaliDate(row.shift_date)}</div>
            <div className="chips">
              {row.is_holiday && <Chip value="HOLIDAY" />}
              {row.shift_code ? <span className="chip chip-muted">{row.shift_code}</span> : <Chip value="PENDING" />}
            </div>
          </div>
          <div className="day-grid">
            <Metric label="ورود" value={formatTime(row.first_in)} />
            <Metric label="خروج" value={formatTime(row.last_out)} />
            <Metric label="کارکرد" value={minutesToHM(row.accepted_work_minutes)} />
            <Metric label="استراحت" value={minutesToHM(row.rest_minutes)} />
            <Metric label="تأخیر" value={minutesToHM(row.late_minutes)} />
            <Metric label="تعجیل" value={minutesToHM(row.early_leave_minutes)} />
            <Metric
              label="اضافه‌کاری"
              value={minutesToHM(row.overtime_approved_minutes || row.overtime_proposed_minutes)}
              hint={
                row.overtime_proposed_minutes > row.overtime_approved_minutes
                  ? `${faDigits(row.overtime_proposed_minutes)} دقیقه پیشنهاد — در انتظار تأیید`
                  : undefined
              }
            />
            <Metric label="غیبت" value={minutesToHM(row.absence_minutes)} />
          </div>
          {Object.keys(row.leave_minutes_by_type).length > 0 && (
            <div className="chips">
              {Object.entries(row.leave_minutes_by_type).map(([code, minutes]) => (
                <span key={code} className="chip chip-info">
                  مرخصی {code}: {faDigits(minutes)} دقیقه
                </span>
              ))}
            </div>
          )}
          {row.mission_minutes > 0 && (
            <div className="chips">
              <span className="chip chip-info">مأموریت: {faDigits(row.mission_minutes)} دقیقه</span>
            </div>
          )}
          <div className="chips">
            {row.incomplete_sessions > 0 && <Chip value="OPEN" />}
            {row.flags.includes('ABSENT') && <Chip value="ABSENT" />}
            {row.flags
              .filter((f) => f.startsWith('LATE') || f.startsWith('EARLY'))
              .map((f) => (
                <Chip key={f} value={f} />
              ))}
          </div>
        </section>
      ))}
    </div>
  )
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="metric">
      <div className="metric-value">{value}</div>
      <div className="metric-label">{label}</div>
      {hint && <div className="metric-hint">{hint}</div>}
    </div>
  )
}
