/**
 * Pfad-Prefix, unter dem die App ausgeliefert wird.
 *
 * Normalbetrieb (Docker, Entwicklung) ist das die Wurzel, also `''`. Unter
 * Home-Assistant-Ingress liegt die App dagegen unter
 * `/api/hassio_ingress/<token>/`. Das Backend schreibt diesen Prefix als
 * `<base href="…">` in die index.html — von dort lesen wir ihn hier zurück.
 *
 * Der Prefix muss an zwei Stellen mitgezogen werden: an die API-Aufrufe (sonst
 * landet `fetch('/api/…')` bei der Home-Assistant-API statt beim Add-on) und an
 * den Router (sonst schiebt ein Klick die Adresse auf die HA-Wurzel).
 *
 * Bewusst über das `<base>`-Element und nicht über `document.baseURI`: Ohne
 * Tag liefert `baseURI` die aktuelle Adresse, bei einem Neuladen auf
 * `/dashboard` also fälschlich den Prefix `/dashboard`.
 */
function detectBasePath(): string {
  const base = document.querySelector('base')
  if (!base) return ''
  return new URL(base.href).pathname.replace(/\/+$/, '')
}

export const BASE_PATH = detectBasePath()
