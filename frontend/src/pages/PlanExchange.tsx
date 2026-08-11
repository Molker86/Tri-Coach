import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { Alert, Field, Loading } from '../components/ui'
import type { AiExport, PlanImportResult } from '../types'

/** Ein Block über wenige Tage beginnt normalerweise heute. */
function today(): string {
  return new Date().toISOString().slice(0, 10)
}

const DAY_OPTIONS = [2, 3, 4, 5, 6, 7]
const DEFAULT_DAYS = 7

export default function PlanExchange() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const requestId = params.get('request') ? Number(params.get('request')) : undefined
  const paramStart = params.get('start') || today()
  const paramDays = params.get('days') ? Number(params.get('days')) : DEFAULT_DAYS

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

  function downloadJson() {
    if (!exported) return
    const blob = new Blob([JSON.stringify(exported.payload, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `tri-coach-daten-${startDate}.json`
    link.click()
    URL.revokeObjectURL(url)
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
      navigate(`/plan/${result.plan.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import fehlgeschlagen.')
      setBusy(false)
    }
  }

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

      <div className="card">
        <div className="card-title">
          <h2>
            <span className="step-marker">1</span>
            Datenpaket kopieren
          </h2>
          <div className="row">
            <div style={{ minWidth: 170 }}>
              <Field label="Erster Tag">
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                />
              </Field>
            </div>
            <div style={{ minWidth: 130 }}>
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
              <button className="btn btn-secondary" onClick={downloadJson}>
                Nur JSON herunterladen
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
