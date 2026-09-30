import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { Icons } from './ui'

const ALL = ['admin', 'state_officer', 'district_officer', 'phc_manager']
const OFFICERS = ['admin', 'state_officer', 'district_officer']

const NAV = [
  { to: '/', label: 'Overview', icon: 'overview', roles: ALL },
  { to: '/inventory', label: 'Inventory', icon: 'inventory', roles: ALL },
  { to: '/medicines', label: 'Medicines', icon: 'medicines', roles: ALL },
  { to: '/alerts', label: 'Alerts', icon: 'alerts', roles: ALL },
  { to: '/redistribution', label: 'Redistribution', icon: 'swap', roles: ALL },
  { to: '/upload', label: 'Upload', icon: 'upload', roles: OFFICERS },
  { to: '/federated', label: 'Federated', icon: 'federated', roles: ALL },
  { to: '/audit', label: 'Audit Log', icon: 'audit', roles: OFFICERS },
]

const ROLE_LABEL = {
  admin: 'Admin',
  state_officer: 'State Officer',
  district_officer: 'District Officer',
  phc_manager: 'PHC In-charge',
}

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const items = NAV.filter((n) => n.roles.includes(user.role))

  const onLogout = async () => {
    await logout()
    navigate('/login')
  }

  const scopeLine = user.phc_name
    || [user.district_name, user.state_name].filter(Boolean).join(', ')
    || 'All states'

  return (
    <>
      <aside className="sidebar">
        <div className="sidebar-logo">{Icons.logo}<span>PHC Stock</span></div>
        <div className="sidebar-subtitle">National Command Center</div>
        <ul className="nav-links">
          {items.map((n) => (
            <li key={n.to}>
              <NavLink to={n.to} end={n.to === '/'}>{Icons[n.icon]}<span>{n.label}</span></NavLink>
            </li>
          ))}
        </ul>
        <div className="sidebar-footer">
          <div style={{ fontWeight: 700, color: 'var(--fg)' }}>{user.full_name}</div>
          <div className="role-box" style={{ margin: '6px 0' }}>{ROLE_LABEL[user.role] || user.role}</div>
          <div>{scopeLine}</div>
          <button className="btn" style={{ marginTop: 8, width: '100%' }} onClick={onLogout}>
            {Icons.logout} Sign out
          </button>
        </div>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </>
  )
}
