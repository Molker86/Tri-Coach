# Tri-Coach — Kontext für Claude Code

## Was das ist

Trainingsplanungs-App für Ausdauersport. Der Nutzer beantwortet einen
Fragebogen, die App erzeugt daraus Prompt + Datenpaket für eine KI, der Nutzer
kopiert das per Hand in eine KI und fügt die Antwort zurück in die App ein. Die
Antwort wird zu einem strukturierten Trainingsblock über wenige Tage. Absolvierte
Trainings werden erfasst und fließen in den nächsten Export ein.

**Asymmetrie merken:** Rückblick vier Wochen, Vorausplanung wenige Tage
(Vorgabe 7, einstellbar 1–14 über `days` am Export). Das ist eine bewusste
Entscheidung — siehe „Planungshorizont".

**Wichtig:** Die App ruft *keine* KI-API auf. Der Austausch läuft bewusst über
Kopieren und Einfügen — so war die Anforderung. Ein späterer Direktaufruf wäre
eine Erweiterung, kein Ersatz: Der Export-Endpunkt liefert bereits den fertigen
Prompt, der Import-Endpunkt akzeptiert bereits rohen Antworttext.

## Ursprüngliche Anforderungen

- Anmelden/Registrieren über die Landingpage.
- „Neues Training": Einzeldisziplinen Laufen, Schwimmen, Radfahren — oder Triathlon.
- Geclusterte Fragen, Multiple Choice mit **Freitextfeld je Cluster**.
  Ausnahme: Die Wochentagsabfrage hat bewusst *kein* Freitextfeld.
- Beim Triathlon zusätzlich: welche Sportart an welchem Tag möglich ist.
- Abfrage zu Bodyworkout/Dehneinheiten — oder nichts davon.
- Physiologische Werte: Ruhepuls, Maximalpuls, VO2max, HRV, Größe, Gewicht, Alter.
- Alle Angaben als JSON zum Kopieren; KI-Antwort als JSON wieder einfügbar.
- Stammdaten jederzeit änderbar.
- Nach dem Training Werte erfassen (Puls, Strecke, Zeit …).
- Immer die letzten 4 Wochen plus die Wunschdaten steuern die nächste Planung.
- Geplant wird jeweils nur der nächste kurze Block (Nachforderung, ersetzt den
  ursprünglichen Vier-Wochen-Plan). Ein aktiver Plan kann per Knopfdruck um
  beliebig viele weitere Blöcke verlängert werden — die Auswertung bezieht sich
  immer auf die letzten 4 Wochen, unabhängig davon, wie lange der Block reicht.

## Starten und Testen

```bash
./start.sh                                        # beide Server
cd backend && .venv/bin/python -m pytest tests/ -q # 16 Tests, decken den Vollablauf ab
cd frontend && npm run build                       # Typecheck + Produktionsbuild
```

Datenbank: `backend/data/tricoach.db`, entsteht beim ersten Start. Löschen setzt
alles zurück. JWT-Schlüssel liegt in `backend/.secret_key` (automatisch erzeugt),
überschreibbar per `TRI_SECRET_KEY`; die DB per `TRI_DATABASE_URL`.

## Architekturentscheidungen (und warum)

**Planungshorizont: wenige Tage, Rückblick vier Wochen** (`ai_export.py`,
`PLAN_DAYS_DEFAULT = 7` / `HISTORY_WEEKS = 4`). Ein Plan ist nach der ersten
Woche ohnehin überholt, und für die KI ist ein kurzer Block die deutlich
leichtere und präzisere Aufgabe: statt 28 Tagen füllt sie ein paar Tage, die
dafür genau zur aktuellen Belastungslage passen. Die Individualität kommt nicht
aus der Länge des Plans, sondern aus der Historie — die bleibt vier Wochen tief
und wandert vollständig in jeden Export. Ein aktiver Plan kann per Knopfdruck
um die nächsten 7 Tage verlängert werden (oder beliebig oft wiederholt); die
Auswertung bezieht sich weiterhin auf die letzten 4 Wochen, nicht auf die
bisherige Blocklänge. Deshalb liefert `_history_block()` zusätzlich
`tage_seit_letzter_einheit_je_sportart` und
`tage_seit_letzter_intensiver_einheit`: Auf wenigen Tagen entscheidet der
Abstand zur letzten Einheit, welche Disziplin drankommt und ob am ersten Tag
hart trainiert werden darf. Weil ein Block schnell ausläuft, weist das Dashboard
darauf hin, sobald der aktive Block heute endet oder vorbei ist (`blockStatus()`
in `Dashboard.tsx`) — sonst stünde der Nutzer mit einem abgelaufenen Plan da,
ohne dass die App etwas dazu sagt.

