'use client'

import { createContext, useContext, useEffect, useState, ReactNode } from 'react'
import { api } from './api'

interface User {
  id: number
  email: string
  name: string
  is_staff: boolean
}

interface AuthContextType {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<string | null>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  loading: true,
  login: async () => null,
  logout: async () => {},
})

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api('/api/auth/me/')
      .then(r => r.json())
      .then(data => {
        if (data.authenticated) setUser(data.user)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const login = async (email: string, password: string): Promise<string | null> => {
    const csrfRes = await api('/api/auth/me/')
    const res = await api('/api/auth/login/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    const data = await res.json()
    if (res.ok) {
      setUser(data.user)
      return null
    }
    return data.error || 'Login failed'
  }

  const logout = async () => {
    await api('/api/auth/logout/', { method: 'POST' })
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
