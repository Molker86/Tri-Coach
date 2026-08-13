import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Alert, EmptyState, Loading, Modal } from '../components/ui'
import { paceFormat, sportIcon, sportLabel } from '../constants'
import type { SessionLog, WellnessDay } from '../types'

const STATUS_LABEL: Record<SessionLog['status'], string> = {
  completed: 'Absolviert',
  partial: 'Teilweise',
  skipped: 'Ausgefallen',
}

/** Woher ein geschätztes RPE stammt — als Erklärung beim Überfahren. */
const RPE_QUELLE_TEXT: Record<string, string> = {
  hf_zonen: 'Aus der Zeitverteilung über die Herzfrequenzzonen geschätzt',
  trainingseffekt: 'Aus Garmins Trainingseffekt geschätzt',
  hf_schnitt: 'Aus dem Durchschnittspuls geschätzt',
}

export default function History() {
  const [logs, setLogs] = useState<SessionLog[] | null>(null)
  const [wellness, setWellness] = useState<WellnessDay[]>([])
  const [ansicht, setAnsicht] = useState<'trainings' | 'fitness'>('trainings')
  const [weeks, setWeeks] = useState(4)
  const [selected, setSelected] = useState<SessionLog | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLogs(null)
    api.listLogs(weeks).then(setLogs).catch((err) => setError(err.message))
    // Ohne verbundenes Garmin-Konto bleibt die Liste leer, und der Umschalter
    // erscheint gar nicht erst.
    api.garminWellness(weeks).then(setWellness).catch(() => setWellness([]))
  }, [weeks])

  async function remove(log: SessionLog) {
    if (!confirm('Diesen Eintrag wirklich löschen?')) return
    try {
      await api.deleteLog(log.id)
      setLogs((current) => current?.filter((l) => l.id !== log.id) ?? null)
      setSelected(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Löschen fehlgeschlagen.')
    }
  }

  if (error) return <Alert kind="error">{error}</Alert>
  if (!logs) return <Loading />

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Trainingsverlauf</h1>
          <p>
            Die letzten vier Wochen gehen automatisch in die Erstellung des nächsten
            Plans ein.
          </p>
        </div>
        <div className="row">
          {wellness.length > 0 && (
            <div className="chip-group">
              <button
                className={`chip${ansicht === 'trainings' ? ' selected' : ''}`}
                onClick={() => setAnsicht('trainings')}
              >
                Trainings
              </button>
              <button
                className={`chip${ansicht === 'fitness' ? ' selected' : ''}`}
                onClick={() => setAnsicht('fitness')}
              >
                Fitnessdaten
              </button>
            </div>
          )}
          <select value={weeks} onChange={(e) => setWeeks(Number(e.target.value))}>
            <option value={4}>Letzte 4 Wochen</option>
            <option value={12}>Letzte 12 Wochen</option>
            <option value={52}>Letztes Jahr</option>
          </select>
          <Link className="btn btn-secondary" to="/training-nachtragen">
            Nachtragen
          </Link>
          <Link className="btn btn-primary" to="/training-erfassen">
            Training erfassen
          </Link>
        </div>
      </div>

      {ansicht === 'fitness' ? (
        <FitnessTabelle tage={wellness} />
      ) : logs.length === 0 ? (
        <EmptyState icon="📝" title="Noch keine Trainings erfasst">
          <p>
            Nach der ersten Einheit siehst du hier deinen Verlauf. Bereits absolvierte
            Trainings kannst du nachtragen — sie zählen in den letzten vier Wochen mit.
          </p>
          <div className="row row-center">
            <Link className="btn btn-secondary" to="/training-nachtragen">
              Training nachtragen
            </Link>
            <Link className="btn btn-primary" to="/training-erfassen">
              Erstes Training erfassen
            </Link>
          </div>
        </EmptyState>
      ) : (
        <div className="card">
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
                  <th>TRIMP</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
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
                      ) : log.rpe_source === 'manual' ? (
                        log.rpe
                      ) : (
                        // Die Tilde macht sichtbar, dass die Zahl geschätzt ist —
                        // sie geht in sRPE-Last und Belastungsverhältnis ein.
                        <span title={RPE_QUELLE_TEXT[log.rpe_source] ?? 'Geschätzt'}>
                          ~{log.rpe}
                        </span>
                      )}
                    </td>
                    <td data-label="TRIMP">{log.trimp ?? '–'}</td>
                    <td className="nowrap cell-actions">
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => setSelected(log)}
                      >
                        Details
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {selected && (
        <Modal
          title={`${sportLabel(selected.sport)} am ${new Date(
            selected.date,
          ).toLocaleDateString('de-DE')}`}
          onClose={() => setSelected(null)}
        >
          <div className="table-wrap">
            <table>
              <tbody>
                <DetailRow label="Status" value={STATUS_LABEL[selected.status]} />
                <DetailRow label="Dauer" value={selected.duration_min} unit="min" />
                <DetailRow label="Distanz" value={selected.distance_km} unit="km" />
                <DetailRow
                  label={paceFormat(selected.sport).label}
                  value={selected.avg_pace}
                  unit={paceFormat(selected.sport).unit}
                />
                <DetailRow label="Durchschnittspuls" value={selected.avg_hr} unit="bpm" />
                <DetailRow label="Maximalpuls" value={selected.max_hr} unit="bpm" />
                <DetailRow label="Leistung" value={selected.avg_power} unit="Watt" />
                <DetailRow label="Frequenz" value={selected.avg_cadence} unit="1/min" />
                <DetailRow label="Höhenmeter" value={selected.elevation_gain_m} unit="m" />
                <DetailRow label="Kalorien" value={selected.calories} unit="kcal" />
                <DetailRow label="TRIMP" value={selected.trimp} />
                <DetailRow
                  label="Trainingslast (Garmin)"
                  value={selected.garmin_training_load}
                />
                <DetailRow
                  label="Trainingseffekt aerob"
                  value={selected.garmin_aerobic_te}
                  unit="/ 5"
                />
                <DetailRow
                  label="Trainingseffekt anaerob"
                  value={selected.garmin_anaerobic_te}
                  unit="/ 5"
                />
                <DetailRow
                  label="Anstrengung (RPE)"
                  value={
                    selected.rpe === null
                      ? null
                      : selected.rpe_source === 'manual'
                        ? String(selected.rpe)
                        : `~${selected.rpe} (geschätzt)`
                  }
                  unit="/ 10"
                />
                <DetailRow label="Befinden" value={selected.feeling} unit="/ 5" />
                <DetailRow label="Muskelkater" value={selected.soreness} unit="/ 5" />
                <DetailRow label="Schlaf" value={selected.sleep_hours} unit="h" />
                <DetailRow label="Schlafqualität" value={selected.sleep_quality} unit="/ 5" />
                <DetailRow label="Morgenpuls" value={selected.morning_hr} unit="bpm" />
                <DetailRow label="Morgen-HRV" value={selected.morning_hrv} unit="ms" />
                <DetailRow label="Bedingungen" value={selected.conditions} />
                <DetailRow label="Notizen" value={selected.notes} />
              </tbody>
            </table>
          </div>

          <div className="row row-end mt-2">
            <button className="btn btn-danger" onClick={() => remove(selected)}>
              Eintrag löschen
            </button>
          </div>
        </Modal>
      )}
    </>
  )
}

