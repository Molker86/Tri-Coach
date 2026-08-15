import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api, jobLaeuft, pollJob } from '../api/client'
import { Alert, EmptyState, Loading, Modal } from '../components/ui'
import { sportIcon, sportLabel } from '../constants'
import type {
  GarminEinheitStatus,
  GarminJob,
  GarminKalenderEintrag,
  GarminPlanUebertragung,
} from '../types'

const MONATE = [
  'Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
  'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember',
]

/** Montag zuerst — der deutsche Kalender beginnt nicht am Sonntag. */
const WOCHENTAGE = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']

function iso(datum: Date): string {
  return `${datum.getFullYear()}-${String(datum.getMonth() + 1).padStart(2, '0')}-${String(
    datum.getDate(),
  ).padStart(2, '0')}`
}

const HEUTE = iso(new Date())

/** Wie viele Leerfelder vor dem Ersten stehen, damit die Spalten stimmen. */
function fuehrendeLeerfelder(jahr: number, monat: number): number {
  return (new Date(jahr, monat - 1, 1).getDay() + 6) % 7
}

function tageImMonat(jahr: number, monat: number): number {
  return new Date(jahr, monat, 0).getDate()
}

/** Ein Tag im Raster: was Garmin kennt und was noch aussteht. */
interface Tag {
  datum: string
  nummer: number
  eintraege: GarminKalenderEintrag[]
  offen: GarminEinheitStatus[]
}

