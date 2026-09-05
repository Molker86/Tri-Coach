/**
 * Was heute mit den Einheiten des Tages geschehen ist — oder warum nichts.
 *
 * **Der Fall, für den es diese Karte gibt, ist der langweiligste.** Der Prompt
 * der Tagesanpassung nennt „unverändert" ausdrücklich den Regelfall, und ein
 * unveränderter Tag schreibt an keine Einheit etwas: kein `angepasst_am`, kein
 * Badge, kein Hinweis. Ein geglückter Lauf, der zu dem Schluss kam, dass alles
 * passt, sah damit für den Athleten exakt so aus wie einer, der nie
 * stattgefunden hat — und wie einer, der an einem Fehler gestorben ist. Sein
 * Kontingent war weg, seine Antwort nirgends zu sehen.
 *
 * Deshalb steht hier auch dann etwas, wenn nichts passiert ist. Nur ein
 * ausgeschalteter Schalter schweigt: Wer ihn bewusst aus gelassen hat, braucht
 * dazu keine tägliche Erinnerung.
 */

import type { ReactNode } from 'react'

import { Alert, Klappblock } from './ui'
import type { PlanSession, TagesformBefund } from '../types'

export function TagesformKarte({
  befund,
  angepasst,
  onPruefen,
  busy,
}: {
  befund: TagesformBefund | null
  /** Eine Einheit von heute, die die Anpassung tatsächlich umgeschrieben hat. */
  angepasst: PlanSession | null
  onPruefen: () => void
  busy: boolean
}) {
  // Die geänderte Einheit hat Vorrang vor allem anderen: Sie ist der einzige
  // Fall, in dem der Tag *anders aussieht* als gestern Abend geplant, und das
  // gehört über die Einheiten, bevor irgendein Zustandssatz kommt.
  if (angepasst) {
    return (
      <Alert kind="info">
        <Begruendung
          titel="✎ Heute früh an deine Tagesform angepasst."
          text={angepasst.anpassungsbegruendung}
        />
      </Alert>
    )
  }

  if (befund === null || befund.stand === 'aus') return null

  if (befund.stand === 'laeuft') {
    const anteil = befund.progress_pct ?? 0
    return (
      <Alert kind="info">
        <strong>Der heutige Tag wird gerade geprüft …</strong>
        <div className="wizard-progress mt-1">
          <div className="wizard-step-bar current" style={{ flexGrow: Math.max(1, anteil) }} />
          <div className="wizard-step-bar" style={{ flexGrow: Math.max(1, 100 - anteil) }} />
        </div>
        <span className="small faint">
          {anteil}&nbsp;% — du kannst die Seite verlassen, der Lauf geht im
          Hintergrund weiter.
        </span>
      </Alert>
    )
  }

  if (befund.stand === 'geprueft' && befund.von_heute) {
    return (
      <Alert kind="success">
        <Begruendung
          titel="✓ Heute früh geprüft — dein Tag bleibt, wie er geplant war."
          text={befund.text}
        >
          <Pruefknopf befund={befund} onPruefen={onPruefen} busy={busy} />
        </Begruendung>
      </Alert>
    )
  }

  if (befund.stand === 'fehlgeschlagen' && befund.von_heute) {
    return (
      <Alert kind="warning">
        <strong>Die tägliche Prüfung ist heute gescheitert.</strong>{' '}
        {befund.text || 'Näheres steht unter Einstellungen → KI-Planung.'}
        <Pruefknopf befund={befund} onPruefen={onPruefen} busy={busy} />
      </Alert>
    )
  }

  // „ausgefallen", „unbekannt" und alles von vorgestern: Es gibt keine Auskunft
  // über den heutigen Tag. Leise, aber nicht stumm — der Knopf steht dabei.
  return (
    <Alert kind="info">
      <strong>Der heutige Tag ist noch nicht geprüft.</strong>{' '}
      {befund.text || 'Die tägliche Prüfung ist heute nicht gelaufen.'}
      <Pruefknopf befund={befund} onPruefen={onPruefen} busy={busy} />
    </Alert>
  )
}

/** Der Satz, der immer steht — und darunter zugeklappt, was die KI dazu sagt.
 *
 * Die Begründung ist Fließtext von mehreren Sätzen und steht ganz oben auf der
 * Startseite, also vor dem, weswegen die App morgens geöffnet wird. Gelesen
 * wird sie einmal; sichtbar bleiben muss nur, *dass* geprüft wurde. Ohne Text
 * bleibt es bei der Zeile — ein leerer Reiter wäre eine Einladung ins Nichts.
 */
function Begruendung({
  titel,
  text,
  children,
}: {
  titel: string
  text?: string | null
  /** Steht unter dem Reiter und bleibt sichtbar, wenn er zu ist. */
  children?: ReactNode
}) {
  if (!text) {
    return (
      <>
        <strong>{titel}</strong>
        {children}
      </>
    )
  }
  return (
    <>
      <Klappblock titel={<strong>{titel}</strong>}>
        <p className="mb-0">{text}</p>
      </Klappblock>
      {children}
    </>
  )
}

/** „Jetzt prüfen" — der Weg, der keinen Garmin-Abgleich voraussetzt.
 *
 * Er kostet einen Lauf aus dem Claude-Kontingent, und das steht dabei: Es ist
 * derselbe Fünf-Stunden-Topf, aus dem der Athlet daneben selbst arbeitet.
 */
function Pruefknopf({
  befund,
  onPruefen,
  busy,
}: {
  befund: TagesformBefund
  onPruefen: () => void
  busy: boolean
}) {
  if (befund.stand === 'laeuft') return null
  return (
    <div className="row row-end mt-1">
      <span className="small faint">Kostet einen Lauf aus deinem Claude-Kontingent.</span>
      <button className="btn btn-ghost btn-sm" disabled={busy} onClick={onPruefen}>
        Jetzt prüfen
      </button>
    </div>
  )
}
