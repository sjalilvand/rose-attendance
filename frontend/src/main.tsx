import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { registerSW } from 'virtual:pwa-register'
import { AuthProvider, useAuth } from './context/AuthContext'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import PunchPage from './pages/PunchPage'
import HistoryPage from './pages/HistoryPage'
import SummaryPage from './pages/SummaryPage'
import RequestsPage from './pages/RequestsPage'
import ApprovalsPage from './pages/ApprovalsPage'
import SettingsPage from './pages/SettingsPage'
import './styles.css'

registerSW({ immediate: true })

function RequireAuth({ children }: { children: JSX.Element }) {
  const { ready, me } = useAuth()
  if (!ready) return <div className="page-loading">در حال بارگذاری…</div>
  if (!me) return <Navigate to="/login" replace />
  return <Layout>{children}</Layout>
}

function PublicOnly({ children }: { children: JSX.Element }) {
  const { ready, me } = useAuth()
  if (!ready) return <div className="page-loading">در حال بارگذاری…</div>
  if (me) return <Navigate to="/" replace />
  return children
}

function AppRoutes() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <PublicOnly>
            <LoginPage />
          </PublicOnly>
        }
      />
      <Route
        path="/"
        element={
          <RequireAuth>
            <PunchPage />
          </RequireAuth>
        }
      />
      <Route
        path="/history"
        element={
          <RequireAuth>
            <HistoryPage />
          </RequireAuth>
        }
      />
      <Route
        path="/summary"
        element={
          <RequireAuth>
            <SummaryPage />
          </RequireAuth>
        }
      />
      <Route
        path="/requests"
        element={
          <RequireAuth>
            <RequestsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/approvals"
        element={
          <RequireAuth>
            <ApprovalsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/settings"
        element={
          <RequireAuth>
            <SettingsPage />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
