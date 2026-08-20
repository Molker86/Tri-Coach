import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import { Loading } from './components/ui'
import { useAuth } from './auth/AuthContext'
import Dashboard from './pages/Dashboard'
import Einstellungen from './pages/Einstellungen'
import GarminKalender from './pages/GarminKalender'
import GarminPage from './pages/GarminPage'
import History from './pages/History'
import Landing from './pages/Landing'
import Login from './pages/Login'
import NewTraining from './pages/NewTraining'
import PlanExchange from './pages/PlanExchange'
import PlanView from './pages/PlanView'
import ProfilePage from './pages/ProfilePage'
import Register from './pages/Register'
import type { ReactNode } from 'react'

function Protected({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <Loading />
  if (!user) return <Navigate to="/login" replace />
  return <Layout>{children}</Layout>
}

function PublicOnly({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <Loading />
  if (user) return <Navigate to="/dashboard" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<PublicOnly><Landing /></PublicOnly>} />
      <Route path="/login" element={<PublicOnly><Login /></PublicOnly>} />
      <Route path="/registrieren" element={<PublicOnly><Register /></PublicOnly>} />

      <Route path="/dashboard" element={<Protected><Dashboard /></Protected>} />
      <Route path="/neues-training" element={<Protected><NewTraining /></Protected>} />
      <Route path="/plan-erzeugen" element={<Protected><PlanExchange /></Protected>} />
      <Route path="/plan" element={<Protected><PlanView /></Protected>} />
      <Route path="/plan/:planId" element={<Protected><PlanView /></Protected>} />
      <Route path="/verlauf" element={<Protected><History /></Protected>} />
      <Route path="/profil" element={<Protected><ProfilePage /></Protected>} />
      <Route path="/garmin" element={<Protected><GarminPage /></Protected>} />
      <Route path="/garmin-kalender" element={<Protected><GarminKalender /></Protected>} />
      <Route path="/einstellungen" element={<Protected><Einstellungen /></Protected>} />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
