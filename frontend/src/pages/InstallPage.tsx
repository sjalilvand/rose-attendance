/** صفحهٔ عمومی نصب نسخهٔ موبایل (PWA) — QR + راهنمای اندروید/iOS/دسکتاپ.
 * عمداً خارج از چیدمان اصلی است تا بدون لاگین هم باز شود (اسکن با گوشی). */
import { useEffect, useState } from 'react'

type InstallPromptEvent = Event & {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

export default function InstallPage() {
  const [installEvt, setInstallEvt] = useState<InstallPromptEvent | null>(null)
  const [installed, setInstalled] = useState(false)
  const siteUrl = window.location.origin

  useEffect(() => {
    const onBip = (e: Event) => {
      e.preventDefault()
      setInstallEvt(e as InstallPromptEvent)
    }
    const onInstalled = () => {
      setInstalled(true)
      setInstallEvt(null)
    }
    window.addEventListener('beforeinstallprompt', onBip)
    window.addEventListener('appinstalled', onInstalled)
    if (window.matchMedia('(display-mode: standalone)').matches) setInstalled(true)
    return () => {
      window.removeEventListener('beforeinstallprompt', onBip)
      window.removeEventListener('appinstalled', onInstalled)
    }
  }, [])

  async function install() {
    if (!installEvt) return
    await installEvt.prompt()
    const choice = await installEvt.userChoice
    if (choice.outcome === 'accepted') setInstalled(true)
    setInstallEvt(null)
  }

  return (
    <div className="install-wrap">
      <div className="login-brand">
        <span className="brand-mark big" aria-hidden>
          ✿
        </span>
        <h1>رز سفید</h1>
        <p>نصب نسخهٔ موبایل سامانه حضور و غیاب</p>
      </div>

      <section className="card install-card">
        <h2 className="h">نصب با اسکن QR</h2>
        <p className="hint">دوربین گوشی را روی کد بگیرید تا آدرس سامانه باز شود:</p>
        <div className="install-qr">
          <img src="/qr-install.svg" alt="QR نصب سامانه رز سفید" />
        </div>
        <p className="install-url" dir="ltr">
          {siteUrl}
        </p>
        {installed ? (
          <div className="banner ok">اپ روی این دستگاه نصب شده است. ✓</div>
        ) : installEvt ? (
          <button className="btn primary" onClick={() => void install()}>
            نصب اپ روی این دستگاه
          </button>
        ) : (
          <p className="hint">در گوشی: منوی مرورگر → «افزودن به صفحهٔ اصلی» / Add to Home screen</p>
        )}
      </section>

      <section className="card install-guide">
        <h2 className="h">راهنمای نصب</h2>
        <div className="guide-row">
          <strong>اندروید (کروم):</strong>
          <span>
            آدرس بالا را باز کنید → منوی ⋮ → «افزودن به صفحهٔ اصلی» → تأیید. آیکون اپ مثل برنامهٔ
            عادی گوشی می‌ماند و تمام‌صفحه باز می‌شود.
          </span>
        </div>
        <div className="guide-row">
          <strong>iPhone (سافاری):</strong>
          <span>آدرس را در سافاری باز کنید → دکمهٔ اشتراک ⬆︎ → Add to Home Screen.</span>
        </div>
        <div className="guide-row">
          <strong>کامپیوتر (کروم/اج):</strong>
          <span>آیکون نصب در نوار آدرس → Install — سامانه مثل یک برنامهٔ دسکتاپ باز می‌شود.</span>
        </div>
        <p className="hint">
          برای ثبت تردد آفلاین، نصب الزامی نیست؛ همین آدرس در مرورگر کافی است. نصب فقط آیکون و اجرای
          تمام‌صفحه اضافه می‌کند.
        </p>
      </section>

      <a className="linklike" href="/login">
        بازگشت به صفحهٔ ورود
      </a>
    </div>
  )
}
