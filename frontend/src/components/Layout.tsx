import type { ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'

const TABS = [
  { to: '/', label: 'ثبت تردد', icon: '🕐' },
  { to: '/history', label: 'کارکرد', icon: '📅' },
  { to: '/summary', label: 'خلاصه ماه', icon: '📊' },
  { to: '/settings', label: 'تنظیمات', icon: '⚙️' },
]

export default function Layout({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
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
      <nav className="bottom-nav" aria-label="ناوبری اصلی">
        {TABS.map((tab) => (
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
