import type { ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Übersicht' },
  { to: '/plan', label: 'Trainingsplan' },
  { to: '/neues-training', label: 'Neues Training' },
  { to: '/training-erfassen', label: 'Training erfassen' },
  { to: '/training-nachtragen', label: 'Nachtragen' },
  { to: '/verlauf', label: 'Verlauf' },
  { to: '/profil', label: 'Meine Daten' },
]

export default function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="app-shell">
      <header className="topbar">
        <NavLink to="/dashboard" className="brand">
          <span className="brand-mark">TC</span>
          Tri-Coach
        </NavLink>

        <nav className="nav">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => (isActive ? 'active' : '')}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="topbar-user">
          <span className="nowrap">{user?.username}</span>
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => {
              logout()
              navigate('/')
            }}
          >
            Abmelden
          </button>
        </div>
      </header>

      <main className="page">{children}</main>
    </div>
  )
}
