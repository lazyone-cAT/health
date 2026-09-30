import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import GeoFilters, { geoQuery } from '../components/GeoFilters'
import {
  CoverageBar, Empty, Icons, Modal, PageHeader, Spinner, StatusChip, Toast,
} from '../components/ui'

const STATUS_FILTERS = [
  ['all', 'All lines'],
  ['stock_out', 'Stock-out'],
  ['critical', 'Critical <7d'],
  ['low', 'Low 7–14d'],
  ['ok', 'OK ≥14d'],
]

export default function Inventory() {
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const [rows, setRows] = useState(null)
  const [proj, setProj] = useState({})
  const [q, setQ] = useState(params.get('q') || '')
  const [status, setStatus] = useState('all')
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({ stock_qty: '', avg_daily_consumption: '' })
  const [toast, setToast] = useState({ message: '', error: false })
  const canEdit = ['admin', 'district_officer', 'state_officer', 'phc_manager'].includes(user.role)

  const load = useCallback(() => {
    const qs = geoQuery(params)
    if (q) qs.set('q', q)
    if (status !== 'all') qs.set('status', status)
    Promise.all([
      api(`/api/inventory?${qs.toString()}`),
      api(`/api/forecast?${qs.toString()}&limit=1000`).catch(() => null),
    ])
      .then(([inv, fc]) => {
        setRows(inv.inventory)
        const map = {}
        for (const r of fc?.forecast || []) map[`${r.phc_id}:${r.medicine_id}`] = r
        setProj(map)
      })
      .catch((e) => setToast({ message: e.message, error: true }))
  }, [q, status, params])

  useEffect(() => { load() }, [load])

  const openEdit = (row) => {
    setEditing(row)
    setForm({ stock_qty: String(row.stock_qty), avg_daily_consumption: String(row.avg_daily_consumption) })
  }

  const save = async () => {
    try {
      const r = await api(`/api/inventory/${editing.id}/stock`, {
        method: 'POST',
        body: { stock_qty: Number(form.stock_qty), avg_daily_consumption: Number(form.avg_daily_consumption) },
      })
      setEditing(null)
      const note = r.days_of_stock == null
        ? 'Saved (no consumption baseline yet)'
        : `Saved — ${r.days_of_stock} days of cover (${r.new_status})`
      setToast({ message: note, error: false })
      load()
    } catch (e) {
      setToast({ message: e.message, error: true })
    }
  }

  const exportCsv = () => {
    if (!rows) return
    const head = ['phc', 'medicine', 'category', 'stock', 'avg_daily_consumption', 'days_of_stock', 'status', 'forecast_stockout']
    const body = rows.map((r) => [r.phc_name, r.medicine, r.category, r.stock_qty,
      r.avg_daily_consumption, r.days_of_stock ?? '', r.status,
      proj[`${r.phc_id}:${r.medicine_id}`]?.stockout_date || '']
      .map((v) => `"${String(v).replaceAll('"', '""')}"`).join(','))
    const blob = new Blob([[head.join(','), ...body].join('\n')], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'phc_inventory.csv'
    a.click()
  }

  return (
    <>
      <PageHeader
        title="Inventory"
        subtitle="Every PHC × medicine line with days of cover, computed as stock ÷ average daily consumption. Filters cascade state → district → PHC."
      >
        <button className="btn" onClick={exportCsv}>Export CSV</button>
        <button className="btn btn-primary" onClick={load}>Refresh</button>
      </PageHeader>

      <div className="filters-row">
        <div className="search-bar">
          {Icons.search}
          <input placeholder="Search medicine or PHC…" value={q}
            onChange={(e) => setQ(e.target.value)} />
        </div>
        <GeoFilters params={params} setParams={setParams} />
        <select className="form-select" value={status} onChange={(e) => setStatus(e.target.value)}>
          {STATUS_FILTERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </div>

      {!rows ? <Spinner /> : rows.length === 0 ? <Empty>No inventory lines match these filters.</Empty> : (
        <div className="data-table-wrap table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>PHC</th><th>Medicine</th><th>Category</th>
                <th>Stock</th><th>Daily use</th><th>Days of cover</th>
                <th>Status</th><th>Stock-out (forecast)</th><th>Surplus</th><th>Updated</th><th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const f = proj[`${r.phc_id}:${r.medicine_id}`]
                return (
                <tr key={r.id} className={r.status === 'stock_out' ? 'conflict-row' : ''}>
                  <td>{r.phc_name}<div style={{ fontSize: '0.66rem', color: 'var(--muted)' }}>{r.district_name} · {r.block} block</div></td>
                  <td style={{ fontWeight: 600 }}>{r.medicine}</td>
                  <td>{r.category}</td>
                  <td className="mono">{r.stock_qty}</td>
                  <td className="mono">{r.avg_daily_consumption}</td>
                  <td><CoverageBar days={r.days_of_stock} /></td>
                  <td><StatusChip status={r.status} days={r.days_of_stock} /></td>
                  <td className="mono" style={{ fontSize: '0.72rem', color: f ? '#4338ca' : 'var(--muted)' }}>
                    {f ? (f.stockout_date || '—') : '—'}
                    {f?.days_to_stockout != null && <span style={{ color: 'var(--muted)' }}> · {f.days_to_stockout}d</span>}
                  </td>
                  <td className="mono">{r.surplus > 0 ? r.surplus : '—'}</td>
                  <td style={{ color: 'var(--muted)' }}>{(r.updated_at || '').slice(0, 10)}</td>
                  <td>{canEdit && <button className="btn" onClick={() => openEdit(r)}>Update</button>}</td>
                </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <Modal title={`Update stock — ${editing.medicine}`} onClose={() => setEditing(null)}>
          <div style={{ fontSize: '0.78rem', color: 'var(--muted)', marginBottom: 10 }}>
            {editing.phc_name} · currently {editing.stock_qty} {editing.unit} ·{' '}
            {editing.days_of_stock == null ? 'no consumption baseline' : `${editing.days_of_stock} days of cover`}
          </div>
          <div className="form-group">
            <label className="form-label">Stock quantity ({editing.unit})</label>
            <input className="form-input" type="number" min="0" value={form.stock_qty}
              onChange={(e) => setForm({ ...form, stock_qty: e.target.value })} />
          </div>
          <div className="form-group">
            <label className="form-label">Average daily consumption</label>
            <input className="form-input" type="number" min="0" value={form.avg_daily_consumption}
              onChange={(e) => setForm({ ...form, avg_daily_consumption: e.target.value })} />
          </div>
          <div className="mono" style={{ fontSize: '0.74rem', marginBottom: 12 }}>
            days = {form.stock_qty || 0} ÷ {form.avg_daily_consumption || 0} ={' '}
            {Number(form.avg_daily_consumption) > 0
              ? (Number(form.stock_qty) / Number(form.avg_daily_consumption)).toFixed(1)
              : '—'} days
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-primary" onClick={save}>Save</button>
            <button className="btn" onClick={() => setEditing(null)}>Cancel</button>
          </div>
        </Modal>
      )}

      <Toast message={toast.message} error={toast.error} onClose={() => setToast({ message: '', error: false })} />
    </>
  )
}
