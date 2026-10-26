import { useRef, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { downloadImportTemplate, importPersonnel, type ImportReport } from '../lib/api'

const HR_ROLES = ['HR', 'ADMIN']

const COLUMN_GUIDE: [string, string][] = [
  ['personnel_code', 'الزامی — کلید یکتا؛ ردیف تکراری یعنی به‌روزرسانی'],
  ['first_name / last_name', 'الزامی'],
  ['branch_code', 'الزامی — کد شعبهٔ موجود (شعبه ساخته نمی‌شود)'],
  ['shift_code', 'اختیاری — الگوی شیفت سطح شعبه (کد IMP-...)'],
  ['hired_on', 'اختیاری — تاریخ شمسی مثل 1404/01/15'],
  ['national_id / mobile / job_title', 'اختیاری'],
  ['employment_status', 'ACTIVE / SUSPENDED / TERMINATED — پیش‌فرض ACTIVE'],
]

export default function ImportPage() {
  const { me } = useAuth()
  const [file, setFile] = useState<File | null>(null)
  const [dryRun, setDryRun] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [report, setReport] = useState<ImportReport | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  if (!me || !me.roles.some((role) => HR_ROLES.includes(role))) {
    return (
      <div className="page">
        <section className="card">
          <h1 className="h3">ورود گروهی پرسنل</h1>
          <p className="hint">این صفحه مخصوص منابع انسانی است.</p>
        </section>
      </div>
    )
  }

  const submit = async () => {
    if (!file || busy) return
    setBusy(true)
    setError(null)
    setReport(null)
    try {
      setReport(await importPersonnel(file, dryRun))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'خطای نامشخص')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <section className="card">
        <h1 className="h3">ورود گروهی پرسنل</h1>
        <p className="hint">
          فایل Excel (xlsx) را با قالب زیر بارگذاری کنید. «بررسی بدون ثبت» فقط اعتبارسنجی می‌کند و
          چیزی ذخیره نمی‌شود؛ پس از اطمینان، همان فایل را بدون این گزینه ثبت کنید.
        </p>
        <div className="import-grid">
          <label className="field-row">
            <span>فایل</span>
            <input
              ref={inputRef}
              type="file"
              accept=".xlsx"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null)
                setReport(null)
                setError(null)
              }}
            />
          </label>
          <label className="field-row checkbox">
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
            />
            <span>بررسی بدون ثبت (dry run)</span>
          </label>
          <div className="import-actions">
            <button className="btn primary" type="button" disabled={!file || busy} onClick={() => void submit()}>
              {busy ? 'در حال پردازش…' : dryRun ? 'بررسی فایل' : 'ثبت نهایی'}
            </button>
            <button
              className="btn ghost"
              type="button"
              disabled={busy}
              onClick={() => void downloadImportTemplate()}
            >
              دانلود قالب Excel
            </button>
          </div>
          {error && <p className="import-error">{error}</p>}
        </div>
      </section>

      {report && (
        <section className="card">
          <h2 className="h3">{report.dry_run ? 'نتیجهٔ بررسی' : 'نتیجهٔ ثبت'}</h2>
          <div className="stat-chips">
            <span className="chip chip-info">{report.total} ردیف</span>
            <span className="chip chip-ok">{report.created} جدید</span>
            <span className="chip">{report.updated} به‌روزرسانی</span>
            {report.skipped > 0 && <span className="chip chip-danger">{report.skipped} خطا</span>}
            {report.dry_run && <span className="chip chip-warn">بدون ثبت</span>}
          </div>
          {report.errors.length > 0 && (
            <table className="err-table">
              <thead>
                <tr>
                  <th>ردیف</th>
                  <th>کد پرسنلی</th>
                  <th>خطا</th>
                </tr>
              </thead>
              <tbody>
                {report.errors.map((e, i) => (
                  <tr key={`${e.row}-${i}`}>
                    <td>{e.row}</td>
                    <td className="mono">{e.personnel_code || '—'}</td>
                    <td>{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      <section className="card">
        <h2 className="h3">ستون‌های قالب</h2>
        <dl className="kv">
          {COLUMN_GUIDE.map(([name, desc]) => (
            <div key={name} className="guide-row">
              <dt className="mono">{name}</dt>
              <dd>{desc}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  )
}
