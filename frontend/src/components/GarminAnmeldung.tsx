/**
 * Das Garmin-Anmeldeformular — samt Bestätigungscode.
 *
 * Eigene Datei, seit es in den Einstellungen steht statt auf der Garmin-Seite:
 * Wo ein Konto verbunden wird, gehört zu dem, was die App ohne Zutun tut, und
 * das steht an einem Ort. `/garmin` behält den Abgleich selbst.
 *
 * Der Zustand liegt hier drin und nicht beim Aufrufer: Das Passwort und die
 * angefangene Bestätigung sind Sache dieses Formulars und sollen die Seite
 * darum herum nicht mitschleppen.
 */

import { useState } from 'react'
import { ApiError, api } from '../api/client'
import { Alert, TextField } from './ui'

export default function GarminAnmeldung(props: {
  onVerbunden: () => void
  onFehler: (meldung: string) => void
}) {
  const [email, setEmail] = useState<string | null>(null)
  const [passwort, setPasswort] = useState<string | null>(null)
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [mfaHinweis, setMfaHinweis] = useState<string | null>(null)
  const [code, setCode] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handle(aktion: () => Promise<void>) {
    setBusy(true)
    try {
      await aktion()
    } catch (err) {
      props.onFehler(
        err instanceof ApiError || err instanceof Error
          ? err.message
          : 'Etwas ist schiefgelaufen.',
      )
    } finally {
      setBusy(false)
    }
  }

  function verbinde() {
    if (!email || !passwort) {
      props.onFehler('Bitte E-Mail-Adresse und Passwort eingeben.')
      return
    }
    void handle(async () => {
      const ergebnis = await api.garminConnect(email, passwort)
      // Das Passwort verlässt den Zustand sofort wieder — es wird weder
      // gespeichert noch für den zweiten Schritt gebraucht.
      setPasswort(null)
      if (ergebnis.status === 'mfa_erforderlich') {
        setPendingId(ergebnis.pending_id ?? null)
        setMfaHinweis(ergebnis.hinweis ?? null)
      } else {
        props.onVerbunden()
      }
    })
  }

  function sendeCode() {
    if (!pendingId || !code) return
    void handle(async () => {
      await api.garminMfa(pendingId, code)
      setPendingId(null)
      setCode(null)
      setMfaHinweis(null)
      props.onVerbunden()
    })
  }

  if (pendingId) {
    return (
      <div className="stack">
        <Alert kind="info">
          {mfaHinweis ??
            'Garmin hat dir einen Bestätigungscode geschickt. Bitte gib ihn ein.'}
        </Alert>
        <TextField
          label="Code"
          value={code}
          onChange={setCode}
          placeholder="123456"
          autoComplete="one-time-code"
        />
        <div className="row row-end">
          <button
            className="btn btn-primary"
            onClick={sendeCode}
            disabled={busy || !code}
          >
            {busy ? 'Wird geprüft …' : 'Bestätigen'}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="stack">
      <p className="muted">
        Melde dich einmalig mit deinen Garmin-Zugangsdaten an. Das Passwort wird
        <strong> nicht gespeichert</strong> — die App merkt sich nur den
        Zugangsschlüssel, den Garmin dafür ausstellt, und legt ihn verschlüsselt
        ab.
      </p>
      <TextField
        label="Garmin-E-Mail"
        type="email"
        value={email}
        onChange={setEmail}
        autoComplete="username"
      />
      <TextField
        label="Passwort"
        type="password"
        value={passwort}
        onChange={setPasswort}
        autoComplete="current-password"
      />
      <Alert kind="warning">
        Garmin sperrt ein Konto nach wenigen fehlgeschlagenen Anmeldungen für bis
        zu 48 Stunden. Bitte prüfe die Eingabe, bevor du es erneut versuchst.
      </Alert>
      <div className="row row-end">
        <button className="btn btn-primary" onClick={verbinde} disabled={busy}>
          {busy ? 'Verbindet …' : 'Verbinden'}
        </button>
      </div>
    </div>
  )
}
