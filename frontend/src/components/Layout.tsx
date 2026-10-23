import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { startNotifications, stopNotifications, type LiveNotification } from '../lib/ws'

const MANAGER_ROLES = ['BRANCH_MANAGER', 'REGION_MANAGER', 'HR', 'ADMIN']
const HR_ROLES = ['HR', 'ADMIN']

interface Tab {
  to: string
  label: string
  icon: string
}

export default function Layout({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const { me } = useAuth()
  const isManager = Boolean(me && me.roles.some((role) => MANAGER_ROLES.includes(role)))
  const isHrAdmin = Boolean(me && me.roles.some((role) => HR_ROLES.includes(role)))
  const [toast, setToast] = useState<LiveNotification | null>(null)
  const timer = useRef<number | undefined>(undefined)

  // Live decision notifications — one socket per tab, auto-reconnect inside ws.ts.
  useEffect(() => {
    startNotifications((n) => {
      setToast(n)
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setToast(null), 6000)
    })
    return () => stopNotifications()
  }, [])

  const tabs: Tab[] = [
    { to: '/', label: 'ثبت تردد', icon: '🕐' },
    { to: '/history', label: 'کارکرد', icon: '📅' },
    { to: '/summary', label: 'خلاصه ماه', icon: '📊' },
    { to: '/requests', label: 'درخواست', icon: '📝' },
    ...(isManager ? [{ to: '/approvals', label: 'رسیدگی', icon: '✅' } satisfies Tab] : []),
    ...(isHrAdmin ? [{ to: '/import', label: 'ورود گروهی', icon: '📥' } satisfies Tab] : []),
    { to: '/settings', label: 'تنظیمات', icon: '⚙️' },
  ]
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden>✿</span>
          <span className="brand-name">رز سفید</span>
        </div>
        <button
          className="linklike"
          onClick={() => {
            navigate('/login')
          }}
        >
          خروج
        </button>
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
            <span aria-hidden>{tab.icon}</span>
            <span>{tab.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
