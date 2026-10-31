/** برچسب فارسی نقش‌ها — مطابق RoleCode در بک‌اند (apps/core/enums.py). */
const ROLE_FA: Record<string, string> = {
  EMPLOYEE: 'پرسنل',
  BRANCH_MANAGER: 'مدیر شعبه',
  REGION_MANAGER: 'مدیر منطقه',
  HR: 'منابع انسانی',
  ADMIN: 'ادمین',
  AUDITOR: 'حسابرس',
}

export function roleFa(code: string): string {
  return ROLE_FA[code] ?? code
}

export function rolesFa(codes: string[]): string {
  return codes.map(roleFa).join('، ')
}

/** حروف اول برای نشان آواتار؛ «سارا محمدی» → «سم». */
export function initials(fullName: string): string {
  const parts = fullName.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '✿'
  if (parts.length === 1) return parts[0].slice(0, 2)
  return `${parts[0][0]}${parts[1][0]}`
}
