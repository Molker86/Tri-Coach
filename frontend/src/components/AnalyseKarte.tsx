/**
 * Die Trainingsanalyse auf der Übersicht: Knopf, Fortschritt, Kurzfazit — und
 * der Weg über die Zwischenablage als Rückfallebene.
 *
 * Nur manuell — es gibt bewusst keinen Automatik-Zweig, jeder Lauf kostet
 * Kontingent, und das steht am Knopf. Nach dem Muster der `TagesformKarte`
 * mit der Abfrageschleife aus `pollJob`; anders als dort ist das Ergebnis
 * kein Tageszustand, sondern ein gespeicherter Bericht, der hier nur
 * angerissen wird (Kurzfazit) und im Verlauf liegen bleibt.
 *
 * Ohne Claude-Zugang ist der Knopf gesperrt statt versteckt — mit dem Grund
 * daneben — und der Handweg steht aufgeklappt: dieselbe Zweiteilung wie bei
 * der Einzelanpassung im `SessionDetail`.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, jobLaeuft, pollJob } from '../api/client'
import type { AiExport, Analyse, KiJob, KiStatus } from '../types'
import { AnalyseBericht, analyseZeitraum } from './AnalyseBericht'
import { Alert } from './ui'

const KEIN_ZUGANG =
  'Kein Claude-Zugang hinterlegt — trage unter Einstellungen → KI-Planung ein ' +
  'Token ein, oder nutze den Weg über die Zwischenablage.'

export function AnalyseKarte() {
  const [tage, setTage] = useState(1)
  const [kiStatus, setKiStatus] = useState<KiStatus | null>(null)
  const [job, setJob] = useState<KiJob | null>(null)
  const [juengste, setJuengste] = useState<Analyse | null>(null)
  const [zeigeBericht, setZeigeBericht] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Der Weg über die Zwischenablage.
  const [exported, setExported] = useState<AiExport | null>(null)
  const [kopiert, setKopiert] = useState(false)
  const [raw, setRaw] = useState('')
  const [busy, setBusy] = useState(false)
  const abbrechenRef = useRef<(() => void) | null>(null)

  const ladeJuengste = useCallback(() => {
    api
      .listAnalysen()
      .then((liste) => setJuengste(liste[0] ?? null))
      .catch(() => undefined)
  }, [])

  const beobachte = useCallback(
    (neu: KiJob) => {
      setJob(neu)
      abbrechenRef.current?.()
      if (!jobLaeuft(neu)) return
      abbrechenRef.current = pollJob(
        neu.id,
        api.kiJob,
        (stand) => {
          setJob(stand)
          if (jobLaeuft(stand)) return
          // Gescheitert ist gescheitert — die Meldung des Jobs ist die
          // genaueste, die es gibt. Ein Abbruch ist dagegen eine Entscheidung
          // und kein Fehler; seine Meldung steht unten als stiller Satz.
          if (stand.state === 'failed') {
            setError(stand.message ?? stand.error ?? 'Der Lauf ist gescheitert.')
          }
          // Auch ein „done" ohne analyse_id neu laden schadet nicht — der
          // Leerer-Zeitraum-Ausstieg lässt die bisherige Analyse stehen.
          ladeJuengste()
        },
        // Aussetzer der Abfrageschleife selbst (Netz weg, Server neu
        // gestartet): ohne diesen Zweig stünde der Balken einfach still.
        (meldung) => setError(meldung),
      )
    },
    [ladeJuengste],
  )

  useEffect(() => {
    ladeJuengste()
    // Zugang und laufender Job in einem Griff: Auch ein Lauf, der vor dem
    // Neuladen der Seite angestoßen wurde, soll hier weiterticken.
    api
      .kiStatus()
      .then((status) => {
        setKiStatus(status)
        if (status.aktiver_job?.kind === 'analyse') beobachte(status.aktiver_job)
      })
      .catch(() => setKiStatus(null))
    return () => abbrechenRef.current?.()
  }, [beobachte, ladeJuengste])

  const kiVerfuegbar = kiStatus?.verfuegbar === true
  const laeuft = job !== null && jobLaeuft(job)

  function starte() {
    setError(null)
    setBusy(true)
    api
      .startAnalyse(tage)
      .then(beobachte)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setBusy(false))
  }

  function brichAb() {
    if (job) void api.kiAbbrechen(job.id).catch(() => undefined)
  }

  async function erzeugeText() {
    setError(null)
    setBusy(true)
    try {
      setExported(await api.analyseExport(tage))
      setKopiert(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function kopiere() {
    if (!exported) return
    try {
      await navigator.clipboard.writeText(exported.combined)
      setKopiert(true)
      setTimeout(() => setKopiert(false), 2000)
    } catch {
      setError('Kopieren fehlgeschlagen — bitte den Text unten von Hand kopieren.')
    }
  }

  async function uebernimm() {
    setError(null)
    setBusy(true)
    try {
      await api.importAnalyse(raw, tage, exported?.payload.aktivitaeten?.length)
      setRaw('')
      setExported(null)
      ladeJuengste()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  // Die beiden stillen Ausgänge eines beendeten Laufs: sauber zu Ende, aber
  // ohne Bericht (leerer Zeitraum) — oder vom Nutzer abgebrochen.
  const leerMeldung =
    job?.state === 'done' && job.analyse_id === null ? job.message : null
  const abgebrochen = job?.state === 'cancelled'

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
          <div className="row mt-1">
            <span className="small faint">
              {job?.progress_pct ?? 0}&nbsp;% — du kannst die Seite verlassen,
              der Lauf geht im Hintergrund weiter.
            </span>
            <button className="btn btn-ghost btn-sm" onClick={brichAb}>
              Abbrechen
            </button>
          </div>
        </>
      ) : (
        <>
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
              1 = nur heute, 7 = heute und die 6 Tage davor.
            </span>
            <button
              className="btn btn-primary btn-sm"
              onClick={starte}
              disabled={busy || !kiVerfuegbar}
              title={kiVerfuegbar ? undefined : KEIN_ZUGANG}
            >
              Auswerten
            </button>
          </div>
          <p className="small faint mb-0 mt-1">
            {kiVerfuegbar
              ? 'Kostet einen Lauf aus deinem Claude-Kontingent.'
              : KEIN_ZUGANG}
          </p>

          {abgebrochen && (
            <p className="small muted mb-0 mt-1">
              {job?.message ?? 'Der Lauf wurde abgebrochen.'}
            </p>
          )}
          {leerMeldung && <p className="small muted mb-0 mt-1">{leerMeldung}</p>}

          {/* Der Handweg — dieselbe Zweiteilung wie bei der Einzelanpassung:
              mit Zugang zugeklappt als Alternative, ohne Zugang aufgeklappt
              als einziger Weg. */}
          <details className="mt-1" open={!kiVerfuegbar}>
            <summary className="small muted" style={{ cursor: 'pointer' }}>
              {kiVerfuegbar
                ? 'Stattdessen von Hand: Text kopieren und Antwort einfügen'
                : 'Text kopieren und Antwort einfügen'}
            </summary>

            <div className="row mt-1">
              <button
                className="btn btn-secondary btn-sm"
                onClick={erzeugeText}
                disabled={busy}
              >
                {busy ? 'Wird geholt …' : 'Text erzeugen'}
              </button>
              {exported && (
                <button className="btn btn-secondary btn-sm" onClick={kopiere}>
                  {kopiert ? '✓ Kopiert' : 'Text kopieren'}
                </button>
              )}
              <span className="small faint">
                Holt die Original-Daten live von Garmin — das dauert ein paar
                Sekunden.
              </span>
            </div>

            {exported && (
              <details className="mt-1">
                <summary className="small muted" style={{ cursor: 'pointer' }}>
                  Text anzeigen ({Math.round(exported.combined.length / 1024)} KB)
                </summary>
                <div className="code-box mt-1">{exported.combined}</div>
              </details>
            )}

            <textarea
              className="paste-area mt-1"
              rows={4}
              value={raw}
              placeholder='{"kurzfazit": "…", "bericht_html": "…"}'
              onChange={(e) => setRaw(e.target.value)}
            />
            <button
              className="btn btn-primary btn-sm"
              onClick={uebernimm}
              disabled={!raw.trim() || busy}
            >
              {busy ? 'Wird übernommen …' : 'Analyse übernehmen'}
            </button>
          </details>
        </>
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
