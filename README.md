# Tri-Coach

Webanwendung zur Trainingsplanung für Laufen, Schwimmen, Radfahren und Triathlon.
Die App sammelt Zielsetzung, Verfügbarkeit und Leistungswerte, erzeugt daraus ein
Datenpaket für eine KI und verwandelt deren Antwort in die konkreten nächsten
Trainingstage. Geplant wird bewusst nur ein kurzer Block von wenigen Tagen —
Grundlage sind aber immer die letzten vier Wochen erfasster Trainings.

## Starten

```bash
./start.sh
```

Danach: **http://localhost:5173**

Beim ersten Mal einmalig einrichten:

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
cd frontend && npm install
```

| Dienst          | Adresse                     |
| --------------- | --------------------------- |
| Frontend        | http://localhost:5173       |
| Backend         | http://127.0.0.1:8000       |
| API-Dokumentation | http://127.0.0.1:8000/docs |

## Der Ablauf

1. **Anmelden** — Konto anlegen oder aus der Liste auswählen und einloggen. Ein
   Passwort gibt es nicht; das zuletzt genutzte Konto ist vorausgewählt.
2. **Meine Daten** — Größe, Gewicht, Ruhepuls, Maximalpuls, VO2max, HRV und mehr.
   Daraus berechnet die App deine Herzfrequenzzonen (Karvonen).
3. **Neues Training** — Fragebogen in neun Schritten: Disziplin, Ziel,
   Trainingstage, beim Triathlon die Sportart je Tag, Zeitbudget,
   Ergänzungstraining, Ausrüstung, Leistungswerte, Zusammenfassung.
   Jeder Block hat ein Freitextfeld für Individuelles.
4. **Plan erzeugen** — ersten Tag und Blocklänge wählen (Vorgabe: heute, 7 Tage),
   „Text kopieren" liefert Prompt plus Datenpaket. Diesen Text an eine KI
   schicken, deren Antwort zurück ins Feld einfügen, „Plan übernehmen". Bei
   aktivem Plan: Knopf „Nächste 7 Tage planen" verlängert den Block beliebig oft.
5. **Trainingsplan** — die gewählten Tage, jede Einheit mit Aufbau, Zielpuls,
   Pace und Trainingswirkung.
6. **Training erfassen** — nach der Einheit Puls, Strecke, Zeit, Watt, RPE und
   Befinden eintragen.
7. **Nächster Block** — läuft der Block aus, sagt das Dashboard Bescheid. Der
   nächste Export enthält automatisch die letzten vier Wochen: tatsächlicher
   Umfang, ausgefallene Einheiten, RPE-Verlauf, Morgenpuls, HRV und den Abstand
   zur letzten Einheit je Sportart.

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
  sportscience.py   HF-Zonen, TRIMP, sRPE-Last, ACWR, Umsetzungsquote
  ai_export.py      Datenpaket und Prompt für die KI
  plan_import.py    Parser und Validierung der KI-Antwort
  routers/          auth, profile, questionnaire, plans, logs

frontend/src/
  api/client.ts     typisierter API-Client
  auth/             Auth-Context, Token in localStorage
  constants.ts      Labels, Fragenkataloge, Wochentage
  pages/            Landing, Login, Register, Dashboard, NewTraining,
                    PlanExchange, PlanView, LogSession, History, ProfilePage
```

## Tests

```bash
cd backend && .venv/bin/python -m pytest tests/ -q
```

Der Test deckt den kompletten Ablauf ab: Registrierung, Profil samt
Zonenberechnung, Fragebogen mit Normalisierung deutscher Wochentage, KI-Export,
Import einer KI-Antwort inklusive Codefences und Begleittext, Abweisung
fehlerhafter Antworten, Trainingserfassung, Auswertung und Mandantentrennung.

## Datenschutz

Das Datenpaket enthält Gesundheitsdaten — Ruhepuls, Gewicht, HRV, Angaben zu
Verletzungen. Was in eine KI kopiert wird, verlässt den eigenen Rechner und
unterliegt den Bedingungen des jeweiligen Anbieters.

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
