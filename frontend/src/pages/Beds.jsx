import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { Empty, KpiCard, Modal, PageHeader, Panel, Spinner, Toast } from '../components/ui'

const pctBar = (pct, tone) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
    <div className="cover-bar" style={{ minWidth: 70 }}>
      <div className={`cover-fill ${tone}`} style={{ width: `${Math.min(100, pct)}%` }} />
    </div>
    <span className="mono" style={{ fontSize: '0.74rem' }}>{pct}%</span>
  </div>
)

const toneFor = (pct) => (pct >= 90 ? 'danger' : pct >= 75 ? 'warn' : '')

export default function Beds() {
  const { user } = useAuth()
  const [beds, setBeds] = useState(null)
  const [staff, setStaff] = useState(null)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({})
  const [toast, setToast] = useState({ message: '', error: false })
  const canEdit = ['admin', 'district_officer', 'state_officer', 'phc_manager'].includes(user.role)

  const load = useCallback(() => {
    api('/api/beds').then(setBeds).catch((e) => setToast({ message: e.message, error: true }))
    api('/api/staff').then(setStaff).catch((e) => setToast({ message: e.message, error: true }))
  }, [])

  useEffect(() => { load() }, [load])

  const save = async () => {
    try {
      if (editing.kind === 'beds') {
        await api(`/api/beds/${editing.phc.phc_id}`, {
          method: 'POST',
          body: { bed_type: editing.row.bed_type, occupied: Number(form.occupied) },
        })
        setToast({ message: `Saved — ${editing.row.bed_type} occupancy updated.`, error: false })
      } else {
        await api('/api/staff', {
          method: 'POST',
          body: {
            phc_id: editing.phc.phc_id,
            staff_role: editing.row.staff_role,
            present: Number(form.present),
            on_leave: Number(form.on_leave),
          },
        })
        setToast({ message: `Saved — ${editing.row.staff_role} attendance updated.`, error: false })
      }
      setEditing(null)
      load()
    } catch (e) {
      setToast({ message: e.message, error: true })
    }
  }

  if (!beds || !staff) return <Spinner />

  const bs = beds.summary
  const ss = staff.summary

  return (
    <>
      <PageHeader
        title="Beds & Staff"
        subtitle="Aggregate bed capacity and duty staffing across the visible network. Capacity rows only — no patient-level data is ever stored."
      >
        <button className="btn btn-primary" onClick={load}>Refresh</button>
      </PageHeader>

      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(4,1fr)' }}>
        <KpiCard label="Beds (capacity)" value={bs.total} detail={`${bs.phcs} facilities reporting`} />
        <KpiCard label="Beds occupied" value={bs.occupied} tone={bs.occupancy_pct >= 90 ? 'red' : 'yellow'}
          detail={`${bs.occupancy_pct}% occupancy network-wide`} />
        <KpiCard label="Beds available" value={bs.available} tone={bs.available ? 'green' : 'red'}
          detail="Vacant right now" />
        <KpiCard label="Staff present today" value={ss.present}
          tone={ss.present_pct >= 90 ? 'green' : 'yellow'}
          detail={`${ss.present_pct}% of ${ss.staff} sanctioned posts · ${ss.on_leave} on leave`} />
      </div>

      <div className="grid-2">
        <Panel title="Bed occupancy by facility" icon="beds"
          right={<span style={{ fontSize: '0.68rem', color: 'var(--muted)' }}>
            {canEdit ? 'officers can update' : 'read-only'}
          </span>}>
          {!beds.beds.length ? <Empty>No bed capacity rows in scope.</Empty> : (
            <div className="data-table-wrap table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>PHC</th><th>General</th><th>Maternity</th><th>Oxygen</th>
                    <th>Isolation</th><th>Occupancy</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {beds.beds.map((b) => {
                    const cell = (type) => {
                      const t = b.types.find((x) => x.bed_type === type)
                      if (!t) return <td className="mono">—</td>
                      return (
                        <td className="mono" style={{ color: t.occupied >= t.total ? 'var(--danger)' : 'inherit' }}>
                          {t.occupied}/{t.total}
                        </td>
                      )
                    }
                    return (
                      <tr key={b.phc_id}>
                        <td style={{ fontWeight: 600 }}>
                          {b.phc_name}
                          <div style={{ fontSize: '0.66rem', color: 'var(--muted)' }}>
                            {b.district_name} · {b.state_name}
                          </div>
                        </td>
                        {cell('General Ward')}
                        {cell('Maternity')}
                        {cell('Oxygen-supported')}
                        {cell('Isolation')}
                        <td>{pctBar(b.occupancy_pct, toneFor(b.occupancy_pct))}</td>
                        <td>
                          {canEdit && (
                            <button className="btn" onClick={() => {
                              setEditing({ kind: 'beds', phc: b, row: b.types[0] })
                              setForm({ occupied: String(b.types[0].occupied) })
                            }}>Update</button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel title="Staffing today" icon="audit"
          right={<span style={{ fontSize: '0.68rem', color: 'var(--muted)' }}>
            {staff.days[staff.days.length - 1]}
          </span>}>
          {!staff.today.length ? <Empty>No attendance rows in scope.</Empty> : (
            <div className="data-table-wrap table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>PHC</th><th>Present</th><th>On leave</th><th>Absent</th>
                    <th>Staffing</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {staff.today.map((s) => (
                    <tr key={s.phc_id}>
                      <td style={{ fontWeight: 600 }}>
                        {s.phc_name}
                        <div style={{ fontSize: '0.66rem', color: 'var(--muted)' }}>
                          {s.roles.map((r) => `${r.present}/${r.staff}`).join(' · ')}
                        </div>
                      </td>
                      <td className="mono">{s.present}</td>
                      <td className="mono">{s.on_leave}</td>
                      <td className="mono" style={{ color: s.absent > 0 ? 'var(--warn)' : 'inherit' }}>{s.absent}</td>
                      <td>{pctBar(s.present_pct, toneFor(s.present_pct))}</td>
                      <td>
                        {canEdit && (
                          <button className="btn" onClick={() => {
                            setEditing({ kind: 'staff', phc: s, row: s.roles[0] })
                            setForm({ present: String(s.roles[0].present), on_leave: String(s.roles[0].on_leave) })
                          }}>Update</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>

      <Panel title="Attendance trend — last 7 days" icon="overview">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7,1fr)', gap: 10 }}>
          {staff.trend.map((t) => (
            <div key={t.duty_date} className="validation-cell">
              <div className="v-num" style={{ fontSize: '1.15rem' }}>{t.present}</div>
              <div className="v-lab">{t.duty_date.slice(5)}</div>
              <div className="mono" style={{ fontSize: '0.68rem', color: 'var(--muted)', marginTop: 4 }}>
                {t.present_pct}% · {t.on_leave} leave
              </div>
              <div className="cover-bar" style={{ minWidth: 0, marginTop: 6 }}>
                <div className={`cover-fill ${toneFor(t.present_pct)}`} style={{ width: `${t.present_pct}%` }} />
              </div>
            </div>
          ))}
        </div>
        <div style={{ fontSize: '0.74rem', color: 'var(--muted)', marginTop: 10 }}>
          Beds are aggregate capacity rows (total vs occupied) per facility — this platform
          never records patient identities, diagnoses or bed assignments.
        </div>
      </Panel>

      {editing && (
        <Modal title={
          editing.kind === 'beds'
            ? `Update beds — ${editing.phc.phc_name}`
            : `Update attendance — ${editing.phc.phc_name}`
        } onClose={() => setEditing(null)}>
          {editing.kind === 'beds' ? (
            <>
              <div className="form-group">
                <label className="form-label">Bed type</label>
                <select className="form-select" value={editing.row.bed_type}
                  onChange={(e) => {
                    const row = editing.phc.types.find((t) => t.bed_type === e.target.value)
                    setEditing({ ...editing, row })
                    setForm({ occupied: String(row.occupied) })
                  }}>
                  {editing.phc.types.map((t) => (
                    <option key={t.id} value={t.bed_type}>{t.bed_type}</option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Occupied ({editing.row.total} total)</label>
                <input className="form-input" type="number" min="0" max={editing.row.total}
                  value={form.occupied}
                  onChange={(e) => setForm({ ...form, occupied: e.target.value })} />
              </div>
              <div className="mono" style={{ fontSize: '0.74rem', marginBottom: 12 }}>
                occupancy = {form.occupied || 0} ÷ {editing.row.total} ={' '}
                {editing.row.total > 0 ? _pctLabel(form.occupied, editing.row.total) : '—'}
              </div>
            </>
          ) : (
            <>
              <div className="form-group">
                <label className="form-label">Role</label>
                <select className="form-select" value={editing.row.staff_role}
                  onChange={(e) => {
                    const row = editing.phc.roles.find((r) => r.staff_role === e.target.value)
                    setEditing({ ...editing, row })
                    setForm({ present: String(row.present), on_leave: String(row.on_leave) })
                  }}>
                  {editing.phc.roles.map((r) => (
                    <option key={r.id} value={r.staff_role}>{r.staff_role}</option>
                  ))}
                </select>
              </div>
              <div className="grid-2" style={{ marginBottom: 10 }}>
                <div className="form-group">
                  <label className="form-label">Present</label>
                  <input className="form-input" type="number" min="0" value={form.present}
                    onChange={(e) => setForm({ ...form, present: e.target.value })} />
                </div>
                <div className="form-group">
                  <label className="form-label">On leave</label>
                  <input className="form-input" type="number" min="0" value={form.on_leave}
                    onChange={(e) => setForm({ ...form, on_leave: e.target.value })} />
                </div>
              </div>
              <div className="mono" style={{ fontSize: '0.74rem', marginBottom: 12 }}>
                sanctioned {editing.row.staff} · present + leave must not exceed it
              </div>
            </>
          )}
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

function _pctLabel(occupied, total) {
  const pct = total > 0 ? (Number(occupied) / total) * 100 : 0
  return `${pct.toFixed(0)}%`
}
