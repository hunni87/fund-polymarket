import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

import { api, getToken } from '../api/client'
import type { Member, SystemStatus } from '../api/types'

interface AuthState {
  member: Member | null
  status: SystemStatus | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [member, setMember] = useState<Member | null>(null)
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [loading, setLoading] = useState(true)

  async function load() {
    if (!getToken()) {
      setMember(null)
      setLoading(false)
      return
    }
    try {
      const [me, sys] = await Promise.all([api.me(), api.systemStatus()])
      setMember(me)
      setStatus(sys)
    } catch {
      setMember(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const value: AuthState = {
    member,
    status,
    loading,
    login: async (email, password) => {
      await api.login(email, password)
      setLoading(true)
      await load()
    },
    logout: () => {
      api.logout()
      setMember(null)
    },
    refresh: load,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
