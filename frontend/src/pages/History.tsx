import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Alert, EmptyState, Loading, Modal } from '../components/ui'
import { paceFormat, sportIcon, sportLabel } from '../constants'
import type { SessionLog } from '../types'

const STATUS_LABEL: Record<SessionLog['status'], string> = {
  completed: 'Absolviert',
  partial: 'Teilweise',
  skipped: 'Ausgefallen',
}

export default function History() {
  const [logs, setLogs] = useState<SessionLog[] | null>(null)
  const [weeks, setWeeks] = useState(4)
  const [selected, setSelected] = useState<SessionLog | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLogs(null)
    api.listLogs(weeks).then(setLogs).catch((err) => setError(err.message))
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

      {logs.length === 0 ? (
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
            <table>
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
                    <td className="nowrap">
                      {new Date(log.date).toLocaleDateString('de-DE', {
                        weekday: 'short',
                        day: '2-digit',
                        month: '2-digit',
                      })}
                    </td>
                    <td className="nowrap">
                      {sportIcon(log.sport)} {sportLabel(log.sport)}
                      {log.status !== 'completed' && (
                        <> <span className="badge">{STATUS_LABEL[log.status]}</span></>
                      )}
                    </td>
                    <td>{log.duration_min ? `${log.duration_min} min` : '–'}</td>
                    <td>{log.distance_km ? `${log.distance_km} km` : '–'}</td>
                    <td>{log.avg_hr ?? '–'}</td>
                    <td>{log.rpe ?? '–'}</td>
                    <td>{log.trimp ?? '–'}</td>
                    <td className="nowrap">
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
                <DetailRow label="Anstrengung (RPE)" value={selected.rpe} unit="/ 10" />
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
