import { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import { LoadingState } from './components/ui'
import { useAuth } from './lib/auth'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import VpsList from './pages/VpsList'
import CreateVps from './pages/CreateVps'
import VpsDetail from './pages/VpsDetail'
import VpsConsole from './pages/VpsConsole'
import Nodes from './pages/Nodes'
import Templates from './pages/Templates'
import Networks from './pages/Networks'
import Storage from './pages/Storage'
import Backups from './pages/Backups'
import Users from './pages/Users'
import ActivityLogs from './pages/ActivityLogs'
import Monitoring from './pages/Monitoring'
import SettingsPage from './pages/Settings'
import Tasks from './pages/Tasks'

function Protected({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading)
    return (
      <div className="flex min-h-screen items-center justify-center bg-black">
        <LoadingState label="Authenticating…" />
      </div>
    )
  if (!user) return <Navigate to="/login" replace />
  return <Layout>{children}</Layout>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <Protected>
            <Dashboard />
          </Protected>
        }
      />
      <Route
        path="/vps"
        element={
          <Protected>
            <VpsList />
          </Protected>
        }
      />
      <Route
        path="/vps/create"
        element={
          <Protected>
            <CreateVps />
          </Protected>
        }
      />
      <Route
        path="/vps/:id"
        element={
          <Protected>
            <VpsDetail />
          </Protected>
        }
      />
      <Route
        path="/vps/:id/console"
        element={
          <Protected>
            <VpsConsole />
          </Protected>
        }
      />
      <Route path="/nodes" element={<Protected><Nodes /></Protected>} />
      <Route path="/templates" element={<Protected><Templates /></Protected>} />
      <Route path="/network" element={<Protected><Networks /></Protected>} />
      <Route path="/storage" element={<Protected><Storage /></Protected>} />
      <Route path="/backups" element={<Protected><Backups /></Protected>} />
      <Route path="/users" element={<Protected><Users /></Protected>} />
      <Route path="/logs" element={<Protected><ActivityLogs /></Protected>} />
      <Route path="/monitoring" element={<Protected><Monitoring /></Protected>} />
      <Route path="/settings" element={<Protected><SettingsPage /></Protected>} />
      <Route path="/tasks" element={<Protected><Tasks /></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
