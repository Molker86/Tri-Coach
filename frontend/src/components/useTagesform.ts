/**
 * Wie es um die Tagesanpassung von heute steht — und der Knopf dazu.
 *
 * **Ein zweiter Hook neben `useEinheitAnpassung`, mit Absicht.** Der beobachtet
 * einen Lauf, den der Nutzer gerade selbst angestoßen hat, und dessen Karte er
 * anschließend wegklicken kann. Dieser beobachtet einen *Zustand des Tages*:
 * Er gilt, ob jemand hinsieht oder nicht, wird nicht weggeklickt, und er ist
 * auch dann eine Aussage, wenn gar nichts gelaufen ist. Beides in einen Hook zu
 * ziehen hieße, zwei verschiedene Fragen mit denselben Feldern zu beantworten.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, jobLaeuft, pollJob } from '../api/client'
import type { TagesformBefund } from '../types'

export interface Tagesform {
  befund: TagesformBefund | null
  laeuft: boolean
  /** Stößt die Prüfung von Hand an. Wirft die Fehlermeldung zum Anzeigen. */
  pruefeJetzt: () => Promise<void>
}

/**
 * @param onFertig Wird gerufen, sobald ein Lauf endet: Die Einheiten des Tages
 *   können danach in neuer Fassung dastehen, die Seite muss also nachladen.
 *   Über eine Referenz gehalten, damit ein bei jedem Rendern neu gebautes
 *   `reload` die Abfrageschleife nicht neu startet.
 * @param onFehler Netz- oder Serverfehler.
 */
export function useTagesform(
  onFertig: () => void,
  onFehler?: (meldung: string) => void,
): Tagesform {
  const [befund, setBefund] = useState<TagesformBefund | null>(null)
  const abbrechenRef = useRef<(() => void) | null>(null)

  const fertigRef = useRef(onFertig)
  const fehlerRef = useRef(onFehler)
  useEffect(() => {
    fertigRef.current = onFertig
    fehlerRef.current = onFehler
  })

  const beobachte = useCallback((jobId: number) => {
    abbrechenRef.current?.()
    abbrechenRef.current = pollJob(
      jobId,
      api.kiJob,
      (job) => {
        if (jobLaeuft(job)) return
        // **Erst den Befund neu holen, dann nachladen.** Der Job allein sagt
        // nicht, ob Claude überhaupt gefragt wurde — das entscheidet der
        // Endpunkt an `model_used`, und ohne diesen zweiten Griff stünde
        // „geprüft" an einem Lauf, der ohne Fitnessdaten abgebrochen ist.
        api
          .kiTagesform()
          .then(setBefund)
          .catch(() => undefined)
          .finally(() => fertigRef.current())
      },
      (meldung) => fehlerRef.current?.(meldung),
    )
  }, [])

  useEffect(() => {
    api
      .kiTagesform()
      .then((neu) => {
        setBefund(neu)
        // Auch ein Lauf, der vor dem Öffnen der Seite angestoßen wurde, soll
        // hier weiterlaufen — sonst stünde der Balken still, während im Server
        // gerade der Tag umgeschrieben wird.
        if (neu.stand === 'laeuft' && neu.job_id !== null) beobachte(neu.job_id)
      })
      .catch(() => setBefund(null))
    return () => abbrechenRef.current?.()
  }, [beobachte])

  const pruefeJetzt = useCallback(async () => {
    const job = await api.kiTagesformPruefen()
    setBefund((alt) =>
      alt === null
        ? alt
        : { ...alt, stand: 'laeuft', job_id: job.id, progress_pct: job.progress_pct },
    )
    beobachte(job.id)
  }, [beobachte])

  return { befund, laeuft: befund?.stand === 'laeuft', pruefeJetzt }
}
