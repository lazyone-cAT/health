import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth, isOfficer } from '../auth'
import {
  CoverageBar, Modal, PageHeader, Panel, Spinner, Toast,
} from '../components/ui'

export default function Medicines() {
  const { user } = useAuth()
  const [rows, setRows] = useState(null)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ name: '', category: '', strength: '', unit: 'tablet' })
  const [toast, setToast] = useState({ message: '', error: false })

  const load = () => api('/api/medicines').then((d) => setRows(d.medicines))
    .catch((e) => setToast({ message: e.message, error: true }))

  useEffect(() => { load() }, [])

  const add = async () => {
    try {
      await api('/api/medicines', { method: 'POST', body: form })
      setAdding(false)
      setForm({ name: '', category: '', strength: '', unit: 'tablet' })
      setToast({ message: 'Medicine added to the essential list.', error: false })
      load()
    } catch (e) {
      setToast({ message: e.message, error: true })
    }
  }

  return (
    <>
      <PageHeader
        title="Medicines"
        subtitle="Essential medicine catalogue with district-wide stock position and how many PHCs are already out."
      >
        {isOfficer(user) && <button className="btn btn-primary" onClick={() => setAdding(true)}>Add medicine</button>}
      </PageHeader>

      {!rows ? <Spinner /> : (
        <div className="data-table-wrap table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Medicine</th><th>Category</th><th>Strength</th><th>Unit</th>
                <th>District stock</th><th>PHCs stocked</th><th>PHCs out</th>
                <th>Avg cover</th><th>Essential</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.medicine_id}>
                  <td style={{ fontWeight: 600 }}>{m.name}</td>
                  <td>{m.category}</td>
                  <td className="mono">{m.strength || '—'}</td>
                  <td>{m.unit}</td>
                  <td className="mono">{Number(m.district_stock).toFixed(0)}</td>
                  <td className="mono">{m.stocked_phcs}</td>
                  <td className="mono" style={{ color: m.stock_out_phcs ? 'var(--danger)' : 'inherit', fontWeight: m.stock_out_phcs ? 700 : 400 }}>
                    {m.stock_out_phcs}
                  </td>
                  <td><CoverageBar days={m.avg_days} /></td>
                  <td>{m.essential ? <span className="badge">Essential</span> : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid-2" style={{ marginTop: 14 }}>
        <Panel title="How cover is calculated" icon="medicines">
          <div className="mono" style={{ fontSize: '0.8rem' }}>days_of_stock = stock_qty ÷ avg_daily_consumption</div>
          <div style={{ fontSize: '0.78rem', color: 'var(--muted)', marginTop: 8 }}>
            Stock-out when stock is 0. Critical below 7 days. Low below 14 days.
            Surplus = stock − (avg_daily_consumption × 14), and is what can be offered to another PHC.
          </div>
        </Panel>
        <Panel title="Coverage distribution" icon="overview">
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {rows && (
              <>
                <span className="chip chip-stock_out">{rows.filter((r) => r.stock_out_phcs > 0).length} medicines with a stock-out PHC</span>
                <span className="chip chip-ok">{rows.filter((r) => r.stock_out_phcs === 0).length} fully available</span>
              </>
            )}
          </div>
        </Panel>
      </div>

      {adding && (
        <Modal title="Add medicine" onClose={() => setAdding(false)}>
          <div className="form-group">
            <label className="form-label">Name</label>
            <input className="form-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div className="form-group">
            <label className="form-label">Category</label>
            <input className="form-input" value={form.category} placeholder="Analgesic, Antibiotic, NCD…"
              onChange={(e) => setForm({ ...form, category: e.target.value })} />
          </div>
          <div className="grid-2" style={{ marginBottom: 10 }}>
            <div className="form-group">
              <label className="form-label">Strength</label>
              <input className="form-input" value={form.strength} placeholder="500mg"
                onChange={(e) => setForm({ ...form, strength: e.target.value })} />
            </div>
            <div className="form-group">
              <label className="form-label">Unit</label>
              <input className="form-input" value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-primary" onClick={add}>Add</button>
            <button className="btn" onClick={() => setAdding(false)}>Cancel</button>
          </div>
        </Modal>
      )}

      <Toast message={toast.message} error={toast.error} onClose={() => setToast({ message: '', error: false })} />
    </>
  )
}
