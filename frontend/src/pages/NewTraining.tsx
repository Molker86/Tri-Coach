import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import {
  Alert,
  Field,
  Loading,
  NumberField,
  TextArea,
  TextField,
} from '../components/ui'
import {
  DISCIPLINES,
  EQUIPMENT_OPTIONS,
  GOAL_OPTIONS,
  RACE_DISTANCES,
  SPORT_ICON,
  SPORT_LABEL,
  SUPPLEMENTAL_OPTIONS,
  TRIATHLON_SPORTS,
  WEEKDAYS,
} from '../constants'
import type {
  Discipline,
  Profile,
  Sport,
  TrainingRequestInput,
  Weekday,
} from '../types'

type StepKey =
  | 'discipline'
  | 'goal'
  | 'days'
  | 'daySports'
  | 'budget'
  | 'supplemental'
  | 'equipment'
  | 'values'
  | 'summary'

const EMPTY_REQUEST: TrainingRequestInput = {
  discipline: 'run',
  goal_type: null,
  goal_text: null,
  race_date: null,
  race_distance: null,
  available_days: [],
  day_sport_map: {},
  day_time_budget: {},
  long_session_day: null,
  weekly_hours_target: null,
  supplemental: [],
  equipment: [],
  free_text: {},
}

export default function NewTraining() {
  const navigate = useNavigate()

  const [form, setForm] = useState<TrainingRequestInput>(EMPTY_REQUEST)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [stepIndex, setStepIndex] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.getProfile().then(setProfile).catch((err) => setError(err.message))
  }, [])

  // Die Tagesbelegung je Sportart ist nur beim Triathlon sinnvoll.
  const steps: StepKey[] = useMemo(() => {
    const base: StepKey[] = ['discipline', 'goal', 'days']
    if (form.discipline === 'triathlon') base.push('daySports')
    return [...base, 'budget', 'supplemental', 'equipment', 'values', 'summary']
  }, [form.discipline])

  const step = steps[Math.min(stepIndex, steps.length - 1)]

  function patch(changes: Partial<TrainingRequestInput>) {
    setForm((current) => ({ ...current, ...changes }))
  }

  function patchProfile(changes: Partial<Profile>) {
    setProfile((current) => (current ? { ...current, ...changes } : current))
  }

  function setFreeText(key: string, value: string) {
    setForm((current) => ({
      ...current,
      free_text: { ...current.free_text, [key]: value },
    }))
  }

  function toggleDay(day: Weekday) {
    setForm((current) => {
      const wasSelected = current.available_days.includes(day)
      const nextDays = wasSelected
        ? current.available_days.filter((d) => d !== day)
        : [...current.available_days, day]

      // Abgewählte Tage dürfen keine Restdaten hinterlassen.
      const day_sport_map = { ...current.day_sport_map }
      const day_time_budget = { ...current.day_time_budget }
      if (wasSelected) {
        delete day_sport_map[day]
        delete day_time_budget[day]
      }

      return {
        ...current,
        // In Wochenreihenfolge halten, unabhängig von der Klickreihenfolge.
        available_days: WEEKDAYS.filter((d) => nextDays.includes(d.key)).map((d) => d.key),
        day_sport_map,
        day_time_budget,
        long_session_day:
          wasSelected && current.long_session_day === day
            ? null
            : current.long_session_day,
      }
    })
  }

  function setAllDays(selected: boolean) {
    setForm((current) =>
      selected
        ? { ...current, available_days: WEEKDAYS.map((d) => d.key) }
        : // Wie beim einzelnen Abwählen: nichts von den verworfenen Tagen stehen lassen.
          {
            ...current,
            available_days: [],
            day_sport_map: {},
            day_time_budget: {},
            long_session_day: null,
          },
    )
  }

  function toggleDaySport(day: Weekday, sport: Sport) {
    setForm((current) => {
      const existing = current.day_sport_map[day] ?? []
      const next = existing.includes(sport)
        ? existing.filter((s) => s !== sport)
        : [...existing, sport]
      return {
        ...current,
        day_sport_map: { ...current.day_sport_map, [day]: next },
      }
    })
  }

  function toggleFromList(list: string[], value: string): string[] {
    return list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
  }

  const allDaysSelected = form.available_days.length === WEEKDAYS.length

  const canAdvance = (() => {
    switch (step) {
      case 'days':
        return form.available_days.length > 0
      case 'goal':
        return form.goal_type !== null
      default:
        return true
    }
  })()

  async function finish() {
    setBusy(true)
    setError(null)
    try {
      if (profile) {
        const { age: _a, bmi: _b, hr_zones: _z, updated_at: _u, ...payload } = profile
        await api.updateProfile(payload)
      }
      const created = await api.createRequest(form)
      navigate(`/plan-erzeugen?request=${created.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Speichern fehlgeschlagen.')
      setBusy(false)
    }
  }

  if (!profile && !error) return <Loading />

  return (
    <div className="page-narrow" style={{ margin: '0 auto' }}>
      <div className="wizard-progress">
        {steps.map((key, index) => (
          <div
            key={key}
            className={`wizard-step-bar ${
              index < stepIndex ? 'done' : index === stepIndex ? 'current' : ''
            }`}
          />
        ))}
      </div>

      <div className="wizard-meta">
        Schritt {stepIndex + 1} von {steps.length}
      </div>

      {error && <Alert kind="error">{error}</Alert>}

      <div className="card">
        {step === 'discipline' && (
          <>
            <h1>Was möchtest du trainieren?</h1>
            <p className="muted">
              Die Auswahl bestimmt, welche Fragen danach kommen.
            </p>
            <div className="choice-grid">
              {DISCIPLINES.map((discipline) => (
                <button
                  key={discipline.key}
                  className={`choice ${
                    form.discipline === discipline.key ? 'selected' : ''
                  }`}
                  onClick={() => patch({ discipline: discipline.key as Discipline })}
                >
                  <span className="choice-title">
                    <span className="choice-icon">{discipline.icon}</span>
                    {discipline.label}
                  </span>
                  <span className="choice-desc">{discipline.description}</span>
                </button>
              ))}
            </div>
          </>
        )}

        {step === 'goal' && (
          <>
            <h1>Wofür trainierst du?</h1>
            <p className="muted">
              Das Ziel bestimmt Periodisierung, Intensitätsverteilung und Umfang.
            </p>

            <div className="question-block">
              <div className="question-label">Welches Ziel verfolgst du?</div>
              <div className="question-hint">Wähle den Schwerpunkt.</div>
              <div className="choice-grid">
                {GOAL_OPTIONS.map((goal) => (
                  <button
                    key={goal.key}
                    className={`choice ${form.goal_type === goal.key ? 'selected' : ''}`}
                    onClick={() => patch({ goal_type: goal.key })}
                  >
                    <span className="choice-title">{goal.label}</span>
                    <span className="choice-desc">{goal.hint}</span>
                  </button>
                ))}
              </div>
            </div>

            {(form.goal_type === 'Wettkampfvorbereitung' ||
              form.goal_type === 'Bestzeit' ||
              form.goal_type === 'Erstfinish') && (
              <div className="question-block">
                <div className="question-label">Welcher Wettkampf?</div>
                <div className="grid grid-2">
                  <Field label="Distanz">
                    <select
                      value={form.race_distance ?? ''}
                      onChange={(e) =>
                        patch({ race_distance: e.target.value || null })
                      }
                    >
                      <option value="">Bitte wählen</option>
                      {RACE_DISTANCES[form.discipline].map((distance) => (
                        <option key={distance} value={distance}>
                          {distance}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <TextField
                    label="Wettkampfdatum"
                    type="date"
                    value={form.race_date}
                    onChange={(v) => patch({ race_date: v })}
                  />
                </div>
              </div>
            )}

            <div className="freetext-slot">
              <TextArea
                label="Ergänzung in eigenen Worten"
                hint="Alles, was das Ziel genauer beschreibt — Zeitvorgaben, Schwächen, Motivation."
                placeholder="z. B. Ich will die Olympische Distanz unter 2:30 finishen, das Schwimmen ist meine Schwäche."
                value={form.goal_text}
                onChange={(v) => patch({ goal_text: v })}
              />
            </div>
          </>
        )}

        {step === 'days' && (
          <>
            <h1>An welchen Tagen willst du trainieren?</h1>
            <p className="muted">
              Wähle alle Tage aus, an denen Training grundsätzlich möglich ist.
            </p>
            <div className="row mb-1" style={{ justifyContent: 'flex-end' }}>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => setAllDays(!allDaysSelected)}
              >
                {allDaysSelected ? 'Auswahl aufheben' : 'Alle Tage auswählen'}
              </button>
            </div>
            <div className="day-grid">
              {WEEKDAYS.map((day) => (
                <button
                  key={day.key}
                  className={`day-toggle ${
                    form.available_days.includes(day.key) ? 'selected' : ''
                  }`}
                  onClick={() => toggleDay(day.key)}
                >
                  {day.short}
                </button>
              ))}
            </div>
            {form.available_days.length === 0 && (
              <p className="small faint mt-1 mb-0">
                Mindestens ein Tag muss ausgewählt sein.
              </p>
            )}
          </>
        )}

        {step === 'daySports' && (
          <>
            <h1>Welche Sportart geht an welchem Tag?</h1>
            <p className="muted">
              Nicht jeder Tag lässt jede Disziplin zu — das Schwimmbad hat andere
              Zeiten als die Laufstrecke vor der Tür. Ohne Auswahl entscheidet die KI
              frei.
            </p>

            {form.available_days.map((day) => (
              <div className="question-block" key={day}>
                <div className="question-label">
                  {WEEKDAYS.find((d) => d.key === day)?.label}
                </div>
                <div className="row">
                  {TRIATHLON_SPORTS.map((sport) => (
                    <button
                      key={sport}
                      className={`chip ${
                        (form.day_sport_map[day] ?? []).includes(sport) ? 'selected' : ''
                      }`}
                      onClick={() => toggleDaySport(day, sport)}
                    >
                      {SPORT_ICON[sport]} {SPORT_LABEL[sport]}
                    </button>
                  ))}
                </div>
              </div>
            ))}

            <div className="freetext-slot">
              <TextArea
                label="Ergänzung in eigenen Worten"
                placeholder="z. B. Schwimmen nur dienstags vor 8 Uhr, Rolle steht das ganze Jahr bereit."
                value={form.free_text.day_sports ?? null}
                onChange={(v) => setFreeText('day_sports', v ?? '')}
              />
            </div>
          </>
        )}

        {step === 'budget' && (
          <>
            <h1>Wie viel Zeit hast du?</h1>
            <p className="muted">
              Ein Plan, der nicht in deinen Alltag passt, wird nicht umgesetzt.
            </p>

            <div className="question-block">
              <div className="question-label">Zeitbudget je Trainingstag</div>
              <div className="question-hint">
                In Minuten. Leer lassen, wenn der Tag flexibel ist.
              </div>
              <div className="grid grid-3">
                {form.available_days.map((day) => (
                  <NumberField
                    key={day}
                    label={WEEKDAYS.find((d) => d.key === day)?.label ?? day}
                    unit="min"
                    step={15}
                    min={0}
                    placeholder="flexibel"
                    value={form.day_time_budget[day] ?? null}
                    onChange={(value) => {
                      const budget = { ...form.day_time_budget }
                      if (value === null) delete budget[day]
                      else budget[day] = value
                      patch({ day_time_budget: budget })
                    }}
                  />
                ))}
              </div>
            </div>

            <div className="grid grid-2">
              <NumberField
                label="Wunsch-Wochenumfang"
                unit="Stunden"
                step={0.5}
                hint="Realistisch ansetzen — lieber konstant als ambitioniert."
                value={form.weekly_hours_target}
                onChange={(v) => patch({ weekly_hours_target: v })}
              />
              <Field
                label="Tag für die lange Einheit"
                hint="Meist der Tag mit dem größten Zeitfenster."
              >
                <select
                  value={form.long_session_day ?? ''}
                  onChange={(e) => patch({ long_session_day: e.target.value || null })}
                >
                  <option value="">Keine Vorgabe</option>
                  {form.available_days.map((day) => (
                    <option key={day} value={day}>
                      {WEEKDAYS.find((d) => d.key === day)?.label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            <div className="freetext-slot">
              <TextArea
                label="Ergänzung in eigenen Worten"
                placeholder="z. B. Mittwochs nur abends nach 20 Uhr, jedes zweite Wochenende bin ich unterwegs."
                value={form.free_text.budget ?? null}
                onChange={(v) => setFreeText('budget', v ?? '')}
              />
            </div>
          </>
        )}

        {step === 'supplemental' && (
          <>
            <h1>Ergänzendes Training</h1>
            <p className="muted">
              Kraft und Beweglichkeit sind kein Beiwerk — sie senken das
              Verletzungsrisiko und verbessern die Ökonomie.
            </p>

            <div className="choice-grid">
              {SUPPLEMENTAL_OPTIONS.map((option) => (
                <button
                  key={option.key}
                  className={`choice ${
                    form.supplemental.includes(option.key) ? 'selected' : ''
                  }`}
                  onClick={() =>
                    patch({ supplemental: toggleFromList(form.supplemental, option.key) })
                  }
                >
                  <span className="choice-title">{option.label}</span>
                  <span className="choice-desc">{option.hint}</span>
                </button>
              ))}
              <button
                className={`choice ${form.supplemental.length === 0 ? 'selected' : ''}`}
                onClick={() => patch({ supplemental: [] })}
              >
                <span className="choice-title">Nichts davon</span>
                <span className="choice-desc">
                  Nur die Ausdauereinheiten der gewählten Disziplin.
                </span>
              </button>
            </div>

            <div className="freetext-slot">
              <TextArea
                label="Ergänzung in eigenen Worten"
                placeholder="z. B. Zweimal pro Woche Rumpfstabilität, aber keine Kniebeugen wegen des Knies."
                value={form.free_text.supplemental ?? null}
                onChange={(v) => setFreeText('supplemental', v ?? '')}
              />
            </div>
          </>
        )}

        {step === 'equipment' && (
          <>
            <h1>Was steht dir zur Verfügung?</h1>
            <p className="muted">
              Die KI plant nur, was du auch umsetzen kannst.
            </p>

            <div className="row">
              {EQUIPMENT_OPTIONS.map((option) => (
                <button
                  key={option.key}
                  className={`chip ${
                    form.equipment.includes(option.key) ? 'selected' : ''
                  }`}
                  onClick={() =>
                    patch({ equipment: toggleFromList(form.equipment, option.key) })
                  }
                >
                  {option.label}
                </button>
              ))}
            </div>

            <div className="freetext-slot mt-2">
              <TextArea
                label="Ergänzung in eigenen Worten"
                placeholder="z. B. 25-m-Becken, Powermeter nur am Rennrad, kein Zugang zur Laufbahn."
                value={form.free_text.equipment ?? null}
                onChange={(v) => setFreeText('equipment', v ?? '')}
              />
            </div>
          </>
        )}

        {step === 'values' && profile && (
          <>
            <h1>Deine Werte</h1>
            <p className="muted">
              Je genauer diese Angaben, desto präziser die Zonen und die Steuerung.
              Alles ist optional und jederzeit unter „Meine Daten" änderbar.
            </p>

            <div className="question-block">
              <div className="question-label">Körperdaten</div>
              <div className="grid grid-3">
                <TextField
                  label="Geburtsdatum"
                  type="date"
                  value={profile.birth_date}
                  onChange={(v) => patchProfile({ birth_date: v })}
                />
                <NumberField
                  label="Größe"
                  unit="cm"
                  value={profile.height_cm}
                  onChange={(v) => patchProfile({ height_cm: v })}
                />
                <NumberField
                  label="Gewicht"
                  unit="kg"
                  step={0.1}
                  value={profile.weight_kg}
                  onChange={(v) => patchProfile({ weight_kg: v })}
                />
                <Field label="Geschlecht">
                  <select
                    value={profile.sex ?? ''}
                    onChange={(e) =>
                      patchProfile({ sex: (e.target.value || null) as Profile['sex'] })
                    }
                  >
                    <option value="">Keine Angabe</option>
                    <option value="female">Weiblich</option>
                    <option value="male">Männlich</option>
                    <option value="diverse">Divers</option>
                  </select>
                </Field>
              </div>
            </div>

            <div className="question-block">
              <div className="question-label">Herz- und Ausdauerwerte</div>
              <div className="grid grid-3">
                <NumberField
                  label="Ruhepuls"
                  unit="bpm"
                  value={profile.resting_hr}
                  onChange={(v) => patchProfile({ resting_hr: v })}
                />
                <NumberField
                  label="Maximalpuls"
                  unit="bpm"
                  value={profile.max_hr}
                  onChange={(v) => patchProfile({ max_hr: v })}
                />
                <NumberField
                  label="VO2max"
                  unit="ml/kg/min"
                  step={0.1}
                  value={profile.vo2max}
                  onChange={(v) => patchProfile({ vo2max: v })}
                />
                <NumberField
                  label="HRV"
                  unit="ms"
                  step={0.1}
                  value={profile.hrv_rmssd}
                  onChange={(v) => patchProfile({ hrv_rmssd: v })}
                />
                <NumberField
                  label="Schwellenpuls"
                  unit="bpm"
                  value={profile.lthr}
                  onChange={(v) => patchProfile({ lthr: v })}
                />
              </div>
            </div>

            <div className="question-block">
              <div className="question-label">Leistungswerte</div>
              <div className="grid grid-3">
                <NumberField
                  label="FTP Rad"
                  unit="Watt"
                  value={profile.ftp_watts}
                  onChange={(v) => patchProfile({ ftp_watts: v })}
                />
                <TextField
                  label="Schwellenpace Laufen"
                  placeholder="4:15"
                  value={profile.threshold_pace_run}
                  onChange={(v) => patchProfile({ threshold_pace_run: v })}
                />
                <TextField
                  label="CSS Schwimmen"
                  placeholder="1:45"
                  value={profile.css_swim}
                  onChange={(v) => patchProfile({ css_swim: v })}
                />
                <NumberField
                  label="Aktuelles Wochenvolumen"
                  unit="Stunden"
                  step={0.5}
                  value={profile.current_weekly_hours}
                  onChange={(v) => patchProfile({ current_weekly_hours: v })}
                />
              </div>
            </div>

            <TextArea
              label="Verletzungen und Einschränkungen"
              placeholder="z. B. Achillessehnenreizung links seit Mai"
              value={profile.injuries}
              onChange={(v) => patchProfile({ injuries: v })}
            />
          </>
        )}

        {step === 'summary' && (
          <>
            <h1>Zusammenfassung</h1>
            <p className="muted">
              Prüfe deine Angaben. Danach erzeugt Tri-Coach das Datenpaket für die KI.
            </p>

            <div className="table-wrap">
              <table>
                <tbody>
                  <SummaryRow
                    label="Disziplin"
                    value={DISCIPLINES.find((d) => d.key === form.discipline)?.label}
                  />
                  <SummaryRow
                    label="Ziel"
                    value={
                      GOAL_OPTIONS.find((g) => g.key === form.goal_type)?.label ??
                      form.goal_type
                    }
                  />
                  {form.race_distance && (
                    <SummaryRow
                      label="Wettkampf"
                      value={`${form.race_distance}${
                        form.race_date
                          ? ` am ${new Date(form.race_date).toLocaleDateString('de-DE')}`
                          : ''
                      }`}
                    />
                  )}
                  <SummaryRow
                    label="Trainingstage"
                    value={form.available_days
                      .map((d) => WEEKDAYS.find((w) => w.key === d)?.short)
                      .join(', ')}
                  />
                  {form.discipline === 'triathlon' &&
                    Object.entries(form.day_sport_map).some(([, v]) => v.length > 0) && (
                      <SummaryRow
                        label="Sportart je Tag"
                        value={Object.entries(form.day_sport_map)
                          .filter(([, sports]) => sports.length > 0)
                          .map(
                            ([day, sports]) =>
                              `${WEEKDAYS.find((w) => w.key === day)?.short}: ${sports
                                .map((s) => SPORT_LABEL[s])
                                .join('/')}`,
                          )
                          .join(' · ')}
                      />
                    )}
                  <SummaryRow
                    label="Wochenumfang"
                    value={
                      form.weekly_hours_target ? `${form.weekly_hours_target} h` : null
                    }
                  />
                  <SummaryRow
                    label="Lange Einheit"
                    value={
                      WEEKDAYS.find((w) => w.key === form.long_session_day)?.label ?? null
                    }
                  />
                  <SummaryRow
                    label="Ergänzungstraining"
                    value={
                      form.supplemental.length
                        ? form.supplemental
                            .map(
                              (key) =>
                                SUPPLEMENTAL_OPTIONS.find((o) => o.key === key)?.label,
                            )
                            .join(', ')
                        : 'Keines'
                    }
                  />
                  <SummaryRow
                    label="Ausrüstung"
                    value={
                      form.equipment.length
                        ? form.equipment
                            .map((key) => EQUIPMENT_OPTIONS.find((o) => o.key === key)?.label)
                            .join(', ')
                        : null
                    }
                  />
                  <SummaryRow
                    label="Maximalpuls"
                    value={profile?.max_hr ? `${profile.max_hr} bpm` : null}
                  />
                  <SummaryRow
                    label="Ruhepuls"
                    value={profile?.resting_hr ? `${profile.resting_hr} bpm` : null}
                  />
                </tbody>
              </table>
            </div>

            <Alert kind="info">
              Im nächsten Schritt bekommst du einen fertigen Text zum Kopieren. Den
              schickst du an eine KI und fügst deren Antwort hier wieder ein.
            </Alert>
          </>
        )}

        <div className="wizard-actions">
          <button
            className="btn btn-ghost"
            onClick={() => setStepIndex((i) => Math.max(0, i - 1))}
            disabled={stepIndex === 0 || busy}
          >
            Zurück
          </button>

          {step === 'summary' ? (
            <button className="btn btn-primary btn-lg" onClick={finish} disabled={busy}>
              {busy ? 'Wird gespeichert …' : 'Datenpaket erzeugen'}
            </button>
          ) : (
            <button
              className="btn btn-primary"
              onClick={() => setStepIndex((i) => Math.min(steps.length - 1, i + 1))}
              disabled={!canAdvance || busy}
            >
              Weiter
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function SummaryRow({ label, value }: { label: string; value?: string | null }) {
  return (
    <tr>
      <th style={{ width: '40%' }}>{label}</th>
      <td>{value || <span className="faint">Keine Angabe</span>}</td>
    </tr>
  )
}
