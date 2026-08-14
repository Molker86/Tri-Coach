import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { Alert, Field, Loading } from '../components/ui'
import { PLAN_TAGE, heuteIso } from '../planung'
import type { AiExport, ErsetzterBlock, PlanImportResult } from '../types'

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

  useEffect(() => {
    setExported(null)
    api
      .exportForAi(requestId, startDate, days)
      .then(setExported)
      .catch((err) => setError(err.message))
  }, [requestId, startDate, days])

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

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Nächste Trainingstage von der KI planen lassen</h1>
          <p>
            Zwei Schritte: Text kopieren und an eine KI schicken, Antwort hier wieder
            einfügen.
          </p>
        </div>
      </div>

      {error && <Alert kind="error">{error}</Alert>}

      {ersetzt && <ErsatzHinweis block={ersetzt} start={startDate} />}

      <div className="card">
        <div className="card-title">
          <h2>
            <span className="step-marker">1</span>
            Datenpaket kopieren
          </h2>
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
                <select
                  value={days}
                  onChange={(e) => setDays(Number(e.target.value))}
                >
                  {DAY_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option} Tage
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          </div>
        </div>

        <p className="muted">
          Geplant wird nur der nächste kurze Block — das trifft die Realität besser als
          ein Vier-Wochen-Plan und ist für die KI die leichtere Aufgabe. Als Grundlage
          gehen trotzdem die vollen letzten vier Wochen mit: Profildaten, Fragebogen,
          Herzfrequenzzonen, alle erfassten Trainings, Belastungsverhältnis und der
          Abstand zur letzten Einheit je Sportart.
        </p>

        {!exported ? (
          <Loading text="Datenpaket wird erstellt …" />
        ) : (
          <>
            <div className="row mb-1">
              <button className="btn btn-primary" onClick={copyPrompt}>
                {copied ? '✓ In die Zwischenablage kopiert' : 'Text kopieren'}
              </button>
              <button className="btn btn-secondary" onClick={downloadPrompt}>
                Als Datei herunterladen
              </button>
            </div>

            <details>
              <summary className="small muted" style={{ cursor: 'pointer' }}>
                Text anzeigen ({Math.round(exported.combined.length / 1024)} KB)
              </summary>
              <div className="code-box mt-1">{exported.combined}</div>
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
          value={raw}
          placeholder='{"schema_version": "1.0", "plan": { … }}'
          onChange={(e) => {
            setRaw(e.target.value)
            setPreview(null)
          }}
        />

        <div className="row mt-1">
          <button
            className="btn btn-secondary"
            onClick={checkPlan}
            disabled={!raw.trim() || busy}
          >
            Erst prüfen
          </button>
          <button
            className="btn btn-primary"
            onClick={importPlan}
            disabled={!raw.trim() || busy}
          >
            {busy ? 'Wird übernommen …' : 'Plan übernehmen'}
          </button>
        </div>

        {preview && (
          <div className="mt-2">
            {preview.warnings.length > 0 ? (
              <Alert kind="warning">
                Der Block ist lesbar, aber unvollständig:
                <ul>
                  {preview.warnings.map((warning) => (
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
              <h3>{preview.plan.title}</h3>
              {preview.plan.summary && <p className="muted">{preview.plan.summary}</p>}
              <div className="row small muted">
                <span>
                  {new Date(preview.plan.start_date).toLocaleDateString('de-DE')} –{' '}
                  {new Date(preview.plan.end_date).toLocaleDateString('de-DE')}
                </span>
                <span>·</span>
                <span>{preview.plan.sessions.length} Einheiten</span>
                <span>·</span>
                <span>
                  {new Set(preview.plan.sessions.map((s) => s.date)).size} Tage
                </span>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="card">
        <h3>Hinweis zum Datenschutz</h3>
        <p className="small muted mb-0">
          Das Datenpaket enthält Gesundheitsdaten wie Ruhepuls, Gewicht und Angaben zu
          Verletzungen. Was du in eine KI kopierst, verlässt deinen Rechner und
          unterliegt den Bedingungen des jeweiligen Anbieters. Prüfe vorher, ob du
          damit einverstanden bist.
        </p>
      </div>
    </>
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
