# Tri-Coach

Webanwendung zur Trainingsplanung für Laufen, Schwimmen, Radfahren und Triathlon.
Die App sammelt Zielsetzung, Verfügbarkeit und Leistungswerte, erzeugt daraus ein
Datenpaket für eine KI und verwandelt deren Antwort in die konkreten nächsten
Trainingstage. Geplant wird bewusst nur ein kurzer Block von wenigen Tagen —
Grundlage sind aber immer die letzten vier Wochen erfasster Trainings.

Wer ein **Garmin-Connect-Konto** verbindet, muss dafür nichts mehr eintippen:
Trainings, Schlaf, HRV, Ruhepuls und Garmins Erholungsbewertungen werden
automatisch geholt und steuern den nächsten Trainingsvorschlag mit.

## Starten

```bash
./start.sh
```

Danach: **http://localhost:5173**

Beim ersten Mal einmalig einrichten. **Python 3.12 oder neuer ist nötig** — die
Garmin-Anbindung setzt es voraus, und `python3` zeigt auf manchen Rechnern noch
auf eine ältere Version:

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -U pip
backend/.venv/bin/pip install -r backend/requirements-dev.txt
cd frontend && npm install
```

`requirements-dev.txt` enthält die Laufzeitpakete plus pytest und httpx. Für
einen reinen Betrieb genügt `requirements.txt`.

| Dienst          | Adresse                     |
| --------------- | --------------------------- |
| Frontend        | http://localhost:5173       |
| Backend         | http://127.0.0.1:8000       |
| API-Dokumentation | http://127.0.0.1:8000/docs |

## Der Ablauf

1. **Anmelden** — Konto anlegen oder aus der Liste auswählen und einloggen. Ein
   Passwort gibt es nicht; das zuletzt genutzte Konto ist vorausgewählt.
2. **Garmin verbinden** (empfohlen) — einmalig mit den Garmin-Zugangsdaten
   anmelden, dann den Rückblick holen. Danach kommen Trainings und Fitnessdaten
   von selbst: täglich im Hintergrund oder per Knopfdruck.
3. **Meine Daten** — Größe, Gewicht, Ruhepuls, Maximalpuls, VO2max, HRV und mehr.
   Daraus berechnet die App deine Herzfrequenzzonen (Karvonen). Mit verbundenem
   Garmin-Konto werden Gewicht, Ruhepuls, HRV und VO2max automatisch
   nachgeführt; der Maximalpuls bleibt Handarbeit, weil er alle Zonen bestimmt.
4. **Neues Training** — Fragebogen in neun Schritten: Disziplin, Ziel,
   Trainingstage, beim Triathlon die Sportart je Tag, Zeitbudget,
   Ergänzungstraining, Ausrüstung, Leistungswerte, Zusammenfassung.
   Jeder Block hat ein Freitextfeld für Individuelles.
5. **Plan erzeugen** — ersten Tag und Blocklänge wählen (Vorgabe: heute, 7 Tage),
   „Text kopieren" liefert Prompt plus Datenpaket. Diesen Text an eine KI
   schicken, deren Antwort zurück ins Feld einfügen, „Plan übernehmen". Bei
   aktivem Plan: Knopf „Nächste 7 Tage planen" verlängert den Block beliebig oft.
6. **Trainingsplan** — die gewählten Tage, jede Einheit mit Aufbau, Zielpuls,
   Pace und Trainingswirkung.
7. **Training erfassen** — mit Garmin nur noch für Einheiten ohne Uhr oder um
   RPE und Befinden zu ergänzen; sonst Puls, Strecke, Zeit und Watt von Hand.
8. **Nächster Block** — läuft der Block aus, sagt das Dashboard Bescheid. Der
   nächste Export enthält automatisch die letzten vier Wochen: tatsächlicher
   Umfang, ausgefallene Einheiten, RPE-Verlauf, Morgenpuls, HRV und den Abstand
   zur letzten Einheit je Sportart — dazu, sofern verbunden, Garmins Schlaf-,
   HRV- und Erholungswerte samt vorverdichteter Auffälligkeiten.

## Technik

**Backend** — FastAPI, SQLAlchemy, SQLite, JWT (`PyJWT`). Die Anmeldung läuft
ohne Passwort über eine Kontoauswahl; der Schutz kommt vom Home-Assistant-Ingress
davor. Die Datenbank entsteht beim ersten Start unter `backend/data/`.

**Frontend** — React 19, TypeScript, Vite, React Router. Kein UI-Framework; das
Designsystem liegt in `src/styles.css` und unterstützt helles und dunkles Theme.

### Struktur

```
backend/app/
  main.py           FastAPI-App, CORS, Routen-Registrierung
  models.py         SQLAlchemy-Modelle
  schemas.py        Pydantic-Schemas, inkl. Validierung der KI-Antwort
  security.py       JWT erzeugen und prüfen
  deps.py           Auth-Abhängigkeiten (CurrentUser, DbSession)
  sportscience.py   HF-Zonen, TRIMP, sRPE-Last, ACWR, Umsetzungsquote,
                    Auffälligkeiten aus den Fitnessdaten
  ai_export.py      Datenpaket und Prompt für die KI
  plan_import.py    Parser und Validierung der KI-Antwort
  profile_sync.py   Profilwerte setzen und ihren Verlauf mitschreiben
  crypto.py         Verschlüsselung des Garmin-Tokens
  zeit.py           Zeitstempel aus SQLite vergleichbar machen
  garmin/           errors, client, mapping, matching, sync, runner, automatik
  routers/          auth, profile, questionnaire, plans, logs, garmin

