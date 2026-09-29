import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'

const DEMO = [
  { label: 'district1 / district123  —  District Officer', u: 'district1', p: 'district123' },
  { label: 'admin / admin123  —  Admin', u: 'admin', p: 'admin123' },
  { label: 'khariar1 / phc123  —  PHC In-charge', u: 'khariar1', p: 'phc123' },
]

export default function Login() {
  const { user, login, loading } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (!loading && user) return <Navigate to="/" replace />

  const submit = async (e, u, p) => {
    if (e) e.preventDefault()
    setError('')
    setBusy(true)
    try {
      await login(u ?? username, p ?? password)
      navigate('/')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <div className="login-hero">
        <div>
          <div className="sidebar-logo" style={{ color: '#fff' }}>
            <span style={{ color: '#5eead4' }}>PHC Stock</span>
          </div>
          <h1 style={{ marginTop: 28 }}>District medicine inventory, without the spreadsheet.</h1>
          <p>
            Live stock positions across every PHC, stock-out days computed by simple
            division, redistribution suggestions, and an audit trail for every change.
          </p>
          <div className="hero-kpis">
            <div className="hero-kpi"><div className="n">8</div><div className="l">PHCs tracked</div></div>
            <div className="hero-kpi"><div className="n">20</div><div className="l">Essential medicines</div></div>
            <div className="hero-kpi"><div className="n">÷</div><div className="l">Stock / daily usage</div></div>
          </div>
        </div>
        <div style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
          Stock-out logic: days of cover = stock ÷ average daily consumption. No black box.
        </div>
      </div>

      <div className="login-form-side">
        <div className="login-card">
          <h2 className="page-title" style={{ marginBottom: 4 }}>Sign in</h2>
          <div className="page-subtitle" style={{ marginBottom: 18 }}>
            Role-based access — district view, PHC-scoped view, or admin.
          </div>
          <form onSubmit={submit}>
            <div className="form-group">
              <label className="form-label" htmlFor="username">Username</label>
              <input id="username" className="form-input" value={username}
                onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="password">Password</label>
              <input id="password" type="password" className="form-input" value={password}
                onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
            </div>
            {error && <div className="stale-banner" style={{ margin: '8px 0' }}>{error}</div>}
            <button className="btn btn-primary" style={{ width: '100%', justifyContent: 'center' }} disabled={busy}>
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
          <div className="demo-creds">
            <div style={{ fontWeight: 700, marginBottom: 4 }}>Demo accounts — click to sign in</div>
            {DEMO.map((d) => (
              <button key={d.u} type="button" onClick={(e) => submit(e, d.u, d.p)}>{d.label}</button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
