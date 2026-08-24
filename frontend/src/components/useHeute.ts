import { useEffect, useState } from 'react'
import { heuteIso } from '../planung'

/** Der heutige Tag in Ortszeit — und er bleibt es über Mitternacht hinaus.
 *
 * Stand einmal als modulweite Konstante da und wurde damit genau einmal
 * ausgerechnet: beim Laden der App. Die Routen liegen alle statisch in
 * `App.tsx`, das ist also der Moment, in dem der Tab aufgeht. Eine Sitzung,
 * die über Mitternacht offen bleibt, markierte am Morgen weiter den Vortag —
 * am Telefon der Normalfall, denn dort schläft ein Tab, statt zu schließen.
 *
 * Gerechnet wird über `planung.heuteIso()` — dieselbe Ortszeitregel, die auch
 * die Startdaten neuer Blöcke bestimmt. Eine zweite Fassung von „heute in
 * Ortszeit" ist genau die Doppelung, die `planung.ts` verhindern soll.
 */
export function useHeute(): string {
  const [heute, setHeute] = useState(() => heuteIso())

  useEffect(() => {
    // Gleicher Tag heißt gleicher String — React verwirft die Zuweisung dann
    // von selbst, ein Aufruf ohne Tageswechsel kostet also kein Rendern.
    const pruefe = () => setHeute(heuteIso())

    // Ein Zeitgeber auf den nächsten Tagesbeginn statt einer Schleife: Er
    // feuert genau einmal, und zwar dann, wenn sich wirklich etwas ändert.
    let timer = 0
    const planeMitternacht = () => {
      const jetzt = new Date()
      const naechsterTag = new Date(jetzt)
      naechsterTag.setHours(24, 0, 0, 0)
      // Eine Sekunde Zuschlag, damit der Lauf sicher hinter dem Tageswechsel
      // liegt und nicht knapp davor denselben Tag noch einmal liest.
      timer = window.setTimeout(() => {
        pruefe()
        planeMitternacht()
      }, naechsterTag.getTime() - jetzt.getTime() + 1000)
    }
    planeMitternacht()

    // Telefone drosseln Zeitgeber im Hintergrund und holen sie nicht nach —
    // dieselbe Vorsichtsmaßnahme wie beim Abfragen eines Jobs (`pollJob`).
    document.addEventListener('visibilitychange', pruefe)
    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', pruefe)
    }
  }, [])

  return heute
}
