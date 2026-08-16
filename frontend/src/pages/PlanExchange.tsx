import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, jobLaeuft, pollJob } from '../api/client'
import { Alert, Field, Loading } from '../components/ui'
import { PLAN_TAGE, heuteIso } from '../planung'
import type {
  AiExport,
  ErsetzterBlock,
  KiJob,
  KiStatus,
  PlanImportResult,
} from '../types'

const DAY_OPTIONS = [2, 3, 4, 5, 6, 7]

export default function PlanExchange() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const requestId = params.get('request') ? Number(params.get('request')) : undefined
  // Ein Block über wenige Tage beginnt normalerweise heute.
  const paramStart = params.get('start') || heuteIso()
  const paramDays = params.get('days') ? Number(params.get('days')) : PLAN_TAGE

  const [startDate, setStartDate] = useState(paramStart)
  const [days, setDays] = useState(paramDays)
  const [exported, setExported] = useState<AiExport | null>(null)
  const [raw, setRaw] = useState('')
  const [preview, setPreview] = useState<PlanImportResult | null>(null)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [kiStatus, setKiStatus] = useState<KiStatus | null>(null)
  const [kiJob, setKiJob] = useState<KiJob | null>(null)
  const abbrechenRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    setExported(null)
    api
      .exportForAi(requestId, startDate, days)
      .then(setExported)
      .catch((err) => setError(err.message))
  }, [requestId, startDate, days])

  /** Hängt sich an einen laufenden Lauf und geht am Ende zum fertigen Plan. */
  const beobachte = useCallback(
    (job: KiJob) => {
      setKiJob(job)
      abbrechenRef.current?.()
      if (!jobLaeuft(job)) return
      abbrechenRef.current = pollJob(
        job.id,
        api.kiJob,
        (aktualisiert) => {
          setKiJob(aktualisiert)
          if (jobLaeuft(aktualisiert)) return
          if (aktualisiert.state === 'done' && aktualisiert.plan_id) {
            navigate(`/plan/${aktualisiert.plan_id}`)
          } else if (aktualisiert.message) {
            setError(aktualisiert.message)
          }
        },
        (meldung) => setError(meldung),
      )
    },
    [navigate],
  )

  useEffect(() => {
    // Auch ein Lauf, der in einem anderen Fenster angestoßen wurde, soll hier
    // sichtbar werden — sonst stünde die Seite still, während im Server geplant
    // wird.
    api
      .kiStatus()
      .then((status) => {
        setKiStatus(status)
        if (status.aktiver_job) beobachte(status.aktiver_job)
      })
      .catch(() => setKiStatus(null))
    return () => abbrechenRef.current?.()
  }, [beobachte])

  async function planeMitKi() {
    setError(null)
    setBusy(true)
    try {
      beobachte(await api.kiPlanen(startDate, days, requestId))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Der Lauf ließ sich nicht starten.')
    } finally {
      setBusy(false)
    }
  }

  async function brichAb() {
    if (!kiJob) return
    try {
      setKiJob(await api.kiAbbrechen(kiJob.id))
    } catch {
      // Der Lauf endet ohnehin; eine Fehlermeldung hier hälfe niemandem.
    }
  }

  async function copyPrompt() {
    if (!exported) return
    try {
      await navigator.clipboard.writeText(exported.combined)
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    } catch {
      setError(
        'Der Zugriff auf die Zwischenablage wurde blockiert. Markiere den Text unten und kopiere ihn manuell.',
      )
    }
  }

  /**
   * Lädt genau das herunter, was auch der Kopierknopf liefert: Prompt samt
   * eingebettetem Datenpaket. Das nackte JSON allein wäre für die KI wertlos —
   * ohne die Anweisungen davor fehlt ihr die Aufgabe.
   */
  function downloadPrompt() {
    if (!exported) return
    const blob = new Blob([exported.combined], {
      type: 'text/plain;charset=utf-8',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `tri-coach-prompt-${startDate}.txt`
    // Safari lädt nur herunter, was im Dokument hängt, und bricht ab, wenn die
    // Blob-Adresse noch im selben Tick wieder freigegeben wird.
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  async function checkPlan() {
    setBusy(true)
    setError(null)
    setPreview(null)
    try {
      setPreview(await api.validatePlan(raw, requestId, days))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Prüfung fehlgeschlagen.')
    } finally {
      setBusy(false)
    }
  }

  async function importPlan() {
    setBusy(true)
    setError(null)
    try {
      const result = await api.importPlan(raw, requestId, days)
      // Der Hinweis wandert mit: Er entsteht beim Übernehmen (etwa eine
      // Anfragesperre bei Garmin), zu sehen ist er aber erst im Plan, wo der
      // Kalendereintrag fehlt. Hier stünde er nur für den Bruchteil einer
      // Sekunde bis zum Seitenwechsel.
      navigate(`/plan/${result.plan.id}`, {
        state: result.garmin_hinweis ? { garminHinweis: result.garmin_hinweis } : null,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import fehlgeschlagen.')
      setBusy(false)
    }
  }

  // Steht nur im Payload, wenn der gewählte Zeitraum einen laufenden Block
  // überlappt — das Backend entscheidet das, nicht die Herkunft des Aufrufs.
  const ersetzt: ErsetzterBlock | undefined =
    exported?.payload.planungszeitraum?.ersetzt_laufenden_block

  const kiVerfuegbar = kiStatus?.verfuegbar === true
  const laeuft = jobLaeuft(kiJob)

  const zeitraum = (
    <div className="row">
      <div className="field-slot">
        <Field label="Erster Tag">
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
          />
        </Field>
      </div>
      <div className="field-slot">
        <Field label="Anzahl Tage">
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {DAY_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option} Tage
              </option>
            ))}
          </select>
        </Field>
      </div>
    </div>
  )

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Nächste Trainingstage von der KI planen lassen</h1>
          <p>
            {kiVerfuegbar
              ? 'Ein Knopf — die App holt den Plan selbst und übernimmt ihn.'
              : 'Zwei Schritte: Text kopieren und an eine KI schicken, Antwort hier wieder einfügen.'}
          </p>
        </div>
      </div>

      {error && <Alert kind="error">{error}</Alert>}

      {ersetzt && <ErsatzHinweis block={ersetzt} start={startDate} />}

      {kiVerfuegbar && (
        <div className="card">
          <div className="card-title">
            <h2>Von Claude planen lassen</h2>
            {zeitraum}
          </div>

          {/* Ein abgelaufener Zugang oder ein aufgebrauchtes Kontingent gehört
              an den Knopf: Sonst erführe man den Grund erst, wenn der nächste
              Druck gleich wieder scheitert. */}
          {kiStatus?.einstellungen &&
            kiStatus.einstellungen.status !== 'ready' &&
            kiStatus.einstellungen.status_message && (
              <Alert kind="warning">{kiStatus.einstellungen.status_message}</Alert>
            )}

          {laeuft && kiJob ? (
            <LaufKarte job={kiJob} onAbbrechen={brichAb} />
          ) : (
            <>
              <p className="muted">
                Die App schickt dasselbe Datenpaket an Claude, das du sonst von Hand
                kopierst, und übernimmt die Antwort direkt. Der Lauf dauert je nach
                Denktiefe zwei bis vier Minuten — du kannst die Seite dabei
                verlassen.
              </p>
              <div className="row mb-1">
                <button
                  className="btn btn-primary"
                  onClick={planeMitKi}
                  disabled={busy || !exported}
                >
                  {busy ? 'Wird gestartet …' : 'Block jetzt planen'}
                </button>
                <span className="small faint">
                  Modell: {kiStatus?.modell} · Denktiefe: {kiStatus?.effort}
                </span>
              </div>
              {kiStatus?.letzter_job && !laeuft && (
                <LetzterLauf job={kiStatus.letzter_job} />
              )}
            </>
          )}
        </div>
      )}

      {!kiVerfuegbar && (
        <Alert kind="info">
          Es ist kein Claude-Zugang hinterlegt — der Plan entsteht deshalb über
          Kopieren und Einfügen. Wer die App als Home-Assistant-Add-on betreibt,
          erzeugt mit <code>claude setup-token</code> ein Token und trägt es in den
          Add-on-Einstellungen ein; danach genügt hier ein Knopfdruck.
        </Alert>
      )}

      <ManuellerWeg
        aufgeklappt={!kiVerfuegbar}
        zeitraum={kiVerfuegbar ? null : zeitraum}
        exported={exported}
        copied={copied}
        onCopy={copyPrompt}
        onDownload={downloadPrompt}
        raw={raw}
        onRaw={(wert) => {
          setRaw(wert)
          setPreview(null)
        }}
        preview={preview}
        busy={busy}
        onCheck={checkPlan}
        onImport={importPlan}
      />

      <div className="card">
        <h3>Hinweis zum Datenschutz</h3>
        <p className="small muted mb-0">
          Das Datenpaket enthält Gesundheitsdaten wie Ruhepuls, Gewicht und Angaben zu
          Verletzungen. Was an eine KI geht, verlässt deinen Rechner und unterliegt den
          Bedingungen des jeweiligen Anbieters — auch dann, wenn die App den Aufruf
          selbst übernimmt.
        </p>
      </div>
    </>
  )
}

