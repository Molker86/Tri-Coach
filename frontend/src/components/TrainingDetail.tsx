/**
 * Der Dialog zu einem absolvierten Training — die Messwerte, und Löschen.
 *
 * Aus `History` herausgezogen, damit ihn die Übersicht genauso öffnen kann:
 * Die Vorschau der letzten drei Trainings soll sich dort **gleich** verhalten
 * wie die Liste im Verlauf. Das Gegenstück zu `SessionDetail`, das die
 * *geplante* Einheit zeigt.
 */

import { api } from '../api/client'
import { paceFormat } from '../constants'
import type { SessionLog } from '../types'
import { trainingTitel } from './AnalyseBericht'
import { Modal } from './ui'
import { GESCHAETZT, STATUS_LABEL } from './TrainingsTabelle'

/** Garmins Befinden in Worten. Die Zahl steht auf der Skala 0 bis 10, wie in
 *  Connect; die Uhr trifft mit ihren fünf Stufen 0, 2,5, 5, 7,5 und 10. */
function befindenText(wert: number): string {
  if (wert <= 1.2) return 'sehr schwach'
  if (wert <= 3.7) return 'schwach'
  if (wert <= 6.2) return 'normal'
  if (wert <= 8.7) return 'stark'
  return 'sehr stark'
}

export function TrainingDetail({
  log,
  onClose,
  onGeloescht,
  onFehler,
}: {
  log: SessionLog
  onClose: () => void
  /** Nach dem Löschen: Die Seite muss ihre Liste neu aufbauen. */
  onGeloescht: () => void
  onFehler: (meldung: string) => void
}) {
  async function loesche() {
    if (!confirm('Diesen Eintrag wirklich löschen?')) return
    try {
      await api.deleteLog(log.id)
      onGeloescht()
      onClose()
    } catch (err) {
      onFehler(err instanceof Error ? err.message : 'Löschen fehlgeschlagen.')
    }
  }

  return (
    <Modal title={trainingTitel(log)} onClose={onClose}>
      <div className="table-wrap">
        <table>
          <tbody>
            <DetailRow label="Status" value={STATUS_LABEL[log.status]} />
            <DetailRow label="Dauer" value={log.duration_min} unit="min" />
            <DetailRow label="Distanz" value={log.distance_km} unit="km" />
            <DetailRow
              label={paceFormat(log.sport).label}
              value={log.avg_pace}
              unit={paceFormat(log.sport).unit}
            />
            <DetailRow label="Durchschnittspuls" value={log.avg_hr} unit="bpm" />
            <DetailRow label="Maximalpuls" value={log.max_hr} unit="bpm" />
            <DetailRow label="Leistung" value={log.avg_power} unit="Watt" />
            {/* Nur ohne Messung: Die Schätzung kennt keinen Wind und steht
                deshalb nie neben einer gemessenen Leistung. */}
            {log.avg_power === null && log.leistung_geschaetzt && (
              <>
                <DetailRow
                  label="Leistung"
                  value={geschaetzt(log.leistung_geschaetzt.schnitt_w)}
                  unit="Watt"
                />
                <DetailRow
                  label="Normalisierte Leistung"
                  value={geschaetzt(log.leistung_geschaetzt.normalisiert_w)}
                  unit="Watt"
                />
                <DetailRow
                  label="Beste Minute"
                  value={geschaetzt(log.leistung_geschaetzt.beste_minute_w)}
                  unit="Watt"
                />
              </>
            )}
            <DetailRow label="Frequenz" value={log.avg_cadence} unit="1/min" />
            <DetailRow label="Höhenmeter" value={log.elevation_gain_m} unit="m" />
            <DetailRow label="Kalorien" value={log.calories} unit="kcal" />
            <DetailRow label="TRIMP" value={log.trimp} />
            <DetailRow
              label="Trainingslast (Garmin)"
              value={log.garmin_training_load}
            />
            <DetailRow
              label="Trainingseffekt aerob"
              value={log.garmin_aerobic_te}
              unit="/ 5"
            />
            <DetailRow
              label="Trainingseffekt anaerob"
              value={log.garmin_anaerobic_te}
              unit="/ 5"
            />
            <DetailRow
              label="Anstrengung (RPE)"
              value={
                log.rpe === null
                  ? null
                  : GESCHAETZT.has(log.rpe_source)
                    ? `~${log.rpe} (geschätzt)`
                    : String(log.rpe)
              }
              unit="/ 10"
            />
            {/* Befinden und Anstrengung trägt der Athlet in Garmin Connect
                ein — meist gar nicht. Dann fehlt die Zeile, statt eine
                Bewertung zu behaupten. Schlaf und Morgenpuls stehen je Tag
                in der Fitnessdaten-Ansicht. */}
            {log.garmin_feel !== null && (
              <DetailRow
                label="Befinden"
                value={`${log.garmin_feel.toLocaleString('de-DE')} (${befindenText(
                  log.garmin_feel,
                )})`}
                unit="/ 10"
              />
            )}
            <DetailRow label="Notizen" value={log.notes} />
          </tbody>
        </table>
      </div>

      <div className="row row-end mt-2">
        <button className="btn btn-danger" onClick={loesche}>
          Eintrag löschen
        </button>
      </div>
    </Modal>
  )
}

function geschaetzt(watt: number | null): string | null {
  return watt === null ? null : `~${watt} (geschätzt)`
}

function DetailRow({
  label,
  value,
  unit,
}: {
  label: string
  value: string | number | null
  unit?: string
}) {
  if (value === null || value === '') return null
  return (
    <tr>
      <th style={{ width: '45%' }}>{label}</th>
      <td>
        {value}
        {unit ? ` ${unit}` : ''}
      </td>
    </tr>
  )
}
