import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, jobLaeuft, pollJob } from '../api/client'
import { Alert, EmptyState, Loading, Modal, TextArea } from '../components/ui'
import { useHeute } from '../components/useHeute'
import { heuteIso, planErzeugenPfad } from '../planung'
import type {
  Ernaehrungsplan,
  ErnaehrungsProfil,
  ErnaehrungsSpielraum,
  ErnaehrungsTag,
  KiJob,
  KiStatus,
} from '../types'

const WOCHENTAGE = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']

/** Wochentag als Spaltenindex, Montag = 0. */
function montagsIndex(iso: string): number {
  return (new Date(`${iso}T00:00:00`).getDay() + 6) % 7
}

function tagesName(iso: string): string {
  return WOCHENTAGE[montagsIndex(iso)]
}

function kurzdatum(iso: string): string {
  const [, monat, tag] = iso.split('-')
  return `${tag}.${monat}.`
}

export default function Ernaehrung() {
  const heute = useHeute()

  const [plan, setPlan] = useState<Ernaehrungsplan | null>(null)
  const [spielraum, setSpielraum] = useState<ErnaehrungsSpielraum | null>(null)
  const [profil, setProfil] = useState<ErnaehrungsProfil | null>(null)
  const [geladen, setGeladen] = useState(false)

  const [start, setStart] = useState(() => heuteIso())
  const [tage, setTage] = useState<number | null>(null)

  const [kiStatus, setKiStatus] = useState<KiStatus | null>(null)
  const [job, setJob] = useState<KiJob | null>(null)
  const abbrechenRef = useRef<(() => void) | null>(null)

  const [fehler, setFehler] = useState<string | null>(null)
  const [hinweise, setHinweise] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [dialogOffen, setDialogOffen] = useState(false)

  const laedt = useCallback(async () => {
    const [aktiv, raum, prof] = await Promise.all([
      api.ernaehrungAktiv(),
      api.ernaehrungSpielraum(start),
      api.ernaehrungProfil(),
    ])
    setPlan(aktiv)
    setSpielraum(raum)
    setProfil(prof)
    // Die Vorgabe kommt aus dem Server und wird nur gesetzt, solange der Nutzer
    // nichts eigenes eingestellt hat — sonst spränge das Feld bei jedem Laden
    // zurück.
    setTage((bisher) => bisher ?? (raum.vorgabe_tage || null))
    return raum
  }, [start])

  const reloadRef = useRef(laedt)
  useEffect(() => {
    reloadRef.current = laedt
  })

  /** Hängt sich an einen laufenden Lauf und lädt am Ende neu. */
  const beobachte = useCallback((lauf: KiJob) => {
    setJob(lauf)
    abbrechenRef.current?.()
    if (!jobLaeuft(lauf)) return
    abbrechenRef.current = pollJob(
      lauf.id,
      api.kiJob,
      (aktualisiert) => {
        setJob(aktualisiert)
        if (jobLaeuft(aktualisiert)) return
        if (aktualisiert.state === 'done') {
          void reloadRef.current()
        } else if (aktualisiert.message) {
          setFehler(aktualisiert.message)
        }
      },
      (meldung) => setFehler(meldung),
    )
  }, [])

  useEffect(() => {
    laedt()
      .catch((err) =>
        setFehler(err instanceof Error ? err.message : 'Laden fehlgeschlagen.'),
      )
      .finally(() => setGeladen(true))
  }, [laedt])

  useEffect(() => {
    api
      .kiStatus()
      .then((status) => {
        setKiStatus(status)
        // Es gibt genau **einen** aktiven KI-Lauf für alle Aufgaben. Ohne die
        // Prüfung auf `kind` griffe diese Seite den Lauf einer Blockplanung ab
        // und deutete dessen Ende als ihr eigenes.
        if (status.aktiver_job?.kind === 'ernaehrung') beobachte(status.aktiver_job)
      })
      .catch(() => setKiStatus(null))
    return () => abbrechenRef.current?.()
  }, [beobachte])

  const laeuft = jobLaeuft(job)
  const kiVerfuegbar = kiStatus?.verfuegbar === true
  const maxTage = spielraum?.max_tage ?? 0
  const planbar = (spielraum?.hat_trainingsblock ?? false) && maxTage > 0

  async function planeMitKi() {
    setFehler(null)
    setHinweise([])
    setBusy(true)
    try {
      beobachte(await api.kiErnaehrung(start, tage ?? undefined))
    } catch (err) {
      setFehler(
        err instanceof Error ? err.message : 'Der Lauf ließ sich nicht starten.',
      )
    } finally {
      setBusy(false)
    }
  }

  async function brichAb() {
    if (!job) return
    try {
      setJob(await api.kiAbbrechen(job.id))
    } catch {
      // Der Lauf endet ohnehin; eine Fehlermeldung hier hälfe niemandem.
    }
  }

  async function loesche() {
    if (!plan) return
    if (!window.confirm('Den Ernährungsplan wirklich löschen?')) return
    setBusy(true)
    setFehler(null)
    try {
      await api.ernaehrungLoeschen()
      await laedt()
    } catch (err) {
      setFehler(err instanceof Error ? err.message : 'Löschen fehlgeschlagen.')
    } finally {
      setBusy(false)
    }
  }

  if (!geladen) return <Loading />

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Ernährung</h1>
          <p className="muted mb-0">
            Was wann gegessen wird — abgestimmt auf das Training, das für diese
            Tage geplant ist.
          </p>
        </div>
      </div>

      {fehler && <Alert kind="error">{fehler}</Alert>}
      {hinweise.length > 0 && (
        <Alert kind="warning">
          <ul className="mb-0">
            {hinweise.map((h) => (
              <li key={h}>{h}</li>
            ))}
          </ul>
        </Alert>
      )}

      {!spielraum?.hat_trainingsblock ? (
        <EmptyState icon="🍽️" title="Noch kein Trainingsplan">
          <p>
            Ein Ernährungsplan richtet sich nach dem geplanten Training. Plane
            zuerst einen Trainingsblock — danach entsteht der Ernährungsplan mit
            einem Knopfdruck.
          </p>
          <Link className="btn btn-primary" to={planErzeugenPfad(heuteIso())}>
            Trainingsblock planen
          </Link>
        </EmptyState>
      ) : (
        <div className="card">
          <div className="row mb-1">
            <button
              className="btn btn-primary"
              onClick={planeMitKi}
              disabled={busy || laeuft || !planbar || !kiVerfuegbar}
            >
              {busy ? 'Wird gestartet …' : 'Neuen Ernährungsplan erstellen'}
            </button>

            <label className="ern-feld">
              <span className="small muted">Ab</span>
              <input
                type="date"
                value={start}
                min={heute}
                onChange={(e) => {
                  setStart(e.target.value)
                  // Die Obergrenze hängt am Startdatum; eine stehengebliebene
                  // Zahl wäre nach dem Verschieben womöglich zu groß.
                  setTage(null)
                }}
              />
            </label>

            <label className="ern-feld">
              <span className="small muted">Tage</span>
              <input
                type="number"
                min={1}
                max={maxTage}
                value={tage ?? ''}
                onChange={(e) => {
                  const roh = Number(e.target.value)
                  setTage(e.target.value === '' ? null : Math.min(roh, maxTage))
                }}
              />
            </label>

            <button
              className="btn btn-secondary"
              onClick={() => setDialogOffen(true)}
              disabled={busy}
            >
              Ernährungsplan individualisieren
              {profil?.hinweise ? ' ✓' : ''}
            </button>

            {plan && (
              <button
                className="btn btn-danger"
                onClick={loesche}
                disabled={busy || laeuft}
              >
                Ernährungsplan löschen
              </button>
            )}
          </div>

          <p className="small muted mb-0">
            {spielraum.hinweis ??
              `Höchstens ${maxTage} Tag(e) — so weit reicht der Trainingsblock` +
                ` „${spielraum.block_titel}" (bis ${kurzdatum(
                  spielraum.block_ende ?? '',
                )}).`}
          </p>

          {laeuft && job && <LaufKarte job={job} onAbbrechen={brichAb} />}

          {!kiVerfuegbar && !laeuft && (
            <Alert kind="info">
              Es ist kein Claude-Zugang hinterlegt — der Ernährungsplan entsteht
              deshalb über Kopieren und Einfügen. Den Zugang trägst du unter{' '}
              <Link to="/einstellungen">Einstellungen</Link> ein.
            </Alert>
          )}
        </div>
      )}

      {spielraum?.hat_trainingsblock && (
        <ManuellerWeg
          aufgeklappt={!kiVerfuegbar}
          start={start}
          tage={tage}
          gesperrt={busy || laeuft || !planbar}
          onFehler={setFehler}
          onUebernommen={(warnungen) => {
            setHinweise(warnungen)
            void laedt()
          }}
        />
      )}

      {plan && <PlanAnsicht plan={plan} heute={heute} />}

      {dialogOffen && (
        <IndividualisierenDialog
          hinweise={profil?.hinweise ?? ''}
          onClose={() => setDialogOffen(false)}
          onGespeichert={(neu) => {
            setProfil(neu)
            setDialogOffen(false)
          }}
          onFehler={setFehler}
        />
      )}
    </div>
  )
}