/** Die Fitnessdaten aus Garmin, Tag für Tag.
 *
 * Jede Zelle trägt `data-label`: Unterhalb von 640 px bricht `.table-cards`
 * jede Zeile in eine Karte auf und nimmt die Beschriftung von dort — ohne das
 * Attribut stünden die Werte am Telefon nackt da.
 */
function FitnessTabelle({ tage }: { tage: WellnessDay[] }) {
  if (tage.length === 0) {
    return (
      <EmptyState icon="⌚" title="Noch keine Fitnessdaten">
        <p>
          Verbinde dein Garmin-Konto, dann erscheinen hier Schlaf, HRV, Ruhepuls
          und Erholungswerte.
        </p>
        <div className="row row-center">
          <Link className="btn btn-primary" to="/garmin">
            Garmin verbinden
          </Link>
        </div>
      </EmptyState>
    )
  }

  return (
    <div className="card">
      <div className="table-wrap">
        <table className="table-cards">
          <thead>
            <tr>
              <th>Datum</th>
              <th>Schlaf</th>
              <th>Score</th>
              <th>HRV</th>
              <th>Ruhepuls</th>
              <th>Reife</th>
              <th>Körperbatterie</th>
              <th>Stress</th>
            </tr>
          </thead>
          <tbody>
            {tage.map((tag) => (
              <tr key={tag.date}>
                <td className="nowrap cell-title" data-label="Datum">
                  {new Date(tag.date).toLocaleDateString('de-DE', {
                    weekday: 'short',
                    day: '2-digit',
                    month: '2-digit',
                  })}
                </td>
                <td data-label="Schlaf">
                  {tag.sleep_seconds !== null
                    ? `${(tag.sleep_seconds / 3600).toFixed(1)} h`
                    : '–'}
                </td>
                <td data-label="Schlafscore">{tag.sleep_score ?? '–'}</td>
                <td data-label="HRV">
                  {tag.hrv_last_night_ms !== null
                    ? `${Math.round(tag.hrv_last_night_ms)} ms`
                    : '–'}
                </td>
                <td data-label="Ruhepuls">{tag.resting_hr ?? '–'}</td>
                <td data-label="Trainingsreife">{tag.readiness_score ?? '–'}</td>
                <td data-label="Körperbatterie">
                  {tag.body_battery_high !== null
                    ? `${tag.body_battery_low ?? '?'}–${tag.body_battery_high}`
                    : '–'}
                </td>
                <td data-label="Stress">{tag.stress_avg ?? '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
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
