/**
 * Hell oder dunkel — und wer das entscheidet.
 *
 * Die App folgte bisher allein `prefers-color-scheme`. Ein Schalter dafür
 * bräuchte im CSS eine zweite Fassung aller dunklen Tokens: einmal in der
 * Medienabfrage, einmal unter `[data-theme='dark']`. Zwei Kopien derselben
 * Palette laufen irgendwann auseinander.
 *
 * Deshalb entscheidet JavaScript: Die Wahl steht in `localStorage`, und bei
 * „System" wird `matchMedia` gefragt. Geschrieben wird immer ein ausdrückliches
 * `data-theme` auf `<html>`, und das CSS kennt nur noch diesen einen Fall.
 * Gesetzt wird es zweimal — vor dem ersten Zeichnen durch das Inline-Skript in
 * `index.html`, damit nichts aufblitzt, und danach von hier aus bei jeder
 * Änderung.
 *
 * Bewusst nur im Browser und nicht am Konto: Wer die App auf zwei Geräten
 * öffnet, stellt sie zweimal ein — bei einer Frage der Darstellung ist das
 * richtig so.
 */

export type Farbwahl = 'system' | 'light' | 'dark'

/** Schlüssel wie `tricoach.lastUser` im `AuthContext`. */
const SCHLUESSEL = 'tricoach.theme'

const DUNKEL = '(prefers-color-scheme: dark)'

export function leseFarbwahl(): Farbwahl {
  const wert = localStorage.getItem(SCHLUESSEL)
  return wert === 'light' || wert === 'dark' ? wert : 'system'
}

export function setzeFarbwahl(wahl: Farbwahl): void {
  if (wahl === 'system') localStorage.removeItem(SCHLUESSEL)
  else localStorage.setItem(SCHLUESSEL, wahl)
  wendeAn(wahl)
}

function wendeAn(wahl: Farbwahl): void {
  const dunkel = wahl === 'dark' || (wahl === 'system' && matchMedia(DUNKEL).matches)
  document.documentElement.dataset.theme = dunkel ? 'dark' : 'light'
}

/**
 * Lässt „System" der Systemeinstellung folgen, solange sie gilt.
 *
 * Ohne das bliebe die App bis zum Neuladen in der Farbe, die beim Öffnen galt —
 * und am Telefon, wo abends automatisch umgeschaltet wird, ist genau das der
 * Normalfall. Gibt die Abmeldung zurück.
 */
export function beobachteSystemfarbe(): () => void {
  const abfrage = matchMedia(DUNKEL)
  const bei = () => {
    if (leseFarbwahl() === 'system') wendeAn('system')
  }
  abfrage.addEventListener('change', bei)
  return () => abfrage.removeEventListener('change', bei)
}
