import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { Empty, PageHeader, Panel, Spinner } from '../components/ui'

function statusChip(status) {
  if (status === 'online') return 'ok'
  if (status === 'suppressed') return 'critical'
  return 'stock_out'
}

export default function Federated() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback((resync = false) => {
    setBusy(true)
    api(`/api/federated/live${resync ? '?resync=1' : ''}`)
      .then((d) => { setData(d); setError('') })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false))
  }, [])

  useEffect(() => { load(false) }, [load])

  if (error) return <Empty>{error}</Empty>
  if (!data) return <Spinner />

  const agg = data.aggregated_result
  const card = data.model_card || {}
  const offline = agg.nodes_total - agg.nodes_reporting

  return (
    <>
      <PageHeader
        title="Federated Analytics"
        subtitle="Live federation round: every state node trains the demand model on its own data; only aggregates and coefficients reach the coordinator."
      >
        <button className="btn" onClick={() => load(true)} disabled={busy}>
          {busy ? 'Running…' : 'Resync nodes'}
        </button>
        <span className="chip chip-ok">live · {data.generated_at}</span>
      </PageHeader>

      <div className="fed-head">
        <div>
          <div className="fed-title">{data.query}</div>
          <div className="fed-sub">
            {data.coordinator} · federation {data.federation_id} · {data.rounds} rounds · {data.total_ms}ms
          </div>
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
          <div className="kpi-detail">{offline ? `${offline} node(s) suppressed this round` : 'all state nodes responded'}</div></div>
        <div className="kpi-card"><div className="kpi-label">Stock-out lines (federated)</div>
          <div className="kpi-value red">{agg.stock_out}</div><div className="kpi-detail">secure sum of {agg.lines} local aggregates</div></div>
        <div className="kpi-card"><div className="kpi-label">Critical lines</div>
          <div className="kpi-value yellow">{agg.critical}</div><div className="kpi-detail">below 7 days cover</div></div>
        <div className="kpi-card"><div className="kpi-label">FedAvg model R²</div>
          <div className="kpi-value green">{agg.fedavg_r2 ?? '—'}</div>
          <div className="kpi-detail">agreement {agg.agreement_rate != null ? Math.round(agg.agreement_rate * 100) + '%' : '—'} · {agg.fedavg_train_rows} rows</div></div>
      </div>

      <Panel title="State nodes" icon="federated">
        <div className="node-grid">
          {data.nodes.map((n) => (
            <div key={n.node_id} className={`node-card ${n.status}`}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="node-id">{n.node_id}</span>
                <span className={`chip chip-${statusChip(n.status)}`}>{n.status}</span>
              </div>
              <div className="node-name">{n.state}</div>
              {n.local_aggregates ? (
                <div className="node-agg">
                  <div><span>phcs </span><b>{n.local_aggregates.phcs}</b></div>
                  <div><span>lines </span><b>{n.local_aggregates.lines_reported}</b></div>
                  <div><span>latency </span><b>{n.latency_ms}ms</b></div>
                  <div><span>stock-out </span><b>{n.local_aggregates.stock_out}</b></div>
                  <div><span>critical </span><b>{n.local_aggregates.critical}</b></div>
                  <div><span>low </span><b>{n.local_aggregates.low}</b></div>
                  <div><span>cover </span><b>{n.local_aggregates.avg_days_cover}d</b></div>
                  <div><span>local R² </span><b>{n.local_model?.holdout_r2 ?? '—'}</b></div>
                </div>
              ) : (
                <div style={{ fontSize: '0.74rem', color: 'var(--danger)' }}>
                  {n.error ? `node error: ${n.error}` : 'suppressed — below minimum rows for this node'}
                </div>
              )}
              <div style={{ fontSize: '0.68rem', color: 'var(--muted)', marginTop: 8 }}>
                rounds joined: {n.rounds_joined}/{data.rounds}
                {n.local_model ? ` · trained on ${n.local_model.train_rows} local rows` : ''}
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
              <span style={{ color: 'var(--muted)' }}>{r.result} · {r.ms}ms</span>
            </div>
          ))}
        </Panel>
        <Panel title="Averaged model (FedAvg)" icon="overview">
          <div style={{ fontSize: '0.8rem', lineHeight: 1.7 }}>
            <div><b>Target:</b> <span className="mono">{card.target}</span></div>
            <div><b>Algorithm:</b> {card.algorithm}</div>
            <div><b>Features:</b> <span className="mono">{(card.features || []).join(', ')}</span></div>
            <div><b>Training rows:</b> {card.train_rows} across {data.nodes.filter((n) => n.local_model).length} node(s) · holdout {card.holdout_days}d</div>
            <div><b>Weighted local R²:</b> {card.weighted_local_r2 ?? '—'} · <b>Global holdout R²:</b> {agg.fedavg_r2 ?? '—'}</div>
            {card.coef && (
              <div style={{ marginTop: 6 }}>
                <b>Coefficients:</b>
                <div className="mono" style={{ fontSize: '0.7rem', color: 'var(--muted)', wordBreak: 'break-all' }}>
                  [{card.coef.map((c) => c.toFixed(4)).join(', ')}] + {card.intercept?.toFixed(4)}
                </div>
              </div>
            )}
          </div>
        </Panel>
      </div>

      <div className="grid-2" style={{ marginTop: 14 }}>
        <Panel title="Privacy model" icon="overview">
          <div style={{ fontSize: '0.8rem', lineHeight: 1.7 }}>
            <div><b>Mechanism:</b> {data.privacy.mechanism}</div>
            <div><b>Raw rows shared:</b> {data.privacy.raw_rows_shared ? 'yes' : 'no — aggregates and coefficients only'}</div>
            <div><b>Minimum rows per node:</b> {data.privacy.min_node_rows} (small-cell suppression)</div>
            <div><b>Noise:</b> {data.privacy.noise}</div>
          </div>
          <div className="stale-banner" style={{ marginTop: 12, background: 'var(--warn-soft)', borderColor: '#facc15', color: 'var(--warn)' }}>
            {data.live_note}
          </div>
        </Panel>
      </div>
    </>
  )
}