export default function GarminKalender() {
  const heute = new Date()
  const [jahr, setJahr] = useState(heute.getFullYear())
  const [monat, setMonat] = useState(heute.getMonth() + 1)

  const [eintraege, setEintraege] = useState<GarminKalenderEintrag[]>([])
  const [plan, setPlan] = useState<GarminPlanUebertragung | null>(null)
  const [verbunden, setVerbunden] = useState<boolean | null>(null)
  const [job, setJob] = useState<GarminJob | null>(null)

  const [laden, setLaden] = useState(true)
  const [busy, setBusy] = useState(false)
  const [fehler, setFehler] = useState<string | null>(null)
  const [erfolg, setErfolg] = useState<string | null>(null)
  const [gewaehlt, setGewaehlt] = useState<GarminKalenderEintrag | null>(null)

  const abbrechenRef = useRef<(() => void) | null>(null)

  const ladePlan = useCallback(async () => {
    try {
      setPlan(await api.garminWorkoutStatus())
    } catch {
      // Ohne aktiven Plan gibt es nichts zu übertragen — kein Fehlerfall.
      setPlan(null)
    }
  }, [])

  const ladeKalender = useCallback(async () => {
    setLaden(true)
    try {
      const zustand = await api.garminStatus()
      setVerbunden(zustand.konto !== null)
      if (zustand.konto === null) {
        setEintraege([])
        return
      }
      const [kalender] = await Promise.all([api.garminKalender(jahr, monat), ladePlan()])
      setEintraege(kalender.eintraege)
      setFehler(null)
    } catch (err) {
      setFehler(err instanceof Error ? err.message : 'Der Kalender ließ sich nicht laden.')
    } finally {
      setLaden(false)
    }
  }, [jahr, monat, ladePlan])

  useEffect(() => {
    void ladeKalender()
    return () => abbrechenRef.current?.()
  }, [ladeKalender])

  /** Beobachtet einen laufenden Übertragungsjob bis zum Ende. */
  const beobachte = useCallback(
    (laufender: GarminJob) => {
      setJob(laufender)
      abbrechenRef.current?.()
      if (!jobLaeuft(laufender)) return
      abbrechenRef.current = pollJob(
        laufender.id,
        api.garminJob,
        (aktualisiert) => {
          setJob(aktualisiert)
          if (!jobLaeuft(aktualisiert)) void ladeKalender()
        },
        (meldung) => setFehler(meldung),
      )
    },
    [ladeKalender],
  )

  async function handle<T>(aktion: () => Promise<T>, danach?: (wert: T) => void) {
    setBusy(true)
    setFehler(null)
    setErfolg(null)
    try {
      danach?.(await aktion())
    } catch (err) {
      setFehler(
        err instanceof ApiError || err instanceof Error
          ? err.message
          : 'Etwas ist schiefgelaufen.',
      )
    } finally {
      setBusy(false)
    }
  }

  function blaettere(schritte: number) {
    const ziel = new Date(jahr, monat - 1 + schritte, 1)
    setJahr(ziel.getFullYear())
    setMonat(ziel.getMonth() + 1)
  }

  const tage = useMemo<Tag[]>(() => {
    const offeneJeTag = new Map<string, GarminEinheitStatus[]>()
    for (const einheit of plan?.einheiten ?? []) {
      if (einheit.zustand === 'aktuell') continue
      if (!offeneJeTag.has(einheit.date)) offeneJeTag.set(einheit.date, [])
      offeneJeTag.get(einheit.date)!.push(einheit)
    }

    return Array.from({ length: tageImMonat(jahr, monat) }, (_, index) => {
      const datum = `${jahr}-${String(monat).padStart(2, '0')}-${String(index + 1).padStart(2, '0')}`
      return {
        datum,
        nummer: index + 1,
        eintraege: eintraege.filter((e) => e.datum === datum),
        offen: offeneJeTag.get(datum) ?? [],
      }
    })
  }, [eintraege, plan, jahr, monat])

  const laeuft = jobLaeuft(job)

  if (laden && verbunden === null) return <Loading text="Kalender wird geladen …" />

  if (verbunden === false) {
    return (
      <EmptyState icon="⌚" title="Kein Garmin-Konto verbunden">
        <p>
          Der Kalender zeigt, was auf deiner Uhr liegt. Dafür muss zuerst dein
          Garmin-Konto verbunden sein.
        </p>
        <Link className="btn btn-primary" to="/garmin">
          Garmin verbinden
        </Link>
      </EmptyState>
    )
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Garmin-Kalender</h1>
          <p className="muted">
            Was hier steht, steht auch in Garmin Connect und auf deiner Uhr.
          </p>
        </div>
        <div className="row">
          <Link className="btn btn-secondary" to="/plan">
            Zum Trainingsplan
          </Link>
        </div>
      </div>

      {fehler && <Alert kind="error">{fehler}</Alert>}
      {erfolg && <Alert kind="success">{erfolg}</Alert>}

      <UebertragungsKarte
        plan={plan}
        job={job}
        laeuft={laeuft}
        busy={busy}
        onUebertragen={() =>
          void handle(() => api.garminWorkoutsUebertragen(), beobachte)
        }
        onEntfernen={() => {
          if (!confirm('Alle übertragenen Einheiten dieses Plans aus Garmin entfernen?'))
            return
          void handle(() => api.garminWorkoutsEntfernen(), beobachte)
        }}
      />

      <div className="card">
        <div className="card-title">
          <h2>
            {MONATE[monat - 1]} {jahr}
          </h2>
          <div className="row">
            <button className="btn btn-ghost btn-sm" onClick={() => blaettere(-1)}>
              ‹ Vorheriger
            </button>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setJahr(heute.getFullYear())
                setMonat(heute.getMonth() + 1)
              }}
            >
              Heute
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => blaettere(1)}>
              Nächster ›
            </button>
          </div>
        </div>

        {laden ? (
          <Loading text="Monat wird geladen …" />
        ) : (
          <div className="kalender">
            <div className="kalender-kopf" aria-hidden="true">
              {WOCHENTAGE.map((tag) => (
                <span key={tag}>{tag}</span>
              ))}
            </div>

            <div className="kalender-raster">
              {Array.from({ length: fuehrendeLeerfelder(jahr, monat) }, (_, i) => (
                <div className="kalender-tag kalender-fueller" key={`leer-${i}`} />
              ))}

              {tage.map((tag) => (
                <div
                  className={[
                    'kalender-tag',
                    tag.datum === HEUTE ? 'is-heute' : '',
                    tag.eintraege.length === 0 && tag.offen.length === 0 ? 'is-leer' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  key={tag.datum}
                >
                  <div className="kalender-tag-kopf">
                    <span className="kalender-tag-zahl">{tag.nummer}</span>
                    <span className="kalender-tag-name">
                      {new Date(tag.datum).toLocaleDateString('de-DE', {
                        weekday: 'short',
                      })}
                    </span>
                  </div>

                  {tag.eintraege.map((eintrag) => (
                    <button
                      key={`${eintrag.art}-${eintrag.schedule_id}-${eintrag.titel}`}
                      className={`kalender-chip art-${eintrag.art}${
                        eintrag.aus_tri_coach ? ' ist-eigen' : ''
                      }`}
                      onClick={() => setGewaehlt(eintrag)}
                    >
                      <span className="kalender-chip-icon">
                        {eintrag.sportart ? sportIcon(eintrag.sportart) : '•'}
                      </span>
                      <span className="kalender-chip-text">{eintrag.titel}</span>
                    </button>
                  ))}

                  {tag.offen.map((einheit) => (
                    <button
                      key={`offen-${einheit.plan_session_id}`}
                      className="kalender-chip ist-offen"
                      disabled={busy || laeuft}
                      title="Noch nicht in Garmin — antippen zum Übertragen"
                      onClick={() =>
                        void handle(
                          () => api.garminEinheitUebertragen(einheit.plan_session_id),
                          () => {
                            setErfolg(`„${einheit.title}“ liegt jetzt in Garmin.`)
                            void ladeKalender()
                          },
                        )
                      }
                    >
                      <span className="kalender-chip-icon">{sportIcon(einheit.sport)}</span>
                      <span className="kalender-chip-text">{einheit.title}</span>
                      <span className="kalender-chip-marke">
                        {einheit.zustand === 'geaendert' ? 'geändert' : 'offen'}
                      </span>
                    </button>
                  ))}
                </div>
              ))}
            </div>
          </div>
        )}

        <p className="small faint mt-1 mb-0">
          Gestrichelt umrandet: geplant, aber noch nicht in Garmin. Antippen legt die
          Einheit auf die Uhr.
        </p>
      </div>

      {gewaehlt && (
        <EintragsFenster
          eintrag={gewaehlt}
          busy={busy}
          onClose={() => setGewaehlt(null)}
          onEntfernen={(mitVorlage) => {
            if (!gewaehlt.schedule_id) return
            void handle(
              () =>
                api.garminKalenderLoeschen(
                  gewaehlt.schedule_id!,
                  mitVorlage ? gewaehlt.workout_id : null,
                ),
              () => {
                setGewaehlt(null)
                setErfolg(
                  mitVorlage
                    ? 'Das Training wurde aus Garmin gelöscht.'
                    : 'Der Termin wurde aus dem Kalender genommen.',
                )
                void ladeKalender()
              },
            )
          }}
          onVerschieben={(datum) => {
            if (!gewaehlt.schedule_id || !gewaehlt.workout_id) return
            void handle(
              () =>
                api.garminKalenderVerschieben(
                  gewaehlt.schedule_id!,
                  gewaehlt.workout_id!,
                  datum,
                ),
              () => {
                setGewaehlt(null)
                setErfolg('Das Training liegt jetzt auf dem neuen Tag.')
                void ladeKalender()
              },
            )
          }}
        />
      )}
    </>
  )
}