frontend/src/
  api/client.ts     typisierter API-Client
  auth/             Auth-Context, Token in localStorage
  constants.ts      Labels, Fragenkataloge, Wochentage
  pages/            Landing, Login, Register, Dashboard, NewTraining,
                    PlanExchange, PlanView, LogSession, History, ProfilePage,
                    GarminPage
```

## Tests

```bash
cd backend && .venv/bin/python -m pytest tests/ -q
```

Die Tests decken den kompletten Ablauf ab: Registrierung, Profil samt
Zonenberechnung, Fragebogen mit Normalisierung deutscher Wochentage, KI-Export,
Import einer KI-Antwort inklusive Codefences und Begleittext, Abweisung
fehlerhafter Antworten, Trainingserfassung, Auswertung und Mandantentrennung.

Für Garmin kommen dazu: Anmeldung mit und ohne Bestätigungscode, Umrechnung der
Garmin-Felder, wiederholter Abgleich ohne Doppeleinträge, Schutz selbst
eingetragener Werte, Triathlon als eine Koppeleinheit, Verhalten bei
Anfragesperre und abgelaufenem Token sowie der Migrationshelfer. Die
Garmin-Tests laufen gegen eine Nachbildung — es geht dabei **keine** Anfrage an
Garmin.

## Datenschutz

Das Datenpaket enthält Gesundheitsdaten — Ruhepuls, Gewicht, HRV, Schlaf,
Angaben zu Verletzungen. Was in eine KI kopiert wird, verlässt den eigenen
Rechner und unterliegt den Bedingungen des jeweiligen Anbieters.

**Garmin-Zugangsdaten:** Das Passwort wird einmal zum Anmelden benutzt und
danach verworfen — gespeichert wird nur der Zugangsschlüssel, den Garmin
ausstellt, und der liegt verschlüsselt in der Datenbank. Der Schlüssel dafür
wird aus `TRI_SECRET_KEY` abgeleitet. Wird der gewechselt, sind gespeicherte
Token unlesbar und das Konto muss neu verbunden werden. Wer Zugriff auf die
Maschine selbst hat, kommt an beides — geschützt ist die *Kopie* der Datenbank,
etwa in einem Home-Assistant-Backup.

**Anfragegrenze:** Garmin sperrt ein Konto nach wenigen fehlgeschlagenen
Anmeldungen für bis zu 48 Stunden, und jeder weitere Versuch verlängert die
Sperre. Die App begrenzt Anmeldeversuche deshalb selbst und wiederholt gesperrte
Anfragen nie automatisch.

Die Anwendung ist für den lokalen Einsatz gebaut. Vor einem Betrieb im Netz
fehlen mindestens: HTTPS, ein gesetzter `TRI_SECRET_KEY`, angepasste
CORS-Herkünfte, Rate-Limiting am Login und eine Datenbank mit Migrationen
(Alembic) statt `create_all`.

## Docker

Für den Einsatz im Heimnetz (z. B. im Intranet) kann die App als Docker-Container
bereitgestellt werden:

```bash
# Einmalig: Secret Key erzeugen und in .env speichern
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))" # kopieren und in .env einfügen

# Starten
docker compose up --build
```

Die App läuft dann unter **http://localhost:8000** (oder der IP des Hosts im Netz).

**Datenpersistenz**: Die SQLite-Datenbank liegt in `./data/tricoach.db` und überlebt
Container-Neustarts. Das `TRI_SECRET_KEY` ist in `.env` gespeichert — ohne Änderung
bleiben Login-Sessions bei Neu-Starts erhalten.

**Sicherheit für das Heimnetz**: HTTPS ist nicht konfiguriert, da der Betrieb über
ein privates LAN vorgesehen ist. Für die Freigabe über das Internet wird ein
Reverse-Proxy mit TLS empfohlen (z. B. Caddy, Traefik oder Nginx).

## Home Assistant Add-on

Tri-Coach läuft als **Custom Add-on** in Home Assistant OS (HAOS) — über die Sidebar
erreichbar, authentifiziert via HA-Session (Ingress), komplett lokal gebaut.

### Installation (schnell)

1. **Repository hinzufügen**:
   - Home Assistant: **Einstellungen → Add-ons → Add-on Store** → oben rechts ⋮ → **Repositories**
   - URL: `https://github.com/Molker86/tri-coach`
   - Speichern

2. **Installieren & Starten**:
   - Im Store nach „Tri-Coach" suchen → **Installieren**
   - (Supervisor baut lokal; ~15–20 Min auf Raspberry Pi)
   - Nach Build: **Starten**
   - Optional: **„In Sidebar anzeigen"** aktivieren

3. **Zugriff**:
   - Icon (🏃) in der HA-Sidebar → Tri-Coach öffnet sich embedded
   - Registrieren → wie unter „Der Ablauf" beschrieben

### Aktualisierungen

Nach einem `git push` auf `main` wird das Repo beim nächsten Check aktualisiert.
Im Add-on-Store auf der Tri-Coach-Karte: Falls eine neue Version vorhanden, **Update** anklicken.
