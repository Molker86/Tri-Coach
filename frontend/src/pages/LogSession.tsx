import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { Alert, Field, NumberField, TextArea, TextField } from '../components/ui'
import { SPORT_ICON, SPORT_LABEL, sessionTypeLabel, sportLabel } from '../constants'
import type { Plan, PlanSession, SessionLogInput, Sport } from '../types'

const LOGGABLE_SPORTS: Sport[] = ['run', 'bike', 'swim', 'strength', 'mobility', 'brick']

/** Rückblick der Auswertung — muss zu `HISTORY_WEEKS` im Backend passen. */
const HISTORY_WINDOW_DAYS = 28

/** Wie weit zurück offene Planeinheiten zur Verknüpfung angeboten werden.
 *
 * Beim Nachtragen so weit wie die Auswertung reicht: Wer eine drei Wochen alte
 * Einheit nachträgt, soll sie noch ihrer Planeinheit zuordnen können — sonst
 * bliebe die Umsetzungsquote unnötig löchrig.
 */
const LINK_WINDOW_DAYS: Record<Mode, number> = { log: 14, backfill: HISTORY_WINDOW_DAYS }

export type Mode = 'log' | 'backfill'

/** Lokales Datum als ISO-String.
 *
 * `toISOString()` rechnet nach UTC um und liegt damit je nach Zeitzone und
 * Uhrzeit einen Tag daneben — beim Nachtragen fatal, weil das Datum hier auch
 * die Obergrenze des Eingabefelds bestimmt.
 */
function isoDate(value: Date): string {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 10)
}

const today = () => isoDate(new Date())

function daysAgo(days: number): string {
  const day = new Date()
  day.setDate(day.getDate() - days)
  return isoDate(day)
}

function emptyForm(mode: Mode): SessionLogInput {
  return {
    plan_session_id: null,
    // Nachgetragen wird eine Einheit, die schon vorbei ist — gestern ist der
    // wahrscheinlichste Fall und spart einen Klick.
    date: mode === 'backfill' ? daysAgo(1) : today(),
    sport: 'run',
    status: 'completed',
    duration_min: null,
    distance_km: null,
    avg_hr: null,
    max_hr: null,
    avg_pace: null,
    avg_power: null,
    avg_cadence: null,
    elevation_gain_m: null,
    calories: null,
    rpe: null,
    feeling: null,
    soreness: null,
    sleep_hours: null,
    sleep_quality: null,
    morning_hr: null,
    morning_hrv: null,
    conditions: null,
    notes: null,
  }
}

