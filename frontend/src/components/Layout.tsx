import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

/** Die Kopfleiste am Schreibtisch.
 *
 * Sieben Einträge ist die Obergrenze — ein achter drückt die Leiste auf zwei
 * Zeilen. „Training erfassen" ist entfallen, weil es keine Handeingabe mehr
 * gibt: Absolvierte Einheiten kommen ausschließlich über den Garmin-Abgleich.
 */
const NAV_ITEMS = [
  { to: '/dashboard', label: 'Übersicht' },
  { to: '/plan', label: 'Trainingsplan' },
  { to: '/neues-training', label: 'Neues Training' },
  { to: '/verlauf', label: 'Verlauf' },
  { to: '/garmin', label: 'Garmin' },
  { to: '/profil', label: 'Meine Daten' },
  { to: '/einstellungen', label: 'Einstellungen' },
]

/** Was am Telefon unten in die Leiste kommt.
 *
 * Sieben gleichwertige Reiter nebeneinander sind auf einem Telefon weder
 * lesbar noch treffsicher. Unten stehen deshalb nur die vier Wege des
 * Trainingsalltags — nachsehen, was ansteht, und nachsehen, was war. Den Platz
 * des früheren „Erfassen" nimmt Garmin ein: Von dort kommen die absolvierten
 * Einheiten, also gehört der Abgleich in den Alltag und nicht hinter „Mehr“.
 */
const MOBILE_PRIMARY = [
  { to: '/dashboard', label: 'Übersicht', icon: IconHome },
  { to: '/plan', label: 'Plan', icon: IconCalendar },
  { to: '/garmin', label: 'Garmin', icon: IconWatch },
  { to: '/verlauf', label: 'Verlauf', icon: IconChart },
]

/** Und was dahinter liegt.
 *
 * „Einstellungen" gehört bewusst hierher und nicht nach unten: Die untere
 * Leiste steht im CSS auf fünf Spalten (vier Wege plus „Mehr"), ein fünfter
 * Weg spränge sie. Und sie ist eine Seite, die man einmal einrichtet und
 * danach selten wieder öffnet.
 */
const MOBILE_MORE = [
  { to: '/garmin-kalender', label: 'Garmin-Kalender' },
  { to: '/neues-training', label: 'Neues Training' },
  { to: '/profil', label: 'Meine Daten' },
  { to: '/einstellungen', label: 'Einstellungen' },
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

function IconWatch() {
  return (
    <svg className="mobile-nav-icon" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="6.5" y="6.5" width="11" height="11" rx="2.5" />
      <path d="M9 6.5V3.5h6v3M9 17.5v3h6v-3M12 9.5V12l2 1.5" />
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
