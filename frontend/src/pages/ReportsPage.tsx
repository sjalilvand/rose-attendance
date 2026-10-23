import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import {
  downloadMonthlyReport,
  fetchMonthlyPreview,
  fetchOrgBranches,
  type MonthlyPreview,
  type OrgBranch,
} from '../lib/api'
import { JALALI_MONTHS, faDigits, jalaliMonthName, jalaliToday, minutesToHM } from '../lib/jalali'

const HR_ROLES = ['HR', 'ADMIN']

const TOTAL_CARDS: [keyof MonthlyPreview['totals'], string][] = [
  ['employees', 'پرسنل'],
  ['required_minutes', 'دقیقه لازم'],
  ['accepted_work_minutes', 'کار پذیرفته'],
  ['late_minutes', 'تأخیر'],
  ['early_leave_minutes', 'تعجیل'],
  ['absence_minutes', 'غیبت'],
  ['shortage_minutes', 'کسری'],
  ['overtime_minutes', 'اضافه‌کار'],
  ['mission_minutes', 'مأموریت'],
  ['leave_minutes', 'مرخصی'],
  ['final_count', 'نهایی‌شده'],
]

export default function ReportsPage() {
  const { me } = useAuth()
  const today = jalaliToday()
  const [jy, setJy] = useState(today.jy)
  const [jm, setJm] = useState(today.jm)
  const [branch, setBranch] = useState('')
  const [branches, setBranches] = useState<OrgBranch[]>([])
  const [preview, setPreview] = useState<MonthlyPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    fetchOrgBranches({ page_size: 200 })
      .then((d) => setBranches(d.results))
      .catch(() => setBranches([]))
  }, [])

  if (!me || !me.roles.some((role) => HR_ROLES.includes(role))) {
    return (
      <div className="page">
        <section className="card">
          <h1 className="h3">گزارش‌های HR</h1>
          <p className="hint">این صفحه مخصوص منابع انسانی است.</p>
        </section>
      </div>
    )
  }

  const years = [today.jy - 2, today.jy - 1, today.jy].map(String)

  const runPreview = async () => {
    setBusy(true)
    setError(null)
    try {
      setPreview(await fetchMonthlyPreview(jy, jm, branch || undefined))
      setLoaded(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در تهیهٔ پیش‌نمایش')
    } finally {
      setBusy(false)
    }
  }

  const runDownload = async () => {
    setBusy(true)
    setError(null)
    try {
      await downloadMonthlyReport(jy, jm, branch || undefined)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'دانلود گزارش ناموفق بود')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <section className="card">
        <h1 className="h3">گزارش ماهانهٔ HR</h1>
        <p className="hint">
          دورهٔ شمسی را انتخاب کنید؛ «بروزرسانی» ابتدا همهٔ ردیف‌های (پرسنل × شعبه) دوره را از نو
          محاسبه می‌کند و بعد مجموع‌ها را نشان می‌دهد. «دانلود Excel» همان محاسبهٔ تازه را در یک
          فایل سه‌برگه‌ای (خلاصهٔ ماهانه، ماندهٔ مرخصی، راهنما) می‌دهد.
        </p>
        <div className="grid3">
          <label className="field-row">
            <span>سال شمسی</span>
            <select value={jy} onChange={(e) => setJy(Number(e.target.value))}>
              {years.map((y) => (
                <option key={y} value={y}>{faDigits(y)}</option>
              ))}
            </select>
          </label>
          <label className="field-row">
            <span>ماه</span>
            <select value={jm} onChange={(e) => setJm(Number(e.target.value))}>
              {JALALI_MONTHS.map((name, i) => (
                <option key={name} value={i + 1}>{faDigits(i + 1)} — {name}</option>
              ))}
            </select>
          </label>
          <label className="field-row">
            <span>شعبه</span>
            <select value={branch} onChange={(e) => setBranch(e.target.value)}>
              <option value="">همهٔ شعب</option>
              {branches.map((b) => (
                <option key={b.code} value={b.code}>{b.code} — {b.name}</option>
              ))}
            </select>
          </label>
        </div>
        <div className="import-actions">
          <button className="btn primary" type="button" disabled={busy} onClick={() => void runPreview()}>
            {busy ? 'در حال محاسبه…' : 'بروزرسانی و نمایش'}
          </button>
          <button className="btn" type="button" disabled={busy} onClick={() => void runDownload()}>
            دانلود گزارش Excel
          </button>
        </div>
        {error && <p className="import-error">{error}</p>}
      </section>

      {preview && (
        <section className="card">
          <h2 className="h3">
            مجموع‌های {jalaliMonthName(preview.period.jm)} {faDigits(preview.period.jy)}
            {preview.branch ? ` — شعبهٔ ${preview.branch}` : ''}
          </h2>
          <div className="stat-chips">
            {TOTAL_CARDS.map(([key, label]) => (
              <span key={key} className={`chip${key === 'shortage_minutes' && preview.totals[key] > 0 ? ' chip-danger' : ' chip-info'}`}>
                {label}: {typeof preview.totals[key] === 'number' && String(key).endsWith('_minutes')
                  ? minutesToHM(preview.totals[key] as number)
                  : faDigits(preview.totals[key] as number)}
              </span>
            ))}
          </div>
          {preview.by_branch.length > 0 && (
            <table className="data-table">
              <thead>
                <tr>
                  <th>شعبه</th>
                  <th>پرسنل</th>
                  <th>لازم</th>
                  <th>کار پذیرفته</th>
                  <th>تأخیر</th>
                  <th>غیبت</th>
                  <th>کسری</th>
                  <th>اضافه‌کار</th>
                  <th>مرخصی</th>
                </tr>
              </thead>
              <tbody>
                {preview.by_branch.map((row) => (
                  <tr key={row.branch}>
                    <td className="mono">{row.branch}</td>
                    <td>{faDigits(row.employees)}</td>
                    <td>{minutesToHM(row.required_minutes)}</td>
                    <td>{minutesToHM(row.accepted_work_minutes)}</td>
                    <td>{minutesToHM(row.late_minutes)}</td>
                    <td>{minutesToHM(row.absence_minutes)}</td>
                    <td>{minutesToHM(row.shortage_minutes)}</td>
                    <td>{minutesToHM(row.overtime_minutes)}</td>
                    <td>{minutesToHM(row.leave_minutes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      {!preview && loaded && (
        <section className="card">
          <p className="hint">ردیفی برای این دوره/شعبه یافت نشد.</p>
        </section>
      )}
    </div>
  )
}