export default function LogSession({ mode = 'log' }: { mode?: Mode }) {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const preselectedId = params.get('session') ? Number(params.get('session')) : null
  const isBackfill = mode === 'backfill'

  const [form, setForm] = useState<SessionLogInput>(() => emptyForm(mode))
  const [plan, setPlan] = useState<Plan | null>(null)
  const [linked, setLinked] = useState<PlanSession | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api
      .activePlan()
      .then((loaded) => {
        setPlan(loaded)
        if (!loaded || preselectedId === null) return
        const session = loaded.sessions.find((s) => s.id === preselectedId)
        if (session) applySession(session)
      })
      .catch((err) => setError(err.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preselectedId])

  function patch(changes: Partial<SessionLogInput>) {
    setForm((current) => ({ ...current, ...changes }))
  }

  /** Übernimmt Datum, Sportart und die geplanten Werte als Startpunkt. */
  function applySession(session: PlanSession) {
    setLinked(session)
    setForm((current) => ({
      ...current,
      plan_session_id: session.id,
      date: session.date,
      sport: session.sport,
      duration_min: session.duration_min,
      distance_km: session.distance_km,
    }))
  }

  function clearLink() {
    setLinked(null)
    patch({ plan_session_id: null })
  }

  async function save(another = false) {
    setBusy(true)
    setError(null)
    try {
      const stored = await api.createLog(form)
      if (!another) {
        navigate('/verlauf')
        return
      }
      // Nachtragen kommt selten allein: Formular leeren, aber das Datum stehen
      // lassen — meist folgt die nächste Einheit aus demselben Zeitraum.
      setSaved(
        `${sportLabel(stored.sport)} vom ${new Date(stored.date).toLocaleDateString(
          'de-DE',
        )} gespeichert.`,
      )
      setLinked(null)
      setForm({ ...emptyForm(mode), date: form.date })
      setBusy(false)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Speichern fehlgeschlagen.')
      setBusy(false)
    }
  }

  // Offene Einheiten aus dem Plan zur Verknüpfung anbieten.
  const linkCutoff = daysAgo(LINK_WINDOW_DAYS[mode])
  const openSessions = (plan?.sessions ?? []).filter(
    (session) =>
      !session.logged &&
      session.sport !== 'rest' &&
      session.date <= today() &&
      session.date >= linkCutoff,
  )

  const isSwim = form.sport === 'swim'
  // Ältere Einträge bleiben im Verlauf, steuern die nächste Planung aber nicht mehr.
  const outsideHistoryWindow = form.date < daysAgo(HISTORY_WINDOW_DAYS)

  return (
    <div className="page-narrow" style={{ margin: '0 auto' }}>
      <div className="page-header">
        <div>
          <h1>{isBackfill ? 'Training nachtragen' : 'Training erfassen'}</h1>
          <p>
            {isBackfill
              ? 'Eine Einheit aus der Vergangenheit ergänzen — sie zählt in den letzten vier Wochen mit und steuert damit deinen nächsten Plan.'
              : 'Nach der Einheit ausfüllen — diese Werte steuern deinen nächsten Plan.'}
          </p>
        </div>
        <Link
          className="btn btn-ghost btn-sm"
          to={isBackfill ? '/training-erfassen' : '/training-nachtragen'}
        >
          {isBackfill ? 'Heute trainiert?' : 'Liegt länger zurück?'}
        </Link>
      </div>

      {error && <Alert kind="error">{error}</Alert>}
      {saved && <Alert kind="success">{saved}</Alert>}

      {openSessions.length > 0 && !linked && (
        <div className="card">
          <h3>Offene Einheiten aus deinem Plan</h3>
          <p className="small muted">
            Wähle die passende Einheit, dann werden Datum und Sportart übernommen
            {isBackfill ? ' und die Umsetzung des Plans stimmt wieder' : ''}.
          </p>
          <div className="stack">
            {openSessions.map((session) => (
              <button
                key={session.id}
                className="session-card"
                onClick={() => applySession(session)}
              >
                <span className="session-icon">{SPORT_ICON[session.sport]}</span>
                <span className="session-body">
                  <span className="session-title">{session.title}</span>
                  <span className="session-meta">
                    <span>
                      {new Date(session.date).toLocaleDateString('de-DE', {
                        weekday: 'short',
                        day: '2-digit',
                        month: '2-digit',
                      })}
                    </span>
                    <span>{SPORT_LABEL[session.sport]}</span>
                    <span>{sessionTypeLabel(session.session_type)}</span>
                    {session.duration_min ? <span>{session.duration_min} min</span> : null}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {linked && (
        <Alert kind="info">
          Verknüpft mit der geplanten Einheit „{linked.title}" vom{' '}
          {new Date(linked.date).toLocaleDateString('de-DE')}.{' '}
          <button className="btn btn-ghost btn-sm" onClick={clearLink}>
            Verknüpfung lösen
          </button>
        </Alert>
      )}

      {isBackfill && outsideHistoryWindow && (
        <Alert kind="warning">
          Diese Einheit liegt mehr als vier Wochen zurück. Sie bleibt in deinem Verlauf,
          fließt aber nicht mehr in die Auswertung für den nächsten Plan ein.
        </Alert>
      )}

      <div className="card">
        <h2>Grunddaten</h2>
        <div className="grid grid-3">
          <TextField
            label="Datum"
            type="date"
            hint={isBackfill ? 'Der Tag, an dem du trainiert hast.' : undefined}
            value={form.date}
            max={isBackfill ? today() : undefined}
            onChange={(v) => patch({ date: v ?? (isBackfill ? daysAgo(1) : today()) })}
          />
          <Field label="Sportart">
            <select
              value={form.sport}
              onChange={(e) => patch({ sport: e.target.value as Sport })}
            >
              {LOGGABLE_SPORTS.map((sport) => (
                <option key={sport} value={sport}>
                  {SPORT_LABEL[sport]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Wie ist es gelaufen?">
            <select
              value={form.status}
              onChange={(e) =>
                patch({ status: e.target.value as SessionLogInput['status'] })
              }
            >
              <option value="completed">Vollständig absolviert</option>
              <option value="partial">Teilweise absolviert</option>
              <option value="skipped">Ausgefallen</option>
            </select>
          </Field>
        </div>
      </div>

      {form.status !== 'skipped' && (
        <>
          <div className="card">
            <h2>Messwerte</h2>
            <div className="grid grid-3">
              <NumberField
                label="Dauer"
                unit="min"
                value={form.duration_min}
                onChange={(v) => patch({ duration_min: v })}
              />
              <NumberField
                label="Distanz"
                unit="km"
                step={0.01}
                value={form.distance_km}
                onChange={(v) => patch({ distance_km: v })}
              />
              <TextField
                label={isSwim ? 'Pace (min/100 m)' : 'Pace (min/km)'}
                placeholder={isSwim ? '1:52' : '5:26'}
                value={form.avg_pace}
                onChange={(v) => patch({ avg_pace: v })}
              />
              <NumberField
                label="Durchschnittspuls"
                unit="bpm"
                value={form.avg_hr}
                onChange={(v) => patch({ avg_hr: v })}
              />
              <NumberField
                label="Maximalpuls in der Einheit"
                unit="bpm"
                value={form.max_hr}
                onChange={(v) => patch({ max_hr: v })}
              />
              <NumberField
                label="Höhenmeter"
                unit="m"
                value={form.elevation_gain_m}
                onChange={(v) => patch({ elevation_gain_m: v })}
              />
              <NumberField
                label="Durchschnittsleistung"
                unit="Watt"
                hint="Radfahren mit Wattmessung."
                value={form.avg_power}
                onChange={(v) => patch({ avg_power: v })}
              />
              <NumberField
                label={isSwim ? 'Zugfrequenz' : 'Trittfrequenz / Schrittfrequenz'}
                unit="1/min"
                value={form.avg_cadence}
                onChange={(v) => patch({ avg_cadence: v })}
              />
              <NumberField
                label="Kalorien"
                unit="kcal"
                value={form.calories}
                onChange={(v) => patch({ calories: v })}
              />
            </div>
          </div>

          <div className="card">
            <h2>Wie hat es sich angefühlt?</h2>
            <p className="small muted">
              {isBackfill
                ? 'Trag ein, woran du dich erinnerst — RPE und Befinden sind für die Steuerung wichtiger als exakte Messwerte. Leere Felder sind in Ordnung.'
                : 'Subjektive Werte sind für die Steuerung mindestens so wichtig wie die Messwerte — sie zeigen Ermüdung früher als jede Uhr.'}
            </p>
            <div className="grid grid-2">
              <Field
                label="Anstrengung (RPE)"
                hint="1 = sehr leicht, 10 = maximale Ausbelastung."
              >
                <select
                  value={form.rpe ?? ''}
                  onChange={(e) =>
                    patch({ rpe: e.target.value ? Number(e.target.value) : null })
                  }
                >
                  <option value="">Keine Angabe</option>
                  {Array.from({ length: 10 }, (_, i) => i + 1).map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Befinden" hint="1 = schlecht, 5 = ausgezeichnet.">
                <select
                  value={form.feeling ?? ''}
                  onChange={(e) =>
                    patch({ feeling: e.target.value ? Number(e.target.value) : null })
                  }
                >
                  <option value="">Keine Angabe</option>
                  {[1, 2, 3, 4, 5].map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Muskelkater" hint="1 = keiner, 5 = stark.">
                <select
                  value={form.soreness ?? ''}
                  onChange={(e) =>
                    patch({ soreness: e.target.value ? Number(e.target.value) : null })
                  }
                >
                  <option value="">Keine Angabe</option>
                  {[1, 2, 3, 4, 5].map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Schlafqualität" hint="1 = schlecht, 5 = erholsam.">
                <select
                  value={form.sleep_quality ?? ''}
                  onChange={(e) =>
                    patch({ sleep_quality: e.target.value ? Number(e.target.value) : null })
                  }
                >
                  <option value="">Keine Angabe</option>
                  {[1, 2, 3, 4, 5].map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </Field>

              <NumberField
                label={isBackfill ? 'Schlaf in der Nacht davor' : 'Schlaf letzte Nacht'}
                unit="Stunden"
                step={0.5}
                value={form.sleep_hours}
                onChange={(v) => patch({ sleep_hours: v })}
              />
              <NumberField
                label="Morgenpuls"
                unit="bpm"
                hint="Ein Anstieg über mehrere Tage zeigt Ermüdung an."
                value={form.morning_hr}
                onChange={(v) => patch({ morning_hr: v })}
              />
              <NumberField
                label="Morgendliche HRV"
                unit="ms"
                step={0.1}
                value={form.morning_hrv}
                onChange={(v) => patch({ morning_hrv: v })}
              />
              <TextField
                label="Bedingungen"
                placeholder="z. B. 28 °C, Gegenwind, hügelig"
                value={form.conditions}
                onChange={(v) => patch({ conditions: v })}
              />
            </div>
          </div>
        </>
      )}

      <div className="card">
        <TextArea
          label="Notizen"
          hint={
            form.status === 'skipped'
              ? 'Warum ist die Einheit ausgefallen? Das fließt in die nächste Planung ein.'
              : 'Was ist dir aufgefallen?'
          }
          value={form.notes}
          onChange={(v) => patch({ notes: v })}
        />
      </div>

      <div className="row row-end mt-2">
        <button className="btn btn-ghost" onClick={() => navigate(-1)} disabled={busy}>
          Abbrechen
        </button>
        {isBackfill && (
          <button
            className="btn btn-secondary"
            onClick={() => save(true)}
            disabled={busy}
          >
            Speichern und weiteres nachtragen
          </button>
        )}
        <button
          className="btn btn-primary btn-lg"
          onClick={() => save(false)}
          disabled={busy}
        >
          {busy ? 'Speichert …' : isBackfill ? 'Nachtragen' : 'Training speichern'}
        </button>
      </div>
    </div>
  )
}
