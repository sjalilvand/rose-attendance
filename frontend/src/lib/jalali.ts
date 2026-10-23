/** Jalali (Solar Hijri) helpers — the organisation calendar (approved decision
 * #2 of §34). Conversion uses the standard jalaali algorithm (MIT, Behrang
 * Norouzinia) inlined to stay dependency-free; "today"/display times are
 * anchored to Asia/Tehran regardless of the device timezone. */

const BREAKS = [
  -61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097, 2192,
  2262, 2324, 2394, 2456, 3178,
]

const div = (a: number, b: number): number => Math.trunc(a / b)
const mod = (a: number, b: number): number => a - Math.trunc(a / b) * b

interface JalCalResult {
  leap: number
  gy: number
  march: number
}

function jalCal(jy: number): JalCalResult {
  const bl = BREAKS.length
  const gy = jy + 621
  let leapJ = -14
  let jp = BREAKS[0]
  if (jy < jp || jy >= BREAKS[bl - 1]) throw new Error('سال شمسی نامعتبر: ' + jy)
  let jump = 0
  for (let i = 1; i < bl; i += 1) {
    const jm = BREAKS[i]
    jump = jm - jp
    if (jy < jm) break
    leapJ = leapJ + div(jump, 33) * 8 + div(mod(jump, 33), 4)
    jp = jm
  }
  let n = jy - jp
  leapJ = leapJ + div(n, 33) * 8 + div(mod(n, 33) + 3, 4)
  if (mod(jump, 33) === 4 && jump - n === 4) leapJ += 1
  const leapG = div(gy, 4) - div((div(gy, 100) + 1) * 3, 4) - 150
  const march = 20 + leapJ - leapG
  if (jump - n < 6) n = n - jump + div(jump + 4, 33) * 33
  let leap = mod(mod(n + 1, 33) - 1, 4)
  if (leap === -1) leap = 4
  return { leap, gy, march }
}

function g2d(gy: number, gm: number, gd: number): number {
  let d =
    div((gy + div(gm - 8, 6) + 100100) * 1461, 4) +
    div(153 * mod(gm + 9, 12) + 2, 5) +
    gd -
    34840408
  d = d - div(div(gy + 100100 + div(gm - 8, 6), 100) * 3, 4) + 752
  return d
}

function d2g(jdn: number): { gy: number; gm: number; gd: number } {
  let j = 4 * jdn + 139361631
  j = j + div(div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908
  const i = div(mod(j, 1461), 4) * 5 + 308
  const gd = div(mod(i, 153), 5) + 1
  const gm = mod(div(i, 153), 12) + 1
  const gy = div(j, 1461) - 100100 + div(8 - gm, 6)
  return { gy, gm, gd }
}

/** Jalali day number (JDN-based, standard jalaali algorithm). */
function j2d(jy: number, jm: number, jd: number): number {
  const r = jalCal(jy)
  return g2d(r.gy, 3, r.march) + (jm - 1) * 31 - div(jm, 7) * (jm - 7) + jd - 1
}

function d2j(jdn: number): JalaliDate {
  const gy = d2g(jdn).gy
  let jy = gy - 621
  const r = jalCal(jy)
  const jdn1f = g2d(gy, 3, r.march)
  let k = jdn - jdn1f
  if (k >= 0) {
    if (k <= 185) {
      return { jy, jm: 1 + div(k, 31), jd: mod(k, 31) + 1 }
    }
    k -= 186
  } else {
    jy -= 1
    k += 179
    if (r.leap === 1) k += 1
  }
  return { jy, jm: 7 + div(k, 30), jd: mod(k, 30) + 1 }
}

export interface JalaliDate {
  jy: number
  jm: number
  jd: number
}

export function toJalali(date: Date): JalaliDate {
  return d2j(g2d(date.getFullYear(), date.getMonth() + 1, date.getDate()))
}

export function toGregorian(jy: number, jm: number, jd: number): Date {
  const g = d2g(j2d(jy, jm, jd))
  return new Date(g.gy, g.gm - 1, g.gd)
}
export function isLeapJalaliYear(jy: number): boolean {
  return jalCal(jy).leap === 0
}

export function jalaliMonthLength(jy: number, jm: number): number {
  if (jm <= 6) return 31
  if (jm <= 11) return 30
  return isLeapJalaliYear(jy) ? 30 : 29
}

/** Gregorian [from, to] of a Jalali month — mirrors backend
 * apps.core.jalali.jalali_month_range (approved decision #2 of §34). */
export function jalaliMonthRange(jy: number, jm: number): { from: string; to: string } {
  const first = toGregorian(jy, jm, 1)
  const last = toGregorian(jy, jm, jalaliMonthLength(jy, jm))
  return { from: isoDate(first), to: isoDate(last) }
}

function isoDate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** Tehran-anchored Jalali "today". */
export function jalaliToday(): JalaliDate {
  const tehranDate = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tehran',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date())
  const [y, m, d] = tehranDate.split('-').map(Number)
  return toJalali(new Date(y, m - 1, d))
}

export const JALALI_MONTHS = [
  'فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
  'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند',
]

export function jalaliMonthName(jm: number): string {
  return JALALI_MONTHS[jm - 1] ?? String(jm)
}

const FA_DIGITS = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹']

export function faDigits(value: string | number): string {
  return String(value).replace(/\d/g, (d) => FA_DIGITS[Number(d)])
}

/** '2026-10-12' → '۱۴۰۵/۰۷/۲۰' */
export function formatJalaliDate(isoDateStr: string): string {
  const [y, m, d] = isoDateStr.split('-').map(Number)
  if (!y || !m || !d) return isoDateStr
  const j = toJalali(new Date(y, m - 1, d))
  return faDigits(`${j.jy}/${String(j.jm).padStart(2, '0')}/${String(j.jd).padStart(2, '0')}`)
}

/** ISO instant → 'HH:mm' in Tehran time. */
export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const fmt = new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'Asia/Tehran',
  })
  return faDigits(fmt.format(new Date(iso)))
}

/** ISO instant → '۱۴۰۵/۰۷/۲۰ — ۰۹:۱۵' (Tehran). */
export function formatJalaliDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const tehranDate = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tehran',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(iso))
  const [y, m, d] = tehranDate.split('-').map(Number)
  const j = toJalali(new Date(y, m - 1, d))
  const time = formatTime(iso)
  return `${faDigits(`${j.jy}/${String(j.jm).padStart(2, '0')}/${String(j.jd).padStart(2, '0')}`)} — ${time}`
}

export function minutesToHM(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return '—'
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h === 0) return faDigits(`${m} دقیقه`)
  return faDigits(`${h}:${String(m).padStart(2, '0')}`)
}
