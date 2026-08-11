import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { Alert, EmptyState, Loading, Modal } from '../components/ui'
import { INTENSITY_ZONE_COLOR, sessionTypeLabel, sportIcon, sportLabel } from '../constants'
import type { Plan, PlanSession, PlanSummary } from '../types'

const DAY_FORMAT: Intl.DateTimeFormatOptions = { weekday: 'long' }

function isToday(iso: string): boolean {
  return iso === new Date().toISOString().slice(0, 10)
}

export default function PlanView() {
  const { planId } = useParams()
  const navigate = useNavigate()

  const [plan, setPlan] = useState<Plan | null>(null)
  const [plans, setPlans] = useState<PlanSummary[]>([])
  const [selected, setSelected] = useState<PlanSession | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  function reload(navigateTo?: string) {
    setLoading(true)
    const load = planId ? api.getPlan(Number(planId)) : api.activePlan()
    Promise.all([load, api.listPlans()])
      .then(([loaded, summaries]) => {
        setPlan(loaded)
        setPlans(summaries)
        if (navigateTo && navigateTo !== window.location.pathname) {
          navigate(navigateTo)
        }
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    reload()
  }, [planId])

  // Einheiten nach Woche und Tag gruppieren. Ein Block über wenige Tage liegt
  // komplett in Woche 1 — die Wochenebene zeigen wir dann gar nicht erst an, sie
  // bleibt nur für ältere Mehrwochenpläne im Verlauf erhalten.
  const weeks = useMemo(() => {
    if (!plan) return []
    const byWeek = new Map<number, Map<string, PlanSession[]>>()

    for (const session of plan.sessions) {
      if (!byWeek.has(session.week_number)) byWeek.set(session.week_number, new Map())
      const days = byWeek.get(session.week_number)!
      if (!days.has(session.date)) days.set(session.date, [])
      days.get(session.date)!.push(session)
    }

    return [...byWeek.entries()]
      .sort(([a], [b]) => a - b)
      .map(([weekNumber, days]) => ({
        weekNumber,
        days: [...days.entries()].sort(([a], [b]) => a.localeCompare(b)),
      }))
  }, [plan])

  if (loading) return <Loading />
  if (error) return <Alert kind="error">{error}</Alert>

  if (!plan && plans.length === 0) {
    return (
      <EmptyState icon="📋" title="Noch kein Trainingsplan vorhanden">
        <p>
          Beantworte den Fragebogen, lass dir von einer KI einen Plan erzeugen und füge
          ihn hier ein.
        </p>
        <Link className="btn btn-primary" to="/neues-training">
          Neues Training starten
        </Link>
      </EmptyState>
    )
  }

  if (!plan) {
    return (
      <>
        <div className="page-header">
          <div>
            <h1>Trainingsplan</h1>
            <p>Kein aktiver Plan</p>
          </div>
          <div className="row">
            <Link className="btn btn-secondary" to="/neues-training">
              Neuen Plan erstellen
            </Link>
          </div>
        </div>

        {plans.length > 0 && (
          <div className="card">
            <h3>Frühere Pläne</h3>
            <div className="table-wrap">
              <table>
                <tbody>
                  {plans.map((entry) => (
                    <tr key={entry.id}>
                      <td>
                        <Link to={`/plan/${entry.id}`}>{entry.title}</Link>
                      </td>
                      <td className="nowrap muted small">
                        {new Date(entry.start_date).toLocaleDateString('de-DE')} –{' '}
                        {new Date(entry.end_date).toLocaleDateString('de-DE')}
                      </td>
                      <td className="nowrap muted small">{entry.session_count} Einheiten</td>
                      <td className="nowrap">
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() =>
                            api
                              .activatePlan(entry.id)
                              .then(() => reload())
                              .catch((err) => setError(err.message))
                          }
                        >
                          Aktivieren
                        </button>
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => {
                            if (!confirm(`Plan „${entry.title}" wirklich löschen?`)) return
                            api
                              .deletePlan(entry.id)
                              .then(() => reload())
                              .catch((err) => setError(err.message))
                          }}
                        >
                          Löschen
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </>
    )
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>{plan.title}</h1>
          <p>
            {new Date(plan.start_date).toLocaleDateString('de-DE')} –{' '}
            {new Date(plan.end_date).toLocaleDateString('de-DE')} ·{' '}
            {plan.sessions.filter((s) => s.sport !== 'rest').length} Einheiten
            {plan.is_active && <> · <span className="badge badge-success">Aktiv</span></>}
          </p>
        </div>
        <div className="row">
          {plan.is_active && (() => {
            const nextStart = new Date(plan.end_date)
            nextStart.setDate(nextStart.getDate() + 1)
            const nextStartStr = nextStart.toISOString().slice(0, 10)
            return (
              <Link className="btn btn-secondary" to={`/plan-erzeugen?start=${nextStartStr}&days=7`}>
                Nächste 7 Tage planen
              </Link>
            )
          })()}
          {!plan.is_active && (
            <button
              className="btn btn-secondary"
              onClick={() =>
                api
                  .activatePlan(plan.id)
                  .then(() => reload())
                  .catch((err) => setError(err.message))
              }
            >
              Als aktiv setzen
            </button>
          )}
          <Link className="btn btn-secondary" to="/profil">
            Meine Daten anpassen
          </Link>
          <Link className="btn btn-primary" to="/neues-training">
            Neuen Plan erstellen
          </Link>
        </div>
      </div>

      {plan.summary && (
        <div className="card">
          <h3>Zur Ausrichtung des Blocks</h3>
          <p className="mb-0">{plan.summary}</p>
        </div>
      )}

      {plan.coaching_notes && (
        <div className="card">
          <h3>Hinweise zur Steuerung</h3>
          <p className="mb-0">{plan.coaching_notes}</p>
        </div>
      )}

      <div className="card mt-2">
        {weeks.map((week) => (
          <div className="week-block" key={week.weekNumber}>
            {weeks.length > 1 && (
              <div className="week-head">
                <h3>Woche {week.weekNumber}</h3>
                <span className="week-stats">
                  {week.days.reduce(
                    (sum, [, sessions]) =>
                      sum +
                      sessions.reduce((inner, s) => inner + (s.duration_min ?? 0), 0),
                    0,
                  )}{' '}
                  min
                </span>
              </div>
            )}

            {week.days.map(([date, sessions]) => (
              <div className={`day-row ${isToday(date) ? 'is-today' : ''}`} key={date}>
                <div>
                  <div className="day-label">
                    {new Date(date).toLocaleDateString('de-DE', DAY_FORMAT)}
                    {isToday(date) && ' · heute'}
                  </div>
                  <div className="day-date">
                    {new Date(date).toLocaleDateString('de-DE', {
                      day: '2-digit',
                      month: '2-digit',
                    })}
                  </div>
                </div>

                <div className="session-list">
                  {sessions.map((session) => (
                    <SessionCard
                      key={session.id}
                      session={session}
                      onOpen={() => session.sport !== 'rest' && setSelected(session)}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>

      {plans.length > (plan ? 1 : 0) && (
        <div className="card">
          <h3>Frühere Pläne</h3>
          <div className="table-wrap">
            <table>
              <tbody>
                {plans.map((entry) => (
                  <tr key={entry.id}>
                    <td>
                      <Link to={`/plan/${entry.id}`}>{entry.title}</Link>
                      {entry.is_active && (
                        <> <span className="badge badge-success">Aktiv</span></>
                      )}
                    </td>
                    <td className="nowrap muted small">
                      {new Date(entry.start_date).toLocaleDateString('de-DE')} –{' '}
                      {new Date(entry.end_date).toLocaleDateString('de-DE')}
                    </td>
                    <td className="nowrap muted small">{entry.session_count} Einheiten</td>
                    <td className="nowrap">
                      {!entry.is_active && (
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() =>
                            api
                              .activatePlan(entry.id)
                              .then(() => reload())
                              .catch((err) => setError(err.message))
                          }
                        >
                          Aktivieren
                        </button>
                      )}
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => {
                          if (!confirm(`Plan „${entry.title}" wirklich löschen?`)) return
                          api
                            .deletePlan(entry.id)
                            .then(() => reload())
                            .catch((err) => setError(err.message))
                        }}
                      >
                        Löschen
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {selected && (
        <SessionDetail session={selected} onClose={() => setSelected(null)} />
      )}
    </>
  )
}

function SessionCard({
  session,
  onOpen,
}: {
  session: PlanSession
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

function SessionDetail({
  session,
  onClose,
}: {
  session: PlanSession
  onClose: () => void
}) {
  return (
    <Modal title={session.title} onClose={onClose}>
      <div className="row mb-1">
        <span className="badge">{sportIcon(session.sport)} {sportLabel(session.sport)}</span>
        <span className="badge">{sessionTypeLabel(session.session_type)}</span>
        {session.intensity_zone && (
          <span
            className="badge badge-zone"
            style={{
              background: INTENSITY_ZONE_COLOR[session.intensity_zone] ?? 'var(--surface-3)',
            }}
          >
            {session.intensity_zone}
          </span>
        )}
        <span className="badge">
          {new Date(session.date).toLocaleDateString('de-DE', {
            weekday: 'long',
            day: '2-digit',
            month: '2-digit',
          })}
        </span>
      </div>

      {session.description && <p>{session.description}</p>}

      {session.structure && (
        <>
          <h4>Aufbau</h4>
          <div className="code-box">{session.structure}</div>
        </>
      )}

      {session.purpose && (
        <>
          <h4 className="mt-1">Trainingswirkung</h4>
          <p className="muted">{session.purpose}</p>
        </>
      )}

      <h4 className="mt-1">Vorgaben</h4>
      <div className="table-wrap">
        <table>
          <tbody>
            {session.duration_min ? (
              <tr><th>Dauer</th><td>{session.duration_min} min</td></tr>
            ) : null}
            {session.distance_km ? (
              <tr><th>Distanz</th><td>{session.distance_km} km</td></tr>
            ) : null}
            {session.target_hr_low && session.target_hr_high ? (
              <tr>
                <th>Herzfrequenz</th>
                <td>{session.target_hr_low}–{session.target_hr_high} bpm</td>
              </tr>
            ) : null}
            {session.target_pace ? (
              <tr><th>Pace</th><td>{session.target_pace}</td></tr>
            ) : null}
            {session.target_power ? (
              <tr><th>Leistung</th><td>{session.target_power}</td></tr>
            ) : null}
            {session.rpe_target ? (
              <tr><th>Anstrengung (RPE)</th><td>{session.rpe_target} / 10</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="row row-end mt-2">
        {session.logged ? (
          <span className="badge badge-success">Training bereits erfasst</span>
        ) : (
          <Link
            className="btn btn-primary"
            to={`/training-erfassen?session=${session.id}`}
          >
            Training erfassen
          </Link>
        )}
      </div>
    </Modal>
  )
}
