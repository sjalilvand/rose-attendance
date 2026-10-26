import { JALALI_MONTHS, faDigits, jalaliMonthLength, jalaliToday, toGregorian, toJalali } from '../lib/jalali'

const pad = (n: number): string => String(n).padStart(2, '0')

function isoFromDate(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 'YYYY-MM-DD' میلادی → اجزای جلالی؛ خالی/نامعتبر → امروزِ تهران. */
function toParts(value: string): { jy: number; jm: number; jd: number } {
  if (value) {
    const [y, m, d] = value.split('-').map(Number)
    if (y && m && d) {
      try {
        return toJalali(new Date(y, m - 1, d))
      } catch {
        /* سال خارج از بازهٔ الگوریتم — به امروز برمی‌گردیم */
      }
    }
  }
  return jalaliToday()
}

interface Props {
  /** تاریخ میلادی ISO ('YYYY-MM-DD') — همان قرارداد <input type="date"> قبلی. */
  value: string
  onChange: (iso: string) => void
  ariaLabel?: string
}

/**
 * انتخابگر تاریخ شمسی (گام ۴ — شمسی‌سازی تقویم‌های موجود).
 *
 * جایگزین پیکر بومی میلادی مرورگر: سه فهرست بازگشتی «روز / ماه / سال» با
 * نام ماه‌های فارسی، طول واقعی ماه (۲۹/۳۰/۳۱) و ارقام فارسی. قرارداد خروجی
 * همان رشتهٔ ISO میلادی قبلی است تا کد مصرف‌کننده تغییر نکند.
 */
export default function JalaliDateInput({ value, onChange, ariaLabel }: Props) {
  const { jy, jm, jd } = toParts(value)
  const todayJy = jalaliToday().jy
  const years: number[] = []
  for (let y = todayJy + 1; y >= todayJy - 8; y -= 1) years.push(y)
  const daysInMonth = jalaliMonthLength(jy, jm)

  const set = (y: number, m: number, d: number) => {
    // اگر روز از طول ماه جدید بیشتر بود، به آخرین روز همان ماه محدود می‌شود
    const day = Math.min(d, jalaliMonthLength(y, m))
    onChange(isoFromDate(toGregorian(y, m, day)))
  }

  return (
    <span className="jalali-date" aria-label={ariaLabel}>
      <select
        value={jd}
        onChange={(e) => set(jy, jm, Number(e.target.value))}
        aria-label="روز"
      >
        {Array.from({ length: daysInMonth }, (_, i) => i + 1).map((d) => (
          <option key={d} value={d}>
            {faDigits(d)}
          </option>
        ))}
      </select>
      <select
        value={jm}
        onChange={(e) => set(jy, Number(e.target.value), jd)}
        aria-label="ماه"
      >
        {JALALI_MONTHS.map((name, i) => (
          <option key={name} value={i + 1}>
            {name}
          </option>
        ))}
      </select>
      <select
        value={jy}
        onChange={(e) => set(Number(e.target.value), jm, jd)}
        aria-label="سال"
      >
        {years.map((y) => (
          <option key={y} value={y}>
            {faDigits(y)}
          </option>
        ))}
      </select>
    </span>
  )
}
