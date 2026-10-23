import { useEffect, useState } from 'react'
import Chip from '../components/Chip'
import { ApiError, fetchSummaries, type SummaryRow } from '../lib/api'
import { faDigits, jalaliMonthName, minutesToHM } from '../lib/jalali'

/** خلاصه ماهانه — ردیف‌های پرسنل × شعبه × ماه شمسی؛ نگهداری حداقل ۲ سال
 * (تصمیم‌های مصوب ۱ و ۶) پس از پاکسازی جزئیات سه‌ماهه. */
export default function SummaryPage() {
  const [rows, setRows] = useState<SummaryRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchSummaries()
      .then((data) => setRows(data.results))
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : 'خطای شبکه')
        setRows([])
      })
  }, [])

  return (
    <div className="page">
      <section className="card">
        <h1 className="h3">خلاصه‌های ماهانه</h1>
        <p className="hint">
          خلاصه هر شعبه جداگانه ساخته می‌شود و مجموع فرد، جمع ردیف‌های شعبه‌ای است (بدون دوباره‌شماری).
        </p>
        {error && <div className="banner danger">{error}</div>}
      </section>

      {rows === null && <div className="card page-loading">در حال بارگذاری…</div>}
      {rows !== null && rows.length === 0 && (
        <div className="card muted">هنوز خلاصه‌ای برای شما تولید نشده است.</div>
      )}

      {rows?.map((row) => (
        <section className="card" key={row.id}>
          <div className="row between">
            <div className="h3">
              {jalaliMonthName(row.period_month)} {faDigits(row.period_year)}
            </div>
            <div className="chips">
              <span className="chip chip-muted">{row.branch}</span>
              <Chip value={row.summary_state} />
            </div>
          </div>
          <div className="day-grid">
            <Metric label="کارکرد قابل قبول" value={minutesToHM(row.accepted_work_minutes)} />
            <Metric label="موظفی" value={minutesToHM(row.required_minutes)} />
            <Metric label="تأخیر" value={minutesToHM(row.late_minutes)} />
            <Metric label="تعجیل" value={minutesToHM(row.early_leave_minutes)} />
            <Metric label="اضافه‌کاری تأییدشده" value={minutesToHM(row.overtime_minutes)} />
            <Metric label="غیبت" value={minutesToHM(row.absence_minutes)} />
            <Metric label="کسری کار" value={minutesToHM(row.shortage_minutes)} />
            <Metric label="مأموریت" value={minutesToHM(row.mission_minutes)} />
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
          <div className="chips">
            {row.incomplete_session_count > 0 && (
              <span className="chip chip-warn">تردد ناقص: {faDigits(row.incomplete_session_count)}</span>
            )}
            {row.out_of_range_count > 0 && (
              <span className="chip chip-warn">خارج محدوده: {faDigits(row.out_of_range_count)}</span>
            )}
            {row.no_location_count > 0 && (
              <span className="chip chip-muted">بدون موقعیت: {faDigits(row.no_location_count)}</span>
            )}
          </div>
        </section>
      ))}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <div className="metric-value">{value}</div>
      <div className="metric-label">{label}</div>
    </div>
  )
}
