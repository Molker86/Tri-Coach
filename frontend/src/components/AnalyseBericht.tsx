/**
 * Der Analysebericht der KI — als Modal zu genau einem absolvierten Training.
 *
 * Ein Dialog für beide Lagen: Gibt es schon einen Bericht, steht er hier; gibt
 * es keinen, steht hier der Knopf, der ihn schreiben lässt — samt Weg über die
 * Zwischenablage. Zwei getrennte Bedienelemente („auswerten" an der einen
 * Stelle, „ansehen" an der anderen) hätten im Verlauf und auf der Übersicht
 * jeweils anders ausgesehen; so ist es ein Knopf je Zeile, und der Dialog
 * zeigt, was gerade dran ist.
 *
 * Der Bericht ist HTML aus einem Sprachmodell und wird **beim Rendern**
 * bereinigt, nicht beim Speichern: Gespeichert wird die Antwort unverändert
 * (dieselbe Philosophie wie `roh_antwort`), und die Regeln, was ein Browser
 * gefahrlos darf, gehören dorthin, wo der Browser ist. Bereinigt wird mit
 * DOMPurify statt mit einem Eigenbau — ein selbstgeschriebener HTML-Sanitizer
 * ist ein bekanntes Sicherheits-Antimuster.
 */

import DOMPurify from 'dompurify'
import { useEffect, useState } from 'react'
import { api, jobLaeuft } from '../api/client'
import { sportIcon, sportLabel } from '../constants'
import type { AiExport, Analyse, AnalyseDetail, SessionLog } from '../types'
import { Alert, Loading, Modal } from './ui'
import { KEIN_ZUGANG, type AnalysenLauf } from './useAnalysen'

/**
 * Ein Attributwert, der etwas von außen nachladen könnte: jedes `url()`, das
 * nicht auf eine Definition im selben SVG zeigt (`url(#verlauf)` bleibt),
 * `image-set()`, das auch eine blanke Zeichenkette als Adresse nimmt, und
 * jeder CSS-Escape — `\75rl(` liest der Browser als `url(`.
 */
