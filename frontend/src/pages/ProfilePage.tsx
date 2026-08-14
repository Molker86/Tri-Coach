import { useEffect, useState } from 'react'
import { api } from '../api/client'
import {
  Alert,
  Field,
  Loading,
  NumberField,
  Stat,
  TextArea,
  TextField,
} from '../components/ui'
import type { Profile, ProfileHistoryEntry } from '../types'

const VON_GARMIN = 'Wird täglich aus Garmin nachgeführt.'

const ZONE_COLORS: Record<string, string> = {
  Z1: 'var(--zone-1)',
  Z2: 'var(--zone-2)',
  Z3: 'var(--zone-3)',
  Z4: 'var(--zone-4)',
  Z5: 'var(--zone-5)',
}

export default function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null)
  const [history, setHistory] = useState<ProfileHistoryEntry[]>([])
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [garminFuehrtNach, setGarminFuehrtNach] = useState(false)

  useEffect(() => {
    Promise.all([api.getProfile(), api.getProfileHistory()])
      .then(([p, h]) => {
        setProfile(p)
        setHistory(h)
      })
      .catch((err) => setError(err.message))

    // Ob Werte automatisch vom Gerät kommen, muss hier stehen — sonst wundert
    // sich der Nutzer, warum eine Eingabe am nächsten Tag wieder anders ist.
    api
      .garminStatus()
      .then((z) =>
        setGarminFuehrtNach(
          z.konto?.status === 'connected' && z.konto.profile_sync_enabled,
        ),
      )
      .catch(() => setGarminFuehrtNach(false))
  }, [])

  function patch(changes: Partial<Profile>) {
    setProfile((current) => (current ? { ...current, ...changes } : current))
    setSaved(false)
  }

  async function save() {
    if (!profile) return
    setBusy(true)
    setError(null)
    try {
      // Berechnete Felder und die aus Garmin nachgeführten Bestzeiten gehören
      // nicht in den Request zurück — das Backend kennt sie nicht als Eingabe.
      const {
        age: _age,
        bmi: _bmi,
        hr_zones: _zones,
        updated_at: _u,
        garmin_personal_bests: _pb,
        ...payload
      } = profile
      const updated = await api.updateProfile(payload)
      setProfile(updated)
      setHistory(await api.getProfileHistory())
      setSaved(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Speichern fehlgeschlagen.')
    } finally {
      setBusy(false)
    }
  }

  if (!profile) return error ? <Alert kind="error">{error}</Alert> : <Loading />

  const estimatedMax = profile.hr_zones[0]?.estimated_max_hr
  const garminBestzeiten = profile.garmin_personal_bests ?? []

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Meine Daten</h1>
          <p>
            Diese Werte fließen in jeden Trainingsplan ein. Ändere sie jederzeit —
            der nächste Plan berücksichtigt den neuen Stand.
          </p>
        </div>
        <button className="btn btn-primary" onClick={save} disabled={busy}>
          {busy ? 'Speichert …' : 'Speichern'}
        </button>
      </div>

      {error && <Alert kind="error">{error}</Alert>}
      {saved && <Alert kind="success">Deine Daten wurden gespeichert.</Alert>}

      <div className="grid grid-4 mb-1">
        <Stat label="Alter" value={profile.age ?? '–'} unit={profile.age ? 'Jahre' : ''} />
        <Stat label="BMI" value={profile.bmi ?? '–'} />
        <Stat
          label="VO2max"
          value={profile.vo2max ?? '–'}
          unit={profile.vo2max ? 'ml/kg/min' : ''}
        />
        <Stat
          label="Ruhepuls"
          value={profile.resting_hr ?? '–'}
          unit={profile.resting_hr ? 'bpm' : ''}
        />
      </div>

      <div className="card">
        <h2>Körperdaten</h2>
        <div className="grid grid-3">
          <TextField
            label="Geburtsdatum"
            type="date"
            value={profile.birth_date}
            onChange={(v) => patch({ birth_date: v })}
          />
          <Field label="Geschlecht" hint="Beeinflusst die Berechnung der Trainingslast.">
            <select
              value={profile.sex ?? ''}
              onChange={(e) =>
                patch({ sex: (e.target.value || null) as Profile['sex'] })
              }
            >
              <option value="">Keine Angabe</option>
              <option value="female">Weiblich</option>
              <option value="male">Männlich</option>
              <option value="diverse">Divers</option>
            </select>
          </Field>
          <NumberField
            label="Größe"
            unit="cm"
            value={profile.height_cm}
            onChange={(v) => patch({ height_cm: v })}
          />
          <NumberField
            label="Gewicht"
            unit="kg"
            step={0.1}
            hint={garminFuehrtNach ? VON_GARMIN : undefined}
            value={profile.weight_kg}
            onChange={(v) => patch({ weight_kg: v })}
          />
          <NumberField
            label="Körperfettanteil"
            unit="%"
            step={0.1}
            value={profile.body_fat_pct}
            onChange={(v) => patch({ body_fat_pct: v })}
          />
        </div>
      </div>

      <div className="card">
        <h2>Herz- und Ausdauerwerte</h2>
        <div className="grid grid-3">
          <NumberField
            label="Ruhepuls"
            unit="bpm"
            hint={
              garminFuehrtNach
                ? 'Median der letzten 7 Tage aus Garmin.'
                : 'Morgens im Liegen gemessen.'
            }
            value={profile.resting_hr}
            onChange={(v) => patch({ resting_hr: v })}
          />
          <NumberField
            label="Maximalpuls"
            unit="bpm"
            hint={
              garminFuehrtNach
                ? 'Bleibt Handarbeit — Garmins Schätzung ist zu ungenau, und dieser Wert bestimmt alle Zonen.'
                : 'Aus einem Ausbelastungstest, nicht geschätzt.'
            }
            value={profile.max_hr}
            onChange={(v) => patch({ max_hr: v })}
          />
          <NumberField
            label="Schwellenpuls (LTHR)"
            unit="bpm"
            hint={
              garminFuehrtNach
                ? 'Aus Garmins erkannter Laktatschwelle.'
                : 'Mittlere HF bei einem harten 30-min-Test.'
            }
            value={profile.lthr}
            onChange={(v) => patch({ lthr: v })}
          />
          <NumberField
            label="VO2max"
            unit="ml/kg/min"
            step={0.1}
            hint={garminFuehrtNach ? VON_GARMIN : undefined}
            value={profile.vo2max}
            onChange={(v) => patch({ vo2max: v })}
          />
          <NumberField
            label="HRV"
            unit="ms"
            step={0.1}
            hint={garminFuehrtNach ? VON_GARMIN : 'Herzratenvariabilität, morgens gemessen.'}
            value={profile.hrv_rmssd}
            onChange={(v) => patch({ hrv_rmssd: v })}
          />
        </div>
      </div>

      {profile.hr_zones.length > 0 && (
        <div className="card">
          <div className="card-title">
            <h2>Deine Herzfrequenzzonen</h2>
            <span className="badge">{profile.hr_zones[0].basis}</span>
          </div>
          {estimatedMax && (
            <Alert kind="warning">
              Der Maximalpuls ist aus deinem Alter geschätzt (211 − 0,64 × Alter). Trag
              einen gemessenen Wert ein, sobald du ihn hast — die Zonen werden dadurch
              deutlich genauer.
            </Alert>
          )}
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Zone</th>
                  <th>Bereich</th>
                  <th>Herzfrequenz</th>
                </tr>
              </thead>
              <tbody>
                {profile.hr_zones.map((zone) => (
                  <tr key={zone.zone}>
                    <td>
                      <span
                        className="zone-dot"
                        style={{ background: ZONE_COLORS[zone.zone] }}
                      />
                      <strong>{zone.zone}</strong>
                    </td>
                    <td>{zone.label}</td>
                    <td className="nowrap">
                      {zone.low_bpm} – {zone.high_bpm} bpm
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card">
        <h2>Leistungswerte je Sportart</h2>
        <div className="grid grid-3">
          <NumberField
            label="FTP Rad"
            unit="Watt"
            hint={
              garminFuehrtNach
                ? 'Funktionelle Schwellenleistung — aus Garmin nachgeführt.'
                : 'Funktionelle Schwellenleistung.'
            }
            value={profile.ftp_watts}
            onChange={(v) => patch({ ftp_watts: v })}
          />
          <TextField
            label="Schwellenpace Laufen"
            hint={
              garminFuehrtNach
                ? 'Aus Garmins Laktatschwelle. Format mm:ss pro Kilometer.'
                : 'Format mm:ss pro Kilometer, z. B. 4:15.'
            }
            placeholder="4:15"
            value={profile.threshold_pace_run}
            onChange={(v) => patch({ threshold_pace_run: v })}
          />
          <TextField
            label="CSS Schwimmen"
            hint={
              garminFuehrtNach
                ? 'Garmin führt keinen CSS-Wert — bitte selbst eintragen (400-m- und 200-m-Test).'
                : 'Kritische Schwimmgeschwindigkeit pro 100 m, z. B. 1:45.'
            }
            placeholder="1:45"
            value={profile.css_swim}
            onChange={(v) => patch({ css_swim: v })}
          />
        </div>
      </div>

      <div className="card">
        <h2>Trainingskontext</h2>
        <div className="grid grid-3">
          <NumberField
            label="Aktuelles Wochenvolumen"
            unit="Stunden"
            step={0.5}
            hint="Was du derzeit tatsächlich trainierst."
            value={profile.current_weekly_hours}
            onChange={(v) => patch({ current_weekly_hours: v })}
          />
          <Field
            label="Alltagsbelastung"
            hint="Beruf und Privatleben — hohe Belastung verlangt mehr Regeneration."
          >
            <select
              value={profile.stress_level ?? ''}
              onChange={(e) =>
                patch({ stress_level: e.target.value ? Number(e.target.value) : null })
              }
            >
              <option value="">Keine Angabe</option>
              <option value="1">1 — sehr entspannt</option>
              <option value="2">2 — entspannt</option>
              <option value="3">3 — mittel</option>
              <option value="4">4 — fordernd</option>
              <option value="5">5 — sehr fordernd</option>
            </select>
          </Field>
        </div>

        <TextArea
          label="Verletzungen und Einschränkungen"
          hint="Alles, was die KI beim Planen berücksichtigen muss."
          placeholder="z. B. Achillessehnenreizung links, Schulterprobleme beim Kraulen"
          value={profile.injuries}
          onChange={(v) => patch({ injuries: v })}
        />

        {garminBestzeiten.length > 0 && (
          <Field
            label="Bestzeiten aus Garmin"
            hint="Von Garmin erkannt und bei jedem Abgleich aktualisiert. Garmin führt sie nur fürs Laufen — Schwimmen und Rad trägst du unten ein."
          >
            <div className="table-wrap">
              <table className="table-cards">
                <thead>
                  <tr>
                    <th>Strecke</th>
                    <th>Zeit</th>
                    <th>Datum</th>
                  </tr>
                </thead>
                <tbody>
                  {garminBestzeiten.map((best) => (
                    <tr key={best.strecke}>
                      <td className="cell-title" data-label="Strecke">
                        {best.strecke}
                      </td>
                      <td className="nowrap" data-label="Zeit">
                        <strong>{best.zeit}</strong>
                      </td>
                      <td className="nowrap" data-label="Datum">
                        {best.datum
                          ? new Date(best.datum).toLocaleDateString('de-DE')
                          : '–'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Field>
        )}

        <TextArea
          label={garminBestzeiten.length > 0 ? 'Weitere Bestzeiten' : 'Bestzeiten'}
          hint={
            garminBestzeiten.length > 0
              ? 'Was Garmin nicht kennt: Schwimmen, Rad, ältere Wettkämpfe.'
              : 'Hilft der KI, dein Leistungsniveau einzuschätzen.'
          }
          placeholder="z. B. 10 km in 42:30 (2025), Halbmarathon 1:38"
          value={profile.personal_bests}
          onChange={(v) => patch({ personal_bests: v })}
        />

        <TextArea
          label="Sonstiges"
          placeholder="Was sonst noch wichtig ist."
          value={profile.notes}
          onChange={(v) => patch({ notes: v })}
        />
      </div>

      {history.length > 1 && (
        <div className="card">
          <h2>Verlauf deiner Werte</h2>
          <p className="small muted">
            Jede Änderung an Gewicht, Ruhepuls, HRV, VO2max, Maximalpuls oder FTP wird
            hier festgehalten und geht als Trend in den nächsten Plan ein.
          </p>
          <div className="table-wrap">
            <table className="table-cards">
              <thead>
                <tr>
                  <th>Datum</th>
                  <th>Gewicht</th>
                  <th>Ruhepuls</th>
                  <th>HRV</th>
                  <th>VO2max</th>
                  <th>FTP</th>
                </tr>
              </thead>
              <tbody>
                {[...history].reverse().map((entry, index) => (
                  <tr key={`${entry.recorded_at}-${index}`}>
                    <td className="nowrap cell-title" data-label="Stand">
                      {new Date(entry.recorded_at).toLocaleDateString('de-DE')}
                    </td>
                    <td data-label="Gewicht">{entry.weight_kg ?? '–'}</td>
                    <td data-label="Ruhepuls">{entry.resting_hr ?? '–'}</td>
                    <td data-label="HRV">{entry.hrv_rmssd ?? '–'}</td>
                    <td data-label="VO2max">{entry.vo2max ?? '–'}</td>
                    <td data-label="FTP">{entry.ftp_watts ?? '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="row row-end mt-2">
        <button className="btn btn-primary btn-lg" onClick={save} disabled={busy}>
          {busy ? 'Speichert …' : 'Speichern'}
        </button>
      </div>
    </>
  )
}
