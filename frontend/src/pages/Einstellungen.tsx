/**
 * Was die App ohne Zutun tut — und womit sie es tut.
 *
 * Die Schalter gab es teils schon, aber verstreut: die Garmin-Automatik mitten
 * auf der Verbindungsseite, Modell und Denktiefe der KI überhaupt nur über die
 * API, und der Claude-Zugang ausschließlich in den Add-on-Optionen von Home
 * Assistant — wofür man die App verlassen und das Add-on neu starten musste.
 *
 * Gespeichert wird sofort, ohne Speichern-Knopf; dieselbe Handhabung wie bisher
 * auf der Garmin-Seite. Die Ausnahme ist der Token: Ein Zugang, der beim Tippen
 * zeichenweise gespeichert würde, stünde die halbe Zeit als unbrauchbar da.
 */

import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import GarminAnmeldung from '../components/GarminAnmeldung'
import { Alert, Field, Loading, TextField } from '../components/ui'
import { type Farbwahl, leseFarbwahl, setzeFarbwahl } from '../theme'
import { WEEKDAYS } from '../constants'
import type {
  BringStatus,
  GarminStatus,
  KiSettings,
  KiSettingsIn,
  KiStatus,
} from '../types'

const STUNDEN = Array.from({ length: 24 }, (_, i) => i)
// Fünferschritte: Die Schleife wacht zwar minütlich auf, aber eine Liste mit
// sechzig Einträgen zu durchsuchen, um „so ungefähr um neun" auszudrücken, ist
// kein Gewinn an Genauigkeit.
const MINUTEN = Array.from({ length: 12 }, (_, i) => i * 5)

const MODELLE = [
  { wert: '', text: 'Vorgabe' },
  { wert: 'opus', text: 'Opus — am stärksten' },
  { wert: 'sonnet', text: 'Sonnet — schneller, günstiger' },
  { wert: 'haiku', text: 'Haiku — am sparsamsten' },
]

const DENKTIEFEN: { wert: KiSettings['effort']; text: string }[] = [
  { wert: '', text: 'Vorgabe' },
  { wert: 'low', text: 'niedrig' },
  { wert: 'medium', text: 'mittel' },
  { wert: 'high', text: 'hoch' },
  { wert: 'xhigh', text: 'sehr hoch' },
  { wert: 'max', text: 'maximal' },
]

const FARBWAHLEN: { wert: Farbwahl; text: string }[] = [
  { wert: 'system', text: 'Wie das System' },
  { wert: 'light', text: 'Hell' },
  { wert: 'dark', text: 'Dunkel' },
]

