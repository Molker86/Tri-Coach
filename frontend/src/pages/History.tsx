import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { AnalyseBericht } from '../components/AnalyseBericht'
import { TrainingDetail } from '../components/TrainingDetail'
import { TrainingsTabelle } from '../components/TrainingsTabelle'
import { Alert, EmptyState, Loading } from '../components/ui'
import { useAnalysen } from '../components/useAnalysen'
import { schlafdauer } from '../constants'
import type { SessionLog, WellnessDay } from '../types'

/**
 * Der Trainingsverlauf: alle absolvierten Einheiten, jede mit ihrer Analyse.
 *
 * Die Analysen haben hier **keine** eigene Rubrik mehr. Sie hatten eine,
 * solange ein Bericht einen Zeitraum bewertete und zu keiner Einheit gehörte —
 * eine Liste neben den Trainings, aus der nicht hervorging, worüber sie
 * eigentlich urteilt. Jetzt hängt jeder Bericht an seinem Training und steht
 * an dessen Zeile; die Rubrik wäre dieselbe Liste ein zweites Mal.
 */
export default function History() {
  const [logs, setLogs] = useState<SessionLog[] | null>(null)
  const [wellness, setWellness] = useState<WellnessDay[]>([])
  const [ansicht, setAnsicht] = useState<'trainings' | 'fitness'>('trainings')
  const [weeks, setWeeks] = useState(4)
  const [selected, setSelected] = useState<SessionLog | null>(null)
  const [analyseFuer, setAnalyseFuer] = useState<SessionLog | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Auslösen, Fortschritt und Ablage der Analysen — derselbe Hook wie auf der
  // Übersicht, damit sich beide Seiten gleich verhalten.
  const analysen = useAnalysen()

  useEffect(() => {
    setLogs(null)
    api.listLogs(weeks).then(setLogs).catch((err) => setError(err.message))
    // Ohne verbundenes Garmin-Konto bleibt die Liste leer, und der Umschalter
    // erscheint gar nicht erst.
    api.garminWellness(weeks).then(setWellness).catch(() => setWellness([]))
  }, [weeks])

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
          <Link className="btn btn-primary" to="/garmin">
            Mit Garmin abgleichen
          </Link>
        </div>
      </div>

      {/* Fehler eines Laufs gehören an die Seite und nicht nur in den Dialog:
          Wer ihn schließt, während der Lauf noch läuft, sähe sonst nie, dass er
          gescheitert ist. Bei offenem Dialog steht er dort — sonst zweimal. */}
      {!analyseFuer && analysen.fehler && (
        <Alert kind="error">{analysen.fehler}</Alert>
      )}

      {ansicht === 'fitness' ? (
        <FitnessTabelle tage={wellness} />
      ) : logs.length === 0 ? (
        <EmptyState icon="⌚" title="Noch keine Trainings">
          <p>
            Deine absolvierten Einheiten kommen aus Garmin Connect. Verbinde dein Konto
            und gleiche ab — danach steht hier dein Verlauf, und die letzten vier Wochen
            steuern deinen nächsten Plan.
          </p>
          <div className="row row-center">
            <Link className="btn btn-primary" to="/garmin">
              Garmin verbinden
            </Link>
          </div>
        </EmptyState>
      ) : (
        <div className="card">
          <TrainingsTabelle
            logs={logs}
            analysen={analysen.proTraining}
            laeuftFuer={analysen.laeuftFuer}
            onDetails={setSelected}
            onAnalyse={setAnalyseFuer}
          />
        </div>
      )}

      {analyseFuer && (
        <AnalyseBericht
          log={analyseFuer}
          analyse={analysen.proTraining.get(analyseFuer.id) ?? null}
          lauf={analysen}
          onClose={() => setAnalyseFuer(null)}
        />
      )}

      {selected && (
        <TrainingDetail
          log={selected}
          onClose={() => setSelected(null)}
          onGeloescht={() => {
            setLogs((current) => current?.filter((l) => l.id !== selected.id) ?? null)
            // Mit dem Training verschwindet auch seine Analyse — die Zuordnung
            // muss das wissen, sonst bliebe sie als Karteileiche im Speicher.
            analysen.neuLaden()
          }}
          onFehler={setError}
        />
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
                  {tag.sleep_seconds !== null ? schlafdauer(tag.sleep_seconds) : '–'}
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
