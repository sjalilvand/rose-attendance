import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { fetchMe, hasSession, logout as apiLogout, type MeInfo } from '../lib/api'

interface AuthContextValue {
  ready: boolean
  me: MeInfo | null
  refreshMe: () => Promise<void>
  loginDone: () => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue>({
  ready: false,
  me: null,
  refreshMe: async () => undefined,
  loginDone: async () => undefined,
  logout: () => undefined,
})

export function AuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false)
  const [me, setMe] = useState<MeInfo | null>(null)

  const refreshMe = useCallback(async () => {
    if (!hasSession()) {
      setMe(null)
      setReady(true)
      return
    }
    try {
      const info = await fetchMe()
      setMe(info)
    } catch {
      setMe(null)
    } finally {
      setReady(true)
    }
  }, [])

  const loginDone = useCallback(async () => {
    setReady(true)
    await refreshMe()
  }, [refreshMe])

  const logout = useCallback(() => {
    void apiLogout()
    setMe(null)
  }, [])

  useEffect(() => {
    void refreshMe()
  }, [refreshMe])

  const value = useMemo(
    () => ({ ready, me, refreshMe, loginDone, logout }),
    [ready, me, refreshMe, loginDone, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  return useContext(AuthContext)
}
