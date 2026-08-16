import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { ApiError, api, jobLaeuft, pollJob } from '../api/client'
import { Alert, EmptyState, Loading, Modal } from '../components/ui'
import { INTENSITY_ZONE_COLOR, sessionTypeLabel, sportIcon, sportLabel } from '../constants'
import { heuteIso, naechsterBlockStart, planErzeugenPfad } from '../planung'
import type {
  GarminJob,
  GarminPlanUebertragung,
  GarminUebertragungsZustand,
  Plan,
  PlanDeleteResult,
  PlanSession,
  PlanSummary,
} from '../types'

const DAY_FORMAT: Intl.DateTimeFormatOptions = { weekday: 'long' }

// Antwortcodes, mit denen das Löschen daran scheitert, dass Garmin nicht
// mitspielt (abgelaufene Anmeldung, Anfragesperre, sonstiger Fehlschlag). Nur
// dabei lohnt die Rückfrage, ob trotzdem gelöscht werden soll.
const GARMIN_HAKT = [409, 429, 502]

function isToday(iso: string): boolean {
  return iso === heuteIso()
}

export default function PlanView() {
  const { planId } = useParams()
  const navigate = useNavigate()
  // useLocation statt window.location: Unter Ingress trägt window.location.pathname
  // den Prefix /api/hassio_ingress/<token>, navigateTo aber nicht — der Vergleich
  // wäre dort immer verschieden.
  const location = useLocation()

  const [plan, setPlan] = useState<Plan | null>(null)
  const [plans, setPlans] = useState<PlanSummary[]>([])
  const [selected, setSelected] = useState<PlanSession | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // Garmin-Übertragung. Der Zustand kostet keine Anfrage an Garmin — er wird
  // aus dem Vergleich Plan gegen bereits Übertragenes im Server errechnet.
  const [garmin, setGarmin] = useState<GarminPlanUebertragung | null>(null)
  const [garminJob, setGarminJob] = useState<GarminJob | null>(null)
  const [garminBusy, setGarminBusy] = useState(false)
  // Welcher Plan gerade gelöscht wird. Das dauert, sobald Einheiten in Garmin
  // stehen: Jede kostet zwei Anfragen, und ohne sichtbaren Zustand wirkte der
  // Knopf sekundenlang, als hätte ihn niemand gedrückt.
  const [loeschen, setLoeschen] = useState<number | null>(null)
  const abbrechenRef = useRef<(() => void) | null>(null)
  // Warum der Block *nicht* automatisch nach Garmin ging. Der Satz entsteht
  // beim Übernehmen und reist über den Router-Zustand hierher.
  const [uebertragungsHinweis] = useState<string | null>(
    () => (location.state as { garminHinweis?: string } | null)?.garminHinweis ?? null,
  )

  const ladeGarmin = useCallback((forPlanId: number) => {
    api
      .garminWorkoutStatus(forPlanId)
      .then(setGarmin)
      .catch(() => setGarmin(null))
  }, [])

  /** Verfolgt einen Übertragungslauf, bis er fertig ist. */
  const beobachte = useCallback(
    (job: GarminJob, forPlanId: number) => {
      setGarminJob(job)
      abbrechenRef.current?.()
      abbrechenRef.current = pollJob(
        job.id,
        api.garminJob,
        (aktualisiert) => {
          setGarminJob(aktualisiert)
          if (!jobLaeuft(aktualisiert)) ladeGarmin(forPlanId)
        },
        (meldung) => setError(meldung),
      )
    },
    [ladeGarmin],
  )

  function reload(navigateTo?: string) {
    setLoading(true)
    const load = planId ? api.getPlan(Number(planId)) : api.activePlan()
    Promise.all([load, api.listPlans()])
      .then(([loaded, summaries]) => {
        setPlan(loaded)
        setPlans(summaries)
        if (loaded) {
          ladeGarmin(loaded.id)
          // Ein übernommener Block geht von selbst nach Garmin. Wer hier
          // landet, hat dafür nichts gedrückt — der Fortschritt muss also von
          // allein auftauchen, sonst wirkt die Seite untätig, während im
          // Server gerade ein Dutzend Anfragen laufen.
          api
            .garminStatus()
            .then(({ aktiver_job }) => {
              if (aktiver_job?.kind.startsWith('workout')) {
                beobachte(aktiver_job, loaded.id)
              }
            })
            .catch(() => undefined)
        } else setGarmin(null)
        if (navigateTo && navigateTo !== location.pathname) {
          navigate(navigateTo)
        }
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    reload()
    return () => abbrechenRef.current?.()
  }, [planId])

  function uebertrageNachGarmin() {
    if (!plan) return
    setGarminBusy(true)
    setError(null)
    api
      .garminWorkoutsUebertragen(plan.id)
      .then((job) => beobachte(job, plan.id))
      .catch((err) => setError(err.message))
      .finally(() => setGarminBusy(false))
  }

  /**
   * Löschen an einer Stelle, damit Kopfzeile und Tabelle nicht auseinanderlaufen.
   * Beides gibt es, weil der Knopf in der Tabelle den einzigen Plan gar nicht
   * erreicht — sie wird erst ab dem zweiten angezeigt.
   */
  function loeschePlan(id: number, titel: string) {
    // Bereits übertragene Einheiten nimmt der Server aus Garmin, bevor er den
    // Plan löscht — danach käme er nicht mehr an sie heran.
    const inGarmin = id === plan?.id ? (garmin?.aktuell ?? 0) + (garmin?.geaendert ?? 0) : 0
    const hinweis = inGarmin
      ? `\n\nDie übertragenen Einheiten werden dabei aus dem Garmin-Kalender genommen.`
      : ''
    if (
      !confirm(
        `Plan „${titel}“ wirklich löschen?\n\n` +
          `Erfasste Trainings bleiben im Verlauf erhalten.${hinweis}`,
      )
    )
      return

    setLoeschen(id)
    api
      .deletePlan(id)
      .then(fertig)
      .catch((err) => {
        // Der Server hat nicht gelöscht, weil er die Einheiten nicht aus Garmin
        // bekam — sie wären danach unerreichbar. Das ist eine Entscheidung des
        // Nutzers, keine Fehlermeldung: Er darf darauf bestehen. Nur bei genau
        // diesem Grund, sonst stünde „Trotzdem löschen?" auch unter einem Plan,
        // den es gar nicht mehr gibt.
        if (!(err instanceof ApiError) || !GARMIN_HAKT.includes(err.status)) throw err
        if (!confirm(`${err.message}\n\nTrotzdem löschen?`)) throw err
        return api.deletePlan(id, { garminUebergehen: true }).then(fertig)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoeschen(null))

    function fertig(ergebnis: PlanDeleteResult) {
      // Einzelne Einheiten, die Garmin nicht hergab: Der Plan ist weg, sie
      // stehen aber noch im fremden Kalender. Als Dialog statt als Meldung auf
      // der Seite — die wird gleich neu geladen und nähme den Satz mit.
      if (ergebnis.garmin_fehler.length) {
        alert(
          'Diese Einheiten konnten nicht aus dem Garmin-Kalender genommen ' +
            'werden und stehen dort weiter:\n\n' +
            ergebnis.garmin_fehler.join('\n') +
            '\n\nIm Kalender dieser App lassen sie sich von Hand entfernen.',
        )
      }
      // Wer den gerade geöffneten Plan löscht, stünde sonst auf /plan/<id>
      // und liefe beim Neuladen in ein 404. Der Wechsel der Route stößt über
      // den Effekt auf [planId] das Neuladen selbst an.
      if (planId && Number(planId) === id) navigate('/plan')
      else reload()
    }
  }

  /** Zustand je Einheit, damit die Karten ihn zeigen können. */
  const garminJeEinheit = useMemo(() => {
    const karte = new Map<number, GarminUebertragungsZustand>()
    for (const eintrag of garmin?.einheiten ?? []) {
      karte.set(eintrag.plan_session_id, eintrag.zustand)
    }
    return karte
  }, [garmin])

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
              <table className="table-cards">
                <tbody>
                  {plans.map((entry) => (
                    <tr key={entry.id}>
                      <td className="cell-title">
                        <Link to={`/plan/${entry.id}`}>{entry.title}</Link>
                      </td>
                      <td className="nowrap muted small" data-label="Zeitraum">
                        {new Date(entry.start_date).toLocaleDateString('de-DE')} –{' '}
                        {new Date(entry.end_date).toLocaleDateString('de-DE')}
                      </td>
                      <td className="nowrap muted small" data-label="Umfang">
                        {entry.session_count} Einheiten
                      </td>
                      <td className="nowrap cell-actions">
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
                          disabled={loeschen !== null}
                          onClick={() => loeschePlan(entry.id, entry.title)}
                        >
                          {loeschen === entry.id ? 'Wird gelöscht …' : 'Löschen'}
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
          {/* Zwei Wege in einen neuen Block, und der Unterschied muss am Knopf
              ablesbar sein: „neu planen" wirft die Resttage weg und plant sie
              anhand der aktuellen Lage neu, „nächste 7 Tage" hängt hinten an.
              Läuft der Block nicht mehr, fallen beide zusammen — dann bleibt
              nur einer stehen. */}
          {plan.is_active && plan.end_date >= heuteIso() && (
            <Link className="btn btn-primary" to={planErzeugenPfad(heuteIso())}>
              Neu planen ab heute
            </Link>
          )}
          {plan.is_active && (
            <Link
              className="btn btn-secondary"
              to={planErzeugenPfad(naechsterBlockStart(plan.end_date))}
            >
              {plan.end_date >= heuteIso()
                ? 'Nächste 7 Tage planen'
                : 'Nächsten Block planen'}
            </Link>
          )}
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
          {/* Der Fragebogen ist nur nötig, wenn sich die Rahmenbedingungen
              geändert haben — für einen frischen Block reicht der letzte. */}
          <Link className="btn btn-secondary" to="/neues-training">
            Fragebogen neu ausfüllen
          </Link>
          <button
            className="btn btn-danger"
            disabled={loeschen !== null}
            onClick={() => loeschePlan(plan.id, plan.title)}
          >
            {loeschen === plan.id ? 'Wird gelöscht …' : 'Plan löschen'}
          </button>
        </div>
      </div>

      {/* Kommt vom Übernehmen mit: Die App wollte den Block auf die Uhr legen
          und kam nicht durch. Ohne diesen Satz stünde nur ein leerer Kalender
          da, ohne Grund. */}
      {uebertragungsHinweis && <Alert kind="warning">{uebertragungsHinweis}</Alert>}

      {garmin?.garmin_verbunden && (
        <GarminKarte
          garmin={garmin}
          job={garminJob}
          busy={garminBusy}
          onUebertragen={uebertrageNachGarmin}
        />
      )}

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
                <div className="day-row-head">
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
                      garminZustand={garminJeEinheit.get(session.id)}
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
            <table className="table-cards">
              <tbody>
                {plans.map((entry) => (
                  <tr key={entry.id}>
                    <td className="cell-title">
                      <Link to={`/plan/${entry.id}`}>{entry.title}</Link>
                      {entry.is_active && (
                        <> <span className="badge badge-success">Aktiv</span></>
                      )}
                    </td>
                    <td className="nowrap muted small" data-label="Zeitraum">
                      {new Date(entry.start_date).toLocaleDateString('de-DE')} –{' '}
                      {new Date(entry.end_date).toLocaleDateString('de-DE')}
                    </td>
                    <td className="nowrap muted small" data-label="Umfang">
                      {entry.session_count} Einheiten
                    </td>
                    <td className="nowrap cell-actions">
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
                        disabled={loeschen !== null}
                        onClick={() => loeschePlan(entry.id, entry.title)}
                      >
                        {loeschen === entry.id ? 'Wird gelöscht …' : 'Löschen'}
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

/** Der Weg auf die Uhr: übertragen, nachsehen, im Kalender verwalten. */
function GarminKarte({
  garmin,
  job,
  busy,
  onUebertragen,
}: {
  garmin: GarminPlanUebertragung
  job: GarminJob | null
  busy: boolean
  onUebertragen: () => void
}) {
  const offen = garmin.offen + garmin.geaendert + garmin.fehler
  const laeuft = jobLaeuft(job)

  return (
    <div className="card">
      <div className="card-title">
        <h3>Auf der Uhr</h3>
        <Link className="btn btn-ghost btn-sm" to="/garmin-kalender">
          Garmin-Kalender öffnen
        </Link>
      </div>

      {job?.message && !laeuft && (
        <Alert kind={job.state === 'done' ? 'success' : 'warning'}>{job.message}</Alert>
      )}

      <div className="row">
        {/* Bleibt anklickbar, wenn alles als aktuell gilt: Diese Seite fragt nur
            den eigenen Stand ab, ohne Garmin dabei zu berühren. Erst der Lauf
            selbst sieht nach — ein toter Knopf ließe den Nutzer in einem
            falschen Stand sitzen. */}
        <button
          className={offen === 0 ? 'btn btn-secondary' : 'btn btn-primary'}
          onClick={onUebertragen}
          disabled={busy || laeuft || garmin.einheiten.length === 0}
        >
          {laeuft
            ? 'Wird übertragen …'
            : offen === 0
              ? 'Mit Garmin abgleichen'
              : 'Garmin Trainings übertragen'}
        </button>
        <span className="muted small">
          {laeuft
            ? (job?.message ?? 'Die Einheiten wandern in den Garmin-Kalender …')
            : offen === 0
              ? `Alle ${garmin.aktuell} Einheiten liegen im Garmin-Kalender — ` +
                `der Abgleich prüft es nach.`
              : `${garmin.aktuell} von ${garmin.einheiten.length} übertragen — ` +
                `${offen} ${offen === 1 ? 'Einheit wartet' : 'Einheiten warten'}.`}
        </span>
      </div>

      {garmin.vergangen > 0 && !laeuft && (
        <p className="small faint mb-0 mt-1">
          {garmin.vergangen} vergangene{' '}
          {garmin.vergangen === 1 ? 'Einheit bleibt' : 'Einheiten bleiben'} außen vor —
          ein Training von gestern hilft auf der Uhr niemandem mehr.
        </p>
      )}
    </div>
  )
}

const GARMIN_MARKE: Record<GarminUebertragungsZustand, { text: string; art: string } | null> = {
  aktuell: { text: '⌚ auf der Uhr', art: 'badge-accent' },
  geaendert: { text: '⌚ geändert', art: 'badge-warning' },
  fehler: { text: '⌚ nicht übertragen', art: 'badge-warning' },
  offen: null,
}

function SessionCard({
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

      {/* Kein Weg zum Erfassen mehr: Die Einheit wird als absolviert markiert,
          sobald der Garmin-Abgleich eine passende Aktivität findet
          (`garmin/matching.py` über Tag und Sportart). */}
      <div className="row row-end mt-2">
        {session.logged ? (
          <span className="badge badge-success">Training bereits erfasst</span>
        ) : (
          <span className="small muted">
            Wird als absolviert markiert, sobald die Einheit aus Garmin kommt.
          </span>
        )}
      </div>
    </Modal>
  )
}
