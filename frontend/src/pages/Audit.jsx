import { useEffect, useState } from 'react'
import { api } from '../api'
import { Empty, PageHeader, Panel, Spinner, Toast } from '../components/ui'

export default function Audit() {
  const [rows, setRows] = useState(null)
  const [toast, setToast] = useState({ message: '', error: false })

  useEffect(() => {
    api('/api/audit').then((d) => setRows(d.audit)).catch((e) => setToast({ message: e.message, error: true }))
  }, [])

  return (
    <>
      <PageHeader
        title="Audit log"
        subtitle="Every login, stock edit, upload, alert action and redistribution is recorded with the acting user."
      />

      {!rows ? <Spinner /> : rows.length === 0 ? <Empty>No audit entries yet.</Empty> : (
        <Panel title={`Last ${rows.length} events`} icon="audit">
          <div className="data-table-wrap table-scroll">
            <table className="data-table">
              <thead>
                <tr><th>#</th><th>When</th><th>User</th><th>Action</th><th>Detail</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td className="mono">{r.id}</td>
                    <td style={{ color: 'var(--muted)' }}>{r.created_at}</td>
                    <td className="mono">{r.username || 'system'}</td>
                    <td><span className="badge">{r.action}</span></td>
                    <td>{r.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      <Toast message={toast.message} error={toast.error} onClose={() => setToast({ message: '', error: false })} />
    </>
  )
}
