import { useCallback, useEffect, useRef, useState } from 'react'

export const POLL_INTERVAL_MS = 30000
export const STALE_AFTER_MS = POLL_INTERVAL_MS * 3

/**
 * Auto-refresh a loader every 30s.
 *
 * `load` must reject on failure (do not swallow errors inside it) so the
 * hook can flag the view as stale and keep showing the last good payload.
 */
export function usePoll(load, interval = POLL_INTERVAL_MS) {
  const [lastUpdated, setLastUpdated] = useState(null)
  const [error, setError] = useState(null)
  const loadRef = useRef(load)
  loadRef.current = load

  const refresh = useCallback(async () => {
    try {
      await loadRef.current()
      setLastUpdated(Date.now())
      setError(null)
      return true
    } catch (e) {
      setError(e && e.message ? e.message : 'refresh failed')
      return false
    }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, interval)
    const onVisible = () => {
      if (!document.hidden) refresh()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(id)
      document.removeEventListener('visibilitychange', onVisible)
    }
    // `load` identity changes when filters/tab change — refetch then too.
  }, [refresh, interval, load])

  const stale = Boolean(error) || (lastUpdated !== null && Date.now() - lastUpdated > STALE_AFTER_MS)
  return { refresh, lastUpdated, error, stale, interval }
}

/**
 * Freshness line for a page header: server `generated_at` + auto-refresh age,
 * escalating to a stale banner when polling fails or falls behind.
 */
export function Freshness({ generatedAt, lastUpdated, error, stale }) {
  const time = lastUpdated ? new Date(lastUpdated).toLocaleTimeString() : 'loading…'
  if (stale) {
    return (
      <div className="stale-banner" role="status">
        Data may be stale — last successful refresh {time}
        {generatedAt ? ` (server time ${generatedAt})` : ''}.
        {error ? ` Auto-refresh failed: ${error}.` : ''} Retrying every 30s.
      </div>
    )
  }
  return (
    <div className="freshness">
      <span className="chip chip-ok">live</span>
      <span>
        auto-refresh 30s · updated {time}
        {generatedAt ? ` · server ${generatedAt}` : ''}
      </span>
    </div>
  )
}
