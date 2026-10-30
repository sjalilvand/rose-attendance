import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, login } from '../lib/api'
import { useAuth } from '../context/AuthContext'

export default function LoginPage() {
  const navigate = useNavigate()
  const { loginDone } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username.trim(), password)
      await loginDone()
      navigate('/', { replace: true })
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === 'ACCOUNT_LOCKED') setError('حساب موقتاً قفل است؛ ۱۵ دقیقه بعد تلاش کنید.')
        else if (err.status === 401 || err.status === 400) setError('نام کاربری یا گذرواژه نادرست است.')
        else setError(err.message)
      } else {
        setError('خطای شبکه؛ اتصال خود را بررسی کنید.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="card login-card" onSubmit={onSubmit}>
        <div className="login-brand">
          <span className="brand-mark big" aria-hidden>✿</span>
          <h1>رز سفید</h1>
          <p>سامانه حضور و غیاب — ثبت تردد بدون ردیابی مستمر GPS</p>
        </div>
        <a
          href="http://130.185.73.157:8082/api/sso/launch?clientId=rose-techno-8a4e1f"
          className="btn btn-primary"
          style={{
            display: 'block',
            textAlign: 'center',
            marginBottom: '14px',
            background: '#be185d',
            color: '#fff',
            textDecoration: 'none',
            padding: '10px 14px',
            borderRadius: '8px',
          }}
        >
          ورود یکپارچه با رز هاب (SSO)
        </a>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
          <span style={{ flex: 1, height: 1, background: '#e5e7eb' }} />
          <span style={{ fontSize: 12, color: '#9ca3af' }}>یا ورود با حساب سامانه</span>
          <span style={{ flex: 1, height: 1, background: '#e5e7eb' }} />
        </div>
        <label>
          نام کاربری
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            inputMode="text"
            required
          />
        </label>
        <label>
          گذرواژه
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && <div className="banner danger">{error}</div>}
        <button className="btn primary" disabled={busy} type="submit">
          {busy ? 'در حال ورود…' : 'ورود'}
        </button>
        <p className="hint">
          با پنج تلاش ناموفق، حساب به مدت ۱۵ دقیقه قفل می‌شود (بخش ۶ سند).
        </p>
        <p className="hint install-hint">
          <a className="linklike" href="/install">📱 نصب نسخهٔ موبایل (QR)</a>
        </p>
      </form>
    </div>
  )
}
