/**
 * Die Trainingsanalyse auf der Übersicht: Knopf, Fortschritt, Kurzfazit.
 *
 * Nur manuell — es gibt bewusst keinen Automatik-Zweig, jeder Lauf kostet
 * Kontingent, und das steht am Knopf. Nach dem Muster der `TagesformKarte`
 * mit der Abfrageschleife aus `pollJob`; anders als dort ist das Ergebnis
 * kein Tageszustand, sondern ein gespeicherter Bericht, der hier nur
 * angerissen wird (Kurzfazit) und im Verlauf liegen bleibt.
 */

import { useEffect, useRef, useState } from 'react'
import { api, jobLaeuft, pollJob } from '../api/client'
import type { Analyse, KiJob } from '../types'
import { AnalyseBericht, analyseZeitraum } from './AnalyseBericht'
import { Alert } from './ui'

export function AnalyseKarte() {
  const [tage, setTage] = useState(1)
  const [job, setJob] = useState<KiJob | null>(null)
  const [juengste, setJuengste] = useState<Analyse | null>(null)
  const [zeigeBericht, setZeigeBericht] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abbrechenRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    api
      .listAnalysen()
      .then((liste) => setJuengste(liste[0] ?? null))
      .catch(() => setJuengste(null))
    return () => abbrechenRef.current?.()
  }, [])

  function starte() {
    setError(null)
    api
      .startAnalyse(tage)
      .then((neu) => {
        setJob(neu)
        abbrechenRef.current?.()
        abbrechenRef.current = pollJob(neu.id, api.kiJob, (stand) => {
          setJob(stand)
          if (jobLaeuft(stand)) return
          if (stand.state === 'failed') setError(stand.message ?? stand.error)
          // Auch ein „done" ohne analyse_id neu laden schadet nicht — der
          // Leerer-Zeitraum-Ausstieg lässt die bisherige Analyse stehen.
          api
            .listAnalysen()
            .then((liste) => setJuengste(liste[0] ?? null))
            .catch(() => undefined)
        })
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }

  const laeuft = job !== null && jobLaeuft(job)
  // Der Leerer-Zeitraum-Ausstieg: sauber zu Ende, aber ohne Bericht. Seine
  // Meldung ist die einzige Stelle, an der das steht.
  const leerMeldung =
    job?.state === 'done' && job.analyse_id === null ? job.message : null

  return (
    <div className="card">
      <div className="card-title">
        <h2>Trainingsanalyse</h2>
      </div>
      <p className="small muted">
        Claude holt die Original-Aufzeichnungen deiner Trainings von Garmin und
        bewertet sie kritisch — Ausführung gegen Plan, Pacing, Zonen, Belastung
        gegen Erholung.
      </p>

      {error && <Alert kind="error">{error}</Alert>}

      {laeuft ? (
        <>
          <p className="small mb-0">{job?.message ?? 'Die Analyse läuft …'}</p>
          <div className="wizard-progress mt-1">
            <div
              className="wizard-step-bar current"
              style={{ flexGrow: Math.max(1, job?.progress_pct ?? 0) }}
            />
            <div
              className="wizard-step-bar"
              style={{ flexGrow: Math.max(1, 100 - (job?.progress_pct ?? 0)) }}
            />
          </div>
          <span className="small faint">
            {job?.progress_pct ?? 0}&nbsp;% — du kannst die Seite verlassen, der
            Lauf geht im Hintergrund weiter.
          </span>
        </>
      ) : (
        <div className="row">
          <label className="row small" style={{ gap: '0.5rem' }}>
            Tage
            <input
              type="number"
              min={1}
              max={7}
              value={tage}
              style={{ width: '4.5rem' }}
              onChange={(e) =>
                setTage(Math.max(1, Math.min(7, Number(e.target.value) || 1)))
              }
            />
          </label>
          <span className="small faint">
            1 = nur heute, 7 = heute und die 6 Tage davor. Kostet einen Lauf aus
            deinem Claude-Kontingent.
          </span>
          <button className="btn btn-primary btn-sm" onClick={starte}>
            Auswerten
          </button>
        </div>
      )}

      {leerMeldung && !laeuft && (
        <p className="small muted mt-1 mb-0">{leerMeldung}</p>
      )}

      {juengste && (
        <>
          <hr className="divider" />
          <p className="small muted mb-0">
            Analyse vom{' '}
            {new Date(juengste.created_at).toLocaleDateString('de-DE')} (Zeitraum{' '}
            {analyseZeitraum(juengste)}):
          </p>
          <p className="mb-0">{juengste.kurzfazit}</p>
          <div className="row row-end mt-1">
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setZeigeBericht(true)}
            >
              Bericht ansehen
            </button>
          </div>
        </>
      )}

      {zeigeBericht && juengste && (
        <AnalyseBericht analyse={juengste} onClose={() => setZeigeBericht(false)} />
      )}
    </div>
  )
}
