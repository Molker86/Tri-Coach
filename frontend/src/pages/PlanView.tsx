import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { ApiError, api, jobLaeuft, pollJob } from '../api/client'
import { AnpassungsKarte } from '../components/AnpassungsKarte'
import { SessionCard } from '../components/SessionCard'
import { SessionDetail } from '../components/SessionDetail'
import { Alert, EmptyState, Loading } from '../components/ui'
import { useEinheitAnpassung } from '../components/useEinheitAnpassung'
import { useHeute } from '../components/useHeute'
import { naechsterBlockStart, planErzeugenPfad } from '../planung'
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


export default function PlanView() {
  const { planId } = useParams()
  const navigate = useNavigate()
  // Über Mitternacht hinaus richtig — die Seite bleibt am Telefon offen liegen.
  const heute = useHeute()
  const [zeigeVergangenes, setZeigeVergangenes] = useState(false)
  const [fragebogenId, setFragebogenId] = useState<number | null>(null)
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

  // Eine einzelne Einheit anpassen lassen — die Schleife steckt im Hook, weil
  // die Startseite dieselbe Anpassung anbietet.
  const anpassungLauf = useEinheitAnpassung(
    () => reloadRef.current?.(),
    setError,
  )
  const anpassung = anpassungLauf.anpassung

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

  // `reload` hängt an vielem und wird bei jedem Rendern neu gebaut; über eine
  // Referenz bleibt `beobachteAnpassung` trotzdem stabil.
  const reloadRef = useRef<(() => void) | null>(null)

  function reload(navigateTo?: string) {
    setLoading(true)
    const load = planId ? api.getPlan(Number(planId)) : api.activePlan()
    Promise.all([load, api.listPlans()])
      .then(([loaded, summaries]) => {
        setPlan(loaded)
        setPlans(summaries)
        if (loaded) {
          ladeGarmin(loaded.id)
          // Nur für Blöcke von vor `_letzter_fragebogen()`: Sie tragen keinen
          // Verweis, obwohl der Fragebogen existiert. Dieselbe Wahl, die auch
          // der Export trifft — den Knopf auszublenden ließe den Athleten vor
          // einem leeren Formular statt vor seinen Antworten stehen.
          if (loaded.request_id === null) {
            api
              .latestRequest()
              .then((letzter) => setFragebogenId(letzter?.id ?? null))
              .catch(() => setFragebogenId(null))
          } else setFragebogenId(loaded.request_id)
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
        } else {
          setGarmin(null)
          setFragebogenId(null)
        }
        if (navigateTo && navigateTo !== location.pathname) {
          navigate(navigateTo)
        }
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }

  // Ohne Abhängigkeiten: Nach jedem Rendern zeigt die Referenz auf die aktuelle
  // Fassung von `reload`. Der bekannte „latest ref"-Griff — im Rumpf zuzuweisen
  // wäre ein Seiteneffekt im Rendern.
  useEffect(() => {
    reloadRef.current = () => reload()
  })

  useEffect(() => {
    reload()
    // Wieder einklappen, wenn ein anderer Block aufgeschlagen wird.
    setZeigeVergangenes(false)
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

  const vergangeneTage = useMemo(
    () =>
      plan
        ? new Set(plan.sessions.filter((s) => s.date < heute).map((s) => s.date)).size
        : 0,
    [plan, heute],
  )

  // Ein Block trägt seit der Übernahme der Vergangenheit die Tage seiner
  // Vorgänger mit, und die wächst mit jeder Neuplanung. Wer den Plan aufschlägt,
  // will wissen, was *noch* kommt. Die Ausnahme ist ein Block, der ganz vorbei
  // ist: Dort stünde die Seite sonst leer — und unter „Frühere Pläne" ist das
  // der Normalfall.
  const nochOffen = plan?.sessions.some((s) => s.date >= heute) ?? false
  const zeigtAlles = zeigeVergangenes || !nochOffen

  // Dieselbe Frage in der Kopfzeile: Sie nennt, was noch bevorsteht, nicht die
  // Summe aller je geerbten Tage. Bewusst **nicht** an `zeigtAlles` gehängt —
  // eine Zahl, die sich mit einem Anzeigeschalter ändert, wäre keine Bilanz.
  const offeneEinheiten =
    plan?.sessions.filter(
      (s) => s.sport !== 'rest' && (!nochOffen || s.date >= heute),
    ).length ?? 0

  // Einheiten nach Woche und Tag gruppieren. Ein Block über wenige Tage liegt
  // komplett in Woche 1 — die Wochenebene zeigen wir dann gar nicht erst an, sie
  // bleibt nur für ältere Mehrwochenpläne im Verlauf erhalten.
  const weeks = useMemo(() => {
    if (!plan) return []
    const byWeek = new Map<number, { minuten: number; days: Map<string, PlanSession[]> }>()

    for (const session of plan.sessions) {
      let woche = byWeek.get(session.week_number)
      if (!woche) {
        woche = { minuten: 0, days: new Map() }
        byWeek.set(session.week_number, woche)
      }
      // Die Wochensumme zählt **alle** Einheiten der Woche, auch die
      // ausgeblendeten: Eine Bilanz, die sich mit einem Anzeigeschalter ändert,
      // wäre keine.
      woche.minuten += session.duration_min ?? 0
      if (!zeigtAlles && session.date < heute) continue
      if (!woche.days.has(session.date)) woche.days.set(session.date, [])
      woche.days.get(session.date)!.push(session)
    }

    return [...byWeek.entries()]
      .filter(([, woche]) => woche.days.size > 0)
      .sort(([a], [b]) => a - b)
      .map(([weekNumber, woche]) => ({
        weekNumber,
        minuten: woche.minuten,
        days: [...woche.days.entries()].sort(([a], [b]) => a.localeCompare(b)),
      }))
  }, [plan, heute, zeigtAlles])

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
            {offeneEinheiten} Einheiten
            {plan.is_active && <> · <span className="badge badge-success">Aktiv</span></>}
          </p>
        </div>
        <div className="row">
          {/* Zwei Wege in einen neuen Block, und der Unterschied muss am Knopf
              ablesbar sein: „neu planen" wirft die Resttage weg und plant sie
              anhand der aktuellen Lage neu, „nächste 7 Tage" hängt hinten an.
              Läuft der Block nicht mehr, fallen beide zusammen — dann bleibt
              nur einer stehen. */}
          {plan.is_active && plan.end_date >= heute && (
            <Link className="btn btn-primary" to={planErzeugenPfad(heute, undefined, plan.request_id)}>
              Neu planen ab heute
            </Link>
          )}
          {plan.is_active && (
            <Link
              className="btn btn-secondary"
              to={planErzeugenPfad(naechsterBlockStart(plan.end_date), undefined, plan.request_id)}
            >
              {plan.end_date >= heute
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
          {/* „Anpassen" statt „neu ausfüllen": Dieselbe Zeile bleibt bestehen,
              und jeder Plan, der auf sie zeigt, behält seinen Verweis — ein
              neuer Fragebogen erreichte den laufenden Block nie. Ganz von vorn
              geht es weiter über „Neues Training" in der Navigation. */}
          <Link
            className="btn btn-secondary"
            to={fragebogenId ? `/neues-training?request=${fragebogenId}` : '/neues-training'}
          >
            {fragebogenId ? 'Fragebogen anpassen' : 'Fragebogen ausfüllen'}
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

      {/* Steht hier und nicht im Dialog: Der Lauf dauert Minuten, und wer den
          Dialog zwischendurch schließt, verlöre sonst sowohl den Fortschritt
          als auch die Begründung, mit der die KI ihre Änderung erklärt. */}
      {anpassung && (
        <AnpassungsKarte
          job={anpassung}
          onAbbrechen={anpassungLauf.abbrechen}
          onSchliessen={anpassungLauf.vergiss}
        />
      )}

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
        {vergangeneTage > 0 && nochOffen && (
          <button
            className="btn btn-ghost btn-sm mb-1"
            onClick={() => setZeigeVergangenes((an) => !an)}
          >
            {zeigeVergangenes
              ? 'Vergangene Tage ausblenden'
              : `Vergangene Tage anzeigen (${vergangeneTage})`}
          </button>
        )}
        {weeks.map((week) => (
          <div className="week-block" key={week.weekNumber}>
            {weeks.length > 1 && (
              <div className="week-head">
                <h3>Woche {week.weekNumber}</h3>
                <span className="week-stats">{week.minuten} min</span>
              </div>
            )}

            {week.days.map(([date, sessions]) => (
              <div className={`day-row ${date === heute ? 'is-today' : ''}`} key={date}>
                <div className="day-row-head">
                  <div className="day-label">
                    {new Date(date).toLocaleDateString('de-DE', DAY_FORMAT)}
                    {date === heute && ' · heute'}
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
                      onOpen={() => setSelected(session)}
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
        <SessionDetail
          session={selected}
          kiVerfuegbar={anpassungLauf.kiVerfuegbar}
          anpassungLaeuft={anpassungLauf.laeuft}
          onLauf={(job) => {
            anpassungLauf.beobachte(job)
            setSelected(null)
          }}
          onUebernommen={() => {
            setSelected(null)
            reload()
          }}
          onClose={() => setSelected(null)}
        />
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
