const CHIP_STYLES: Record<string, string> = {
  ACCEPTED: 'chip-ok',
  COMPLETE: 'chip-ok',
  IN_RANGE: 'chip-ok',
  FINAL: 'chip-ok',
  APPROVED: 'chip-ok',
  OUT_OF_RANGE: 'chip-warn',
  CLOCK_SKEW: 'chip-warn',
  STALE_OFFLINE: 'chip-warn',
  PENDING: 'chip-info',
  PROVISIONAL: 'chip-info',
  OPEN: 'chip-info',
  OFFLINE_SYNC: 'chip-info',
  NEEDS_REVIEW: 'chip-danger',
  INVALID_SEQUENCE: 'chip-danger',
  ABSENT: 'chip-danger',
  ADJUSTED: 'chip-warn',
}

const CHIP_LABELS: Record<string, string> = {
  ACCEPTED: 'پذیرفته‌شده',
  COMPLETE: 'کامل',
  IN_RANGE: 'در محدوده',
  FINAL: 'قطعی',
  APPROVED: 'تأییدشده',
  OUT_OF_RANGE: 'خارج محدوده',
  CLOCK_SKEW: 'مغایرت ساعت',
  STALE_OFFLINE: 'آفلاین قدیمی',
  PENDING: 'در انتظار',
  PROVISIONAL: 'موقت',
  OPEN: 'باز (بدون خروج)',
  OFFLINE_SYNC: 'آفلاین',
  NEEDS_REVIEW: 'نیاز به بررسی',
  INVALID_SEQUENCE: 'ترتیب نامعتبر',
  ABSENT: 'غایب',
  ADJUSTED: 'اصلاح‌شده',
  CHECK_IN: 'ورود',
  CHECK_OUT: 'خروج',
  ONLINE: 'آنلاین',
  HOLIDAY: 'تعطیل',
  LATE_FLAGGED: 'تأخیر (برچسب)',
  LATE_DEDUCTED: 'تأخیر با کسر',
  LATE_AS_ABSENCE_HALF: 'تأخیر = نیم‌روز غیبت',
  LATE_FORGIVEN: 'تأخیر ارفاق‌شده',
  EARLY_FLAGGED: 'تعجیل',
  EARLY_DEDUCTED: 'تعجیل با کسر',
  EARLY_AS_ABSENCE_HALF: 'تعجیل = نیم‌روز غیبت',
  OVERTIME_AUTO_APPROVED: 'اضافه‌کاری خودکار',
  SESSION_OPEN: 'بازه باز',
  SESSION_INVALID_SEQUENCE: 'ترتیب نامعتبر بازه',
  NO_SHOW_RISK: 'ریسک غیبت',
  ABSENCE_HALF_DAY: 'نیم‌روز غیبت',
}

export default function Chip({ value }: { value: string }) {
  const cls = CHIP_STYLES[value] ?? 'chip-muted'
  const label = CHIP_LABELS[value] ?? value
  return <span className={`chip ${cls}`}>{label}</span>
}
