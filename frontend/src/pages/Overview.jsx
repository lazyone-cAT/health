import { useCallback, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth, isOfficer } from '../auth'
import { Empty, KpiCard, PageHeader, Panel, Spinner, StatusChip } from '../components/ui'
import { geoQuery } from '../components/GeoFilters'
import { Freshness, usePoll } from '../usePoll'

const LEVEL_TITLE = {
  country: 'States',
  state: 'Districts',
  district: 'Primary Health Centres',
  phc: 'Facility',
}

export default function Overview() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    const qs = geoQuery(params)
    return api(`/api/overview?${qs.toString()}`).then(setData)
  }, [params])

  const { refresh, lastUpdated, error: pollError, stale } = usePoll(load)

  if (!data) return pollError ? <Empty>{pollError}</Empty> : <Spinner />

  const s = data.stats
  const scoped = user.role === 'phc_manager'
  const scopeLabel = data.level === 'country'
    ? 'India'
    : data.level === 'state'
      ? data.geo_names.state
      : data.level === 'district'
        ? data.geo_names.district
        : data.geo_names.phc

  const hierarchy = s.states > 1
    ? `${s.states} states · ${s.districts} districts in scope`
    : s.districts > 1
      ? `${s.districts} districts in ${data.geo_names.state}`
      : 'Single facility view'

  const drillParams = (child) => {
    if (data.level === 'country') return { state_id: child.id }
    if (data.level === 'state') return { state_id: data.geo.state_id, district_id: child.id }
    if (data.level === 'district') return { phc_id: child.id }
    return { phc_id: data.geo.phc_id }
  }

  const openChild = (child) => {
    if (data.level === 'phc') navigate(`/inventory?phc_id=${data.geo.phc_id}`)
    else setParams(drillParams(child))
  }

  const crumbs = data.breadcrumb || [{ level: 'country', label: 'India', params: {} }]
  const fc = data.forecast || { top_risks: [], models: {}, settings: {} }
  const emergency = Boolean(fc.settings?.emergency_mode)
  const SEV_LABEL = { stock_out: 'Stock-out', critical: 'Critical', forecast_risk: 'Forecast risk', low: 'Low' }

  const toggleEmergency = async () => {
    setBusy(true)
    try {
      await api('/api/settings', { method: 'POST', body: { emergency_mode: !emergency } })
      await refresh()
      setError('')
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader
        title={`${scopeLabel} — Stock Overview`}
        subtitle="Days of cover = stock ÷ average daily consumption. Below 7 days is critical, below 14 days is low."
      >
        <Link className="btn" to="/alerts">Open alerts</Link>
        <Link className="btn" to="/beds">Beds &amp; Staff</Link>
        {!scoped && <Link className="btn btn-primary" to="/redistribution">Redistribution</Link>}
      </PageHeader>

      <Freshness generatedAt={data.generated_at} lastUpdated={lastUpdated} error={pollError} stale={stale} />
      {error && <div className="stale-banner" role="alert">{error}</div>}

      <nav className="crumbs" aria-label="Drill-down path">
        {crumbs.map((c, i) => (
          <span key={`${c.level}-${i}`}>
            {i > 0 && <span className="crumb-sep">›</span>}
            {i < crumbs.length - 1 ? (
              <a href="#" onClick={(e) => { e.preventDefault(); setParams(c.params) }}>{c.label}</a>
            ) : (
              <b>{c.label}</b>
            )}
          </span>
        ))}
        <span className="crumb-sep">·</span>
        <span className="crumb-note">level: {data.level}</span>
      </nav>

      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(4,1fr)' }}>
        <KpiCard label="PHCs reporting" value={s.phcs} detail={hierarchy} />
        <KpiCard label="Stock-out lines" value={s.stock_out} tone={s.stock_out ? 'red' : 'green'} detail="Stock quantity is zero" />
        <KpiCard label="Critical (<7 days)" value={s.critical} tone={s.critical ? 'yellow' : 'green'} detail="Will run out this week" />
        <KpiCard label="Open alerts" value={s.open_alerts} tone={s.open_alerts ? 'red' : 'green'}
          detail={`${s.lines} lines · ${s.medicines} medicines`} />
      </div>

      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(4,1fr)' }}>
        <KpiCard label="Low (7–14 days)" value={s.low} tone={s.low ? 'yellow' : 'green'} detail="Reorder window" />
        <KpiCard label="Avg days of cover" value={s.avg_days_cover} detail="Average across visible lines" />
        <KpiCard label="Beds occupied" value={s.beds_occupancy_pct ? `${s.beds_occupancy_pct}%` : '—'}
          tone={s.beds_occupancy_pct >= 90 ? 'red' : s.beds_occupancy_pct >= 75 ? 'yellow' : 'green'}
          detail={`${s.beds_occupied} of ${s.beds_total} beds · ${s.beds_available} free`} />
        <KpiCard label="Staff present today" value={s.staff_present_pct ? `${s.staff_present_pct}%` : '—'}
          tone={s.staff_present_pct >= 90 ? 'green' : 'yellow'}
          detail={`${s.staff_present} of ${s.staff_total} posts · ${s.staff_on_leave} on leave`} />
      </div>

      {!scoped && data.level !== 'phc' && data.children.length > 0 && (
        <Panel title={LEVEL_TITLE[data.level]} icon="inventory"
          right={<span style={{ fontSize: '0.7rem', color: 'var(--muted)' }}>
            {data.level === 'phc' ? 'open full inventory' : 'click to drill down'}
          </span>}>
          <div className="phc-grid">
            {data.children.map((c) => (
              <div key={c.id} className="phc-card" style={{ cursor: 'pointer' }}
                onClick={() => openChild(c)}>
                <div className="phc-card-head">
                  <div className="phc-name">{c.name}</div>
                  <div className="phc-block">{c.code || c.block || ''}</div>
                </div>
                <div className="phc-stats">
                  <span><b>{c.phcs}</b> {data.level === 'district' ? 'site' : 'PHCs'}</span>
                  <span><b className={c.stock_out ? 'danger' : ''}>{c.stock_out}</b> out</span>
                  <span><b>{c.critical}</b> crit</span>
                  <span><b>{c.avg_days != null ? c.avg_days.toFixed(0) : '—'}d</b> cover</span>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {data.level === 'phc' && (
        <Panel title="Facility" icon="inventory"
          right={<Link className="btn" to={`/inventory?phc_id=${data.geo.phc_id}`}>Open inventory</Link>}>
          <div className="phc-grid">
            {data.children.map((c) => (
              <div key={c.id} className="phc-card">
                <div className="phc-card-head">
                  <div className="phc-name">{c.name}</div>
                  <div className="phc-block">{c.block}</div>
                </div>
                <div className="phc-stats">
                  <span><b>{c.lines}</b> lines</span>
                  <span><b className={c.stock_out ? 'danger' : ''}>{c.stock_out}</b> out</span>
                  <span><b>{c.critical}</b> crit</span>
                  <span><b>{c.beds}</b> beds</span>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      )}

      <div className="grid-2">
        <Panel title="Most urgent alerts" icon="alerts" right={<Link className="btn" to="/alerts">View all</Link>}>
          {data.top_alerts.length === 0 ? (
            <Empty>No open alerts — every line has at least 14 days of cover.</Empty>
          ) : (
            <div className="alert-list">
              {data.top_alerts.map((a) => (
                <div key={a.id} className={`alert-item ${a.severity}`}>
                  <StatusChip status={a.severity} days={a.days_of_stock} />
                  <div>
                    <div className="alert-msg">{a.message}</div>
                    <div className="alert-meta">{a.phc_name} · {a.medicine} · {a.status}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Alerts by severity" icon="overview">
          <div className="severity-strip" style={{ marginBottom: 0 }}>
            {['stock_out', 'critical', 'forecast_risk', 'low'].map((sev) => (
              <div key={sev} className="severity-card"
                onClick={() => {
                  const next = new URLSearchParams(geoQuery(params))
                  next.set('severity', sev)
                  navigate(`/alerts?${next.toString()}`)
                }}>
                <div className="kpi-label">{SEV_LABEL[sev]}</div>
                <div className={`severity-num ${sev}`}>{data.alerts_by_severity[sev] || 0}</div>
                <div className="kpi-detail">open alerts</div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 14, fontSize: '0.76rem', color: 'var(--muted)' }}>
            Formula: <span className="mono">days_of_stock = stock_qty ÷ avg_daily_consumption</span>.
            Alerts refresh automatically after every stock edit or file upload.
          </div>
        </Panel>
      </div>

      <Panel title="Demand forecast" icon="federated"
        right={<span style={{ fontSize: '0.7rem', color: 'var(--muted)' }}>
          Ridge · {fc.models?.trained || 0} models · 14-day horizon · avg R² {fc.models?.avg_r2 ?? '—'}
        </span>}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          {isOfficer(user) && (
            <button className={`btn ${emergency ? 'btn-primary' : ''}`} disabled={busy}
              onClick={toggleEmergency}>
              Emergency demand {emergency ? 'ON' : 'OFF'}
            </button>
          )}
          <span style={{ fontSize: '0.74rem', color: 'var(--muted)' }}>
            {emergency
              ? `Forecast demand multiplied by ×${fc.settings?.emergency_multiplier ?? 1.5} — projected stock-out dates move earlier.`
              : 'Emergency mode multiplies forecast demand (default ×1.5) to stress-test stock-out dates.'}
          </span>
        </div>
        {fc.top_risks.length === 0 ? (
          <Empty>No line is projected to run out inside the 14-day forecast window.</Empty>
        ) : (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr><th>PHC</th><th>Medicine</th><th>Stock</th><th>Projected stock-out</th><th>Days</th><th>R²</th></tr>
              </thead>
              <tbody>
                {fc.top_risks.map((r, i) => (
                  <tr key={`${r.phc_name}-${r.medicine}-${i}`}>
                    <td>{r.phc_name}</td>
                    <td style={{ fontWeight: 600 }}>{r.medicine}</td>
                    <td className="mono">{r.stock_qty}</td>
                    <td className="mono">{r.stockout_date || '—'}</td>
                    <td><StatusChip status="forecast_risk" days={r.days_to_stockout} /></td>
                    <td className="mono">{r.r2 ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div style={{ marginTop: 10, fontSize: '0.76rem', color: 'var(--muted)' }}>
          One Ridge model per PHC × medicine, trained on 90 days of consumption history
          (day-of-week, trend, 7/30-day lags; last 14 days held out for R²).
          Lines at risk inside 10 days also raise a <span className="mono">forecast_risk</span> alert.
        </div>
      </Panel>
    </>
  )
}
