import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { setTokens } from '../lib/api'
import { useAuth } from '../context/AuthContext'

/** نقطهٔ بازگشت ورود یکپارچه — سرور مرورگر را به این مسیر با توکن‌ها در
 * «fragment» (#...) می‌فرستد؛ fragment هرگز به هیچ سروری ارسال نمی‌شود و
 * بلافاصله پس از خواندن از نوار آدرس پاک می‌گردد. */
export default function SsoCallbackPage() {
  const navigate = useNavigate()
  const { loginDone } = useAuth()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fragment = window.location.hash.replace(/^#/, '')
    const params = new URLSearchParams(fragment)
    const access = params.get('access')
    const refresh = params.get('refresh')
    const ssoError = params.get('error')
    window.history.replaceState(null, '', '/sso') // پاک کردن توکن از نوار آدرس
    if (access && refresh) {
      setTokens(access, refresh)
      void loginDone().then(() => navigate('/', { replace: true }))
    } else {
      setError(ssoError ?? 'پارامترهای بازگشت ناقص است؛ دوباره وارد شوید.')
    }
  }, [loginDone, navigate])

  if (error) {
    return (
      <div className="login-wrap">
        <div className="card login-card">
          <div className="login-brand">
            <span className="brand-mark big" aria-hidden>✿</span>
            <h1>ورود یکپارچه ناموفق بود</h1>
          </div>
          <div className="banner danger">{error}</div>
          <Link className="btn primary" to="/login">
            بازگشت به صفحهٔ ورود
          </Link>
        </div>
      </div>
    )
  }
  return <div className="page-loading">در حال تکمیل ورود…</div>
}
