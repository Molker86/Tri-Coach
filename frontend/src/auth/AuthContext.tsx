import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api, getToken, onUnauthorized, setLastUserId, setToken } from '../api/client'
import type { User } from '../types'

interface AuthState {
  user: User | null
  loading: boolean
  login: (userId: number) => Promise<void>
  register: (email: string, username: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
  }, [])

  // Ein abgelaufenes Token soll überall sofort zum Logout führen.
  useEffect(() => {
    onUnauthorized.handler = logout
    return () => {
      onUnauthorized.handler = null
    }
  }, [logout])

  // Bestehende Sitzung beim Laden wiederherstellen.
  useEffect(() => {
    if (!getToken()) {
      setLoading(false)
      return
    }
    api
      .me()
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (userId: number) => {
    const response = await api.login(userId)
    setToken(response.access_token)
    setLastUserId(response.user.id)
    setUser(response.user)
  }, [])

  const register = useCallback(async (email: string, username: string) => {
    const response = await api.register(email, username)
    setToken(response.access_token)
    setLastUserId(response.user.id)
    setUser(response.user)
  }, [])

  const value = useMemo(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth muss innerhalb von AuthProvider genutzt werden')
  return context
}
