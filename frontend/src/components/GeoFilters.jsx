import { useEffect, useState } from 'react'
import { api } from '../api'

export function useGeo() {
  const [geo, setGeo] = useState(null)
  useEffect(() => {
    api('/api/geography').then(setGeo).catch(() => setGeo({ states: [], level: 'country', scope: {} }))
  }, [])
  return geo
}

const GEO_KEYS = ['state_id', 'district_id', 'phc_id']

export function geoQuery(params) {
  const qs = new URLSearchParams()
  GEO_KEYS.forEach((k) => {
    const v = params.get(k)
    if (v) qs.set(k, v)
  })
  return qs
}

export default function GeoFilters({ params, setParams }) {
  const geo = useGeo()
  const scope = geo?.scope || {}

  const setParam = (key, value) => {
    const next = new URLSearchParams(params)
    const scopeVal = scope[key] ? String(scope[key]) : ''
    if (!value || value === scopeVal) next.delete(key)
    else next.set(key, value)
    if (key === 'state_id') {
      next.delete('district_id')
      next.delete('phc_id')
    }
    if (key === 'district_id') next.delete('phc_id')
    setParams(next, { replace: true })
  }

  const stateId = params.get('state_id') || (scope.state_id ? String(scope.state_id) : '')
  const districtId = params.get('district_id') || (scope.district_id ? String(scope.district_id) : '')
  const phcId = params.get('phc_id') || (scope.phc_id ? String(scope.phc_id) : '')

  const state = (geo?.states || []).find((s) => String(s.state_id) === stateId)
  const district = (state?.districts || []).find((d) => String(d.district_id) === districtId)
  const pinned = (key) => Boolean(scope[key])

  return (
    <>
      <select className="form-select" value={stateId}
        onChange={(e) => setParam('state_id', e.target.value)}>
        {!pinned('state_id') && <option value="">All states</option>}
        {(geo?.states || []).map((s) => (
          <option key={s.state_id} value={s.state_id}>{s.name}</option>
        ))}
      </select>
      <select className="form-select" value={districtId}
        onChange={(e) => setParam('district_id', e.target.value)}>
        {!pinned('district_id') && <option value="">All districts</option>}
        {(state?.districts || []).map((d) => (
          <option key={d.district_id} value={d.district_id}>{d.name}</option>
        ))}
      </select>
      <select className="form-select" value={phcId}
        onChange={(e) => setParam('phc_id', e.target.value)}>
        {!pinned('phc_id') && <option value="">All PHCs</option>}
        {(district?.facilities || []).map((p) => (
          <option key={p.phc_id} value={p.phc_id}>{p.name}</option>
        ))}
      </select>
    </>
  )
}