/** Der Fortschritt eines Planungslaufs.
 *
 * Bewusst ohne Schrittfolge wie beim Garmin-Abgleich: Hier gibt es genau drei
 * Abschnitte, und der längste davon ist das Warten auf die KI, das sich nicht
 * unterteilen lässt.
 */
function LaufKarte({ job, onAbbrechen }: { job: KiJob; onAbbrechen: () => void }) {
  return (
    <>
      <div className="wizard-progress">
        <div
          className="wizard-step-bar current"
          style={{ flexGrow: Math.max(1, job.progress_pct) }}
        />
        <div
          className="wizard-step-bar"
          style={{ flexGrow: Math.max(1, 100 - job.progress_pct) }}
        />
      </div>
      <p className="muted mb-0">{job.message ?? 'Der Lauf wird vorbereitet …'}</p>
      <div className="row mt-1">
        <span className="small faint">
          {job.progress_pct}&nbsp;% — du kannst die Seite verlassen, der Lauf geht im
          Hintergrund weiter.
        </span>
        <button className="btn btn-ghost btn-sm" onClick={onAbbrechen}>
          Abbrechen
        </button>
      </div>
    </>
  )
}

/** Was der letzte Lauf ergeben hat — samt Modell, das tatsächlich geantwortet hat. */
function LetzterLauf({ job }: { job: KiJob }) {
  const wann = new Date(job.started_at).toLocaleString('de-DE', {
    dateStyle: 'short',
    timeStyle: 'short',
  })
  const teile = [wann]
  // „automatisch" steht nur noch an Läufen aus der Zeit vor dem Wegfall der
  // Automatik. Bei allen neuen wäre „von Hand" eine Selbstverständlichkeit.
  if (job.kind === 'auto') teile.push('automatisch')
  if (job.model_used) teile.push(job.model_used)
  if (job.duration_ms) teile.push(`${Math.round(job.duration_ms / 1000)} s`)

  return (
    <p className="small faint mb-0">
      Letzter Lauf: {teile.join(' · ')}
      {job.message ? ` — ${job.message}` : ''}
    </p>
  )
}

