import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { Icons } from './ui'

const NAV = [
  { to: '/', label: 'Overview', icon: 'overview', roles: ['admin', 'district_officer', 'phc_manager'] },
  { to: '/inventory', label: 'Inventory', icon: 'inventory', roles: ['admin', 'district_officer', 'phc_manager'] },
  { to: '/medicines', label: 'Medicines', icon: 'medicines', roles: ['admin', 'district_officer', 'phc_manager'] },
  { to: '/alerts', label: 'Alerts', icon: 'alerts', roles: ['admin', 'district_officer', 'phc_manager'] },
  { to: '/redistribution', label: 'Redistribution', icon: 'swap', roles: ['admin', 'district_officer', 'phc_manager'] },
  { to: '/upload', label: 'Upload', icon: 'upload', roles: ['admin', 'district_officer'] },
  { to: '/federated', label: 'Federated Demo', icon: 'federated', roles: ['admin', 'district_officer', 'phc_manager'] },
  { to: '/audit', label: 'Audit Log', icon: 'audit', roles: ['admin', 'district_officer'] },
]

const ROLE_LABEL = {
  admin: 'Admin',
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

  return (
    <>
      <aside className="sidebar">
        <div className="sidebar-logo">{Icons.logo}<span>PHC Stock</span></div>
        <div className="sidebar-subtitle">District Command Center</div>
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
          {user.phc_name && <div>{user.phc_name}</div>}
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
