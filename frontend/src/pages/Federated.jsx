import { useEffect, useState } from 'react'
import { api } from '../api'
import { Empty, PageHeader, Panel, Spinner } from '../components/ui'

export default function Federated() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api('/api/federated/demo').then(setData).catch((e) => setError(e.message))
  }, [])

  if (error) return <Empty>{error}</Empty>
  if (!data) return <Spinner />

  const agg = data.aggregated_result

  return (
    <>
      <PageHeader
        title="Federated Analytics — Demo"
        subtitle="Hardcoded mock of a cross-PHC federated query: nodes compute aggregates locally, only the sums leave the node."
      >
        <span className="chip chip-muted">demo data</span>
      </PageHeader>

      <div className="fed-head">
        <div>
          <div className="fed-title">{data.query}</div>
          <div className="fed-sub">{data.coordinator} · federation {data.federation_id} · {data.rounds} rounds</div>
        </div>
        <div className="fed-badges">
          <span className={`fed-badge ${data.privacy.raw_rows_shared ? 'warn' : 'ok'}`}>
            raw rows shared: {data.privacy.raw_rows_shared ? 'yes' : 'no'}
          </span>
          <span className="fed-badge">min node rows: {data.privacy.min_node_rows}</span>
          <span className="fed-badge">{data.privacy.noise}</span>
        </div>
      </div>

      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(4,1fr)' }}>
        <div className="kpi-card"><div className="kpi-label">Nodes reporting</div>
          <div className="kpi-value">{agg.nodes_reporting}<span style={{ fontSize: '1rem', color: 'var(--muted)' }}>/{agg.nodes_total}</span></div>
          <div className="kpi-detail">1 node offline this round</div></div>
        <div className="kpi-card"><div className="kpi-label">Stock-out lines (federated)</div>
          <div className="kpi-value red">{agg.stock_out}</div><div className="kpi-detail">sum of local aggregates</div></div>
        <div className="kpi-card"><div className="kpi-label">Critical lines</div>
          <div className="kpi-value yellow">{agg.critical}</div><div className="kpi-detail">below 7 days</div></div>
        <div className="kpi-card"><div className="kpi-label">Weighted avg cover</div>
          <div className="kpi-value green">{agg.weighted_avg_days_cover}</div><div className="kpi-detail">agreement {Math.round(agg.agreement_rate * 100)}%</div></div>
      </div>

      <Panel title="Nodes" icon="federated">
        <div className="node-grid">
          {data.nodes.map((n) => (
            <div key={n.node_id} className={`node-card ${n.status}`}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="node-id">{n.node_id}</span>
                <span className={`chip chip-${n.status === 'online' ? 'ok' : n.status === 'degraded' ? 'critical' : 'stock_out'}`}>{n.status}</span>
              </div>
              <div className="node-name">{n.phc}</div>
              {n.local_aggregates ? (
                <div className="node-agg">
                  <div><span>lines </span><b>{n.local_aggregates.lines_reported}</b></div>
                  <div><span>latency </span><b>{n.latency_ms}ms</b></div>
                  <div><span>stock-out </span><b>{n.local_aggregates.stock_out}</b></div>
                  <div><span>critical </span><b>{n.local_aggregates.critical}</b></div>
                  <div><span>low </span><b>{n.local_aggregates.low}</b></div>
                  <div><span>cover </span><b>{n.local_aggregates.avg_days_cover}d</b></div>
                </div>
              ) : (
                <div style={{ fontSize: '0.74rem', color: 'var(--danger)' }}>
                  No response · last seen {n.last_seen}
                </div>
              )}
              <div style={{ fontSize: '0.68rem', color: 'var(--muted)', marginTop: 8 }}>
                rounds joined: {n.rounds_joined}/{data.rounds}
              </div>
            </div>
          ))}
        </div>
      </Panel>

      <div className="grid-2" style={{ marginTop: 14 }}>
        <Panel title="Round log" icon="audit">
          {data.round_log.map((r) => (
            <div key={r.round} className="round-row">
              <span className="round-n">R{r.round}</span>
              <span className="round-phase">{r.phase}</span>
              <span className="mono" style={{ fontSize: '0.74rem' }}>{r.participants} nodes</span>
              <span style={{ color: 'var(--muted)' }}>{r.result}</span>
            </div>
          ))}
        </Panel>
        <Panel title="Privacy model" icon="overview">
          <div style={{ fontSize: '0.8rem', lineHeight: 1.7 }}>
            <div><b>Mechanism:</b> {data.privacy.mechanism}</div>
            <div><b>Raw rows shared:</b> {data.privacy.raw_rows_shared ? 'yes' : 'no — aggregates only'}</div>
            <div><b>Minimum rows per node:</b> {data.privacy.min_node_rows} (small-cell suppression)</div>
            <div><b>Noise:</b> {data.privacy.noise}</div>
          </div>
          <div className="stale-banner" style={{ marginTop: 12, background: 'var(--warn-soft)', borderColor: '#facc15', color: 'var(--warn)' }}>
            {data.demo_note}
          </div>
        </Panel>
      </div>

    </>
  )
}