export default function Einstellungen() {
  const [garmin, setGarmin] = useState<GarminStatus | null>(null)
  const [ki, setKi] = useState<KiStatus | null>(null)
  const [bring, setBring] = useState<BringStatus | null>(null)
  const [fehler, setFehler] = useState<string | null>(null)
  const [erfolg, setErfolg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [geladen, setGeladen] = useState(false)

  const lade = useCallback(async () => {
    try {
      const [g, k, b] = await Promise.all([
        api.garminStatus(),
        api.kiStatus(),
        api.bringStatus(),
      ])
      setGarmin(g)
      setKi(k)
      setBring(b)
    } catch (err) {
      setFehler(err instanceof Error ? err.message : 'Etwas ist schiefgelaufen.')
    } finally {
      setGeladen(true)
    }
  }, [])

  useEffect(() => {
    void lade()
  }, [lade])

  async function handle<T>(aktion: () => Promise<T>, meldung?: string) {
    setBusy(true)
    setFehler(null)
    setErfolg(null)
    try {
      await aktion()
      if (meldung) setErfolg(meldung)
      await lade()
    } catch (err) {
      setFehler(
        err instanceof ApiError || err instanceof Error
          ? err.message
          : 'Etwas ist schiefgelaufen.',
      )
    } finally {
      setBusy(false)
    }
  }

  if (!geladen) return <Loading text="Einstellungen werden geladen …" />

  return (
    <div className="page page-narrow">
      <div className="page-header">
        <div>
          <h1>Einstellungen</h1>
          <p className="muted">
            Was die App von selbst erledigt, und mit welchem Zugang sie das tut.
          </p>
        </div>
      </div>

      {fehler && <Alert kind="error">{fehler}</Alert>}
      {erfolg && <Alert kind="success">{erfolg}</Alert>}

      <GarminKarte
        zustand={garmin}
        busy={busy}
        onAendern={(daten) => void handle(() => api.garminSettings(daten))}
        onVerbunden={() => {
          setFehler(null)
          setErfolg('Garmin-Konto verbunden.')
          void lade()
        }}
        onFehler={setFehler}
        onTrennen={() =>
          void handle(api.garminDisconnect, 'Verbindung zu Garmin getrennt.')
        }
      />

      <BringKarte
        zustand={bring}
        busy={busy}
        onAendern={(daten, meldung) =>
          void handle(() => api.bringSettings(daten), meldung)
        }
        onTrennen={() =>
          void handle(api.bringTrennen, 'Bring-Konto entfernt.')
        }
      />

      <KiKarte
        zustand={ki}
        busy={busy}
        onAendern={(daten, meldung) =>
          void handle(() => api.kiSettings(daten), meldung)
        }
        onPruefen={() =>
          void handle(async () => {
            const neu = await api.kiPruefen()
            if (!neu.verfuegbar) throw new Error(ZUGANG_FEHLT)
          }, 'Der Zugang trägt — die App kann selbst planen.')
        }
      />

      <DarstellungsKarte />
    </div>
  )
}

const ZUGANG_FEHLT =
  'Claude Code meldet sich nicht als angemeldet. Prüfe das Token oder erzeuge ' +
  'mit `claude setup-token` ein neues.'

// --------------------------------------------------------------------------
// Garmin
// --------------------------------------------------------------------------

function GarminKarte(props: {
  zustand: GarminStatus | null
  busy: boolean
  onAendern: (daten: {
    auto_sync_enabled?: boolean
    sync_hour?: number
    sync_minute?: number
    profile_sync_enabled?: boolean
    auto_push_enabled?: boolean
  }) => void
  onVerbunden: () => void
  onFehler: (meldung: string) => void
  onTrennen: () => void
}) {
  const konto = props.zustand?.konto ?? null

  return (
    <div className="card">
      <div className="card-title">
        <h2>Garmin</h2>
        {konto !== null && (
          <button
            className="btn btn-ghost btn-sm"
            disabled={props.busy}
            onClick={() => {
              if (
                confirm(
                  'Verbindung zu Garmin trennen?\n\n' +
                    'Deine bereits importierten Trainings und Fitnessdaten ' +
                    'bleiben erhalten.',
                )
              )
                props.onTrennen()
            }}
          >
            Trennen
          </button>
        )}
      </div>

      {konto === null ? (
        <GarminAnmeldung
          onVerbunden={props.onVerbunden}
          onFehler={props.onFehler}
        />
      ) : (
        <div className="stack">
          <p className="muted small mb-0">
            Verbunden als {konto.email}. Abgleich, Rückblick und Kalender stehen
            unter <Link to="/garmin">Garmin</Link>.
          </p>

          <label className="check-row">
            <input
              type="checkbox"
              checked={konto.auto_sync_enabled}
              disabled={props.busy}
              onChange={(e) => props.onAendern({ auto_sync_enabled: e.target.checked })}
            />
            <span>
              Trainingsdaten täglich automatisch holen
              <span className="field-hint">
                Läuft im Hintergrund — die App muss dafür nicht geöffnet sein.
              </span>
            </span>
          </label>

          <Field
            label="Ab welcher Uhrzeit"
            hint={
              'Die App sieht minütlich nach. War der Rechner um diese Zeit aus, ' +
              'wird es nach dem nächsten Start nachgeholt.'
            }
          >
            <div className="uhrzeit-wahl">
              <select
                value={konto.sync_hour}
                disabled={props.busy || !konto.auto_sync_enabled}
                onChange={(e) => props.onAendern({ sync_hour: Number(e.target.value) })}
              >
                {STUNDEN.map((stunde) => (
                  <option key={stunde} value={stunde}>
                    {String(stunde).padStart(2, '0')}
                  </option>
                ))}
              </select>
              <span aria-hidden="true">:</span>
              <select
                value={konto.sync_minute}
                disabled={props.busy || !konto.auto_sync_enabled}
                onChange={(e) => props.onAendern({ sync_minute: Number(e.target.value) })}
              >
                {MINUTEN.map((minute) => (
                  <option key={minute} value={minute}>
                    {String(minute).padStart(2, '0')}
                  </option>
                ))}
              </select>
              <span className="uhrzeit-einheit">Uhr</span>
            </div>
          </Field>

          <label className="check-row">
            <input
              type="checkbox"
              checked={konto.auto_push_enabled}
              disabled={props.busy}
              onChange={(e) => props.onAendern({ auto_push_enabled: e.target.checked })}
            />
            <span>
              Neue Trainingspläne sofort in den Garmin-Kalender legen
              <span className="field-hint">
                Sobald du einen Block übernimmst, wandern seine Einheiten als
                Workouts auf die Uhr — und die Einheiten des abgelösten Blocks
                verschwinden aus dem Kalender. Ohne den Haken bleibt es beim Knopf
                im Trainingsplan.
              </span>
            </span>
          </label>

          <label className="check-row">
            <input
              type="checkbox"
              checked={konto.profile_sync_enabled}
              disabled={props.busy}
              onChange={(e) =>
                props.onAendern({ profile_sync_enabled: e.target.checked })
              }
            />
            <span>
              Gewicht, Ruhepuls, HRV, VO2max, Schwellenpuls und Bestzeiten ins
              Profil übernehmen
              <span className="field-hint">
                Bestzeiten sind die von Garmin erkannten Laufrekorde. Unangetastet
                bleiben der Maximalpuls — Garmin schätzt ihn, und er bestimmt alle
                Herzfrequenzzonen — sowie FTP, Schwellenpace und CSS: Die trägst du
                unter „Meine Daten“ selbst ein.
              </span>
            </span>
          </label>
        </div>
      )}
    </div>
  )
}

// --------------------------------------------------------------------------
// Bring
// --------------------------------------------------------------------------

function BringKarte(props: {
  zustand: BringStatus | null
  busy: boolean
  onAendern: (
    daten: { email?: string; passwort?: string; list_uuid?: string },
    meldung?: string,
  ) => void
  onTrennen: () => void
}) {
  const konto = props.zustand?.konto ?? null
  const listen = props.zustand?.listen ?? []

  const [email, setEmail] = useState<string | null>(null)
  const [passwort, setPasswort] = useState<string | null>(null)
  // Wie beim Claude-Zugang: Solange ein Passwort liegt, bleibt das Feld zu —
  // zurücklesen lässt es sich nicht, ein leeres Feld sähe nach „keines" aus.
  const [tippt, setTippt] = useState(false)

  const feldOffen = tippt || konto === null || konto.passwort_status !== 'hinterlegt'

  return (
    <div className="card">
      <div className="card-title">
        <h2>Bring</h2>
        {konto !== null && (
          <button
            className="btn btn-ghost btn-sm"
            disabled={props.busy}
            onClick={() => {
              if (confirm('Bring-Konto entfernen?')) props.onTrennen()
            }}
          >
            Entfernen
          </button>
        )}
      </div>
      <p className="muted small">
        Mit hinterlegtem Konto wandern die Zutaten deines Ernährungsplans auf
        Knopfdruck auf die Einkaufsliste — zusammengezählt über alle Tage. Steht
        dort schon etwas davon, wird die Menge dazugerechnet statt ein zweites
        Mal angelegt.
      </p>

      {konto?.passwort_status === 'unlesbar' && (
        <Alert kind="warning">
          Das hinterlegte Passwort lässt sich nicht mehr entschlüsseln — das
          passiert, wenn sich der Schlüssel des Add-ons geändert hat. Trage es
          bitte neu ein.
        </Alert>
      )}
      {konto?.status === 'error' && konto.status_message && (
        <Alert kind="warning">{konto.status_message}</Alert>
      )}

      <div className="stack">
        <TextField
          label="Bring-E-Mail"
          type="email"
          value={email ?? konto?.email ?? ''}
          onChange={setEmail}
          autoComplete="username"
        />

        {feldOffen ? (
          <>
            <TextField
              label="Passwort"
              type="password"
              value={passwort}
              onChange={setPasswort}
              autoComplete="current-password"
            />
            <p className="small muted">
              Anders als bei Garmin wird das Passwort gespeichert —
              verschlüsselt. Bring stellt keinen dauerhaften Zugangsschlüssel
              aus, den die App stattdessen behalten könnte.
            </p>
          </>
        ) : (
          <Field label="Passwort" hint="Verschlüsselt hinterlegt.">
            <div className="row">
              <button
                className="btn btn-secondary btn-sm"
                disabled={props.busy}
                onClick={() => setTippt(true)}
              >
                Ersetzen
              </button>
            </div>
          </Field>
        )}

        <div className="row row-end">
          <button
            className="btn btn-primary"
            disabled={props.busy || (feldOffen && !passwort && !email)}
            onClick={() => {
              const daten: { email?: string; passwort?: string } = {}
              const neueMail = (email ?? '').trim()
              if (neueMail) daten.email = neueMail
              if (passwort) daten.passwort = passwort
              setPasswort(null)
              setTippt(false)
              props.onAendern(daten, 'Bring-Zugang gespeichert.')
            }}
          >
            {props.busy ? 'Wird geprüft …' : 'Speichern und prüfen'}
          </button>
        </div>

        {listen.length > 0 && (
          <Field
            label="Einkaufsliste"
            hint="Wohin die Zutaten aus dem Ernährungsplan geschrieben werden."
          >
            <select
              value={konto?.list_uuid ?? ''}
              disabled={props.busy}
              onChange={(e) => props.onAendern({ list_uuid: e.target.value })}
            >
              <option value="" disabled>
                Bitte wählen …
              </option>
              {listen.map((liste) => (
                <option key={liste.uuid} value={liste.uuid}>
                  {liste.name}
                </option>
              ))}
            </select>
          </Field>
        )}

        {konto !== null && konto.status === 'connected' && listen.length === 0 && (
          <p className="small muted mb-0">
            Zu diesem Konto ist keine Einkaufsliste zu sehen. Lege in der
            Bring-App eine an.
          </p>
        )}
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------
// KI-Planung
// --------------------------------------------------------------------------

function KiKarte(props: {
  zustand: KiStatus | null
  busy: boolean
  onAendern: (daten: Partial<KiSettingsIn>, meldung?: string) => void
  onPruefen: () => void
}) {
  const einstellungen = props.zustand?.einstellungen ?? null
  const hatToken = einstellungen?.token_status === 'hinterlegt'
  // Solange ein Zugang hinterlegt ist, steht das Feld nicht offen: Der Wert
  // lässt sich nicht zurücklesen, ein leeres Feld sähe also aus, als wäre
  // keiner da.
  const [tippt, setTippt] = useState(false)
  const [token, setToken] = useState<string | null>(null)

  if (einstellungen === null) return null

  const feldOffen = tippt || einstellungen.token_status !== 'hinterlegt'

  return (
    <div className="card">
      <h2>KI-Planung</h2>
      <p className="muted small">
        Mit hinterlegtem Zugang plant die App den nächsten Block selbst, statt
        dass du Prompt und Antwort durch die Zwischenablage trägst. Der Weg über
        die Zwischenablage bleibt in jedem Fall.
      </p>

      {einstellungen.token_status === 'unlesbar' && (
        <Alert kind="warning">
          Der hinterlegte Zugang lässt sich nicht mehr entschlüsseln — das
          passiert, wenn sich der Schlüssel des Add-ons geändert hat. Trage ihn
          bitte neu ein.
        </Alert>
      )}
      {einstellungen.status !== 'ready' && einstellungen.status_message && (
        <Alert kind="warning">{einstellungen.status_message}</Alert>
      )}

      <div className="stack">
        {feldOffen ? (
          <>
            <TextField
              label="Claude-Token"
              type="password"
              autoComplete="off"
              placeholder="sk-ant-oat01-…"
              hint="Auf einem Rechner mit Claude Code mit `claude setup-token` erzeugen."
              value={token}
              onChange={setToken}
            />
            <div className="row">
              <button
                className="btn btn-primary"
                disabled={props.busy || !token}
                onClick={() => {
                  props.onAendern({ token: token ?? '' }, 'Der Zugang ist gespeichert.')
                  setToken(null)
                  setTippt(false)
                }}
              >
                Speichern
              </button>
              {hatToken && (
                <button
                  className="btn btn-secondary"
                  disabled={props.busy}
                  onClick={() => {
                    setToken(null)
                    setTippt(false)
                  }}
                >
                  Abbrechen
                </button>
              )}
            </div>
          </>
        ) : (
          <Field label="Claude-Token" hint="Gespeichert und verschlüsselt abgelegt.">
            <div className="row">
              <span className="badge badge-success">✓ hinterlegt</span>
              <button
                className="btn btn-secondary"
                disabled={props.busy}
                onClick={() => setTippt(true)}
              >
                Ersetzen
              </button>
              <button
                className="btn btn-secondary"
                disabled={props.busy}
                onClick={() => props.onAendern({ token: '' }, 'Der Zugang ist entfernt.')}
              >
                Entfernen
              </button>
            </div>
          </Field>
        )}

        <div className="row">
          <button
            className="btn btn-secondary"
            disabled={props.busy}
            onClick={props.onPruefen}
          >
            Verbindung prüfen
          </button>
          <span className="small muted">
            {props.zustand?.verfuegbar
              ? 'Die App kann selbst planen.'
              : 'Kein nutzbarer Zugang — es bleibt bei der Zwischenablage.'}
          </span>
        </div>

        <hr className="divider" />

        <label className="check-row">
          <input
            type="checkbox"
            checked={einstellungen.auto_plan_enabled}
            disabled={props.busy}
            onChange={(e) => props.onAendern({ auto_plan_enabled: e.target.checked })}
          />
          <span>
            Einmal pro Woche automatisch einen Block planen
            <span className="field-hint">
              Der neue Block deckt sieben Tage ab und ersetzt den laufenden. Kostet{' '}
              <strong>einen Lauf pro Woche</strong> aus dem Kontingent deines
              Claude-Abos — dasselbe Kontingent, das du daneben selbst benutzt.
              {einstellungen.last_auto_plan_on &&
                ` Zuletzt am ${new Date(
                  einstellungen.last_auto_plan_on,
                ).toLocaleDateString('de-DE')}.`}
            </span>
          </span>
        </label>

        <Field
          label="Wann"
          hint={
            'Der Block entsteht aus den Daten, die zu diesem Zeitpunkt da ' +
            'sind — lege ihn deshalb nach den Garmin-Abgleich.'
          }
        >
          <div className="uhrzeit-wahl">
            <select
              value={einstellungen.auto_plan_weekday}
              disabled={props.busy || !einstellungen.auto_plan_enabled}
              onChange={(e) =>
                props.onAendern({ auto_plan_weekday: Number(e.target.value) })
              }
            >
              {WEEKDAYS.map((tag, i) => (
                <option key={tag.key} value={i}>
                  {tag.label}
                </option>
              ))}
            </select>
            <select
              value={einstellungen.auto_plan_hour}
              disabled={props.busy || !einstellungen.auto_plan_enabled}
              onChange={(e) =>
                props.onAendern({ auto_plan_hour: Number(e.target.value) })
              }
            >
              {STUNDEN.map((stunde) => (
                <option key={stunde} value={stunde}>
                  {String(stunde).padStart(2, '0')}
                </option>
              ))}
            </select>
            <span aria-hidden="true">:</span>
            <select
              value={einstellungen.auto_plan_minute}
              disabled={props.busy || !einstellungen.auto_plan_enabled}
              onChange={(e) =>
                props.onAendern({ auto_plan_minute: Number(e.target.value) })
              }
            >
              {MINUTEN.map((minute) => (
                <option key={minute} value={minute}>
                  {String(minute).padStart(2, '0')}
                </option>
              ))}
            </select>
            <span className="uhrzeit-einheit">Uhr</span>
          </div>
        </Field>

        <div className="grid grid-2">
          <Field label="Modell" hint={`Vorgabe: ${props.zustand?.modell ?? '—'}`}>
            <select
              value={einstellungen.model}
              disabled={props.busy}
              onChange={(e) => props.onAendern({ model: e.target.value })}
            >
              {MODELLE.map((m) => (
                <option key={m.wert} value={m.wert}>
                  {m.text}
                </option>
              ))}
            </select>
          </Field>
          <Field
            label="Denktiefe"
            hint={`Vorgabe: ${props.zustand?.effort ?? '—'}. Mehr Denktiefe heißt mehr Kontingent.`}
          >
            <select
              value={einstellungen.effort}
              disabled={props.busy}
              onChange={(e) =>
                props.onAendern({ effort: e.target.value as KiSettings['effort'] })
              }
            >
              {DENKTIEFEN.map((d) => (
                <option key={d.wert} value={d.wert}>
                  {d.text}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------
// Darstellung
// --------------------------------------------------------------------------

function DarstellungsKarte() {
  const [wahl, setWahl] = useState<Farbwahl>(leseFarbwahl)

  return (
    <div className="card">
      <h2>Darstellung</h2>
      <Field
        label="Farben"
        hint="Gilt nur auf diesem Gerät — die Wahl steht im Browser, nicht am Konto."
      >
        <select
          value={wahl}
          onChange={(e) => {
            const neu = e.target.value as Farbwahl
            setWahl(neu)
            setzeFarbwahl(neu)
          }}
        >
          {FARBWAHLEN.map((f) => (
            <option key={f.wert} value={f.wert}>
              {f.text}
            </option>
          ))}
        </select>
      </Field>
    </div>
  )
}
