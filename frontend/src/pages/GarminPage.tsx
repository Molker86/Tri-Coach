import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api, jobLaeuft, pollJob } from '../api/client'
import { Alert, Loading, Stat } from '../components/ui'
import type { GarminDublette, GarminJob, GarminStatus } from '../types'

/** Wie weit der einmalige Rückblick reicht, in Tagen. */
const RUECKBLICK_OPTIONEN = [
  { tage: 30, label: 'Letzter Monat' },
  { tage: 90, label: 'Letzte 3 Monate' },
  { tage: 365, label: 'Letztes Jahr' },
]

const SCHRITTE = [
  'Trainings',
  'Ruhepuls',
  'Herzfrequenzvariabilität',
  'VO2max',
  'Schlaf',
  'Gewicht',
  'Körperbatterie',
  'Erholungswerte',
  'Leistungswerte',
  'Übungskatalog',
]

function vorTagen(tage: number): string {
  const datum = new Date()
  datum.setDate(datum.getDate() - tage)
  return datum.toISOString().slice(0, 10)
}

function relativeZeit(zeitpunkt: string | null): string {
  if (!zeitpunkt) return 'noch nie'
  const minuten = Math.round((Date.now() - new Date(zeitpunkt).getTime()) / 60000)
  if (minuten < 2) return 'gerade eben'
  if (minuten < 60) return `vor ${minuten} Minuten`
  const stunden = Math.round(minuten / 60)
  if (stunden < 24) return `vor ${stunden} Stunden`
  const tage = Math.round(stunden / 24)
  return tage === 1 ? 'gestern' : `vor ${tage} Tagen`
}

