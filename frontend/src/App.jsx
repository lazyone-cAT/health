import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from './auth'
import Layout from './components/Layout'
import { Spinner } from './components/ui'
import Alerts from './pages/Alerts'
import Audit from './pages/Audit'
import Federated from './pages/Federated'
import Inventory from './pages/Inventory'
import Login from './pages/Login'
import Medicines from './pages/Medicines'
import Overview from './pages/Overview'
import Redistribution from './pages/Redistribution'
import Upload from './pages/Upload'

function Protected({ children }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <Spinner />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <Protected>
            <Layout />
          </Protected>
        }
      >
        <Route path="/" element={<Overview />} />
        <Route path="/inventory" element={<Inventory />} />
        <Route path="/medicines" element={<Medicines />} />
        <Route path="/alerts" element={<Alerts />} />
        <Route path="/redistribution" element={<Redistribution />} />
        <Route path="/upload" element={<Upload />} />
        <Route path="/federated" element={<Federated />} />
        <Route path="/audit" element={<Audit />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
