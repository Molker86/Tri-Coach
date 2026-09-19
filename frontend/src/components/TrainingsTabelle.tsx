/**
 * Die Liste absolvierter Trainings — im Verlauf und auf der Übersicht dieselbe.
 *
 * Zwei Knöpfe je Zeile: „Details" öffnet die Messwerte, der zweite die
 * KI-Analyse zu **genau diesem** Training — je nachdem, ob es schon eine gibt,
 * als Bericht oder als Knopf, der ihn schreiben lässt. Die Zeile sagt vorher,
 * was sie sein wird: Ohne Bericht steht dort „Auswerten", mit Bericht sein
 * Kurzfazit.
 *
 * Eine Komponente für beide Seiten, weil der Verlauf und die Vorschau auf der
 * Startseite sich **gleich** verhalten sollen — sie unterscheiden sich nur
 * darin, wie viele Zeilen sie zeigen.
 */

import { sportIcon, sportLabel } from '../constants'
import type { Analyse, SessionLog } from '../types'

export const STATUS_LABEL: Record<SessionLog['status'], string> = {
  completed: 'Absolviert',
  partial: 'Teilweise',
  skipped: 'Ausgefallen',
}

/** Woher ein RPE stammt — als Erklärung beim Überfahren. */
export const RPE_QUELLE_TEXT: Record<string, string> = {
  athlet: 'Vom Athleten in Garmin Connect bewertet',
  hf_zonen: 'Aus der Zeitverteilung über die Herzfrequenzzonen geschätzt',
  trainingseffekt: 'Aus Garmins Trainingseffekt geschätzt',
  hf_schnitt: 'Aus dem Durchschnittspuls geschätzt',
}

/** Nur diese Quellen sind Schätzungen — sie bekommen die Tilde. */
export const GESCHAETZT = new Set(['hf_zonen', 'trainingseffekt', 'hf_schnitt'])

export function TrainingsTabelle({
  logs,
  analysen,
  laeuftFuer,
  onDetails,
  onAnalyse,
}: {
  logs: SessionLog[]
  /** Analyse je Training, über `session_log_id` — aus `useAnalysen`. */
  analysen: Map<number, Analyse>
  /** Welches Training gerade bewertet wird; `null`, wenn nichts läuft. */
  laeuftFuer: number | null
  onDetails: (log: SessionLog) => void
  onAnalyse: (log: SessionLog) => void
}) {
  return (
    <div className="table-wrap">
      <table className="table-cards">
        <thead>
          <tr>
            <th>Datum</th>
            <th>Sportart</th>
            <th>Dauer</th>
            <th>Distanz</th>
            <th>Ø Puls</th>
            <th>RPE</th>
            <th>Analyse</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {logs.map((log) => {
            const analyse = analysen.get(log.id) ?? null
            const laeuft = laeuftFuer === log.id
            return (
              <tr key={log.id}>
                <td className="nowrap" data-label="Datum">
                  {new Date(log.date).toLocaleDateString('de-DE', {
                    weekday: 'short',
                    day: '2-digit',
                    month: '2-digit',
                  })}
                </td>
                <td className="nowrap cell-title">
                  {sportIcon(log.sport)} {sportLabel(log.sport)}
                  {log.status !== 'completed' && (
                    <> <span className="badge">{STATUS_LABEL[log.status]}</span></>
                  )}
                  {log.source === 'garmin' && (
                    <> <span className="badge badge-accent">Garmin</span></>
                  )}
                </td>
                <td data-label="Dauer">
                  {log.duration_min ? `${log.duration_min} min` : '–'}
                </td>
                <td data-label="Distanz">
                  {log.distance_km ? `${log.distance_km} km` : '–'}
                </td>
                <td data-label="Ø Puls">{log.avg_hr ?? '–'}</td>
                <td data-label="RPE">
                  {log.rpe === null ? (
                    '–'
                  ) : GESCHAETZT.has(log.rpe_source) ? (
                    // Die Tilde macht sichtbar, dass die Zahl geschätzt ist —
                    // sie geht in sRPE-Last und Belastungsverhältnis ein.
                    <span title={RPE_QUELLE_TEXT[log.rpe_source] ?? 'Geschätzt'}>
                      ~{log.rpe}
                    </span>
                  ) : (
                    <span title={RPE_QUELLE_TEXT[log.rpe_source]}>{log.rpe}</span>
                  )}
                </td>
                {/* Der Vermerk, worum es bei dieser Rubrik geht: Man sieht auf
                    einen Blick, welche Einheiten noch nie bewertet wurden. */}
                <td data-label="Analyse" className="cell-fazit">
                  {laeuft ? (
                    <span className="badge badge-accent">Läuft …</span>
                  ) : analyse ? (
                    <span className="fazit small" title={analyse.kurzfazit}>
                      {analyse.kurzfazit}
                    </span>
                  ) : (
                    <span className="small faint">Noch nicht bewertet</span>
                  )}
                </td>
                <td className="nowrap cell-actions">
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => onDetails(log)}
                  >
                    Details
                  </button>
                  <button
                    className={`btn btn-sm ${analyse ? 'btn-ghost' : 'btn-secondary'}`}
                    onClick={() => onAnalyse(log)}
                  >
                    {laeuft ? 'Fortschritt' : analyse ? 'Bericht' : 'Auswerten'}
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
