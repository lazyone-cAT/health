import { useCallback, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import GeoFilters, { geoQuery } from '../components/GeoFilters'
import { Empty, PageHeader, Panel, Spinner, StatusChip, Toast } from '../components/ui'
import { Freshness, usePoll } from '../usePoll'

const TABS = [
  ['open', 'Open'],
  ['resolved', 'Resolved'],
  ['all', 'Everything'],
]

export default function Alerts() {
  const [params, setParams] = useSearchParams()
  const severity = params.get('severity') || ''
  const [tab, setTab] = useState('open')
  const [data, setData] = useState(null)
  const [toast, setToast] = useState({ message: '', error: false })

  const load = useCallback(() => {
    const qs = geoQuery(params)
    qs.set('status', tab)
    return api(`/api/alerts?${qs.toString()}`).then(setData)
  }, [tab, params])

  const { refresh, lastUpdated, error: pollError, stale } = usePoll(load)

  const act = async (id, action) => {
    try {
      await api(`/api/alerts/${id}/action`, { method: 'POST', body: { action } })
      setToast({ message: `Alert ${action}d.`, error: false })
      refresh()
    } catch (e) {
      setToast({ message: e.message, error: true })
    }
  }

  const counts = data?.counts || {}
  let alerts = data?.alerts || []
  if (severity) alerts = alerts.filter((a) => a.severity === severity)

  return (
    <>
      <PageHeader
        title="Alerts"
        subtitle="Auto-generated whenever a line falls below 14 days of cover, and auto-resolved when stock recovers."
      >
        <span className="chip chip-stock_out">{counts.stock_out || 0} stock-out</span>
        <span className="chip chip-critical">{counts.critical || 0} critical</span>
        <span className="chip chip-forecast_risk">{counts.forecast_risk || 0} forecast risk</span>
        <span className="chip chip-low">{counts.low || 0} low</span>
      </PageHeader>

      <Freshness generatedAt={data?.generated_at} lastUpdated={lastUpdated} error={pollError} stale={stale} />

      <div className="filters-row">
        <GeoFilters params={params} setParams={setParams} />
      </div>

      <div className="section-nav">
        {TABS.map(([v, l]) => (
          <a key={v} href="#" className={tab === v ? 'active' : ''}
            onClick={(e) => { e.preventDefault(); setTab(v) }}>{l}</a>
        ))}
        {severity && (
          <a href="#" className="active" onClick={(e) => {
            e.preventDefault()
            const next = new URLSearchParams(params)
            next.delete('severity')
            setParams(next)
          }}>
            severity: {severity} ✕
          </a>
        )}
      </div>

      {!data ? (pollError ? <Empty>{pollError}</Empty> : <Spinner />) : alerts.length === 0 ? (
        <Empty>{tab === 'open' ? 'No open alerts. Every tracked line has at least 14 days of cover.' : 'No alerts in this view.'}</Empty>
      ) : (
        <div className="alert-list">
          {alerts.map((a) => (
            <div key={a.id} className={`alert-item ${a.severity}`}>
              <StatusChip status={a.severity} days={a.days_of_stock} />
              <div>
                <div className="alert-msg">{a.message}</div>
                <div className="alert-meta">
                  {a.phc_name} · {a.district_name} · {a.block} block · {a.medicine} · status: {a.status}
                  {a.ack_by ? ` · by ${a.ack_by}` : ''} · raised {a.created_at}
                </div>
              </div>
              <div className="alert-actions">
                {a.status === 'open' && (
                  <button className="btn" onClick={() => act(a.id, 'acknowledge')}>Acknowledge</button>
                )}
                {a.status !== 'resolved' && (
                  <button className="btn btn-primary" onClick={() => act(a.id, 'resolve')}>Resolve</button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <Panel title="Severity thresholds" icon="alerts">
        <div style={{ fontSize: '0.78rem', color: 'var(--muted)' }}>
          <span className="mono">stock_out</span> = stock ≤ 0 ·{' '}
          <span className="mono">critical</span> = days_of_stock &lt; 7 ·{' '}
          <span className="mono">low</span> = 7 ≤ days_of_stock &lt; 14 ·{' '}
          <span className="mono">forecast_risk</span> = Ridge model projects a stock-out within 10 days ·{' '}
          <span className="mono">ok</span> = ≥ 14 days. PHC in-charges see only their own facility's alerts.
        </div>
      </Panel>

      <Toast message={toast.message} error={toast.error} onClose={() => setToast({ message: '', error: false })} />
    </>
  )
}
