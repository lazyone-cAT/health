import { createContext, useContext, useEffect, useState } from 'react'
import { api } from './api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined)

  useEffect(() => {
    api('/api/me')
      .then((d) => setUser(d.user))
      .catch(() => setUser(null))
  }, [])

  const login = async (username, password) => {
    const d = await api('/api/login', { method: 'POST', body: { username, password } })
    setUser(d.user)
    return d.user
  }

  const logout = async () => {
    try {
      await api('/api/logout', { method: 'POST' })
    } finally {
      setUser(null)
    }
  }

  return (
    <AuthContext.Provider value={{ user, login, logout, loading: user === undefined }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}

export const isOfficer = (user) =>
  Boolean(user) && ['admin', 'state_officer', 'district_officer'].includes(user.role)
