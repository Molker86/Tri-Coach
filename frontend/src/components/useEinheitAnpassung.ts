/**
 * Die Maschinerie hinter einer Einzelanpassung — ein Lauf, der Minuten dauert.
 *
 * Sie steht bewusst **nicht** im Dialog: Wer ihn zwischendurch schließt, soll
 * trotzdem sehen, dass im Server gerade etwas passiert — und am Ende, was dabei
 * herauskam. Die Begründung der KI ist die einzige Stelle, an der der Athlet
 * erfährt, ob sie seinem Wunsch gefolgt ist.
 *
 * Als Hook und nicht als zweite Fassung in jeder Seite: Trainingsplan und
 * Startseite bieten dieselbe Anpassung an, und zwei Kopien der
 * Abfrageschleife liefen beim nächsten Zustand des Laufs auseinander.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, jobLaeuft, pollJob } from '../api/client'
import type { KiJob, KiStatus } from '../types'

export interface EinheitAnpassung {
  /** Ohne Claude-Zugang bleibt nur der Weg über die Zwischenablage. */
  kiVerfuegbar: boolean
  /** Der laufende oder zuletzt beendete Lauf — `null`, solange keiner war. */
  anpassung: KiJob | null
  laeuft: boolean
  beobachte: (job: KiJob) => void
  abbrechen: () => void
  vergiss: () => void
}

/**
 * @param onFertig Wird gerufen, sobald ein Lauf endet. Die Einheit steht danach
 *   in neuer Fassung im Plan, und der Server hat sie schon auf die Uhr gelegt —
 *   die Seite muss also nachladen. Über eine Referenz gehalten, damit ein bei
 *   jedem Rendern neu gebautes `reload` die Schleife nicht neu startet.
 * @param onFehler Netz- oder Serverfehler der Abfrageschleife.
 */
export function useEinheitAnpassung(
  onFertig: () => void,
  onFehler?: (meldung: string) => void,
): EinheitAnpassung {
  const [kiStatus, setKiStatus] = useState<KiStatus | null>(null)
  const [anpassung, setAnpassung] = useState<KiJob | null>(null)
  const abbrechenRef = useRef<(() => void) | null>(null)

  const fertigRef = useRef(onFertig)
  const fehlerRef = useRef(onFehler)
  useEffect(() => {
    fertigRef.current = onFertig
    fehlerRef.current = onFehler
  })

  const beobachte = useCallback((job: KiJob) => {
    setAnpassung(job)
    abbrechenRef.current?.()
    if (!jobLaeuft(job)) return
    abbrechenRef.current = pollJob(
      job.id,
      api.kiJob,
      (aktualisiert) => {
        setAnpassung(aktualisiert)
        if (!jobLaeuft(aktualisiert)) fertigRef.current()
      },
      (meldung) => fehlerRef.current?.(meldung),
    )
  }, [])

  useEffect(() => {
    // Auch ein Lauf, der vor dem Neuladen der Seite angestoßen wurde, soll hier
    // sichtbar werden — sonst stünde die Seite still, während im Server gerade
    // eine Einheit umgeschrieben wird.
    api
      .kiStatus()
      .then((status) => {
        setKiStatus(status)
        if (status.aktiver_job?.kind === 'einheit') beobachte(status.aktiver_job)
      })
      .catch(() => setKiStatus(null))
    return () => abbrechenRef.current?.()
  }, [beobachte])

  const abbrechen = useCallback(() => {
    if (anpassung) void api.kiAbbrechen(anpassung.id).catch(() => undefined)
  }, [anpassung])

  return {
    kiVerfuegbar: kiStatus?.verfuegbar === true,
    anpassung,
    laeuft: jobLaeuft(anpassung),
    beobachte,
    abbrechen,
    vergiss: useCallback(() => setAnpassung(null), []),
  }
}
