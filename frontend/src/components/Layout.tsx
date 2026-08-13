import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

/** Die Kopfleiste am Schreibtisch.
 *
 * Sieben Einträge ist die Obergrenze — ein achter drückt die Leiste auf zwei
 * Zeilen. „Nachtragen" ist deshalb Garmin gewichen: Wer seine Trainings
 * automatisch bekommt, trägt kaum noch von Hand nach, und der Weg dorthin
 * bleibt über „Mehr" am Telefon, über den Verlauf und über die Erfassungsseite
 * erreichbar.
 */
const NAV_ITEMS = [
  { to: '/dashboard', label: 'Übersicht' },
  { to: '/plan', label: 'Trainingsplan' },
  { to: '/neues-training', label: 'Neues Training' },
  { to: '/training-erfassen', label: 'Training erfassen' },
  { to: '/verlauf', label: 'Verlauf' },
  { to: '/garmin', label: 'Garmin' },
  { to: '/profil', label: 'Meine Daten' },
]

/** Was am Telefon unten in die Leiste kommt.
 *
 * Sieben gleichwertige Reiter nebeneinander sind auf einem Telefon weder
 * lesbar noch treffsicher. Unten stehen deshalb nur die vier Wege des
 * Trainingsalltags — nachsehen, was ansteht, und erfassen, was war. Der Rest
 * liegt hinter „Mehr“ und ist damit genau einen Tipp weiter weg.
 */
const MOBILE_PRIMARY = [
  { to: '/dashboard', label: 'Übersicht', icon: IconHome },
  { to: '/plan', label: 'Plan', icon: IconCalendar },
  { to: '/training-erfassen', label: 'Erfassen', icon: IconPlus },
  { to: '/verlauf', label: 'Verlauf', icon: IconChart },
]

const MOBILE_MORE = [
  { to: '/garmin-kalender', label: 'Garmin-Kalender' },
  { to: '/garmin', label: 'Garmin Connect' },
  { to: '/neues-training', label: 'Neues Training' },
  { to: '/training-nachtragen', label: 'Training nachtragen' },
  { to: '/profil', label: 'Meine Daten' },
]

export default function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [sheetOpen, setSheetOpen] = useState(false)

  // Ein Seitenwechsel schließt das Menü — sonst bliebe es über der neuen Seite
  // stehen, auch wenn der Wechsel gar nicht aus dem Menü kam (Zurück-Geste).
  useEffect(() => setSheetOpen(false), [location.pathname])

  useEffect(() => {
    if (!sheetOpen) return
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setSheetOpen(false)
    }
    // Ohne Sperre scrollt der Hintergrund unter dem Menü weg.
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = previous
      window.removeEventListener('keydown', onKey)
    }
  }, [sheetOpen])

  function signOut() {
    logout()
    navigate('/')
  }

  return (
    <div className="app-shell">
      <header className="topbar topbar-app">
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
          <button className="btn btn-ghost btn-sm" onClick={signOut}>
            Abmelden
          </button>
        </div>
      </header>

      <main className="page">{children}</main>

      <nav className="mobile-nav" aria-label="Hauptnavigation">
        {MOBILE_PRIMARY.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `mobile-nav-item${isActive ? ' active' : ''}`
            }
          >
            <item.icon />
            {item.label}
          </NavLink>
        ))}
        <button
          className={`mobile-nav-item${sheetOpen ? ' active' : ''}`}
          onClick={() => setSheetOpen(true)}
          aria-expanded={sheetOpen}
        >
          <IconMore />
          Mehr
        </button>
      </nav>

      {sheetOpen && (
        <div
          className="sheet-backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget) setSheetOpen(false)
          }}
        >
          <div className="sheet" role="dialog" aria-modal="true" aria-label="Menü">
            <div className="sheet-handle" />

            {MOBILE_MORE.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) => `sheet-link${isActive ? ' active' : ''}`}
              >
                {item.label}
              </NavLink>
            ))}

            <div className="sheet-foot">
              <span className="small muted">Angemeldet als {user?.username}</span>
              <button className="btn btn-secondary btn-block" onClick={signOut}>
                Abmelden
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* Strichzeichnungen statt Emoji: Sie nehmen die Textfarbe an und markieren den
   aktiven Reiter damit von allein mit. */

function IconHome() {
  return (
    <svg className="mobile-nav-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 10.5 12 4l8 6.5V19a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z" />
    </svg>
  )
}

function IconCalendar() {
  return (
    <svg className="mobile-nav-icon" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3.5" y="5.5" width="17" height="15" rx="2" />
      <path d="M3.5 10h17M8 3.5v4M16 3.5v4" />
    </svg>
  )
}

function IconPlus() {
  return (
    <svg className="mobile-nav-icon" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 8.5v7M8.5 12h7" />
    </svg>
  )
}

function IconChart() {
  return (
    <svg className="mobile-nav-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 19.5V4M4 19.5h16" />
      <path d="m7.5 15 3.5-4.5 3 2.5L19 7" />
    </svg>
  )
}

function IconMore() {
  return (
    <svg className="mobile-nav-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4.5 7.5h15M4.5 12h15M4.5 16.5h15" />
    </svg>
  )
}
