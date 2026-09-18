/**
 * Was heute mit den Einheiten des Tages geschehen ist — oder warum nichts.
 *
 * **Der Fall, für den es diese Zeile gibt, ist der langweiligste.** Der Prompt
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
 *
 * **Eine Zeile, keine Meldungsbox.** Das war einmal ein gerahmtes `Alert` mit
 * Knopfleiste und nahm über der Vorgabe des Tages mehr Platz ein als die
 * Vorgabe selbst — für einen Satz, der an den meisten Tagen „alles bleibt"
 * lautet. Jetzt steht sie als dritte Klappzeile neben „Zur Ausrichtung des
 * Blocks" und „Hinweise zur Steuerung": gleiche Bauform, gleiches Dreieck, nur
 * in der Farbe ihres Zustands. Auch „Jetzt prüfen" liegt darin — der Knopf
 * kostet Kontingent und wird selten gebraucht, also gehört er hinter denselben
 * Klick wie die Begründung.
 */

import type { ReactNode } from 'react'

import { Klappblock } from './ui'
import type { PlanSession, TagesformBefund } from '../types'

/** Ob überhaupt etwas zu zeigen ist — der Aufrufer setzt danach seine Trenner. */
export function zeigtTagesform(
  befund: TagesformBefund | null,
  angepasst: PlanSession | null,
): boolean {
  if (angepasst) return true
  return befund !== null && befund.stand !== 'aus'
}

export function TagesformKarte({
  befund,
  angepasst,
  onPruefen,
  busy,
  kiVerfuegbar,
}: {
  befund: TagesformBefund | null
  /** Eine Einheit von heute, die die Anpassung tatsächlich umgeschrieben hat. */
  angepasst: PlanSession | null
  onPruefen: () => void
  busy: boolean
  /** Ohne Claude-Zugang ist „Jetzt prüfen" gesperrt statt zum Scheitern verurteilt. */
  kiVerfuegbar: boolean
}) {
  // Die geänderte Einheit hat Vorrang vor allem anderen: Sie ist der einzige
  // Fall, in dem der Tag *anders aussieht* als gestern Abend geplant, und das
  // gehört über die Einheiten, bevor irgendein Zustandssatz kommt.
  if (angepasst) {
    return (
      <Zeile
        ton="info"
        titel="✎ Heute früh an deine Tagesform angepasst."
        text={angepasst.anpassungsbegruendung}
      />
    )
  }

  if (befund === null || befund.stand === 'aus') return null

  // Der Balken ist der Inhalt: Ein laufender Lauf hat nichts zu erzählen, was
  // sich aufklappen ließe, und wegklicken soll man ihn auch nicht.
  if (befund.stand === 'laeuft') {
    const anteil = befund.progress_pct ?? 0
    return (
      <div className="klappblock tagesform-zeile">
        <h3 className="tagesform-info">Der heutige Tag wird gerade geprüft …</h3>
        <div className="wizard-progress mt-1">
          <div className="wizard-step-bar current" style={{ flexGrow: Math.max(1, anteil) }} />
          <div className="wizard-step-bar" style={{ flexGrow: Math.max(1, 100 - anteil) }} />
        </div>
        <span className="small faint">
          {anteil}&nbsp;% — du kannst die Seite verlassen, der Lauf geht im
          Hintergrund weiter.
        </span>
      </div>
    )
  }

  if (befund.stand === 'geprueft' && befund.von_heute) {
    return (
      <Zeile
        ton="ok"
        titel="✓ Heute früh geprüft — dein Tag bleibt, wie er geplant war."
        text={befund.text}
        aktion={<Pruefknopf onPruefen={onPruefen} busy={busy} kiVerfuegbar={kiVerfuegbar} />}
      />
    )
  }

  if (befund.stand === 'fehlgeschlagen' && befund.von_heute) {
    return (
      <Zeile
        ton="warn"
        titel="⚠ Die tägliche Prüfung ist heute gescheitert."
        text={befund.text || 'Näheres steht unter Einstellungen → KI-Planung.'}
        aktion={<Pruefknopf onPruefen={onPruefen} busy={busy} kiVerfuegbar={kiVerfuegbar} />}
        offen
      />
    )
  }

  // „ausgefallen", „unbekannt" und alles von vorgestern: Es gibt keine Auskunft
  // über den heutigen Tag. Leise, aber nicht stumm — der Knopf steht darin.
  return (
    <Zeile
      ton="neutral"
      titel="Der heutige Tag ist noch nicht geprüft."
      text={befund.text || 'Die tägliche Prüfung ist heute nicht gelaufen.'}
      aktion={<Pruefknopf onPruefen={onPruefen} busy={busy} kiVerfuegbar={kiVerfuegbar} />}
      offen
    />
  )
}

/** Der Satz, der immer steht — und darunter zugeklappt, was die KI dazu sagt.
 *
 * Die Begründung ist Fließtext von mehreren Sätzen und steht ganz oben auf der
 * Startseite, also vor dem, weswegen die App morgens geöffnet wird. Gelesen
 * wird sie einmal; sichtbar bleiben muss nur, *dass* geprüft wurde. Ohne Text
 * *und* ohne Knopf bleibt es bei der Zeile — ein leerer Reiter wäre eine
 * Einladung ins Nichts.
 *
 * „Gescheitert" und „nicht gelaufen" stehen dagegen offen: Sie sind eine
 * Handlungsaufforderung und kein Nachschlagetext, und mit ihnen der Knopf.
 */
function Zeile({
  ton,
  titel,
  text,
  aktion,
  offen = false,
}: {
  ton: 'ok' | 'warn' | 'info' | 'neutral'
  titel: string
  text?: string | null
  /** Steht im aufgeklappten Teil, nicht daneben. */
  aktion?: ReactNode
  /** Für die Zustände, die eine Handlung verlangen statt nur Auskunft zu geben. */
  offen?: boolean
}) {
  const kopf = <h3 className={`tagesform-${ton}`}>{titel}</h3>
  if (!text && !aktion) return <div className="klappblock tagesform-zeile">{kopf}</div>
  return (
    <Klappblock titel={kopf} offen={offen}>
      {text && <p className="small tagesform-text mb-0">{text}</p>}
      {aktion}
    </Klappblock>
  )
}

/** „Jetzt prüfen" — der Weg, der keinen Garmin-Abgleich voraussetzt.
 *
 * Er kostet einen Lauf aus dem Claude-Kontingent, und das steht dabei: Es ist
 * derselbe Fünf-Stunden-Topf, aus dem der Athlet daneben selbst arbeitet.
 * Ohne Zugang ist er gesperrt und der Satz daneben sagt, warum — ein Knopf,
 * der sicher scheitert, wäre nur ein Umweg zu derselben Auskunft.
 */
function Pruefknopf({
  onPruefen,
  busy,
  kiVerfuegbar,
}: {
  onPruefen: () => void
  busy: boolean
  kiVerfuegbar: boolean
}) {
  const hinweis = kiVerfuegbar
    ? 'Kostet einen Lauf aus deinem Claude-Kontingent.'
    : 'Kein Claude-Zugang hinterlegt — eintragen unter Einstellungen → KI-Planung.'
  return (
    <div className="row row-end mt-1">
      <span className="small faint">{hinweis}</span>
      <button
        className="btn btn-ghost btn-sm"
        disabled={busy || !kiVerfuegbar}
        title={kiVerfuegbar ? undefined : hinweis}
        onClick={onPruefen}
      >
        Jetzt prüfen
      </button>
    </div>
  )
}
