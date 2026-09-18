/**
 * Der Analysebericht der KI — als Modal, nach dem Muster von `SessionDetail`.
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
import { api } from '../api/client'
import type { Analyse, AnalyseDetail } from '../types'
import { Alert, Loading, Modal } from './ui'

/**
 * Struktur-HTML und Inline-SVG bleiben, alles Aktive fliegt.
 *
 * `USE_PROFILES` lässt Script und Event-Handler gar nicht erst zu. Darüber
 * hinaus fallen alle Wege zu externen Ressourcen: Verweise, Bilder, Medien und
 * `use` (das per `href` nachladen könnte) — der Prompt verbietet sie, aber die
 * Antwort eines Sprachmodells ist keine Zusicherung. `ALLOWED_URI_REGEXP`
 * lässt nur Anker innerhalb des Dokuments übrig, damit auch ein Attribut, das
 * eine URL trägt, nirgendwohin zeigen kann. Das `style`-Attribut bleibt
 * erlaubt: Darüber kommen die Farben aus den CSS-Variablen der App.
 */
function bereinige(html: string): string {
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true, svg: true },
    FORBID_TAGS: ['a', 'img', 'audio', 'video', 'link', 'style', 'form', 'input', 'use'],
    ALLOWED_URI_REGEXP: /^#/,
  })
}

export function analyseZeitraum(analyse: Analyse): string {
  const von = new Date(analyse.zeitraum_von).toLocaleDateString('de-DE', {
    day: '2-digit',
    month: '2-digit',
  })
  const bis = new Date(analyse.zeitraum_bis).toLocaleDateString('de-DE', {
    day: '2-digit',
    month: '2-digit',
  })
  return von === bis ? von : `${von} – ${bis}`
}

export function AnalyseBericht({
  analyse,
  onClose,
  onGeloescht,
}: {
  analyse: Analyse
  onClose: () => void
  /** Ohne Rückruf gibt es keinen Löschknopf — die Karte auf der Übersicht
   *  zeigt nur an, gelöscht wird im Verlauf. */
  onGeloescht?: () => void
}) {
  const [detail, setDetail] = useState<AnalyseDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Der Bericht kommt erst hier: Die Liste liefert ihn bewusst nicht mit,
  // er kann beliebig groß sein.
  useEffect(() => {
    api.getAnalyse(analyse.id).then(setDetail).catch((err) => setError(err.message))
  }, [analyse.id])

  async function loesche() {
    if (!confirm('Diese Analyse wirklich löschen?')) return
    try {
      await api.deleteAnalyse(analyse.id)
      onGeloescht?.()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Löschen fehlgeschlagen.')
    }
  }

  return (
    <Modal title={`Trainingsanalyse ${analyseZeitraum(analyse)}`} onClose={onClose}>
      {error && <Alert kind="error">{error}</Alert>}
      {!detail && !error && <Loading text="Bericht wird geladen …" />}
      {detail && (
        <div
          className="analyse-bericht"
          dangerouslySetInnerHTML={{ __html: bereinige(detail.bericht_html) }}
        />
      )}
      <div className="row row-end mt-2">
        <span className="small faint">
          {analyse.aktivitaeten_anzahl}{' '}
          {analyse.aktivitaeten_anzahl === 1 ? 'Aktivität' : 'Aktivitäten'}
          {analyse.model_used ? ` · ${analyse.model_used}` : ''}
        </span>
        {onGeloescht && (
          <button className="btn btn-danger" onClick={loesche}>
            Analyse löschen
          </button>
        )}
      </div>
    </Modal>
  )
}
