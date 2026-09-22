# Tri-Coach für iOS

Native SwiftUI-App zum Tri-Coach-Add-on. Sie zeigt den **aktiven
Trainingsblock im Kalender** und **zu jedem Tag den Ernährungsplan** —
lesend; geplant und angepasst wird weiter in der Web-Oberfläche.

Dazu **zu jeder Kraft- und Mobility-Übung eine Animation**: Wer eine solche
Einheit öffnet, sieht ihre Übungen mit laufender Vorschau; ein Tippen zeigt
die Übung groß, samt Ablauf und betonten Muskeln. Animationen, die Claude
erstellt hat, stehen auf „ungeprüft“ und lassen sich hier freigeben oder mit
Anmerkung verwerfen. Hintergrund: `docs/animationen.md`.

## Animationen

- `TriCoach/Animation/Koerper.swift` — das Körpermodell, Zahl für Zahl wie
  `backend/app/animation/koerper.py`. Der Debug-Build im Simulator rechnet beim
  Start die Referenzposen aus `backend/tests/fixtures/animation_fk_referenz.json`
  nach und schreibt die größte Abweichung ins Protokoll
  („Körpermodell stimmt …“). Wer an einem der beiden Modelle dreht, zieht das
  andere nach.
- `TriCoach/Animation/Figur.swift` — Kamera, Ausschnitt und Zeichnen mit
  `Canvas` in einer `TimelineView`; derselbe Stil wie die Vorschaubilder des
  Backends. Übergänge laufen über die gelösten Zwischenbilder.
- `TriCoach/Animation/Bewegung.swift` — die Modelle. **Wortgetreu dekodiert**,
  ohne `.convertFromSnakeCase`: Die Strategie schriebe auch die Schlüssel der
  Posen um („huefte_beugen_l“ → „huefteBeugenL“).
- Ein Add-on vor 4.6.0 kennt die Endpunkte nicht; die App sagt dann, dass es
  aktualisiert werden will.

## Verbindung

Die App geht zwei Wege:

- **Home Assistant (Normalfall).** Genau wie im Browser durch den Ingress: Die
  App meldet sich mit einem *Langzeit-Zugangstoken* am WebSocket von Home
  Assistant an, sucht das Add-on (`get_panels`, Slug `…_tricoach`), fragt
  dessen Ingress-Adresse ab (`supervisor/api` → `/addons/<slug>/info`) und legt
  eine Ingress-Sitzung an (`/ingress/session`). Danach laufen alle Aufrufe über
  `<ha>/api/hassio_ingress/<token>/api/…` mit dem Cookie `ingress_session`.
  **Am Backend ändert sich dafür nichts, und es wird kein Port geöffnet** — die
  Sicherheitsgrenze bleibt, wo `docs/backend.md` („Anmeldung ohne Passwort“)
  sie festlegt: bei Home Assistant.
- **Direkt.** Auf einen Tri-Coach-Server ohne Ingress, z. B. `http://localhost:8000`
  beim Entwickeln (`./start.sh`). Ohne Home Assistant gibt es keinen
  Zugangsschutz — nur für die Entwicklung gedacht.

Zwei Sorten 401 werden unterschieden wie im Web-Frontend: Nur Tri-Coach selbst
setzt `WWW-Authenticate`. Ein 401 **ohne** den Kopf kommt vom Supervisor
(Ingress-Sitzung abgelaufen) und wird mit einer neuen Sitzung wiederholt; ein
401 **mit** Kopf heißt, das 30-Tage-Token ist abgelaufen — die App meldet sich
mit der gespeicherten Konto-ID still neu an.

Token (HA und Tri-Coach) liegen im Schlüsselbund, der Rest in den UserDefaults.

## Genutzte Endpunkte

| Endpunkt | Wofür |
|---|---|
| `GET /api/auth/users`, `POST /api/auth/login` | Kontoauswahl |
| `GET /api/plans/active` | Kalender: Einheiten des aktiven Blocks |
| `GET /api/ernaehrung/aktiv` | Ernährung je Tag, Supplemente |
| `GET /api/logs?weeks=8` | Kalender: absolvierte Einheiten aus Garmin |
| `GET /api/animationen/einheit/{id}` | Übungen einer Einheit samt Animation |
| `POST /api/animationen/{schluessel}/freigeben`, `…/verwerfen` | Prüfen einer KI-Animation |
| `POST /api/ki/animationen`, `GET /api/ki/jobs/{id}` | Fehlende erstellen lassen, Fortschritt |

Die Modelle in `TriCoach/Modelle/Modelle.swift` spiegeln die Pydantic-Schemas
(wie `frontend/src/types.ts`) — ändert sich dort ein Feld, muss es hier mit.
Zahlen sind durchgehend `Double`, fehlende Felder optional: Ein neues Feld im
Backend bricht die App nicht.

## Bauen

- Xcode 16 oder neuer (das Projekt nutzt synchronisierte Ordner: Jede Datei
  unter `TriCoach/` gehört automatisch zum Target).
- iOS 17 als Mindestversion (`@Observable`).
- Simulator: Schema *TriCoach* wählen, ⌘R.
- Eigenes iPhone: Unter *Signing & Capabilities* das eigene Team wählen. Mit
  einer kostenlosen Apple-ID läuft die App 7 Tage, dann einmal neu aus Xcode
  installieren.

Kommandozeile:

```bash
cd ios
xcodebuild -project TriCoach.xcodeproj -scheme TriCoach \
  -destination 'generic/platform=iOS Simulator' -derivedDataPath build build
```

## Entwickeln im Simulator

Nur im **Debug-Build im Simulator** (alles unter `#if DEBUG && targetEnvironment(simulator)`,
im Release und auf dem iPhone nicht enthalten):

- **`ios/Lokal/zugang.json`** belegt Adresse und Token vor und meldet sich,
  wenn `konto` gesetzt ist, beim Start selbst an. Grund: Ein langes HA-Token
  lässt sich je nach Xcode-Version nicht zuverlässig per Zwischenablage in den
  Simulator bringen. Die Datei steht in `.gitignore`.

  ```json
  {
    "home_assistant_adresse": "http://homeassistant.local:8123",
    "home_assistant_token": "…",
    "konto": "Molker"
  }
  ```

  Zwei weitere Schlüssel öffnen nach dem Laden von selbst eine Seite — für
  den Fall, dass Klicks im Simulator nicht ankommen: `"start_einheit"` (eine
  Kennung oder eine Sportart, `"strength"` = die nächste Krafteinheit ab heute)
  und darin `"start_uebung"` (ein Schlüssel wie `"clamshell"` oder `"*"` für
  die erste Übung mit Animation).

- **Übungen ohne neues Add-on.** Antwortet das Add-on auf
  `/api/animationen/…` noch nicht (vor 4.6.0), nimmt der Simulator die
  Bibliothek aus dem Repository (`backend/app/animation/bibliothek/bibliothek.json`,
  `Hilfen/Entwicklungsbibliothek.swift`) — die Zuordnung dort ist vereinfacht,
  maßgeblich ist die des Backends.

- **`ios/build/diagnose/`** bekommt ein Protokoll (`protokoll.txt`: WebSocket,
  Ingress, jede Anfrage mit Status), die Rohantworten der API als JSON und alle
  drei Sekunden ein Bild des App-Bildschirms (`bildschirm.jpg`). Token,
  Ingress-Sitzung und die Antwort von `/auth/login` werden nie geschrieben.