**Nachtragen ist derselbe Bildschirm, nicht ein zweites Formular.**
`/training-nachtragen` rendert `LogSession` mit `mode="backfill"` — gleiche Felder,
gleiche Validierung, nur andere Voreinstellungen: Datum auf gestern statt heute,
Obergrenze heute, Sportart frei wählbar (sie hängt nie am Plan). Zwei Formulare
würden bei jeder neuen Messgröße auseinanderlaufen. Die Auswertung braucht dafür
nichts Eigenes: `list_logs`, `/logs/stats` und `_history_block()` filtern rein
über `SessionLog.date`, ein nachgetragener Eintrag zählt also automatisch mit,
sobald er ins Vierwochenfenster fällt — liegt er davor, sagt die Oberfläche das
(`outsideHistoryWindow`), statt ihn stillschweigend wirkungslos zu speichern.
Offene Planeinheiten werden beim Nachtragen 28 statt 14 Tage weit zur
Verknüpfung angeboten, damit die Umsetzungsquote nicht löchrig bleibt.

**FastAPI statt Django.** Der Kern der App ist Schema-Arbeit: Ein- und Ausgabe
gegenüber der KI müssen streng validiert werden. Pydantic macht das direkt zum
Typsystem; Djangos Stärken (Admin, ORM-Migrationen, Templates) hätten hier
wenig beigetragen und viel Rahmenwerk gekostet.

**Strings statt DB-Enums** in `models.py`. Validierung passiert in den
Pydantic-Schemas. So kostet eine neue Sportart oder ein neuer Einheitentyp keine
Migration — relevant, weil die KI die Werte liefert.

**Toleranter Import** (`plan_import.py`). KI-Antworten kommen in der Praxis mit
Codefences, Begleittext oder als flaches Objekt ohne `plan`-Wurzel. Der Parser
schneidet das erste vollständige JSON-Objekt heraus (klammerzählend, Strings
werden dabei übersprungen) und normalisiert Sprachvarianten
(`"Laufen"`/`"run"`/`"Rad"`). Abgeschnittene Antworten bekommen eine eigene
Fehlermeldung, weil das der häufigste Fall ist. `_flatten_weeks()` zieht
Antworten, die trotzdem eine `weeks`-Ebene mitbringen, auf die flache Tagesliste
herunter — Modelle greifen gern auf diese vertraute Struktur zurück.

**Warnungen statt Ablehnung.** `validate_coverage()` meldet fehlende oder leere
Tage, blockiert den Import aber nicht — ein Block mit drei statt vier Tagen ist
brauchbar, ein abgelehnter Import frustrierend. Die erwartete Blocklänge kommt
als `days` mit dem Import-Request mit; ohne sie wird nur der gelieferte Zeitraum
auf Lücken geprüft.

**Kein UI-Framework.** `styles.css` ist ein kleines Designsystem mit
CSS-Variablen und Hell/Dunkel-Umschaltung über `prefers-color-scheme`.

