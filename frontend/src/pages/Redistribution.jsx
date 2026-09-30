import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth, isOfficer } from '../auth'
import { Empty, PageHeader, Panel, Spinner, StatusChip, Toast } from '../components/ui'

const NEXT_STEP = {
  proposed: [['accepted', 'Approve'], ['rejected', 'Reject'], ['cancelled', 'Cancel']],
  accepted: [['dispatched', 'Mark dispatched'], ['cancelled', 'Cancel']],
  dispatched: [['delivered', 'Mark delivered']],
  delivered: [],
  rejected: [],
  cancelled: [],
}

const STATUS_CHIP = { proposed: 'low', accepted: 'critical', dispatched: 'critical', delivered: 'ok', cancelled: 'stock_out', rejected: 'muted' }

export default function Redistribution() {
  const { user } = useAuth()
  const officer = isOfficer(user)
  const [suggestions, setSuggestions] = useState(null)
  const [transfers, setTransfers] = useState(null)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState({ message: '', error: false })

  const load = useCallback(() => {
    api('/api/redistribution?status=all').then((d) => setTransfers(d.redistributions))
      .catch((e) => setToast({ message: e.message, error: true }))
    if (officer) {
      api('/api/redistribution/suggestions').then((d) => setSuggestions(d.suggestions))
        .catch(() => setSuggestions([]))
    } else {
      setSuggestions([])
    }
  }, [officer])

  useEffect(() => { load() }, [load])

  const autoPropose = async () => {
    setBusy(true)
    try {
      const r = await api('/api/redistribution/auto-propose', { method: 'POST', body: {} })
      setToast({
        message: r.created
          ? `Proposed ${r.created} transfer(s)${r.skipped ? `, skipped ${r.skipped} already open` : ''}.`
          : `Nothing new to propose${r.skipped ? ` (${r.skipped} already open)` : ''}.`,
        error: false,
      })
      load()
    } catch (e) {
      setToast({ message: e.message, error: true })
    } finally {
      setBusy(false)
    }
  }

  const propose = async (s, donor) => {
    try {
      await api('/api/redistribution', {
        method: 'POST',
        body: {
          from_phc_id: donor ? donor.phc_id : null,
          to_phc_id: s.phc_id,
          medicine_id: s.medicine_id,
          quantity: donor ? donor.offer : s.shortfall,
          reason: `Cover ${s.status.replace('_', ' ')} at ${s.phc_name}`,
        },
      })
      setToast({ message: `Transfer proposed: ${donor ? donor.offer : s.shortfall} units → ${s.phc_name}.`, error: false })
      load()
    } catch (e) {
      setToast({ message: e.message, error: true })
    }
  }

  const advance = async (id, status) => {
    try {
      await api(`/api/redistribution/${id}/status`, { method: 'POST', body: { status } })
      setToast({ message: `Transfer marked ${status}.`, error: false })
      load()
    } catch (e) {
      setToast({ message: e.message, error: true })
    }
  }

  return (
    <>
      <PageHeader
        title="Redistribution"
        subtitle={`Move surplus stock to PHCs below 14 days of cover. Donor search starts in your own district and widens to the state when no local surplus exists. Target safety stock: 14 days.`}
      >
        {officer && (
          <button className="btn btn-primary" disabled={busy} onClick={autoPropose}>
            {busy ? 'Proposing…' : 'Auto-propose all'}
          </button>
        )}
      </PageHeader>

      <div className="grid-2">
        <Panel title="Suggestions — who needs what" icon="swap"
          right={officer ? <span style={{ fontSize: '0.68rem', color: 'var(--muted)' }}>district-first, state-wide fallback</span> : <span style={{ fontSize: '0.68rem', color: 'var(--muted)' }}>PHC in-charge view</span>}>
          {!suggestions ? <Spinner /> : suggestions.length === 0 ? (
            <Empty>No line is below 14 days of cover — nothing needs redistributing.</Empty>
          ) : suggestions.map((s, i) => (
            <div key={`${s.phc_id}-${s.medicine_id}-${i}`} className="sugg-card">
              <div className="sugg-head">
                <div>
                  <div style={{ fontWeight: 700, fontSize: '0.86rem' }}>{s.medicine}</div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--muted)' }}>
                    {s.phc_name} · {s.district_name} needs {s.shortfall} {s.unit} to reach 14 days
                  </div>
                </div>
                <StatusChip status={s.status} days={s.days_of_stock} />
              </div>
              {s.donors.length === 0 ? (
                <div style={{ fontSize: '0.76rem', color: 'var(--danger)' }}>
                  No PHC in your scope has surplus of this medicine — raise a district-pool order.
                </div>
              ) : (
                <>
                  {s.donors.map((d) => (
                    <div key={`${d.phc_id}-${d.scope}`} className="sugg-donor">
                      <div>
                        <b>{d.phc_name}</b>
                        <span style={{ color: 'var(--muted)' }}> · {d.district_name} · {d.days}d cover · surplus {d.surplus}</span>
                        {d.district_name !== s.district_name && (
                          <span className="chip chip-low" style={{ marginLeft: 6 }}>
                            {d.state_name === s.state_name ? 'other district' : 'other state'}
                          </span>
                        )}
                      </div>
                      {officer ? (
                        <button className="btn btn-primary" onClick={() => propose(s, d)}>
                          Propose {d.offer} {s.unit}
                        </button>
                      ) : (
                        <span className="chip chip-ok">available</span>
                      )}
                    </div>
                  ))}
                  {!s.can_cover && (
                    <div style={{ fontSize: '0.74rem', color: 'var(--warn)' }}>
                      Surplus found covers only part of the shortfall.
                    </div>
                  )}
                </>
              )}
            </div>
          ))}
        </Panel>

        <Panel title="Transfer board" icon="inventory">
          {!transfers ? <Spinner /> : transfers.length === 0 ? (
            <Empty>No transfers yet. Propose one from the suggestions panel.</Empty>
          ) : (
            <div className="data-table-wrap table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>#</th><th>Medicine</th><th>From</th><th>To</th>
                    <th>Qty</th><th>Status</th><th>By</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {transfers.map((t) => (
                    <tr key={t.id}>
                      <td className="mono">{t.id}</td>
                      <td style={{ fontWeight: 600 }}>{t.medicine}</td>
                      <td>
                        {t.from_phc_name || 'District pool'}
                        {t.from_district_name && t.from_district_name !== t.to_district_name && (
                          <div style={{ fontSize: '0.66rem', color: 'var(--muted)' }}>{t.from_district_name} → {t.to_district_name}</div>
                        )}
                      </td>
                      <td>{t.to_phc_name}</td>
                      <td className="mono">{t.quantity} {t.unit}</td>
                      <td><span className={`chip chip-${STATUS_CHIP[t.status] || 'ok'}`}>{t.status}</span></td>
                      <td style={{ color: 'var(--muted)' }}>{t.created_by}</td>
                      <td>
                        {(NEXT_STEP[t.status] || []).map(([st, label]) => (
                          <button key={st} className={`btn ${st === 'accepted' || st === 'delivered' ? 'btn-primary' : ''}`}
                            style={{ marginRight: 6 }} onClick={() => advance(t.id, st)}>
                            {label}
                          </button>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div style={{ fontSize: '0.74rem', color: 'var(--muted)', marginTop: 10 }}>
            Marking a transfer <b>delivered</b> moves the stock: donor quantity is deducted and the
            receiving PHC's line is topped up, then all alerts are recalculated.
          </div>
        </Panel>
      </div>

      <Toast message={toast.message} error={toast.error} onClose={() => setToast({ message: '', error: false })} />
    </>
  )
}
