import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { Empty, KpiCard, PageHeader, Panel, Spinner, StatusChip } from '../components/ui'

export default function Overview() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api('/api/overview').then(setData).catch((e) => setError(e.message))
  }, [])

  if (error) return <Empty>{error}</Empty>
  if (!data) return <Spinner />

  const s = data.stats
  const scoped = user.role === 'phc_manager'

  return (
    <>
      <PageHeader
        title={scoped ? `${user.phc_name} — Stock Overview` : 'District Overview'}
        subtitle={`Days of cover = stock ÷ average daily consumption. Below 7 days is critical, below 14 days is low.`}
      >
        <Link className="btn" to="/alerts">Open alerts</Link>
        {!scoped && <Link className="btn btn-primary" to="/redistribution">Redistribution</Link>}
      </PageHeader>

      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(4,1fr)' }}>
        <KpiCard label="PHCs reporting" value={s.phcs} detail={scoped ? 'Single facility view' : 'All facilities in district'} />
        <KpiCard label="Stock-out lines" value={s.stock_out} tone={s.stock_out ? 'red' : 'green'} detail="Stock quantity is zero" />
        <KpiCard label="Critical (<7 days)" value={s.critical} tone={s.critical ? 'yellow' : 'green'} detail="Will run out this week" />
        <KpiCard label="Open alerts" value={s.open_alerts} tone={s.open_alerts ? 'red' : 'green'} detail={`${s.lines} inventory lines tracked`} />
      </div>

      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(4,1fr)' }}>
        <KpiCard label="Low (7–14 days)" value={s.low} tone={s.low ? 'yellow' : 'green'} detail="Reorder window" />
        <KpiCard label="Avg days of cover" value={s.avg_days_cover} detail="District average across all lines" />
        <KpiCard label="Medicines" value={s.medicines} detail="Essential list items" />
        <KpiCard label="District" value="Kalahandi" detail="Block-level PHC network" />
      </div>

      {!scoped && (
        <Panel title="PHC rollup" icon="inventory" right={<span style={{ fontSize: '0.7rem', color: 'var(--muted)' }}>click a facility to open its inventory</span>}>
          <div className="phc-grid">
            {data.phcs.map((p) => (
              <div key={p.phc_id} className="phc-card" style={{ cursor: 'pointer' }}
                onClick={() => navigate(`/inventory?phc_id=${p.phc_id}`)}>
                <div className="phc-card-head">
                  <div className="phc-name">{p.name}</div>
                  <div className="phc-block">{p.block}</div>
                </div>
                <div className="phc-stats">
                  <span><b>{p.lines}</b> lines</span>
                  <span><b className={p.stock_out ? 'danger' : ''}>{p.stock_out}</b> out</span>
                  <span><b>{p.critical}</b> crit</span>
                  <span><b>{p.avg_days != null ? p.avg_days.toFixed(0) : '—'}d</b> cover</span>
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
            {['stock_out', 'critical', 'low'].map((sev) => (
              <div key={sev} className="severity-card" onClick={() => navigate(`/alerts?severity=${sev}`)}>
                <div className="kpi-label">{sev === 'stock_out' ? 'Stock-out' : sev}</div>
                <div className={`severity-num ${sev}`}>{data.alerts_by_severity[sev]}</div>
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
    </>
  )
}