**Der Pfad-Prefix kommt zur Laufzeit, nicht aus dem Build.** Ingress liefert die
App unter `/api/hassio_ingress/<token>/` aus, nicht unter `/`. Absolute Pfade
laufen dort ins Leere: Der Browser löst sie gegen die Home-Assistant-Wurzel auf,
also lädt kein Asset und die Seite bleibt weiß. Weil der Token pro Sitzung neu
ist, kann der Prefix nicht in den Build wandern. Deshalb der Dreischritt: Vite
baut mit `base: './'` relative Verweise, `_index_with_base()` in `main.py`
schreibt aus dem `X-Ingress-Path`-Header ein `<base>`-Tag in die index.html, und
`basePath.ts` liest den Prefix von dort zurück und gibt ihn an die API-Aufrufe
(`client.ts`) und den Router-`basename` (`main.tsx`) weiter. Ohne die beiden
letzten Schritte lädt die Oberfläche, aber `fetch('/api/…')` landet bei der
Home-Assistant-API statt beim Add-on und ein Klick schiebt die Adresse auf die
HA-Wurzel. Das `<base>`-Tag wird auch ohne Ingress gesetzt (dann `/`), weil
relative Verweise beim Neuladen einer Unterseite sonst gegen `/dashboard/`
aufgelöst würden. Wer im Frontend eine Adresse selbst zusammenbaut, muss
`BASE_PATH` mitnehmen — Router-`Link`s und `navigate()` erledigen das von allein,
`window.location` dagegen nicht (deshalb `useLocation()` in `PlanView.tsx`).

**Am Telefon trägt die Navigation unten, nicht oben.** Die Kopfleiste mit sieben
Wegen nebeneinander funktioniert am Schreibtisch; auf einem Telefon bräuchte sie
drei Zeilen und stünde bei jedem Scrollen im Weg. Unterhalb von 860 px entfällt
sie deshalb ganz (`.topbar-app`), stattdessen blendet `Layout.tsx` eine feste
Leiste am unteren Rand ein: Übersicht, Plan, Erfassen, Verlauf und „Mehr“ —
hinter „Mehr“ liegt ein Blatt mit Neues Training, Nachtragen, Meine Daten und
Abmelden. Orientierung geht dabei nicht verloren, weil jede Seite ihre
Überschrift selbst trägt. Zwei Dinge hängen daran: `.page` braucht unten Platz
für die Leiste samt `env(safe-area-inset-bottom)` — dafür steht
`viewport-fit=cover` in der `index.html`, ohne das der Wert auf iOS 0 bleibt —
und Eingabefelder bekommen dort 16 px Schriftgröße, weil iOS darunter beim
Antippen in die Seite hineinzoomt und den Nutzer im vergrößerten Ausschnitt
zurücklässt.

**Tabellen werden auf schmalen Bildschirmen zu Karten.** Acht Spalten passen nur
mit Querscrollen auf ein Telefon, und was man wegschieben muss, sieht man nicht.
`.table-cards` bricht deshalb unterhalb von 640 px jede Zeile in eine Karte auf:
Die Beschriftung je Wert kommt aus `data-label` am `<td>`, die Zelle mit
`.cell-title` wird zur Überschrift der Karte, `.cell-actions` rückt an den
rechten Rand. Das Markup bleibt eine Tabelle — am Schreibtisch ändert sich
nichts, und eine zweite Darstellung, die mit der ersten auseinanderläuft,
entsteht gar nicht erst. Wer eine Spalte ergänzt, muss `data-label` mitgeben,
sonst steht der Wert am Telefon ohne Beschriftung da. Formularraster (`.grid-3`)
rücken auf zwei Spalten zusammen statt untereinander; damit die Eingabefelder
trotz unterschiedlich langer Beschriftungen auf einer Linie bleiben, teilen sich
die Felder per `subgrid` dieselben Zeilen.

**Home-Assistant-Integration: Lokales Build im Repo-Root**
(`config.yaml`, `build.yaml`, `run.sh`, Root-`Dockerfile`). Der HA Supervisor
baut die App beim Installieren lokal — `build.yaml` setzt den Build-Context
auf `../` (Repo-Root), damit der Dockerfile auf `backend/`, `frontend/` und
`run.sh` zugreifen kann. Keine Umorganisation in Unterordnern nötig; `git clone`
oder `git pull` funktioniert direkt. Das zentrale `run.sh` setzt 
Supervisor-spezifische Umgebungsvariablen: `TRI_SECRET_KEY` (optional aus
`options.json`, sonst Auto-Generierung, persistent unter `/data/.secret_key`)
und `TRI_DATABASE_URL` → `/data/tricoach.db`. Vorteil: Dezentral, keine
externen Abhängigkeiten, einfache Update-Struktur. Nachteil: Build dauert auf
Raspberry Pi ~15–20 Min (Node-Frontend wird lokal kompiliert). Zugriff über
**Ingress** (kein offener LAN-Port, authentifiziert via HA-Session). Der
Root-`Dockerfile` nutzt `python:3.12-slim` — kein S6-Overlay oder Bashio
nötig (nur ein Uvicorn-Prozess).

