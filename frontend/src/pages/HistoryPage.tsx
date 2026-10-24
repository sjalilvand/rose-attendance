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

/** کارکرد روزانه به‌صورت جدول — ماه شمسی جاری و دو ماه قبل (پنجره سه‌ماهه مصوب). */
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

      {rows !== null && rows.length > 0 && (
        <section className="card">
          <div className="table-scroll">
            <table className="data-table daily-table">
              <thead>
                <tr>
                  <th>تاریخ</th>
                  <th>شیفت</th>
                  <th>ورود</th>
                  <th>خروج</th>
                  <th>کارکرد</th>
                  <th>استراحت</th>
                  <th>تأخیر</th>
                  <th>تعجیل</th>
                  <th>اضافه‌کاری</th>
                  <th>غیبت</th>
                  <th>وضعیت</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const overtimeTotal = row.overtime_approved_minutes || row.overtime_proposed_minutes
                  const proposedExtra = row.overtime_proposed_minutes > row.overtime_approved_minutes
                  return (
                    <tr key={`${row.shift_date}-${row.shift_code ?? 'x'}`}>
                      <td>{formatJalaliDate(row.shift_date)}</td>
                      <td>{row.shift_code ?? '—'}</td>
                      <td>{formatTime(row.first_in)}</td>
                      <td>{formatTime(row.last_out)}</td>
                      <td>{minutesToHM(row.accepted_work_minutes)}</td>
                      <td>{minutesToHM(row.rest_minutes)}</td>
                      <td>{row.late_minutes > 0 ? minutesToHM(row.late_minutes) : '—'}</td>
                      <td>{row.early_leave_minutes > 0 ? minutesToHM(row.early_leave_minutes) : '—'}</td>
                      <td>
                        {overtimeTotal ? (
                          <>
                            {minutesToHM(overtimeTotal)}
                            {proposedExtra && (
                              <span
                                className="ot-star"
                                title={`${faDigits(row.overtime_proposed_minutes)} دقیقه پیشنهاد — در انتظار تأیید`}
                              >
                                *
                              </span>
                            )}
                          </>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td>{row.absence_minutes > 0 ? minutesToHM(row.absence_minutes) : '—'}</td>
                      <td>
                        <div className="cell-chips">
                          {row.is_holiday && <Chip value="HOLIDAY" />}
                          {row.shift_code ? (
                            <span className="chip chip-muted">{row.shift_code}</span>
                          ) : (
                            <Chip value="PENDING" />
                          )}
                          {row.incomplete_sessions > 0 && <Chip value="OPEN" />}
                          {row.flags.includes('ABSENT') && <Chip value="ABSENT" />}
                          {row.flags
                            .filter((f) => f.startsWith('LATE') || f.startsWith('EARLY'))
                            .map((f) => (
                              <Chip key={f} value={f} />
                            ))}
                          {Object.entries(row.leave_minutes_by_type).map(([code, minutes]) => (
                            <span key={code} className="chip chip-info">
                              مرخصی {code}: {faDigits(minutes)} دقیقه
                            </span>
                          ))}
                          {row.mission_minutes > 0 && (
                            <span className="chip chip-info">مأموریت: {faDigits(row.mission_minutes)} دقیقه</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="daily-note">
            * اضافه‌کاری پیشنهادشده هنوز تأیید نشده است. «—» یعنی صفر یا موردی ثبت نشده. وضعیت مرخصی/مأموریت/پرچم‌های روز در ستون «وضعیت» آمده.
          </p>
        </section>
      )}
    </div>
  )
}
