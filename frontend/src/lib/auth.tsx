import { createContext, ReactNode, useContext, useEffect, useState } from 'react'
import { api } from './api'
import type { User } from './types'

interface AuthState {
  user: User | null
  permissions: string[]
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
  can: (permission: string) => boolean
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [permissions, setPermissions] = useState<string[]>([])
  const [loading, setLoading] = useState(true)

  const refresh = async () => {
    try {
      const me = await api.get<User>('/api/auth/me')
      const perms = await api.get<{ permissions: string[] }>('/api/auth/permissions')
      setUser(me)
      setPermissions(perms.permissions)
    } catch {
      setUser(null)
      setPermissions([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    const onUnauthorized = () => {
      setUser(null)
      setPermissions([])
    }
    window.addEventListener('bluekvm:unauthorized', onUnauthorized)
    return () => window.removeEventListener('bluekvm:unauthorized', onUnauthorized)
  }, [])

  const login = async (username: string, password: string) => {
    const result = await api.post<{ user: User }>('/api/auth/login', { username, password })
    setUser(result.user)
    const perms = await api.get<{ permissions: string[] }>('/api/auth/permissions')
    setPermissions(perms.permissions)
  }

  const logout = async () => {
    try {
      await api.post('/api/auth/logout')
    } finally {
      setUser(null)
      setPermissions([])
    }
  }

  const can = (permission: string) => permissions.includes('*') || permissions.includes(permission)

  return (
    <AuthContext.Provider value={{ user, permissions, loading, login, logout, refresh, can }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