function UebertragungsKarte(props: {
  plan: GarminPlanUebertragung | null
  job: GarminJob | null
  laeuft: boolean
  busy: boolean
  onUebertragen: () => void
  onEntfernen: () => void
}) {
  const { plan, job } = props

  if (plan === null) {
    return (
      <div className="card">
        <p className="mb-0 muted">
          Es gibt keinen aktiven Trainingsplan. Sobald einer da ist, lässt er sich von
          hier aus auf die Uhr legen.
        </p>
      </div>
    )
  }

  const offen = plan.offen + plan.geaendert + plan.fehler
  const uebertragbar = plan.einheiten.length

  return (
    <div className="card">
      <div className="card-title">
        <h2>{plan.plan_title}</h2>
        {plan.aktuell > 0 && !props.laeuft && (
          <button
            className="btn btn-ghost btn-sm"
            onClick={props.onEntfernen}
            disabled={props.busy}
          >
            Aus Garmin entfernen
          </button>
        )}
      </div>

      {props.laeuft ? (
        <>
          <div className="wizard-progress">
            <div
              className="wizard-step-bar current"
              style={{ flexGrow: Math.max(1, job?.progress_pct ?? 1) }}
            />
            <div
              className="wizard-step-bar"
              style={{ flexGrow: Math.max(1, 100 - (job?.progress_pct ?? 0)) }}
            />
          </div>
          <p className="muted mb-0">{job?.message ?? 'Wird übertragen …'}</p>
        </>
      ) : (
        <>
          {job?.message && (
            <Alert kind={job.state === 'done' ? 'success' : 'warning'}>{job.message}</Alert>
          )}

          <p className="muted">
            {plan.aktuell} von {uebertragbar} Einheiten liegen in Garmin
            {plan.geaendert > 0 && `, ${plan.geaendert} haben sich seither geändert`}
            {plan.vergangen > 0 &&
              ` · ${plan.vergangen} vergangene Einheiten bleiben außen vor`}
            .
          </p>

          <div className="row">
            {/* Auch bei „alles aktuell" anklickbar: Der Lauf sieht zuerst nach,
                was wirklich in Garmin steht. Wäre der Knopf hier tot, käme der
                Nutzer aus einem falschen Stand nicht mehr heraus — genau dann,
                wenn er den Knopf braucht. */}
            <button
              className={offen === 0 ? 'btn btn-secondary' : 'btn btn-primary'}
              onClick={props.onUebertragen}
              disabled={props.busy || uebertragbar === 0}
            >
              {offen === 0 ? 'Mit Garmin abgleichen' : 'Garmin Trainings übertragen'}
            </button>
            {offen === 0 ? (
              <span className="muted small">
                Alles ist auf dem neuesten Stand. Der Abgleich prüft nach, ob es in
                Garmin wirklich noch steht, und legt Fehlendes neu an.
              </span>
            ) : (
              <span className="muted small">
                {offen} {offen === 1 ? 'Einheit wartet' : 'Einheiten warten'} — sie
                erscheinen im Garmin-Kalender und auf der Uhr, sobald sie das nächste
                Mal synchronisiert.
              </span>
            )}
          </div>

          <p className="muted small mb-0">
            Sobald der Tag einer Einheit vorbei ist, nimmt die App sie von selbst
            aus deinem Garmin-Kalender und aus der Trainingsbibliothek — dein
            absolviertes Training bleibt davon unberührt.
          </p>
        </>
      )}
    </div>
  )
}