/* --------------------------------------------------------------------------
   Der laufende Lauf
   -------------------------------------------------------------------------- */

function LaufKarte({ job, onAbbrechen }: { job: KiJob; onAbbrechen: () => void }) {
  return (
    <div className="card mt-1">
      <div className="card-title">Der Ernährungsplan entsteht …</div>
      <div className="wizard-progress mb-1">
        <div
          className="wizard-step-bar current"
          style={{ flexGrow: Math.max(1, job.progress_pct) }}
        />
        <div className="wizard-step-bar" style={{ flexGrow: Math.max(1, 100 - job.progress_pct) }} />
      </div>
      <p className="small muted mb-1">{job.message}</p>
      <div className="row row-end">
        <span className="small faint">{job.progress_pct} %</span>
        <button className="btn btn-ghost btn-sm" onClick={onAbbrechen}>
          Abbrechen
        </button>
      </div>
    </div>
  )
}

/* --------------------------------------------------------------------------
   Der dauerhafte Freitext
   -------------------------------------------------------------------------- */

function IndividualisierenDialog(props: {
  hinweise: string
  onClose: () => void
  onGespeichert: (profil: ErnaehrungsProfil) => void
  onFehler: (meldung: string) => void
}) {
  // Bewusst ein lokaler Entwurf mit Speichern-Knopf, nicht die
  // Sofortspeicherung der Einstellungsseite: Ein Freitext, der beim Tippen
  // zeichenweise gespeichert würde, stünde die halbe Zeit als Halbsatz im
  // nächsten Prompt. Dieselbe Ausnahme wie beim Claude-Token.
  const [entwurf, setEntwurf] = useState(props.hinweise)
  const [busy, setBusy] = useState(false)

  async function speichere(text: string) {
    setBusy(true)
    try {
      props.onGespeichert(await api.ernaehrungProfilSpeichern(text))
    } catch (err) {
      props.onFehler(
        err instanceof Error ? err.message : 'Speichern fehlgeschlagen.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title="Ernährungsplan individualisieren" onClose={props.onClose}>
      <p className="muted">
        Was dauerhaft für deine Ernährung gilt: Unverträglichkeiten,
        Ernährungsform, Kantine, Schichtdienst, Abneigungen. Der Text bleibt
        gespeichert und geht in jeden Ernährungsplan — auch in die nach dem
        Löschen des aktuellen —, bis du ihn hier selbst löschst.
      </p>
      <TextArea
        label="Deine Angaben"
        rows={8}
        value={entwurf}
        onChange={(v) => setEntwurf(v ?? '')}
        placeholder="z. B. „Laktoseintolerant, mittags an die Kantine gebunden, kein Fleisch“"
      />
      <div className="row row-end mt-1">
        <button
          className="btn btn-ghost"
          onClick={() => void speichere('')}
          disabled={busy || !entwurf.trim()}
        >
          Text löschen
        </button>
        <button
          className="btn btn-primary"
          onClick={() => void speichere(entwurf)}
          disabled={busy}
        >
          {busy ? 'Speichert …' : 'Speichern'}
        </button>
      </div>
    </Modal>
  )
}

/* --------------------------------------------------------------------------
   Mo–So als Spalten

   Ein Markup für zwei Größen, wie im Garmin-Kalender: Unterhalb von 700 px
   fällt das Spaltenraster auf eine Spalte zusammen, die Füllzellen vor dem
   ersten Tag verschwinden und der Wochentag rückt in die Zelle.
   -------------------------------------------------------------------------- */

function PlanAnsicht({ plan, heute }: { plan: Ernaehrungsplan; heute: string }) {
  const tage = plan.tage
  if (tage.length === 0) return null
  const fuehrend = montagsIndex(tage[0].date)

  return (
    <>
      <div className="card">
        <div className="card-title">{plan.title}</div>
        {plan.summary && <p className="mb-1">{plan.summary}</p>}
        {plan.begruendung && (
          <p className="small muted mb-0">{plan.begruendung}</p>
        )}
      </div>

      <div className="ern-kopf" aria-hidden="true">
        {WOCHENTAGE.map((t) => (
          <span key={t}>{t}</span>
        ))}
      </div>
      <div className="ern-raster">
        {Array.from({ length: fuehrend }, (_, i) => (
          <div className="ern-tag ern-fueller" key={`leer-${i}`} />
        ))}
        {tage.map((tag) => (
          <TagesZelle key={tag.id} tag={tag} istHeute={tag.date === heute} />
        ))}
      </div>

      {plan.supplemente.length > 0 && (
        <div className="card mt-2">
          <div className="card-title">Supplemente</div>
          <ul className="mb-0">
            {plan.supplemente.map((s) => (
              <li key={s.id}>
                <b>{s.name}</b>
                {s.dosierung ? ` — ${s.dosierung}` : ''}
                {s.zeitpunkt ? `, ${s.zeitpunkt}` : ''}
                {s.begruendung && (
                  <span className="small muted"> · {s.begruendung}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  )
}

function TagesZelle({ tag, istHeute }: { tag: ErnaehrungsTag; istHeute: boolean }) {
  const summen: string[] = []
  if (tag.kohlenhydrate_g != null) summen.push(`${tag.kohlenhydrate_g} g KH`)
  if (tag.protein_g != null) summen.push(`${tag.protein_g} g EW`)
  if (tag.fett_g != null) summen.push(`${tag.fett_g} g F`)
  if (tag.fluessigkeit_ml != null)
    summen.push(`${(tag.fluessigkeit_ml / 1000).toFixed(1)} l`)

  return (
    <div className={`ern-tag${istHeute ? ' is-heute' : ''}`}>
      <div className="ern-tag-kopf">
        <span className="ern-tag-zahl">{kurzdatum(tag.date)}</span>
        <span className="ern-tag-name">{tagesName(tag.date)}</span>
      </div>

      {tag.trainingshinweis && (
        <div className="ern-training">{tag.trainingshinweis}</div>
      )}

      {(tag.kalorien_kcal != null || summen.length > 0) && (
        <div className="ern-summen">
          {tag.kalorien_kcal != null && <b>{tag.kalorien_kcal} kcal</b>}
          {summen.map((s) => (
            <span key={s}>{s}</span>
          ))}
        </div>
      )}

      {tag.mahlzeiten.map((m) => (
        <div
          key={m.id}
          className={`ern-mahlzeit${m.bezug ? ` bezug-${m.bezug}` : ''}`}
        >
          <div className="ern-mahlzeit-kopf">
            {m.zeitpunkt && <span className="ern-mahlzeit-zeit">{m.zeitpunkt}</span>}
            {m.name && <span className="ern-mahlzeit-name">{m.name}</span>}
          </div>
          {m.beschreibung && (
            <div className="ern-mahlzeit-text">{m.beschreibung}</div>
          )}
          {m.kalorien_kcal != null && (
            <div className="ern-mahlzeit-makros">{m.kalorien_kcal} kcal</div>
          )}
        </div>
      ))}

      {tag.notiz && <div className="ern-notiz">{tag.notiz}</div>}
    </div>
  )
}


/* --------------------------------------------------------------------------
   Der Weg über die Zwischenablage

   Die Rückfallebene ohne hinterlegten Claude-Zugang — und für den Fall, dass
   das Kontingent aufgebraucht ist oder eine andere KI antworten soll. Ohne
   Zugang steht sie offen, sonst eingeklappt.
   -------------------------------------------------------------------------- */

function ManuellerWeg(props: {
  aufgeklappt: boolean
  start: string
  tage: number | null
  gesperrt: boolean
  onFehler: (meldung: string) => void
  onUebernommen: (warnungen: string[]) => void
}) {
  const [text, setText] = useState<string | null>(null)
  const [kopiert, setKopiert] = useState(false)
  const [roh, setRoh] = useState('')
  const [busy, setBusy] = useState(false)
  const [vorschau, setVorschau] = useState<string[] | null>(null)

  async function erzeuge() {
    setBusy(true)
    try {
      const paket = await api.ernaehrungExport(props.start, props.tage ?? undefined)
      setText(paket.combined)
    } catch (err) {
      props.onFehler(
        err instanceof Error ? err.message : 'Der Text ließ sich nicht bauen.',
      )
    } finally {
      setBusy(false)
    }
  }

  async function kopiere() {
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      setKopiert(true)
      setTimeout(() => setKopiert(false), 2500)
    } catch {
      props.onFehler(
        'Der Zugriff auf die Zwischenablage wurde blockiert. Markiere den Text ' +
          'unten und kopiere ihn von Hand.',
      )
    }
  }

  async function pruefe() {
    setBusy(true)
    try {
      const ergebnis = await api.ernaehrungPruefen(
        roh,
        props.start,
        props.tage ?? undefined,
      )
      setVorschau(ergebnis.warnings)
    } catch (err) {
      props.onFehler(err instanceof Error ? err.message : 'Die Antwort ist unlesbar.')
    } finally {
      setBusy(false)
    }
  }

  async function uebernimm() {
    setBusy(true)
    try {
      const ergebnis = await api.ernaehrungImportieren(
        roh,
        props.start,
        props.tage ?? undefined,
      )
      setRoh('')
      setVorschau(null)
      props.onUebernommen(ergebnis.warnings)
    } catch (err) {
      props.onFehler(err instanceof Error ? err.message : 'Übernehmen fehlgeschlagen.')
    } finally {
      setBusy(false)
    }
  }

  const inhalt = (
    <>
      <div className="card">
        <div className="card-title">
          <span className="step-marker">1</span> Text erzeugen und kopieren
        </div>
        <div className="row mb-1">
          <button
            className="btn btn-secondary"
            onClick={erzeuge}
            disabled={busy || props.gesperrt}
          >
            {busy && !text ? 'Wird gebaut …' : 'Text erzeugen'}
          </button>
          {text && (
            <button className="btn btn-secondary" onClick={kopiere}>
              {kopiert ? '✓ In die Zwischenablage kopiert' : 'Text kopieren'}
            </button>
          )}
        </div>
        {text && (
          <details>
            <summary style={{ cursor: 'pointer' }}>
              Text anzeigen ({Math.round(text.length / 1024)} KB)
            </summary>
            <div className="code-box mt-1">{text}</div>
          </details>
        )}
      </div>

      <div className="card">
        <div className="card-title">
          <span className="step-marker">2</span> Antwort einfügen
        </div>
        <textarea
          className="paste-area"
          value={roh}
          placeholder={'{"schema_version": "1.0", "ernaehrungsplan": { … }}'}
          onChange={(e) => {
            setRoh(e.target.value)
            setVorschau(null)
          }}
        />
        <div className="row mt-1">
          <button
            className="btn btn-secondary"
            onClick={pruefe}
            disabled={!roh.trim() || busy}
          >
            Erst prüfen
          </button>
          <button
            className="btn btn-primary"
            onClick={uebernimm}
            disabled={!roh.trim() || busy}
          >
            Ernährungsplan übernehmen
          </button>
        </div>
        {vorschau && (
          <Alert kind={vorschau.length > 0 ? 'warning' : 'success'}>
            {vorschau.length > 0 ? (
              <ul className="mb-0">
                {vorschau.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            ) : (
              'Die Antwort ist lesbar und vollständig.'
            )}
          </Alert>
        )}
      </div>
    </>
  )

  if (props.aufgeklappt) return inhalt

  return (
    <details className="card">
      <summary style={{ cursor: 'pointer' }}>
        Stattdessen von Hand: Text kopieren und Antwort einfügen
      </summary>
      <p className="small muted mt-1">
        Der Weg über die Zwischenablage bleibt — für den Fall, dass der Zugang
        abgelaufen ist, das Kontingent aufgebraucht, oder du eine andere KI
        benutzen willst.
      </p>
      {inhalt}
    </details>
  )
}
