import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import {
  downloadAnnualReport,
  downloadDisciplinaryReport,
  downloadMonthlyReport,
  fetchMonthlyPreview,
  fetchOrgBranches,
  fetchYearTrend,
  type MonthlyPreview,
  type OrgBranch,
  type YearTrend,
} from '../lib/api'
import { JALALI_MONTHS, faDigits, jalaliMonthName, jalaliToday, minutesToHM } from '../lib/jalali'

const HR_ROLES = ['HR', 'ADMIN']

const TOTAL_CARDS: [keyof MonthlyPreview['totals'], string][] = [
  ['employees', 'پرسنل'],
  ['required_minutes', 'دقیقه لازم'],
  ['accepted_work_minutes', 'کار پذیرفته'],
  ['late_minutes', 'تأخیر'],
  ['late_days', 'روز تأخیر'],
  ['early_leave_minutes', 'تعجیل'],
  ['absence_minutes', 'غیبت'],
  ['absence_days', 'روز غیبت'],
  ['shortage_minutes', 'کسری'],
  ['overtime_minutes', 'اضافه‌کار'],
  ['mission_minutes', 'مأموریت'],
  ['leave_minutes', 'مرخصی'],
  ['final_count', 'نهایی‌شده'],
]

/** نمودار میله‌ای SVG بدون وابستگی — دو ردیفه: کار پذیرفته و غیبت به‌تفکیک ماه */
function TrendChart({ trend }: { trend: YearTrend }) {
  const months = trend.months
  if (months.length === 0) return <p className="hint">داده‌ای برای نمودار نیست.</p>
  const W = 720
  const H = 240
  const PAD_X = 34
  const PAD_TOP = 14
  const PAD_BOTTOM = 34
  const plotW = W - PAD_X * 2
  const plotH = H - PAD_TOP - PAD_BOTTOM
  const maxVal = Math.max(
    1,
    ...months.map((m) => Math.max(m.accepted_work_minutes, m.absence_minutes)),
  )
  const groupW = plotW / months.length
  const barW = Math.min(20, groupW / 3.2)
  return (
    <svg
      className="trend-chart"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label="روند سالانه کار پذیرفته و غیبت"
    >
      {[0.25, 0.5, 0.75, 1].map((f) => (
        <g key={f}>
          <line
            x1={PAD_X}
            x2={W - PAD_X}
            y1={PAD_TOP + plotH * (1 - f)}
            y2={PAD_TOP + plotH * (1 - f)}
            className="trend-grid"
          />
          <text
            x={W - PAD_X + 4}
            y={PAD_TOP + plotH * (1 - f) + 4}
            className="trend-tick"
          >
            {faDigits(minutesToHM(maxVal * f))}
          </text>
        </g>
      ))}
      {months.map((m, i) => {
        const cx = PAD_X + groupW * i + groupW / 2
        const hWork = (m.accepted_work_minutes / maxVal) * plotH
        const hAbs = (m.absence_minutes / maxVal) * plotH
        return (
          <g key={m.jm}>
            <rect
              x={cx - barW - 2}
              y={PAD_TOP + plotH - hWork}
              width={barW}
              height={Math.max(hWork, 1)}
              rx={3}
              className="trend-bar-work"
            >
              <title>
                {`${m.month_name} — کار پذیرفته: ${minutesToHM(m.accepted_work_minutes)}`}
              </title>
            </rect>
            <rect
              x={cx + 2}
              y={PAD_TOP + plotH - hAbs}
              width={barW}
              height={Math.max(hAbs, 1)}
              rx={3}
              className="trend-bar-absence"
            >
              <title>
                {`${m.month_name} — غیبت: ${minutesToHM(m.absence_minutes)} (${faDigits(m.absence_days)} روز)`}
              </title>
            </rect>
            <text x={cx} y={H - PAD_BOTTOM + 16} className="trend-label" textAnchor="middle">
              {m.month_name}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

export default function ReportsPage() {
  const { me } = useAuth()
  const today = jalaliToday()
  const [jy, setJy] = useState(today.jy)
  const [jm, setJm] = useState(today.jm)
  const [branch, setBranch] = useState('')
  const [branches, setBranches] = useState<OrgBranch[]>([])
  const [preview, setPreview] = useState<MonthlyPreview | null>(null)
  const [trend, setTrend] = useState<YearTrend | null>(null)
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

  const runDisciplinary = async () => {
    setBusy(true)
    setError(null)
    try {
      await downloadDisciplinaryReport(jy, jm, branch || undefined)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'دانلود گزارش انتظامی ناموفق بود')
    } finally {
      setBusy(false)
    }
  }

  const runTrend = async () => {
    setBusy(true)
    setError(null)
    try {
      setTrend(await fetchYearTrend(jy, branch || undefined))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطا در تهیهٔ روند سالانه')
    } finally {
      setBusy(false)
    }
  }

  const runAnnualDownload = async () => {
    setBusy(true)
    setError(null)
    try {
      await downloadAnnualReport(jy, branch || undefined)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'دانلود گزارش سالانه ناموفق بود')
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
          فایل سه‌برگه‌ای (خلاصهٔ ماهانه، ماندهٔ مرخصی، راهنما) می‌دهد و «گزارش انتظامی» روزهای
          تأخیر/غیبت و کسری هر پرسنل را برمی‌گرداند.
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
          <button className="btn" type="button" disabled={busy} onClick={() => void runDisciplinary()}>
            گزارش انتظامی تأخیر/غیبت
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

      <section className="card">
        <h2 className="h3">روند سالانه</h2>
        <p className="hint">
          روند ۱۲ ماهِ سال شمسی بر پایهٔ خلاصه‌های ذخیره‌شدهٔ دوره‌ها (بدون محاسبهٔ مجدد) —
          برای محاسبهٔ مجدد کامل سال از دکمهٔ «محاسبهٔ مجدد سال» استفاده کنید. گزارش سالانهٔ
          Excel شامل برگه‌های «روند ماهانه» و «خلاصه سالانه پرسنل» است.
        </p>
        <div className="import-actions">
          <button className="btn primary" type="button" disabled={busy} onClick={() => void runTrend()}>
            نمایش روند سال {faDigits(String(jy))}
          </button>
          <button
            className="btn"
            type="button"
            disabled={busy}
            onClick={() => {
              if (window.confirm('محاسبهٔ مجدد ۱۲ ماه ممکن است کمی طول بکشد؛ ادامه می‌دهید؟')) {
                void (async () => {
                  setBusy(true)
                  setError(null)
                  try {
                    setTrend(await fetchYearTrend(jy, branch || undefined, true))
                  } catch (err) {
                    setError(err instanceof Error ? err.message : 'محاسبهٔ مجدد ناموفق بود')
                  } finally {
                    setBusy(false)
                  }
                })()
              }
            }}
          >
            محاسبهٔ مجدد سال
          </button>
          <button className="btn" type="button" disabled={busy} onClick={() => void runAnnualDownload()}>
            دانلود گزارش سالانهٔ Excel
          </button>
        </div>
        {trend && (
          <div className="trend-wrap">
            <TrendChart trend={trend} />
            <div className="stat-chips">
              <span className="chip chip-info">
                <span className="legend-dot legend-work" /> کار پذیرفته
              </span>
              <span className="chip chip-danger">
                <span className="legend-dot legend-absence" /> غیبت
              </span>
              <span className="chip chip-muted">پرسنل دارای رکورد: {faDigits(trend.totals.employees)}</span>
              <span className="chip chip-muted">روز تأخیر سال: {faDigits(trend.totals.late_days)}</span>
              <span className="chip chip-muted">روز غیبت سال: {faDigits(trend.totals.absence_days)}</span>
            </div>
            {trend.months.length > 0 && (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>ماه</th>
                    <th>پرسنل</th>
                    <th>لازم</th>
                    <th>کار پذیرفته</th>
                    <th>تأخیر</th>
                    <th>روز تأخیر</th>
                    <th>غیبت</th>
                    <th>روز غیبت</th>
                    <th>کسری</th>
                    <th>اضافه‌کار</th>
                    <th>مرخصی</th>
                  </tr>
                </thead>
                <tbody>
                  {trend.months.map((m) => (
                    <tr key={m.jm}>
                      <td>{m.month_name}</td>
                      <td>{faDigits(m.employees)}</td>
                      <td>{minutesToHM(m.required_minutes)}</td>
                      <td>{minutesToHM(m.accepted_work_minutes)}</td>
                      <td>{minutesToHM(m.late_minutes)}</td>
                      <td>{faDigits(m.late_days)}</td>
                      <td>{minutesToHM(m.absence_minutes)}</td>
                      <td>{faDigits(m.absence_days)}</td>
                      <td>{minutesToHM(m.shortage_minutes)}</td>
                      <td>{minutesToHM(m.overtime_minutes)}</td>
                      <td>{minutesToHM(m.leave_minutes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
