/** Gemeinsame Rechenwege für die beiden Einstiege in einen neuen Block.
 *
 * Übersicht und Plan bieten beides an — „neu planen ab heute" und „die nächsten
 * Tage anhängen" —, und beide brauchen dasselbe Datum. Zwei Kopien davon liefen
 * beim nächsten Sonderfall (abgelaufener Block) auseinander.
 */

/** Die Vorgabe des Backends (`PLAN_DAYS_DEFAULT`) als Blocklänge. */
export const PLAN_TAGE = 7

/**
 * Ein Datum als YYYY-MM-DD in **Ortszeit**.
 *
 * Nicht das blanke `toISOString()`: Das rechnet nach UTC um und liefert in
 * Deutschland abends bereits den Folgetag — ein Block „ab heute" finge dann
 * einen Tag zu spät an, und der heutige Tag bliebe ungeplant.
 */
function alsIso(datum: Date): string {
  const versetzt = new Date(datum.getTime() - datum.getTimezoneOffset() * 60000)
  return versetzt.toISOString().slice(0, 10)
}

/** Heute in Ortszeit. */
export function heuteIso(): string {
  return alsIso(new Date())
}

/**
 * Erster Tag des *anschließenden* Blocks: der Tag nach dem Blockende — aber nie
 * in der Vergangenheit. Ein Block, der vor einer Woche ausgelaufen ist, würde
 * sonst rückwirkend geplant.
 */
export function naechsterBlockStart(endDatum: string): string {
  const heute = heuteIso()
  const ende = new Date(`${endDatum}T00:00:00`)
  ende.setDate(ende.getDate() + 1)
  const danach = alsIso(ende)
  return danach > heute ? danach : heute
}

/** Weg zum Austausch mit der KI, mit vorbelegtem Zeitraum. */
export function planErzeugenPfad(start: string, tage: number = PLAN_TAGE): string {
  return `/plan-erzeugen?start=${start}&days=${tage}`
}
