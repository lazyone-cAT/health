import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { Empty, PageHeader, Panel, Spinner, Toast } from '../components/ui'

export default function Upload() {
  const inputRef = useRef(null)
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [history, setHistory] = useState(null)
  const [toast, setToast] = useState({ message: '', error: false })
  const [drag, setDrag] = useState(false)

  const loadHistory = () => api('/api/upload/history').then((d) => setHistory(d.history)).catch(() => setHistory([]))
  useEffect(() => { loadHistory() }, [])

  const onFile = async (file) => {
    if (!file) return
    setBusy(true)
    setPreview(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const d = await api('/api/upload', { method: 'POST', formData: fd })
      setPreview(d)
      setToast({ message: `Parsed ${d.total_rows} rows from ${d.filename}.`, error: false })
    } catch (e) {
      setToast({ message: e.message, error: true })
    } finally {
      setBusy(false)
    }
  }

  const confirm = async () => {
    setBusy(true)
    try {
      const d = await api('/api/upload/confirm', { method: 'POST', body: { upload_id: preview.upload_id } })
      setToast({
        message: `Applied: ${d.rows_inserted} inserted, ${d.rows_updated} updated, ${d.rows_rejected} rejected. Alerts refreshed.`,
        error: false,
      })
      setPreview(null)
      loadHistory()
    } catch (e) {
      setToast({ message: e.message, error: true })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader
        title="Upload inventory"
        subtitle="CSV or Excel with PHC name, medicine name, stock quantity and (optionally) average daily consumption."
      >
        <span className="chip chip-muted">staff only</span>
      </PageHeader>

      <div className={`dropzone ${drag ? 'drag' : ''}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); onFile(e.dataTransfer.files?.[0]) }}>
        <div className="dropzone-title">Drop a file or click to browse</div>
        <div className="dropzone-hint">.csv · .xlsx · .xls — columns are auto-detected, PHC and medicine names are fuzzy-matched</div>
        <input ref={inputRef} type="file" accept=".csv,.xlsx,.xls" hidden
          onChange={(e) => onFile(e.target.files?.[0])} />
      </div>

      {busy && <Spinner />}

      {preview && (
        <Panel title={`Preview — ${preview.filename}`} icon="upload">
          <div className="validation-grid">
            <div className="validation-cell"><div className="v-num">{preview.total_rows}</div><div className="v-lab">Rows read</div></div>
            <div className="validation-cell"><div className="v-num" style={{ color: 'var(--accent)' }}>{preview.valid_rows}</div><div className="v-lab">Valid</div></div>
            <div className="validation-cell"><div className="v-num" style={{ color: 'var(--danger)' }}>{preview.error_rows}</div><div className="v-lab">Rejected</div></div>
            <div className="validation-cell"><div className="v-num" style={{ color: '#a16207' }}>{preview.duplicate_rows}</div><div className="v-lab">Duplicates (upsert)</div></div>
          </div>

          <div className="data-table-wrap table-scroll">
            <table className="data-table">
              <thead>
                <tr><th>#</th><th>PHC</th><th>Match</th><th>Medicine</th><th>Match</th>
                  <th>Stock</th><th>Daily use</th><th>Issues</th></tr>
              </thead>
              <tbody>
                {preview.preview_rows.map((r) => (
                  <tr key={r.row_index} className={r.errors.length ? 'row-error' : ''}>
                    <td className="mono">{r.row_index + 1}</td>
                    <td>{r.phc_name}</td>
                    <td className="mono">{r.phc_match != null ? `${Math.round(r.phc_match * 100)}%` : '—'}</td>
                    <td>{r.medicine_name}</td>
                    <td className="mono">{r.medicine_match != null ? `${Math.round(r.medicine_match * 100)}%` : '—'}</td>
                    <td className="mono">{r.stock_qty ?? '—'}</td>
                    <td className="mono">{r.avg_daily_consumption ?? '—'}</td>
                    <td>{r.errors.length ? r.errors.join('; ')
                      : r.duplicate_of != null ? `duplicate of row ${r.duplicate_of + 1} (will update)` : 'OK'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <button className="btn btn-primary" onClick={confirm} disabled={busy}>Apply to inventory</button>
            <button className="btn" onClick={() => setPreview(null)}>Discard</button>
          </div>
        </Panel>
      )}

      <Panel title="Upload history" icon="audit">
        {!history ? <Spinner /> : history.length === 0 ? <Empty>No uploads yet.</Empty> : (
          <div className="data-table-wrap table-scroll">
            <table className="data-table">
              <thead>
                <tr><th>#</th><th>File</th><th>By</th><th>Rows</th><th>Inserted</th>
                  <th>Updated</th><th>Rejected</th><th>Status</th><th>When</th></tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.id}>
                    <td className="mono">{h.id}</td>
                    <td>{h.filename}</td>
                    <td>{h.uploaded_by}</td>
                    <td className="mono">{h.total_rows}</td>
                    <td className="mono">{h.rows_inserted}</td>
                    <td className="mono">{h.rows_updated}</td>
                    <td className="mono">{h.rows_rejected}</td>
                    <td><span className={`chip chip-${h.status === 'confirmed' ? 'ok' : 'low'}`}>{h.status}</span></td>
                    <td style={{ color: 'var(--muted)' }}>{h.created_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Toast message={toast.message} error={toast.error} onClose={() => setToast({ message: '', error: false })} />
    </>
  )
}
