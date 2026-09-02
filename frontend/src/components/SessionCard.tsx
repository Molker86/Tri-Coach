/**
 * Eine Einheit als anklickbare Karte.
 *
 * Aus `PlanView` herausgezogen, weil das Dashboard dieselbe Karte zeigt — dort
 * stand sie als `<div>` nachgebaut und war deshalb tot: Ansehen und Anpassen
 * ging nur über den Umweg Trainingsplan. Die Kopie hatte außerdem drei Marken
 * nicht (Zone, Garmin-Stand, „angepasst"), was beim Nachbauen niemandem
 * auffällt und beim Ändern erst recht nicht.
 *
 * **Auch Ruhetage sind anklickbar** — kein `disabled`. Aus einer Einheit kann
 * Ruhe werden, und ohne diesen Weg käme man an sie danach nie wieder heran.
 */

import { INTENSITY_ZONE_COLOR, sessionTypeLabel, sportIcon, sportLabel } from '../constants'
import type { GarminUebertragungsZustand, PlanSession } from '../types'

const GARMIN_MARKE: Record<GarminUebertragungsZustand, { text: string; art: string } | null> = {
  aktuell: { text: '⌚ auf der Uhr', art: 'badge-accent' },
  geaendert: { text: '⌚ geändert', art: 'badge-warning' },
  fehler: { text: '⌚ nicht übertragen', art: 'badge-warning' },
  offen: null,
}

export function SessionCard({
  session,
  garminZustand,
  onOpen,
}: {
  session: PlanSession
  garminZustand?: GarminUebertragungsZustand
  onOpen: () => void
}) {
  const zoneColor = session.intensity_zone
    ? INTENSITY_ZONE_COLOR[session.intensity_zone]
    : undefined

  return (
    <button
      className={`session-card ${session.sport === 'rest' ? 'is-rest' : ''} ${
        session.logged ? 'is-logged' : ''
      }`}
      style={zoneColor && !session.logged ? { borderLeftColor: zoneColor } : undefined}
      onClick={onOpen}
    >
      <span className="session-icon">{sportIcon(session.sport)}</span>
      <span className="session-body">
        <span className="session-head">
          <span className="session-title">{session.title}</span>
          {session.intensity_zone && (
            <span
              className="badge badge-zone"
              style={{ background: zoneColor ?? 'var(--surface-3)' }}
            >
              {session.intensity_zone}
            </span>
          )}
          {session.logged && <span className="badge badge-success">✓ erfasst</span>}
          {!session.logged && session.angepasst_am && (
            <span
              // Ohne Wunsch war es die Tagesanpassung nach dem Abgleich; dann
              // trägt die Begründung, was sonst der Wunsch tragen würde.
              title={
                session.anpassungswunsch ??
                session.anpassungsbegruendung ??
                undefined
              }
              className="badge"
            >
              ✎ angepasst
            </span>
          )}
          {!session.logged &&
            garminZustand &&
            GARMIN_MARKE[garminZustand] !== null && (
              <span className={`badge ${GARMIN_MARKE[garminZustand]!.art}`}>
                {GARMIN_MARKE[garminZustand]!.text}
              </span>
            )}
        </span>
        <span className="session-meta">
          <span>{sportLabel(session.sport)}</span>
          <span>{sessionTypeLabel(session.session_type)}</span>
          {session.duration_min ? <span>{session.duration_min} min</span> : null}
          {session.distance_km ? <span>{session.distance_km} km</span> : null}
          {session.target_hr_low && session.target_hr_high ? (
            <span>
              {session.target_hr_low}–{session.target_hr_high} bpm
            </span>
          ) : null}
        </span>
      </span>
    </button>
  )
}