const NACH_AUSSEN = /url\((?!\s*['"]?\s*#)|image-set\(|\\/i

// Eigene Instanz, damit der Hook nur hier greift und nicht an jedem
// anderen Aufruf von DOMPurify in der App.
const purify = DOMPurify()

// Nicht über `ALLOWED_URI_REGEXP: /^#/`, obwohl das kürzer aussieht: DOMPurify
// prüft damit nicht nur Attribute, die eine URL tragen, sondern jeden Wert
// außerhalb einer kurzen Liste (`class`, `id`, `style` …). Jedes SVG verlor so
// `viewBox`, `x`, `y`, `fill` und `points` und zerfiel zu übereinander
// gedrucktem schwarzem Text in der Ecke.
purify.addHook('uponSanitizeAttribute', (_node, data) => {
  const verweis = data.attrName === 'href' || data.attrName === 'xlink:href'
  if (verweis ? !data.attrValue.trim().startsWith('#') : NACH_AUSSEN.test(data.attrValue)) {
    data.keepAttr = false
  }
})

/**
 * Struktur-HTML und Inline-SVG bleiben, alles Aktive fliegt.
 *
 * `USE_PROFILES` lässt Script und Event-Handler gar nicht erst zu. Darüber
 * hinaus fallen alle Wege zu externen Ressourcen: Verweise, Bilder (auch das
 * SVG-`image`), Medien und `use` — der Prompt verbietet sie, aber die Antwort
 * eines Sprachmodells ist keine Zusicherung. Der Hook oben lässt `href` nur
 * als Anker im Dokument und `url()` nur als Verweis ins selbe SVG übrig. Das
 * `style`-Attribut bleibt erlaubt: Darüber kommen die Farben aus den
 * CSS-Variablen der App.
 */
function bereinige(html: string): string {
  return purify.sanitize(html, {
    USE_PROFILES: { html: true, svg: true },
    FORBID_TAGS: [
      'a', 'img', 'image', 'audio', 'video', 'link', 'style', 'form', 'input', 'use',
    ],
  })
}

/** Die Überschrift des Dialogs: welches Training hier bewertet wird. */
export function trainingTitel(log: SessionLog): string {
  const tag = new Date(log.date).toLocaleDateString('de-DE', {
    weekday: 'short',
    day: '2-digit',
    month: '2-digit',
  })
  return `${sportLabel(log.sport)} am ${tag}`
}

export function AnalyseBericht({
  log,
  analyse,
  lauf,
  onClose,
}: {
  log: SessionLog
  /** Der gespeicherte Bericht — `null`, solange das Training keinen hat. */
  analyse: Analyse | null
  lauf: AnalysenLauf
  onClose: () => void
}) {
  const laeuft = lauf.laeuftFuer === log.id
  return (
    <Modal
      title={`Trainingsanalyse — ${trainingTitel(log)}`}
      onClose={onClose}
    >
      {lauf.fehler && <Alert kind="error">{lauf.fehler}</Alert>}

      {laeuft ? (
        <Fortschritt lauf={lauf} />
      ) : analyse ? (
        <Bericht log={log} analyse={analyse} lauf={lauf} onClose={onClose} />
      ) : (
        <Ausloesen log={log} lauf={lauf} />
      )}
    </Modal>
  )
}

/** Der laufende Lauf. Gleicher Balken wie bei Planung und Einzelanpassung. */
function Fortschritt({ lauf }: { lauf: AnalysenLauf }) {
  const job = lauf.job
  return (
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
          {job?.progress_pct ?? 0}&nbsp;% — du kannst den Dialog schließen und
          die Seite verlassen, der Lauf geht im Hintergrund weiter.
        </span>
        <button className="btn btn-ghost btn-sm" onClick={lauf.abbrechen}>
          Abbrechen
        </button>
      </div>
    </>
  )
}

/** Der fertige Bericht — dazu neu auswerten und löschen. */
function Bericht({
  log,
  analyse,
  lauf,
  onClose,
}: {
  log: SessionLog
  analyse: Analyse
  lauf: AnalysenLauf
  onClose: () => void
}) {
  const [detail, setDetail] = useState<AnalyseDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Der Bericht kommt erst hier: Die Liste liefert ihn bewusst nicht mit,
  // er kann beliebig groß sein.
  useEffect(() => {
    setDetail(null)
    api.getAnalyse(analyse.id).then(setDetail).catch((err) => setError(err.message))
  }, [analyse.id])

  async function loesche() {
    if (!confirm('Diese Analyse wirklich löschen?')) return
    try {
      await api.deleteAnalyse(analyse.id)
      lauf.neuLaden()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Löschen fehlgeschlagen.')
    }
  }

  function neuAuswerten() {
    if (
      !confirm(
        'Das Training noch einmal bewerten lassen? Der bisherige Bericht wird ' +
          'dabei ersetzt.',
      )
    )
      return
    void lauf.starte(log.id)
  }

  return (
    <>
      {error && <Alert kind="error">{error}</Alert>}
      {!detail && !error && <Loading text="Bericht wird geladen …" />}
      {detail && (
        <div
          className="analyse-bericht"
          dangerouslySetInnerHTML={{ __html: bereinige(detail.bericht_html) }}
        />
      )}
      <hr className="divider" />
      <div className="row row-end">
        <span className="small faint">
          Analyse vom {new Date(analyse.created_at).toLocaleDateString('de-DE')}
          {analyse.model_used ? ` · ${analyse.model_used}` : ''}
        </span>
        <button
          className="btn btn-secondary btn-sm"
          onClick={neuAuswerten}
          disabled={!lauf.kiVerfuegbar || jobLaeuft(lauf.job)}
          title={lauf.kiVerfuegbar ? undefined : KEIN_ZUGANG}
        >
          Neu auswerten
        </button>
        <button className="btn btn-danger btn-sm" onClick={loesche}>
          Analyse löschen
        </button>
      </div>
    </>
  )
}

/** Noch kein Bericht: der Knopf — und der Weg über die Zwischenablage. */
function Ausloesen({ log, lauf }: { log: SessionLog; lauf: AnalysenLauf }) {
  const [exported, setExported] = useState<AiExport | null>(null)
  const [kopiert, setKopiert] = useState(false)
  const [raw, setRaw] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Ein Lauf je Konto — auch einer für ein anderes Training sperrt hier.
  const andererLauf = jobLaeuft(lauf.job)
  const abgebrochen = lauf.job?.state === 'cancelled'

  async function erzeugeText() {
    setError(null)
    setBusy(true)
    try {
      setExported(await api.analyseExport(log.id))
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
      await api.importAnalyse(raw, log.id)
      setRaw('')
      setExported(null)
      lauf.neuLaden()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {error && <Alert kind="error">{error}</Alert>}

      <p className="small muted">
        {sportIcon(log.sport)} Claude holt die Original-Aufzeichnung dieses
        Trainings von Garmin und bewertet sie kritisch — Ausführung gegen Plan,
        Pacing, Zonen, Belastung gegen Erholung.
      </p>

      <div className="row">
        <button
          className="btn btn-primary btn-sm"
          onClick={() => void lauf.starte(log.id)}
          disabled={!lauf.kiVerfuegbar || andererLauf}
          title={lauf.kiVerfuegbar ? undefined : KEIN_ZUGANG}
        >
          Auswerten
        </button>
        <span className="small faint">
          {lauf.kiVerfuegbar
            ? 'Kostet einen Lauf aus deinem Claude-Kontingent.'
            : KEIN_ZUGANG}
        </span>
      </div>
      {andererLauf && (
        <p className="small muted mb-0 mt-1">
          Es läuft gerade ein anderer Lauf gegen die KI — es geht immer nur einer
          auf einmal.
        </p>
      )}
      {abgebrochen && (
        <p className="small muted mb-0 mt-1">
          {lauf.job?.message ?? 'Der Lauf wurde abgebrochen.'}
        </p>
      )}

      {/* Der Handweg — dieselbe Zweiteilung wie bei der Einzelanpassung:
          mit Zugang zugeklappt als Alternative, ohne Zugang aufgeklappt
          als einziger Weg. */}
      <details className="mt-1" open={!lauf.kiVerfuegbar}>
        <summary className="small muted" style={{ cursor: 'pointer' }}>
          {lauf.kiVerfuegbar
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
  )
}
