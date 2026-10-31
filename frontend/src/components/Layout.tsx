import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { faDigits } from '../lib/jalali'
import { fetchUnreadBadge, type UnreadBadge } from '../lib/api'
import { startNotifications, stopNotifications, type LiveNotification } from '../lib/ws'
import { initials, roleFa } from '../lib/roles'

const MANAGER_ROLES = ['BRANCH_MANAGER', 'REGION_MANAGER', 'HR', 'ADMIN']
const HR_ROLES = ['HR', 'ADMIN']

interface Tab {
  to: string
  label: string
  icon: string
  badge?: number
}

export default function Layout({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const { me } = useAuth()
  const isManager = Boolean(me && me.roles.some((role) => MANAGER_ROLES.includes(role)))
  const isHrAdmin = Boolean(me && me.roles.some((role) => HR_ROLES.includes(role)))
  const [toast, setToast] = useState<LiveNotification | null>(null)
  const [badge, setBadge] = useState<UnreadBadge>({ messages: 0, notifications: 0 })
  const timer = useRef<number | undefined>(undefined)

  const loadBadge = async () => {
    try {
      setBadge(await fetchUnreadBadge())
    } catch {
      /* بدون پروندهٔ پرسنلی (سوپریوزر) بج ندارد */
    }
  }

  // Live decision notifications — one socket per tab, auto-reconnect inside ws.ts.
  useEffect(() => {
    startNotifications((n) => {
      setToast(n)
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setToast(null), 6000)
      void loadBadge() // هر رویداد زنده ممکن است بج نخوانده‌ها را تغییر دهد
    })
    void loadBadge()
    const interval = window.setInterval(() => void loadBadge(), 60000)
    const onPoke = () => void loadBadge()
    window.addEventListener('rose:refresh-badge', onPoke)
    return () => {
      stopNotifications()
      window.clearInterval(interval)
      window.removeEventListener('rose:refresh-badge', onPoke)
    }
  }, [])

  const tabs: Tab[] = [
    { to: '/', label: 'ثبت تردد', icon: '🕐' },
    { to: '/history', label: 'کارکرد', icon: '📅' },
    { to: '/summary', label: 'خلاصه ماه', icon: '📊' },
    { to: '/requests', label: 'درخواست', icon: '📝' },
    { to: '/messages', label: 'پیام', icon: '💬', badge: badge.messages },
    { to: '/notifications', label: 'اعلان', icon: '🔔', badge: badge.notifications },
    ...(isManager ? [{ to: '/approvals', label: 'رسیدگی', icon: '✅' } satisfies Tab] : []),
    ...(isHrAdmin ? [{ to: '/org', label: 'سازمان', icon: '🏢' } satisfies Tab] : []),
    ...(isHrAdmin ? [{ to: '/import', label: 'ورود گروهی', icon: '📥' } satisfies Tab] : []),
    ...(isHrAdmin ? [{ to: '/reports', label: 'گزارش‌ها', icon: '📑' } satisfies Tab] : []),
    ...(isHrAdmin ? [{ to: '/management', label: 'مدیریت', icon: '👥' } satisfies Tab] : []),
    { to: '/settings', label: 'تنظیمات', icon: '⚙️' },
  ]
  const displayName = me?.employee?.full_name ?? me?.username ?? ''
  const mainRole = me?.roles.length ? roleFa(me.roles[0]) : ''
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden>✿</span>
          <span className="brand-name">رز سفید</span>
        </div>
        <div className="header-side">
          {me && (
            <button
              className="user-chip"
              title="مشاهدهٔ پروفایل"
              onClick={() => {
                navigate('/profile')
              }}
            >
              <span className="avatar" aria-hidden>{initials(displayName)}</span>
              <span className="user-meta">
                <strong>{displayName}</strong>
                <small>
                  {mainRole}
                  {me.employee?.home_branch_name ? ` — ${me.employee.home_branch_name}` : ''}
                </small>
              </span>
            </button>
          )}
          <button
            className="linklike"
            onClick={() => {
              navigate('/login')
            }}
          >
            خروج
          </button>
        </div>
      </header>
      <main className="app-main">{children}</main>
      {toast && (
        <div className="toast" role="status">
          <strong>{toast.title}</strong>
        </div>
      )}
      <nav className="bottom-nav" aria-label="ناوبری اصلی">
        {tabs.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.to === '/'}
            className={({ isActive }) => `nav-tab${isActive ? ' active' : ''}`}
          >
            <span aria-hidden className="nav-icon">
              {tab.icon}
              {tab.badge != null && tab.badge > 0 && (
                <span className="nav-badge">{tab.badge > 99 ? '۹۹+' : faDigits(tab.badge)}</span>
              )}
            </span>
            <span>{tab.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
