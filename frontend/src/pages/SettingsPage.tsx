import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { clockOffsetMinutes, measureClockOffset } from '../lib/api'
import { flushQueue } from '../lib/sync'
import { queueCount } from '../lib/db'
import { faDigits } from '../lib/jalali'

export default function SettingsPage() {
  const navigate = useNavigate()
  const { me, logout } = useAuth()
  const [offset, setOffset] = useState<number | null>(null)
  const [pending, setPending] = useState(0)
  const [message, setMessage] = useState<string | null>(null)

  async function refreshLocal() {
    setPending(await queueCount())
  }

  useEffect(() => {
    void refreshLocal()
    setOffset(clockOffsetMinutes())
  }, [])

  return (
    <div className="page">
      <section className="card">
        <h1 className="h3">حساب</h1>
        {me && (
          <dl className="kv">
            <dt>نام</dt>
            <dd>{me.employee?.full_name ?? '—'}</dd>
            <dt>کد پرسنلی</dt>
            <dd className="mono">{me.employee ? faDigits(me.employee.personnel_code) : '—'}</dd>
            <dt>نقش‌ها</dt>
            <dd>{me.roles.map(faDigits).join('، ') || '—'}</dd>
            <dt>شعب مجاز</dt>
            <dd>
              {me.branches.map((b) => `${b.name}${b.is_home ? ' (اصلی)' : ''}`).join('، ') || '—'}
            </dd>
          </dl>
        )}
      </section>

      <section className="card">
        <h2 className="h3">ساعت و همگام‌سازی</h2>
        <p className="hint">
          اختلاف ساعت دستگاه با سرور برای پرچم CLOCK_SKEW استفاده می‌شود (آستانه ±۵ دقیقه، مصوب ۲٫۱).
        </p>
        <dl className="kv">
          <dt>اختلاف ساعت</dt>
          <dd>{offset === null ? '—' : `${faDigits(offset)} دقیقه`}</dd>
          <dt>صف آفلاین</dt>
          <dd>{faDigits(pending)} ثبت</dd>
        </dl>
        <div className="row">
          <button
            className="btn ghost"
            onClick={async () => {
              try {
                const ms = await measureClockOffset()
                setOffset(Math.round(ms / 60000))
                setMessage('اختلاف ساعت دوباره اندازه‌گیری شد.')
              } catch {
                setMessage('اندازه‌گیری ناموفق؛ آنلاین نیستید.')
              }
            }}
          >
            اندازه‌گیری مجدد ساعت
          </button>
          <button
            className="btn ghost"
            onClick={async () => {
              const res = await flushQueue()
              await refreshLocal()
              setMessage(res.processed > 0 ? `${faDigits(res.processed)} ثبت همگام شد.` : 'صف خالی است.')
            }}
          >
            همگام‌سازی صف
          </button>
        </div>
        {message && <div className="banner info">{message}</div>}
      </section>

      <section className="card">
        <h2 className="h3">حریم خصوصی</h2>
        <p className="hint">
          سامانه موقعیت را فقط در لحظه ثبت تردد و برای نمایش برچسب «در محدوده / خارج محدوده»
          می‌پرسد؛ هیچ ردیابی مستمر GPS انجام نمی‌شود و ثبت بدون موقعیت نیز مجاز است (اصول سند ۲٫۱).
        </p>
        <button
          className="btn danger"
          onClick={() => {
            logout()
            navigate('/login', { replace: true })
          }}
        >
          خروج از حساب
        </button>
      </section>
    </div>
  )
}
