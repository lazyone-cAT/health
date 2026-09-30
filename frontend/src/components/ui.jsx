import { useEffect } from 'react'

const svg = (d, extra = {}) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" strokeLinejoin="round" {...extra}>{d}</svg>
)

export const Icons = {
  overview: svg(<><rect x="3" y="3" width="7" height="9" /><rect x="14" y="3" width="7" height="5" /><rect x="14" y="12" width="7" height="9" /><rect x="3" y="16" width="7" height="5" /></>),
  inventory: svg(<><path d="M21 8V21H3V8" /><path d="M1 3h22v5H1z" /><path d="M10 12h4" /></>),
  medicines: svg(<><rect x="3" y="8" width="18" height="13" rx="2" /><path d="M12 8V3" /><path d="M8 3h8" /><path d="M7 13h4M13 13h4M7 17h4" /></>),
  alerts: svg(<><path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.7 21a2 2 0 0 1-3.4 0" /></>),
  swap: svg(<><path d="M16 3h5v5" /><path d="M4 20 21 3" /><path d="M21 16v5h-5" /><path d="m15 15 6 6" /><path d="M4 4l5 5" /></>),
  upload: svg(<><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5-5 5 5" /><path d="M12 5v13" /></>),
  federated: svg(<><circle cx="12" cy="5" r="2.5" /><circle cx="5" cy="19" r="2.5" /><circle cx="19" cy="19" r="2.5" /><path d="M12 7.5 6.5 16.8M12 7.5l5.5 9.3M7.5 19h9" /></>),
  audit: svg(<><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /><path d="M8 13h8M8 17h5" /></>),
  logout: svg(<><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="m16 17 5-5-5-5" /><path d="M21 12H9" /></>),
  search: svg(<><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></>),
  logo: svg(<><path d="M12 2 3 7v10l9 5 9-5V7z" /><path d="M12 22V12" /><path d="m3 7 9 5 9-5" /></>),
  beds: svg(<><path d="M2 18v-6h20v6" /><path d="M2 18v3M22 18v3" /><path d="M4 12V6h6a3 3 0 0 1 3 3v3" /><path d="M13 12V9h6a3 3 0 0 1 3 3v0" /><circle cx="7.5" cy="8.5" r="1.5" /></>),
}

export function KpiCard({ label, value, detail, tone }) {
  return (
    <div className="kpi-card">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${tone || ''}`}>{value}</div>
      {detail && <div className="kpi-detail">{detail}</div>}
    </div>
  )
}

export function Panel({ title, icon, children, right }) {
  return (
    <div className="panel">
      <div className="panel-title">
        {icon && Icons[icon]}
        <span>{title}</span>
        {right && <span style={{ marginLeft: 'auto' }}>{right}</span>}
      </div>
      {children}
    </div>
  )
}

const STATUS_LABEL = {
  stock_out: 'Stock-out',
  critical: 'Critical',
  low: 'Low',
  ok: 'OK',
}

export function StatusChip({ status, days }) {
  const label = STATUS_LABEL[status] || status
  const suffix = days != null && status !== 'stock_out' && status !== 'ok' ? ` · ${days}d` : ''
  return <span className={`chip chip-${status}`}>{label}{suffix}</span>
}

export function Empty({ children = 'Nothing to show here.' }) {
  return <div className="empty">{children}</div>
}

export function Spinner() {
  return <div className="spinner" />
}

export function Toast({ message, error, onClose }) {
  useEffect(() => {
    if (!message) return undefined
    const t = setTimeout(onClose, 3200)
    return () => clearTimeout(t)
  }, [message, onClose])
  if (!message) return null
  return <div className={`toast ${error ? 'error' : ''}`}>{message}</div>
}

export function Modal({ title, children, onClose }) {
  return (
    <div className="modal-overlay show" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div className="modal-title">{title}</div>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}

export function CoverageBar({ days }) {
  const pct = Math.max(0, Math.min(100, ((days || 0) / 30) * 100))
  const tone = days == null ? '' : days < 7 ? 'danger' : days < 14 ? 'warn' : ''
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div className="cover-bar"><div className={`cover-fill ${tone}`} style={{ width: `${pct}%` }} /></div>
      <span className="mono" style={{ fontSize: '0.74rem' }}>{days == null ? '—' : `${days}d`}</span>
    </div>
  )
}

export function PageHeader({ title, subtitle, children }) {
  return (
    <div className="page-header">
      <div>
        <h1 className="page-title">{title}</h1>
        {subtitle && <div className="page-subtitle">{subtitle}</div>}
      </div>
      <div className="page-actions">{children}</div>
    </div>
  )
}