function EintragsFenster(props: {
  eintrag: GarminKalenderEintrag
  busy: boolean
  onClose: () => void
  onEntfernen: (mitVorlage: boolean) => void
  onVerschieben: (datum: string) => void
}) {
  const { eintrag } = props
  const [neuesDatum, setNeuesDatum] = useState(eintrag.datum)
  const istWorkout = eintrag.art === 'workout' && eintrag.schedule_id !== null

  return (
    <Modal title={eintrag.titel} onClose={props.onClose}>
      <div className="row mb-1">
        <span className="badge">
          {eintrag.sportart ? sportIcon(eintrag.sportart) : '•'}{' '}
          {eintrag.sportart ? sportLabel(eintrag.sportart) : (eintrag.garmin_typ ?? 'Garmin')}
        </span>
        <span className="badge">
          {new Date(eintrag.datum).toLocaleDateString('de-DE', {
            weekday: 'long',
            day: '2-digit',
            month: '2-digit',
          })}
        </span>
        {eintrag.art === 'aktivitaet' && (
          <span className="badge badge-success">absolviert</span>
        )}
        {eintrag.aus_tri_coach && <span className="badge badge-accent">aus Tri-Coach</span>}
      </div>

      <div className="table-wrap">
        <table>
          <tbody>
            {eintrag.dauer_min ? (
              <tr><th>Dauer</th><td>{eintrag.dauer_min} min</td></tr>
            ) : null}
            {eintrag.distanz_km ? (
              <tr><th>Distanz</th><td>{eintrag.distanz_km} km</td></tr>
            ) : null}
            {eintrag.garmin_typ ? (
              <tr><th>Garmin-Typ</th><td>{eintrag.garmin_typ}</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {eintrag.art === 'aktivitaet' ? (
        <Alert kind="info">
          Ein absolviertes Training. Es bleibt unangetastet — daraus zieht diese App
          ihre Auswertung und die nächste Planung.
        </Alert>
      ) : null}

      {istWorkout && (
        <>
          <h4 className="mt-2">Auf einen anderen Tag legen</h4>
          <div className="row">
            <div className="field-slot">
              <input
                type="date"
                value={neuesDatum}
                onChange={(e) => setNeuesDatum(e.target.value)}
              />
            </div>
            <button
              className="btn btn-secondary"
              disabled={props.busy || neuesDatum === eintrag.datum}
              onClick={() => props.onVerschieben(neuesDatum)}
            >
              Verschieben
            </button>
          </div>

          <h4 className="mt-2">Entfernen</h4>
          <p className="muted small">
            Nur den Termin zu löschen lässt die Vorlage in deiner Garmin-Bibliothek —
            du kannst sie dort erneut einplanen.
          </p>
          <div className="row">
            <button
              className="btn btn-secondary"
              disabled={props.busy}
              onClick={() => props.onEntfernen(false)}
            >
              Aus dem Kalender nehmen
            </button>
            <button
              className="btn btn-danger"
              disabled={props.busy || !eintrag.workout_id}
              onClick={() => {
                if (!confirm(`„${eintrag.titel}“ endgültig aus Garmin löschen?`)) return
                props.onEntfernen(true)
              }}
            >
              Ganz aus Garmin löschen
            </button>
          </div>
        </>
      )}
    </Modal>
  )
}
