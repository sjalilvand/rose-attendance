import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { changePassword, updateMobile } from '../lib/api'
import { faDigits, formatJalaliDateTime } from '../lib/jalali'
import { initials, rolesFa } from '../lib/roles'

export default function ProfilePage() {
  const { me, refreshMe } = useAuth()
  const [mobile, setMobile] = useState('')
  const [mobileBusy, setMobileBusy] = useState(false)
  const [mobileMsg, setMobileMsg] = useState<string | null>(null)
  const [mobileErr, setMobileErr] = useState<string | null>(null)

  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [passBusy, setPassBusy] = useState(false)
  const [passMsg, setPassMsg] = useState<string | null>(null)
  const [passErr, setPassErr] = useState<string | null>(null)

  useEffect(() => {
    if (me?.employee?.mobile) setMobile(me.employee.mobile)
    else if (me?.mobile) setMobile(me.mobile)
  }, [me?.employee?.mobile, me?.mobile])

  if (!me) return null
  const isSso = me.auth_method === 'SSO'
  // نام نمایشی: اول نام همگام‌شده از رز هاب، بعد پروندهٔ پرسنلی
  const displayName = me.full_name || me.employee?.full_name || me.username

  async function saveMobile(e: React.FormEvent) {
    e.preventDefault()
    setMobileBusy(true)
    setMobileMsg(null)
    setMobileErr(null)
    try {
      setMobileMsg(await updateMobile(mobile.trim()))
      await refreshMe()
    } catch (err) {
      setMobileErr(err instanceof Error ? err.message : 'به‌روزرسانی ناموفق بود.')
    } finally {
      setMobileBusy(false)
    }
  }

  async function savePassword(e: React.FormEvent) {
    e.preventDefault()
    setPassMsg(null)
    setPassErr(null)
    if (next !== confirm) {
      setPassErr('تکرار گذرواژهٔ جدید مطابقت ندارد.')
      return
    }
    setPassBusy(true)
    try {
      setPassMsg(await changePassword(current, next))
      setCurrent('')
      setNext('')
      setConfirm('')
    } catch (err) {
      setPassErr(err instanceof Error ? err.message : 'تغییر گذرواژه ناموفق بود.')
    } finally {
      setPassBusy(false)
    }
  }

  return (
    <div className="page">
      <section className="card profile-head">
        <span className="avatar big" aria-hidden>{initials(displayName)}</span>
        <div>
          <h1 className="h3">{displayName}</h1>
          <p className="hint">
            {rolesFa(me.roles) || '—'}
            {me.employee?.home_branch_name ? ` — ${me.employee.home_branch_name}` : ''}
          </p>
        </div>
      </section>

      <section className="card">
        <h2 className="h3">مشخصات من</h2>
        <dl className="kv">
          <dt>نام کاربری</dt>
          <dd className="mono">{me.username}</dd>
          <dt>نام و نام خانوادگی</dt>
          <dd>{displayName || '—'}</dd>
          <dt>کد ملی</dt>
          <dd className="mono">{me.national_id || '—'}</dd>
          <dt>موبایل (رز هاب)</dt>
          <dd className="mono">{me.mobile || me.employee?.mobile || '—'}</dd>
          <dt>استان</dt>
          <dd>{me.province || '—'}</dd>
          <dt>کد استان</dt>
          <dd className="mono">{me.province_code || '—'}</dd>
          <dt>کلینک محل خدمت</dt>
          <dd>{me.clinic || '—'}</dd>
          <dt>کد پرسنلی</dt>
          <dd className="mono">{me.employee ? faDigits(me.employee.personnel_code) : '—'}</dd>
          <dt>عنوان شغلی</dt>
          <dd>{me.employee?.job_title || '—'}</dd>
          <dt>شعبهٔ اصلی</dt>
          <dd>{me.employee?.home_branch_name || '—'}</dd>
          <dt>نقش‌ها</dt>
          <dd>{rolesFa(me.roles) || '—'}</dd>
          <dt>شعب مجاز</dt>
          <dd>
            {me.branches.map((b) => `${b.name}${b.is_home ? ' (اصلی)' : ''}`).join('، ') || '—'}
          </dd>
          <dt>روش ورود</dt>
          <dd>{isSso ? 'ورود یکپارچهٔ سازمانی (SSO)' : 'گذرواژه'}</dd>
          <dt>آخرین ورود</dt>
          <dd>{me.last_login_at ? formatJalaliDateTime(me.last_login_at) : '—'}</dd>
        </dl>
      </section>

      <section className="card">
        <h2 className="h3">شمارهٔ موبایل</h2>
        <p className="hint">شمارهٔ تماس شما در پروندهٔ پرسنلی؛ با ۰۹ شروع و ۱۱ رقم است.</p>
        <form className="stack" onSubmit={saveMobile}>
          <label>
            موبایل
            <input
              value={mobile}
              onChange={(e) => setMobile(e.target.value)}
              inputMode="numeric"
              placeholder="09xxxxxxxxx"
              className="mono"
            />
          </label>
          {mobileMsg && <div className="banner">{mobileMsg}</div>}
          {mobileErr && <div className="banner danger">{mobileErr}</div>}
          <button className="btn primary" disabled={mobileBusy || !me.employee} type="submit">
            ذخیرهٔ شماره
          </button>
          {!me.employee && <p className="hint">این حساب پروندهٔ پرسنلی ندارد (کاربر سیستمی).</p>}
        </form>
      </section>

      <section className="card">
        <h2 className="h3">تغییر گذرواژه</h2>
        {isSso ? (
          <p className="hint">
            ورود شما از طریق سامانهٔ سازمانی (SSO) انجام می‌شود؛ گذرواژهٔ این سامانه را از
            مسئول سامانهٔ سازمانی خود تغییر دهید.
          </p>
        ) : (
          <form className="stack" onSubmit={savePassword}>
            <label>
              گذرواژهٔ فعلی
              <input
                type="password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            <label>
              گذرواژهٔ جدید (حداقل ۸ نویسه)
              <input
                type="password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                autoComplete="new-password"
                minLength={8}
                required
              />
            </label>
            <label>
              تکرار گذرواژهٔ جدید
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                minLength={8}
                required
              />
            </label>
            {passMsg && <div className="banner">{passMsg}</div>}
            {passErr && <div className="banner danger">{passErr}</div>}
            <button className="btn primary" disabled={passBusy} type="submit">
              تغییر گذرواژه
            </button>
          </form>
        )}
      </section>
    </div>
  )
}