/** Der Weg über die Zwischenablage.
 *
 * Bleibt vollständig erhalten, auch wenn die App den Aufruf selbst kann: Er ist
 * die Rückfallebene, wenn der Zugang abgelaufen ist oder das Kontingent des
 * Abos aufgebraucht — und die einzige Möglichkeit, eine andere KI zu benutzen.
 */
function ManuellerWeg(props: {
  aufgeklappt: boolean
  zeitraum: React.ReactNode
  exported: AiExport | null
  copied: boolean
  onCopy: () => void
  onDownload: () => void
  raw: string
  onRaw: (wert: string) => void
  preview: PlanImportResult | null
  busy: boolean
  onCheck: () => void
  onImport: () => void
}) {
  const inhalt = (
    <>
      <div className="card">
        <div className="card-title">
          <h2>
            <span className="step-marker">1</span>
            Datenpaket kopieren
          </h2>
          {props.zeitraum}
        </div>

        <p className="muted">
          Geplant wird nur der nächste kurze Block — das trifft die Realität besser als
          ein Vier-Wochen-Plan und ist für die KI die leichtere Aufgabe. Als Grundlage
          gehen trotzdem die vollen letzten vier Wochen mit: Profildaten, Fragebogen,
          Herzfrequenzzonen, alle erfassten Trainings, Belastungsverhältnis und der
          Abstand zur letzten Einheit je Sportart.
        </p>

        {!props.exported ? (
          <Loading text="Datenpaket wird erstellt …" />
        ) : (
          <>
            <div className="row mb-1">
              <button className="btn btn-primary" onClick={props.onCopy}>
                {props.copied ? '✓ In die Zwischenablage kopiert' : 'Text kopieren'}
              </button>
              <button className="btn btn-secondary" onClick={props.onDownload}>
                Als Datei herunterladen
              </button>
            </div>

            <details>
              <summary className="small muted" style={{ cursor: 'pointer' }}>
                Text anzeigen ({Math.round(props.exported.combined.length / 1024)} KB)
              </summary>
              <div className="code-box mt-1">{props.exported.combined}</div>
            </details>
          </>
        )}
      </div>

      <div className="card">
        <h2>
          <span className="step-marker">2</span>
          Antwort der KI einfügen
        </h2>
        <p className="muted">
          Füge die vollständige Antwort ein. Code-Blöcke und Begleittext stören nicht —
          das JSON wird automatisch herausgelesen.
        </p>

        <textarea
          className="paste-area"
          value={props.raw}
          placeholder='{"schema_version": "1.0", "plan": { … }}'
          onChange={(e) => props.onRaw(e.target.value)}
        />

        <div className="row mt-1">
          <button
            className="btn btn-secondary"
            onClick={props.onCheck}
            disabled={!props.raw.trim() || props.busy}
          >
            Erst prüfen
          </button>
          <button
            className="btn btn-primary"
            onClick={props.onImport}
            disabled={!props.raw.trim() || props.busy}
          >
            {props.busy ? 'Wird übernommen …' : 'Plan übernehmen'}
          </button>
        </div>

        {props.preview && (
          <div className="mt-2">
            {props.preview.warnings.length > 0 ? (
              <Alert kind="warning">
                Der Block ist lesbar, aber unvollständig:
                <ul>
                  {props.preview.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </Alert>
            ) : (
              <Alert kind="success">
                Der Block ist vollständig und kann übernommen werden.
              </Alert>
            )}

            <div className="card">
              <h3>{props.preview.plan.title}</h3>
              {props.preview.plan.summary && (
                <p className="muted">{props.preview.plan.summary}</p>
              )}
              <div className="row small muted">
                <span>
                  {new Date(props.preview.plan.start_date).toLocaleDateString('de-DE')} –{' '}
                  {new Date(props.preview.plan.end_date).toLocaleDateString('de-DE')}
                </span>
                <span>·</span>
                <span>{props.preview.plan.sessions.length} Einheiten</span>
                <span>·</span>
                <span>
                  {new Set(props.preview.plan.sessions.map((s) => s.date)).size} Tage
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  )

  if (props.aufgeklappt) return inhalt

  return (
    <details className="card">
      <summary style={{ cursor: 'pointer' }}>
        Stattdessen von Hand: Text kopieren und Antwort einfügen
      </summary>
      <p className="small muted mt-1">
        Der Weg über die Zwischenablage bleibt — für den Fall, dass der Zugang
        abgelaufen ist, das Kontingent aufgebraucht, oder du eine andere KI benutzen
        willst.
      </p>
      {inhalt}
    </details>
  )
}

/** Was beim Neuplanen mitten im Block passiert — bevor es passiert.
 *
 * Der Nutzer sieht sonst erst nach dem Übernehmen, dass sein laufender Block
 * verschwunden ist: Er wird stillgelegt und, wenn nie eine Einheit daran
 * erfasst wurde, weggeräumt.
 */
function ErsatzHinweis({ block, start }: { block: ErsetzterBlock; start: string }) {
  const tage = block.verworfene_tage.length
  const einheiten = block.verworfene_einheiten.length

  return (
    <Alert kind="warning">
      Dieser Block löst „{block.titel}“ ab. Ab dem{' '}
      {new Date(start).toLocaleDateString('de-DE')} entfallen dort {tage}{' '}
      {tage === 1 ? 'Tag' : 'Tage'} mit {einheiten}{' '}
      {einheiten === 1 ? 'Einheit' : 'Einheiten'} — die KI bekommt sie als Kontext
      mitgeschickt, ist aber nicht daran gebunden.
      <p className="small mb-0 mt-1">
        Erfasste Trainings bleiben im Verlauf. Bereits nach Garmin übertragene
        Einheiten dieser Tage nimmt die App aus dem Kalender, sobald der neue Block
        dort ankommt — bei verbundenem Konto also gleich nach dem Übernehmen.
      </p>
    </Alert>
  )
}