export default function GarminPage() {
  const [zustand, setZustand] = useState<GarminStatus | null>(null)
  const [fehler, setFehler] = useState<string | null>(null)
  const [erfolg, setErfolg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [rueckblickTage, setRueckblickTage] = useState(365)
  const [job, setJob] = useState<GarminJob | null>(null)
  const [dubletten, setDubletten] = useState<GarminDublette[]>([])

  const abbrechenRef = useRef<(() => void) | null>(null)

  const beobachte = useCallback((laufenderJob: GarminJob) => {
    setJob(laufenderJob)
    abbrechenRef.current?.()
    if (!jobLaeuft(laufenderJob)) return
    abbrechenRef.current = pollJob(
      laufenderJob.id,
      api.garminJob,
      (aktualisiert) => {
        setJob(aktualisiert)
        if (!jobLaeuft(aktualisiert)) void ladeZustand()
      },
      (meldung) => setFehler(meldung),
    )
    // ladeZustand ist stabil (useCallback ohne Abhängigkeiten)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const ladeZustand = useCallback(async () => {
    try {
      const daten = await api.garminStatus()
      setZustand(daten)
      if (daten.aktiver_job) beobachte(daten.aktiver_job)
      else setJob(daten.letzter_job)
      if (daten.konto) {
        setDubletten(await api.garminDubletten())
      }
    } catch (err) {
      setFehler(err instanceof Error ? err.message : 'Laden fehlgeschlagen.')
    }
  }, [beobachte])

  useEffect(() => {
    void ladeZustand()
    // Beim Verlassen der Seite die Abfrageschleife beenden — der Abgleich
    // selbst läuft im Server weiter.
    return () => abbrechenRef.current?.()
  }, [ladeZustand])

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

  const konto = zustand?.konto ?? null
  const laeuft = jobLaeuft(job)

  if (zustand === null && fehler === null) return <Loading text="Garmin-Status wird geladen …" />

  return (
    <div className="page page-narrow">
      <div className="page-header">
        <div>
          <h1>Garmin Connect</h1>
          <p className="muted">
            Trainings und Fitnessdaten kommen von deiner Uhr — und nur von dort:
            Absolvierte Einheiten lassen sich nicht von Hand eintragen. Der Weg
            zurück: Geplante Einheiten wandern als Workout in den Garmin-Kalender.
          </p>
        </div>
        {konto !== null && (
          <div className="row">
            <Link className="btn btn-secondary" to="/garmin-kalender">
              Kalender öffnen
            </Link>
          </div>
        )}
      </div>

      {fehler && <Alert kind="error">{fehler}</Alert>}
      {erfolg && <Alert kind="success">{erfolg}</Alert>}

      {konto === null ? (
        <div className="card">
          <div className="card-title">
            <h2>Kein Konto verbunden</h2>
          </div>
          <p className="muted">
            Ohne verbundenes Konto gibt es weder Trainingsdaten noch einen Weg
            zurück auf die Uhr. Verbinden lässt es sich in den Einstellungen —
            dort steht alles, was die App ohne Zutun tut.
          </p>
          <div className="row row-end">
            <Link className="btn btn-primary" to="/einstellungen">
              Zu den Einstellungen
            </Link>
          </div>
        </div>
      ) : (
        <>
          <VerbindungsKarte zustand={zustand!} />

          {laeuft && job ? (
            <FortschrittsKarte
              job={job}
              onAbbrechen={() => void handle(() => api.garminAbbrechen(job.id))}
            />
          ) : (
            <AbgleichKarte
              job={job}
              konto={konto}
              busy={busy}
              rueckblickTage={rueckblickTage}
              setRueckblickTage={setRueckblickTage}
              onSync={() => void handle(api.garminSync, beobachte)}
              onBackfill={() =>
                void handle(() => api.garminBackfill(vorTagen(rueckblickTage)), beobachte)
              }
            />
          )}

          {dubletten.length > 0 && (
            <DublettenKarte
              treffer={dubletten}
              onLoeschen={(id) =>
                void handle(
                  () => api.deleteLog(id),
                  () => {
                    setDubletten((bisher) =>
                      bisher.filter((d) => d.manual_log_id !== id),
                    )
                    setErfolg('Der handschriftliche Eintrag wurde gelöscht.')
                  },
                )
              }
            />
          )}
        </>
      )}
    </div>
  )
}

function VerbindungsKarte(props: { zustand: GarminStatus }) {
  const konto = props.zustand.konto!
  const problem = konto.status !== 'connected'

  return (
    <div className="card">
      <div className="card-title">
        <h2>Verbindung</h2>
      </div>

      {problem && <Alert kind="warning">{konto.status_message ?? 'Die Verbindung hat ein Problem.'}</Alert>}

      <div className="grid grid-3">
        <Stat label="Konto" value={<span className="small">{konto.email}</span>} />
        <Stat
          label="Zuletzt abgeglichen"
          value={relativeZeit(konto.last_sync_at)}
        />
        <Stat
          label="Aus Garmin"
          value={props.zustand.trainings_gesamt}
          hint={`${props.zustand.fitness_tage_gesamt} Tage Fitnessdaten`}
        />
      </div>

      {/* Verbinden, Trennen und die Schalter dazu stehen unter „Einstellungen":
          Sie beschreiben, was die App ohne Zutun tut, und das gehört an einen
          Ort statt verteilt auf die Seite, auf der man abgleicht. */}
      <p className="small muted mt-2 mb-0">
        Konto trennen, automatischer Abgleich, Abgleichzeit, Übertragung auf die
        Uhr und Profilübernahme stehen in den{' '}
        <Link to="/einstellungen">Einstellungen</Link>.
      </p>
    </div>
  )
}

function FortschrittsKarte(props: { job: GarminJob; onAbbrechen: () => void }) {
  const aktuellerSchritt = props.job.step
  // Eine Übertragung läuft nicht durch die Schrittfolge des Abgleichs — dort
  // heißt jeder Schritt wie die Einheit, die gerade gesendet wird.
  const istUebertragung = props.job.kind.startsWith('workout')

  return (
    <div className="card">
      <div className="card-title">
        <h2>{istUebertragung ? 'Übertragung läuft' : 'Abgleich läuft'}</h2>
        <button className="btn btn-ghost btn-sm" onClick={props.onAbbrechen}>
          Abbrechen
        </button>
      </div>

      <div className="wizard-progress">
        {istUebertragung ? (
          <>
            <div
              className="wizard-step-bar current"
              style={{ flexGrow: Math.max(1, props.job.progress_pct) }}
            />
            <div
              className="wizard-step-bar"
              style={{ flexGrow: Math.max(1, 100 - props.job.progress_pct) }}
            />
          </>
        ) : (
          SCHRITTE.map((schritt, index) => {
            const aktiv = schritt === aktuellerSchritt
            const erledigt = index < SCHRITTE.indexOf(aktuellerSchritt ?? '')
            return (
              <div
                key={schritt}
                className={`wizard-step-bar${erledigt ? ' done' : ''}${aktiv ? ' current' : ''}`}
                title={schritt}
              />
            )
          })
        )}
      </div>

      <p className="muted mb-0">{props.job.message ?? 'Daten werden geladen …'}</p>
      <p className="small faint">
        {props.job.progress_pct}&nbsp;% — du kannst die Seite verlassen, der
        Abgleich läuft im Hintergrund weiter.
      </p>
    </div>
  )
}

function AbgleichKarte(props: {
  job: GarminJob | null
  konto: NonNullable<GarminStatus['konto']>
  busy: boolean
  rueckblickTage: number
  setRueckblickTage: (tage: number) => void
  onSync: () => void
  onBackfill: () => void
}) {
  const gesperrt = props.konto.status === 'token_expired'
  const artDesLetzten = props.job?.state

  return (
    <div className="card">
      <div className="card-title">
        <h2>Daten holen</h2>
      </div>

      {props.job && artDesLetzten !== 'done' && props.job.message && (
        <Alert
          kind={
            artDesLetzten === 'rate_limited' || artDesLetzten === 'failed'
              ? 'warning'
              : 'info'
          }
        >
          {props.job.message}
        </Alert>
      )}
      {props.job && artDesLetzten === 'done' && props.job.message && (
        <Alert kind="success">{props.job.message}</Alert>
      )}

      <div className="row">
        <button
          className="btn btn-primary"
          onClick={props.onSync}
          disabled={props.busy || gesperrt}
        >
          {props.busy ? 'Startet …' : 'Jetzt synchronisieren'}
        </button>
        <span className="muted small">
          {props.konto.synced_through
            ? 'Holt die letzten fünf Tage nach — was älter ist, steht schon hier.'
            : 'Holt beim ersten Mal das letzte Jahr. Das dauert einige Minuten.'}
        </span>
      </div>

      <div className="divider" />

      <h3>Einmaliger Rückblick</h3>
      <p className="muted">
        Holt einen Zeitraum noch einmal — auch Tage, die schon geholt wurden.
        Nötig ist das selten: Der Abgleich oben deckt das letzte Jahr von allein
        ab. Für die Erholungswerte (Trainingsreife, Stress) reichen die letzten
        sechs Wochen — sie sind Momentaufnahmen und rückwirkend ohne
        Aussagekraft für die Planung.
      </p>
      <div className="row">
        <div className="field-slot">
          <select
            value={props.rueckblickTage}
            onChange={(e) => props.setRueckblickTage(Number(e.target.value))}
          >
            {RUECKBLICK_OPTIONEN.map((option) => (
              <option key={option.tage} value={option.tage}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <button
          className="btn btn-secondary"
          onClick={props.onBackfill}
          disabled={props.busy || gesperrt}
        >
          Rückblick holen
        </button>
      </div>
      <p className="small faint">
        Dauert einige Minuten. Zwischen den Abfragen liegen bewusst Pausen — sonst
        sperrt Garmin die Verbindung.
      </p>
    </div>
  )
}

function DublettenKarte(props: {
  treffer: GarminDublette[]
  onLoeschen: (manualLogId: number) => void
}) {
  return (
    <div className="card">
      <div className="card-title">
        <h2>Mögliche Doppeleinträge</h2>
      </div>
      <p className="muted">
        Diese Einheiten hast du früher von Hand eingetragen — inzwischen gibt es
        sie auch aus Garmin. Beide zählen in Wochenübersicht und Belastung. Was
        du löschst, entscheidest du.
      </p>
      <div className="table-wrap">
        <table className="table-cards">
          <thead>
            <tr>
              <th>Datum</th>
              <th>Sportart</th>
              <th>Von Hand</th>
              <th>Aus Garmin</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {props.treffer.map((eintrag) => (
              <tr key={eintrag.manual_log_id}>
                <td className="cell-title" data-label="Datum">
                  {new Date(eintrag.date).toLocaleDateString('de-DE')}
                </td>
                <td data-label="Sportart">{eintrag.sport}</td>
                <td data-label="Von Hand">
                  {eintrag.manual_duration_min ?? '–'} min
                </td>
                <td data-label="Aus Garmin">
                  {eintrag.garmin_duration_min ?? '–'} min
                </td>
                <td className="cell-actions">
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => props.onLoeschen(eintrag.manual_log_id)}
                  >
                    Handeintrag löschen
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
