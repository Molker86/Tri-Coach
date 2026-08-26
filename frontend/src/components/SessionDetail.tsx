/**
 * Der Dialog zu einer Einheit — ansehen und neu schreiben lassen.
 *
 * Aus `PlanView` herausgezogen, damit ihn das Dashboard genauso öffnen kann.
 * Das ging ohne Umbau: Die einzige Datenabhängigkeit ist die Einheit selbst,
 * alles andere sind Rückrufe. An der Seite hängt nur die Job-Maschinerie, und
 * die steht jetzt in `useEinheitAnpassung`.
 */

import { useState } from 'react'
import { api } from '../api/client'
import { Alert, Modal } from './ui'
import { INTENSITY_ZONE_COLOR, sessionTypeLabel, sportIcon, sportLabel } from '../constants'
import { heuteIso } from '../planung'
import type { AiExport, EinheitAnpassung, KiJob, PlanSession, SessionLog } from '../types'

export function SessionDetail({
  session,
  kiVerfuegbar,
  anpassungLaeuft,
  onLauf,
  onUebernommen,
  onClose,
}: {
  session: PlanSession
  kiVerfuegbar: boolean
  anpassungLaeuft: boolean
  onLauf: (job: KiJob) => void
  onUebernommen: () => void
  onClose: () => void
}) {
  // Dieselben Grenzen wie im Server (`routers/plans.anpassbare_einheit`): Eine
  // vergangene Einheit umzuschreiben änderte nichts mehr an dem, was
  // stattgefunden hat, und eine absolvierte ist ohnehin Vergangenheit.
  const darfAngepasstWerden = !session.logged && session.date >= heuteIso()
  // Ein Ruhetag trägt keine dieser Angaben — die Überschrift stünde dann über
  // einer leeren Tabelle. Er lässt sich seit dem Anpassen einzelner Einheiten
  // öffnen, weil aus einer Einheit Ruhe werden kann.
  const hatVorgaben = Boolean(
    session.duration_min ||
    session.distance_km ||
    (session.target_hr_low && session.target_hr_high) ||
    session.target_pace ||
    session.target_power ||
    session.rpe_target,
  )

  return (
    <Modal title={session.title} onClose={onClose}>
      <div className="row mb-1">
        <span className="badge">{sportIcon(session.sport)} {sportLabel(session.sport)}</span>
        {session.sport === 'swim' && session.swim_location && (
          <span className="badge">
            {session.swim_location === 'open_water' ? '🌊 Freiwasser' : '🏊 Becken'}
          </span>
        )}
        {session.sport === 'bike' && session.bike_location && (
          <span className="badge">
            {session.bike_location === 'indoor' ? '🏠 Rolle' : '🛣️ Draußen'}
          </span>
        )}
        <span className="badge">{sessionTypeLabel(session.session_type)}</span>
        {session.intensity_zone && (
          <span
            className="badge badge-zone"
            style={{
              background: INTENSITY_ZONE_COLOR[session.intensity_zone] ?? 'var(--surface-3)',
            }}
          >
            {session.intensity_zone}
          </span>
        )}
        <span className="badge">
          {new Date(session.date).toLocaleDateString('de-DE', {
            weekday: 'long',
            day: '2-digit',
            month: '2-digit',
          })}
        </span>
      </div>

      {session.description && <p>{session.description}</p>}

      {session.structure && (
        <>
          <h4>Aufbau</h4>
          <div className="code-box">{session.structure}</div>
        </>
      )}

      {session.purpose && (
        <>
          <h4 className="mt-1">Trainingswirkung</h4>
          <p className="muted">{session.purpose}</p>
        </>
      )}

      {hatVorgaben && (
        <>
          <h4 className="mt-1">Vorgaben</h4>
          <div className="table-wrap">
            <table>
              <tbody>
                {session.duration_min ? (
                  <tr><th>Dauer</th><td>{session.duration_min} min</td></tr>
                ) : null}
                {session.distance_km ? (
                  <tr><th>Distanz</th><td>{session.distance_km} km</td></tr>
                ) : null}
                {session.target_hr_low && session.target_hr_high ? (
                  <tr>
                    <th>Herzfrequenz</th>
                    <td>{session.target_hr_low}–{session.target_hr_high} bpm</td>
                  </tr>
                ) : null}
                {session.target_pace ? (
                  <tr><th>Pace</th><td>{session.target_pace}</td></tr>
                ) : null}
                {session.target_power ? (
                  <tr><th>Leistung</th><td>{session.target_power}</td></tr>
                ) : null}
                {session.rpe_target ? (
                  <tr><th>Anstrengung (RPE)</th><td>{session.rpe_target} / 10</td></tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </>
      )}

      {session.anpassungswunsch && (
        <p className="small faint mt-1 mb-0">
          ✎ Diese Einheit wurde angepasst — auf den Wunsch „{session.anpassungswunsch}“.
        </p>
      )}

      {/* Kein Weg zum Erfassen mehr: Die Einheit wird als absolviert markiert,
          sobald der Garmin-Abgleich eine Aktivität findet, die aus dem
          übertragenen Workout gestartet wurde (`garmin/matching.py`). An einem
          Ruhetag gibt es nichts zu erfassen — der Satz wäre dort eine Zusage
          ins Leere. */}
      {session.sport !== 'rest' && (
        <div className="mt-2">
          {session.logged ? (
            <Verknuepfung session={session} onGeloest={onUebernommen} />
          ) : (
            <Zuordnung session={session} onZugeordnet={onUebernommen} />
          )}
        </div>
      )}

      {darfAngepasstWerden && (
        <Anpassung
          session={session}
          kiVerfuegbar={kiVerfuegbar}
          anpassungLaeuft={anpassungLaeuft}
          onLauf={onLauf}
          onUebernommen={onUebernommen}
        />
      )}
    </Modal>
  )
}

/** Das erfasste Training — und der Weg, es dieser Einheit wieder abzusprechen.
 *
 * Die einzige Korrektur an einer importierten Einheit, die es gibt. Nötig, weil
 * die Uhr die Workout-Kennung auch dann setzt, wenn die Vorlage nur zum
 * Aufzeichnen lief und etwas ganz anderes daraus wurde.
 */
function Verknuepfung({
  session,
  onGeloest,
}: {
  session: PlanSession
  onGeloest: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [fehler, setFehler] = useState<string | null>(null)

  async function loese() {
    if (
      !confirm(
        'Dieses Training zählt nicht als „' +
          session.title +
          '“?\n\nEs bleibt vollständig im Verlauf und in den Kennzahlen — nur die ' +
          'Einheit gilt danach wieder als nicht absolviert.',
      )
    )
      return

    setFehler(null)
    setBusy(true)
    try {
      await api.verknuepfungLoesen(session.id)
      onGeloest()
    } catch (err) {
      setFehler(err instanceof Error ? err.message : 'Lösen fehlgeschlagen.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="row row-end">
      {fehler && <Alert kind="error">{fehler}</Alert>}
      <span className="badge badge-success">Training bereits erfasst</span>
      <button className="btn btn-ghost btn-sm" disabled={busy} onClick={loese}>
        {busy ? 'Wird gelöst …' : 'Zählt nicht als diese Einheit'}
      </button>
    </div>
  )
}

/** Ein absolviertes Training aus den Nachbartagen dieser Einheit zuschreiben.
 *
 * Gegenstück zu `Verknuepfung`. Nötig, weil die Zuordnung sonst allein an der
 * Workout-Kennung hängt (`garmin/matching.py`): Wer auf der Uhr einen älteren
 * Kalendereintrag startet oder wem Garmin das Aktivitätsdetail schuldig
 * bleibt, bekommt keine — und die tatsächlich absolvierte Einheit stünde für
 * immer als nicht umgesetzt da.
 *
 * An einem künftigen Tag gibt es nichts zuzuordnen; dort bleibt es beim
 * Hinweis, wie bisher.
 */
function Zuordnung({
  session,
  onZugeordnet,
}: {
  session: PlanSession
  onZugeordnet: () => void
}) {
  const [logs, setLogs] = useState<SessionLog[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [fehler, setFehler] = useState<string | null>(null)

  const hinweis = (
    <span className="small muted">
      Wird als absolviert markiert, sobald die Einheit aus dem Workout auf der
      Uhr kommt.
    </span>
  )

  if (session.date > heuteIso()) {
    return <div className="row row-end">{hinweis}</div>
  }

  async function lade() {
    setFehler(null)
    setBusy(true)
    try {
      setLogs(await api.zuordenbareLogs(session.id))
    } catch (err) {
      setFehler(err instanceof Error ? err.message : 'Laden fehlgeschlagen.')
    } finally {
      setBusy(false)
    }
  }

  async function ordneZu(log: SessionLog) {
    setFehler(null)
    setBusy(true)
    try {
      await api.verknuepfungSetzen(session.id, log.id)
      onZugeordnet()
    } catch (err) {
      setFehler(err instanceof Error ? err.message : 'Zuordnen fehlgeschlagen.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="row row-end">
        {hinweis}
        {logs === null && (
          <button className="btn btn-ghost btn-sm" disabled={busy} onClick={lade}>
            {busy ? 'Wird geladen …' : 'Von Hand zuordnen'}
          </button>
        )}
      </div>

      {fehler && <Alert kind="error">{fehler}</Alert>}

      {logs !== null &&
        (logs.length === 0 ? (
          <p className="small muted mt-1 mb-0">
            Um diesen Tag herum liegt kein Training, das noch keiner Einheit
            zugeordnet ist.
          </p>
        ) : (
          <div className="mt-1">
            <p className="small muted mb-1">
              Welches Training zählt als „{session.title}“? Es bleibt dabei
              unverändert im Verlauf — zugeordnet wird nur die Vorgabe.
            </p>
            <div className="row">
              {logs.map((log) => (
                <button
                  key={log.id}
                  className="btn btn-ghost btn-sm btn-block"
                  disabled={busy}
                  onClick={() => ordneZu(log)}
                >
                  {trainingZeile(log)}
                </button>
              ))}
            </div>
          </div>
        ))}
    </>
  )
}

/** Ein Training in einer Zeile — genug, um es wiederzuerkennen, nicht mehr. */
function trainingZeile(log: SessionLog): string {
  const teile = [
    new Date(log.date).toLocaleDateString('de-DE', {
      day: '2-digit',
      month: '2-digit',
    }),
    `${sportIcon(log.sport)} ${sportLabel(log.sport)}`,
  ]
  if (log.duration_min) teile.push(`${log.duration_min} min`)
  if (log.distance_km) {
    teile.push(`${log.distance_km.toFixed(1).replace('.', ',')} km`)
  }
  return teile.join(' · ')
}

/** Eine einzelne Einheit umschreiben lassen — Freitext hinein, Einheit heraus.
 *
 * Zwei Wege wie überall in dieser App: der Knopf, wenn ein Claude-Zugang
 * hinterlegt ist, und darunter der Weg über die Zwischenablage als
 * Rückfallebene. Beide schicken denselben Text an dieselbe Stelle — der Server
 * baut ihn aus einer Funktion, damit sie nicht auseinanderlaufen können.
 */
function Anpassung({
  session,
  kiVerfuegbar,
  anpassungLaeuft,
  onLauf,
  onUebernommen,
}: {
  session: PlanSession
  kiVerfuegbar: boolean
  anpassungLaeuft: boolean
  onLauf: (job: KiJob) => void
  onUebernommen: () => void
}) {
  const [wunsch, setWunsch] = useState('')
  const [busy, setBusy] = useState(false)
  const [fehler, setFehler] = useState<string | null>(null)

  // Nur für den Handweg: erzeugter Prompt, eingefügte Antwort, Ergebnis.
  const [exported, setExported] = useState<AiExport | null>(null)
  const [raw, setRaw] = useState('')
  const [kopiert, setKopiert] = useState(false)
  const [ergebnis, setErgebnis] = useState<EinheitAnpassung | null>(null)

  const bereit = wunsch.trim().length >= 3

  async function planeMitKi() {
    setFehler(null)
    setBusy(true)
    try {
      onLauf(await api.kiEinheitAnpassen(session.id, wunsch.trim()))
    } catch (err) {
      setFehler(err instanceof Error ? err.message : 'Der Lauf ließ sich nicht starten.')
    } finally {
      setBusy(false)
    }
  }

  /**
   * Der Text wird erst erzeugt und dann kopiert, in zwei Schritten. Ihn beim
   * Druck auf „Kopieren" zu holen ginge auch — nur blockieren Browser den
   * Zugriff auf die Zwischenablage, wenn zwischen Klick und Schreiben eine
   * Anfrage liegt.
   */
  async function erzeugeText() {
    setFehler(null)
    setBusy(true)
    try {
      setExported(await api.einheitAnpassungExport(session.id, wunsch.trim()))
    } catch (err) {
      setFehler(err instanceof Error ? err.message : 'Text konnte nicht erzeugt werden.')
    } finally {
      setBusy(false)
    }
  }

  async function kopiere() {
    if (!exported) return
    try {
      await navigator.clipboard.writeText(exported.combined)
      setKopiert(true)
      setTimeout(() => setKopiert(false), 2500)
    } catch {
      setFehler(
        'Der Zugriff auf die Zwischenablage wurde blockiert. Markiere den Text ' +
          'unten und kopiere ihn manuell.',
      )
    }
  }

  async function uebernimm() {
    setFehler(null)
    setBusy(true)
    try {
      setErgebnis(await api.einheitAnpassen(session.id, raw, wunsch.trim()))
    } catch (err) {
      setFehler(err instanceof Error ? err.message : 'Übernehmen fehlgeschlagen.')
    } finally {
      setBusy(false)
    }
  }

  const eingabe = (
    <>
      <textarea
        className="paste-area"
        rows={3}
        value={wunsch}
        placeholder="z. B. „Ich habe heute nur 40 Minuten Zeit“ oder „Mein Knie zwickt, bitte etwas Schonendes“"
        onChange={(e) => {
          setWunsch(e.target.value)
          // Der erzeugte Text gilt für den alten Wunsch — sonst kopierte man
          // eine Aufgabe, die nicht mehr die eigene ist.
          setExported(null)
        }}
      />
      <p className="small faint mt-1">
        Die KI bekommt dabei alles, was sie auch zum Planen eines Blocks bekommt: Profil,
        Herzfrequenzzonen, vier Wochen Historie, die Fitnessdaten aus Garmin — und den
        Block, in dem diese Einheit steht. Der Tag bleibt, wie er ist.
      </p>
    </>
  )

  return (
    <div className="mt-2">
      <h4>Diese Einheit anpassen</h4>
      {fehler && <Alert kind="error">{fehler}</Alert>}

      {kiVerfuegbar ? (
        <>
          {eingabe}
          <div className="row">
            <button
              className="btn btn-primary"
              onClick={planeMitKi}
              disabled={!bereit || busy || anpassungLaeuft}
            >
              {busy ? 'Wird gestartet …' : 'Von Claude anpassen lassen'}
            </button>
            {anpassungLaeuft && (
              <span className="small faint">
                Es läuft bereits eine Anpassung — bitte warte, bis sie fertig ist.
              </span>
            )}
          </div>
        </>
      ) : (
        eingabe
      )}

      <details className="mt-1" open={!kiVerfuegbar}>
        <summary className="small muted" style={{ cursor: 'pointer' }}>
          {kiVerfuegbar
            ? 'Stattdessen von Hand: Text kopieren und Antwort einfügen'
            : 'Text kopieren und Antwort einfügen'}
        </summary>

        <div className="row mt-1">
          <button
            className="btn btn-secondary btn-sm"
            onClick={erzeugeText}
            disabled={!bereit || busy}
          >
            Text erzeugen
          </button>
          {exported && (
            <button className="btn btn-secondary btn-sm" onClick={kopiere}>
              {kopiert ? '✓ Kopiert' : 'Text kopieren'}
            </button>
          )}
        </div>

        {exported && (
          <details className="mt-1">
            <summary className="small muted" style={{ cursor: 'pointer' }}>
              Text anzeigen ({Math.round(exported.combined.length / 1024)} KB)
            </summary>
            <div className="code-box mt-1">{exported.combined}</div>
          </details>
        )}

        <textarea
          className="paste-area mt-1"
          rows={4}
          value={raw}
          placeholder='{"einheit": { … }}'
          onChange={(e) => {
            setRaw(e.target.value)
            setErgebnis(null)
          }}
        />
        <button
          className="btn btn-primary btn-sm"
          onClick={uebernimm}
          disabled={!raw.trim() || !bereit || busy}
        >
          {busy ? 'Wird übernommen …' : 'Angepasste Einheit übernehmen'}
        </button>

        {ergebnis && <AnpassungsErgebnis ergebnis={ergebnis} onFertig={onUebernommen} />}
      </details>
    </div>
  )
}

/** Was beim Handweg herauskam — Begründung, Hinweise und der Stand in Garmin. */
function AnpassungsErgebnis({
  ergebnis,
  onFertig,
}: {
  ergebnis: EinheitAnpassung
  onFertig: () => void
}) {
  const garminText = {
    uebertragen: 'Sie liegt in der neuen Fassung im Garmin-Kalender.',
    entfernt: 'Der Tag ist jetzt frei — die alte Vorgabe wurde aus Garmin genommen.',
    keine: null,
  }[ergebnis.garmin]

  return (
    <Alert kind="success">
      <strong>{ergebnis.session.title}</strong> — übernommen.
      {ergebnis.begruendung && <p className="mb-0 mt-1">{ergebnis.begruendung}</p>}
      {garminText && <p className="small mb-0 mt-1">{garminText}</p>}
      {ergebnis.garmin_hinweis && (
        <p className="small mb-0 mt-1">{ergebnis.garmin_hinweis}</p>
      )}
      {ergebnis.warnings.length > 0 && (
        <ul className="small mb-0">
          {ergebnis.warnings.map((warnung) => (
            <li key={warnung}>{warnung}</li>
          ))}
        </ul>
      )}
      <div className="row row-end mt-1">
        <button className="btn btn-primary btn-sm" onClick={onFertig}>
          Zum Plan
        </button>
      </div>
    </Alert>
  )
}