## Konventionen

- **Alle nutzersichtbaren Texte auf Deutsch**, auch Fehlermeldungen aus der API.
- Code, Bezeichner und Kommentare ebenfalls auf Deutsch gehalten, wo sie
  Fachliches beschreiben.
- Kommentare erklären das *Warum*, nicht das *Was*.
- Frontend-Typen in `src/types.ts` spiegeln die Backend-Schemas. Ändert sich ein
  Pydantic-Schema, muss der Typ mitgezogen werden — es gibt keine Codegenerierung.
- Profil-Updates sind Teil-Updates (`exclude_unset`): Ein Formular, das nur ein
  Feld schickt, darf die anderen nicht löschen.
- Änderungen an Gewicht, Ruhepuls, HRV, VO2max, Maximalpuls oder FTP schreiben
  automatisch einen Eintrag in `ProfileHistory`.

## Sportwissenschaftliche Logik (`sportscience.py`)

- **HF-Zonen**: Karvonen (Herzfrequenzreserve), wenn Ruhe- und Maximalpuls
  bekannt sind, sonst % HFmax. Fehlender Maximalpuls wird über
  `211 − 0,64 × Alter` (Nes et al. 2013) geschätzt und im Frontend als Schätzung
  ausgewiesen.
- **TRIMP** nach Banister, geschlechtsspezifisch gewichtet.
- **sRPE-Last** nach Foster (Dauer × RPE) — funktioniert ohne Pulsgurt.
- **ACWR**: Last der letzten Woche gegen den Vier-Wochen-Schnitt. Über 1,3 gilt
  als erhöhtes Überlastungsrisiko.
- **Umsetzungsquote**: Nur Planeinheiten, deren Datum bereits vergangen ist,
  zählen als fällig. Ein Block, der erst morgen startet, hat deshalb
  korrekterweise `rate_pct: null`.

## Der Prompt (`ai_export.py`)

`PROMPT_TEMPLATE` enthält die verbindlichen Trainingsprinzipien und
`RESPONSE_SCHEMA` das erwartete Antwortformat. Die Prinzipien sind auf den kurzen
Block zugeschnitten: Einordnung in den bisherigen Verlauf statt 3:1-Zyklus,
höchstens eine intensive Einheit je drei Tage, 48 h Abstand *auch über den
Blockanfang hinweg*, und beim Triathlon Disziplinenwahl nach dem längsten
Abstand statt „alle drei pro Woche". Das Template wird mit `.format()` gefüllt —
neue Platzhalter (`{tage}`, `{start}`, `{ende}`) müssen in `build_prompt()`
mitversorgt werden.

Änderungen am Antwortformat müssen an drei Stellen zusammenpassen:
`RESPONSE_SCHEMA`, die `AI*In`-Schemas in `schemas.py` und `build_plan()` in
`plan_import.py`.

## Bekannte Grenzen / mögliche nächste Schritte

- Kein Bearbeiten erfasster Trainings im Frontend (die API kann es bereits:
  `PUT /api/logs/{id}`).
- Keine Diagramme — Verlauf und Wochenübersicht sind Tabellen.
- Kein Alembic; Schemaänderungen erfordern derzeit das Löschen der SQLite-Datei
  oder ein `ALTER TABLE` von Hand. Solange die App in Beta ist, ist das der
  bewusste Weg — kein Kompatibilitätsballast im Modell.
- Kein Rate-Limiting am Login, keine Passwort-zurücksetzen-Funktion.
- Für den Netzbetrieb fehlen HTTPS, gesetzter `TRI_SECRET_KEY` und angepasste
  CORS-Herkünfte (`config.py`).
