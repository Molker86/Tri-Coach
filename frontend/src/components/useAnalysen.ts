/**
 * Die Maschinerie hinter den Trainingsanalysen — für Verlauf und Übersicht.
 *
 * Beide Seiten zeigen dieselbe Liste absolvierter Trainings, nur unterschiedlich
 * lang: der Verlauf alle, die Übersicht die letzten drei. Auslösen, Fortschritt,
 * Ablage und Anzeige sollen sich dabei **gleich** verhalten — also steht das
 * alles hier und nicht zweimal in zwei Seiten. Vorbild ist
 * `useEinheitAnpassung`; der Unterschied ist, dass ein Lauf hier zu genau einer
 * Zeile gehört (`session_log_id`) und die fertigen Berichte als Zuordnung
 * Training → Analyse zurückkommen.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, jobLaeuft, pollJob } from '../api/client'
import type { Analyse, KiJob, KiStatus } from '../types'

export const KEIN_ZUGANG =
  'Kein Claude-Zugang hinterlegt — trage unter Einstellungen → KI-Planung ein ' +
  'Token ein, oder nutze den Weg über die Zwischenablage.'

export interface AnalysenLauf {
  /** Analyse je Training, über `session_log_id`. */
  proTraining: Map<number, Analyse>
  /** Ohne Claude-Zugang bleibt nur der Weg über die Zwischenablage. */
  kiVerfuegbar: boolean
  /** Der laufende oder zuletzt beendete Lauf — `null`, solange keiner war. */
  job: KiJob | null
  /** Welches Training gerade bewertet wird; `null`, wenn nichts läuft. */
  laeuftFuer: number | null
  fehler: string | null
  setFehler: (meldung: string | null) => void
  /** Stößt einen Lauf an und beobachtet ihn. */
  starte: (sessionLogId: number) => Promise<void>
  abbrechen: () => void
  /** Nach einem Handweg-Import oder einem Löschen: Zuordnung neu holen. */
  neuLaden: () => void
}

export function useAnalysen(): AnalysenLauf {
  const [proTraining, setProTraining] = useState<Map<number, Analyse>>(new Map())
  const [kiStatus, setKiStatus] = useState<KiStatus | null>(null)
  const [job, setJob] = useState<KiJob | null>(null)
  const [fehler, setFehler] = useState<string | null>(null)
  const abbrechenRef = useRef<(() => void) | null>(null)

  const neuLaden = useCallback(() => {
    api
      .listAnalysen()
      .then((liste) =>
        setProTraining(new Map(liste.map((a) => [a.session_log_id, a]))),
      )
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
          // und kein Fehler; er steht am Dialog als stiller Satz.
          if (stand.state === 'failed') {
            setFehler(stand.message ?? stand.error ?? 'Der Lauf ist gescheitert.')
          }
          neuLaden()
        },
        // Aussetzer der Abfrageschleife selbst (Netz weg, Server neu
        // gestartet): ohne diesen Zweig stünde der Balken einfach still.
        (meldung) => setFehler(meldung),
      )
    },
    [neuLaden],
  )

  useEffect(() => {
    neuLaden()
    // Zugang und laufender Job in einem Griff: Auch ein Lauf, der vor dem
    // Neuladen der Seite angestoßen wurde, soll hier weiterticken — und an
    // seiner Zeile, denn `session_log_id` steht am Job.
    api
      .kiStatus()
      .then((status) => {
        setKiStatus(status)
        if (status.aktiver_job?.kind === 'analyse') beobachte(status.aktiver_job)
      })
      .catch(() => setKiStatus(null))
    return () => abbrechenRef.current?.()
  }, [beobachte, neuLaden])

  const starte = useCallback(
    async (sessionLogId: number) => {
      setFehler(null)
      try {
        beobachte(await api.startAnalyse(sessionLogId))
      } catch (err) {
        setFehler(err instanceof Error ? err.message : String(err))
      }
    },
    [beobachte],
  )

  return {
    proTraining,
    kiVerfuegbar: kiStatus?.verfuegbar === true,
    job,
    laeuftFuer: job && jobLaeuft(job) ? job.session_log_id : null,
    fehler,
    setFehler,
    starte,
    abbrechen: useCallback(() => {
      if (job) void api.kiAbbrechen(job.id).catch(() => undefined)
    }, [job]),
    neuLaden,
  }
}
