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

**Trainings- und Fitnessdaten kommen aus Garmin Connect.** Wer ein Konto
verbindet, muss nichts mehr von Hand nachtragen: Trainings, Schlaf, HRV,
Ruhepuls und Garmins Erholungsbewertungen werden geholt und fließen in den
nächsten Export ein. Die Formulare bleiben als Rückfallebene — für Einheiten
ohne Uhr und für subjektive Werte, die kein Gerät misst.

**Wichtig:** Die App ruft *keine* KI-API auf. Der Austausch läuft bewusst über
Kopieren und Einfügen — so war die Anforderung. Ein späterer Direktaufruf wäre
eine Erweiterung, kein Ersatz: Der Export-Endpunkt liefert bereits den fertigen
Prompt, der Import-Endpunkt akzeptiert bereits rohen Antworttext.

## Ursprüngliche Anforderungen

- Anmelden/Registrieren über die Landingpage (Nachforderung: Die Anmeldung
  läuft inzwischen ohne Passwort über eine Kontoauswahl — siehe „Anmeldung").
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
cd backend && .venv/bin/python -m pytest tests/ -q # 79 Tests
cd frontend && npm run build                       # Typecheck + Produktionsbuild
```

**Python 3.12 ist Pflicht** (`garminconnect` verlangt es). Auf manchen Rechnern
zeigt `python3` noch auf eine ältere Version — deshalb ausdrücklich:

```bash
rm -rf backend/.venv && python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -U pip
backend/.venv/bin/pip install -r backend/requirements-dev.txt   # enthält requirements.txt
```

`start.sh` prüft die Version und sagt es, falls sie nicht reicht. Test- und
Entwicklungspakete (pytest, httpx) stehen in `requirements-dev.txt` und bleiben
so aus dem Docker-Abbild heraus.

Datenbank: `backend/data/tricoach.db`, entsteht beim ersten Start. Löschen setzt
alles zurück — **und trennt die Garmin-Verbindung**, weil das verschlüsselte
Token mit verschwindet.

Umgebungsvariablen: `TRI_SECRET_KEY` (sonst `backend/.secret_key`, automatisch
erzeugt — ein Wechsel macht gespeicherte Garmin-Token unlesbar und verlangt eine
Neuanmeldung), `TRI_DATABASE_URL`, `TRI_CORS_ORIGINS`, `TRI_GARMIN_AUTOSYNC`
(`0` schaltet den täglichen Abgleich ab; in Tests gesetzt) und
`TRI_GARMIN_SYNC_HOUR` (Ortszeit-Stunde, ab der abgeglichen wird, Vorgabe 5).

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

**Anmeldung ohne Passwort, per Kontoauswahl.** `/api/auth/users` liefert alle
Konten als `{id, username}`, `/api/auth/login` nimmt nur noch eine `user_id` und
gibt dafür ein Token aus. Die App läuft hinter dem Home-Assistant-Ingress, der
die Sitzung bereits authentifiziert hat — ein zweites Passwort davor wäre
Reibung ohne Sicherheitsgewinn, zumal es hier nur um Trainingsdaten im eigenen
Haushalt geht. Die Kehrseite steht damit fest: **Wer die App erreicht, kann sich
als jedes Konto anmelden.** Wird sie je ohne Ingress ins Netz gestellt, muss
davor eine Authentifizierung. Die Auswahlliste ist bewusst unauthentifiziert
(sonst käme niemand an die Anmeldung) und gibt deshalb keine E-Mail preis. Weil
kein Passwort mehr existiert, fragt auch die Registrierung keins mehr ab; die
Spalte `hashed_password` bleibt leer im Modell stehen, weil ihr Entfernen ohne
Alembic bestehende Datenbanken bräche. Das zuletzt genutzte Konto merkt sich
`localStorage` (`tricoach.lastUser`, geschrieben im `AuthContext` nach
erfolgreicher An- oder Neuanmeldung, gelesen von `Login.tsx`) und ist beim
nächsten Mal vorausgewählt — steht es nicht mehr in der Liste, das erste Konto.

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

**Garmin Connect: Token statt Passwort, Thread statt Auftragswarteschlange**
(`app/garmin/`). Das Passwort wird einmal zum Anmelden benutzt und sofort
verworfen; dauerhaft bleibt nur Garmins Zugangsschlüssel, verschlüsselt in der
Datenbank (`crypto.py`, Fernet mit einem aus `SECRET_KEY` abgeleiteten
Schlüssel). Der Grund für die Verschlüsselung liegt nicht in der App, sondern im
Betrieb: `/data/tricoach.db` wandert in jedes Home-Assistant-Backup und von dort
auf NAS oder USB-Stick. Ein Klartext-Token mit Dauerzugriff auf ein fremdes
Gesundheitskonto hätte dort nichts zu suchen. Was das *nicht* schützt: Wer
Zugriff auf die Maschine hat, kommt an Schlüssel und Geheimtext.

**Das eigentliche Risiko ist der Login, nicht der Datenabruf.** Garmin zählt
Anmeldeversuche auf Kontoebene und sperrt bis zu 48 Stunden, und jeder weitere
Versuch verlängert die Sperre. Deshalb: Token wiederverwenden statt neu
anmelden, höchstens drei Anmeldeversuche je Stunde (`client.py`), nach einem 429
wird `rate_limited_until` gesetzt und respektiert, und nirgends wird eine
gesperrte Anfrage automatisch wiederholt. Die Bibliotheksfehler werden an genau
einer Stelle in eigene Fehler mit deutschen Meldungen übersetzt (`errors.py`);
`sync._hole_geschuetzt()` fängt jeden Endpunkt einzeln ab — **außer** der
Anfragesperre, die den ganzen Lauf beenden muss.

**Bereichsabfragen statt Tagesschleife** (`sync.py`). Trainings, Schlaf, HRV,
Ruhepuls, VO2max, Gewicht und Körperbatterie gibt es je Zeitraum in einer
Anfrage — ein Jahr kostet damit rund fünfzig statt dreitausend Anfragen. Nur
Trainingsreife, Trainingsstatus, Stress und der Schlafscore gibt es
ausschließlich tageweise, und diese Schleife läuft bewusst nur `TAGESSCHLEIFE_TAGE`
= 42 Tage weit: Das sind Zustandsgrößen, ein Readiness-Wert von vor zehn Monaten
trägt keine Planungsentscheidung mehr. Zwischen zwei Tagen liegen 5 s Pause —
pro Tag, nicht pro Anfrage. Alles ist ein Upsert über `(user_id, date)` bzw.
`(user_id, garmin_activity_id)`, damit ein zweiter Lauf nichts verdoppelt und
ein Wiederaufsetzen nach einer Sperre folgenlos bleibt.

**Der Abgleich läuft in einem eigenen Thread** (`runner.py`), nicht in
`BackgroundTasks`: Er dauert Minuten und muss abfragbar, abbrechbar und nach
einem Neustart erkennbar unterbrochen sein — nichts davon leistet ein
Hintergrundauftrag von Starlette, der außerdem einen Platz im Threadpool
belegte, über den auch normale Anfragen laufen. Der Fortschritt steht in
`GarminSyncJob`, nicht in einem Dict im Speicher, damit die Oberfläche ihn
abfragen kann. Ein **globales** Schloss, nicht eines je Nutzer: Garmins Grenze
hängt auch an der Herkunftsadresse. Beim Start markiert
`markiere_unterbrochene_jobs()` alle noch als „läuft" eingetragenen Läufe als
unterbrochen — ihr Thread ist mit dem Prozess gestorben. Weil zwei Schreiber auf
derselben SQLite-Datei arbeiten, steht `journal_mode=WAL` und ein `timeout` von
30 s in `database.py`.

**RPE wird geschätzt, ACWR bleibt sRPE-basiert** (`mapping.schaetze_rpe`).
Garmin liefert kein RPE, aber `weekly_summary`, `acute_chronic_ratio` und
`_days_since_hard_session` rechnen alle damit — ohne Schätzung fiele die halbe
Steuerung für importierte Trainings aus. Geschätzt wird aus der Zeitverteilung
über die Herzfrequenzzonen, ersatzweise aus dem Trainingseffekt oder dem
Durchschnittspuls; `rpe_source` hält fest, woher der Wert stammt, und ein selbst
eingetragenes RPE wird beim nächsten Abgleich nicht überschrieben (`logs.py`
setzt `rpe_source` auf `manual`, sobald der Nutzer den Wert ändert). Garmins
`activityTrainingLoad` läuft nur *zusätzlich* mit (`total_garmin_load`) und
ersetzt die sRPE-Last **nicht**: Beide sind unterschiedlich skaliert, und eine
Übergangswoche aus manuellen und importierten Einheiten ergäbe sonst Unsinn.
Eine einheitliche Skala über den Übergang ist mehr wert als die theoretisch
bessere Metrik.

**Ein Triathlon ist eine Koppeleinheit, keine drei Einheiten**
(`mapping.teile_multisport`). Drei Kindeinträge an einem Tag würden die
Einheitenzahl verdreifachen, die sRPE-Last überzählen und
`tage_seit_letzter_einheit_je_sportart` für alle drei Disziplinen auf 0 setzen —
die KI plante dann kein Schwimmen mehr, obwohl nur der Radteil stattfand. Die
Teildisziplinen wandern als Notizzeile an die Elterneinheit.

**Zwei gegenläufige Zeitzonenregeln**, die zusammen in `mapping.py` kommentiert
stehen: Aktivitäten werden über `startTimeLocal` datiert (der Trainingstag ist
der lokale Tag), Schlafdaten über die `*GMT`-Felder (die `*Local`-Varianten sind
bei manchen Zeitzonen doppelt versetzt). Wer das „vereinheitlicht", verschiebt
entweder alle Trainings oder alle Schlafwerte um einen Tag. Verwandt: SQLite
gibt Zeitstempel ohne Zeitzone zurück, ein Vergleich mit `now(timezone.utc)`
wirft — dafür gibt es `app/zeit.py`.

**Fitnessdaten sind ein eigener Block im Export, nicht Teil der Historie**
(`ai_export._fitness_block`). Die Historie beschreibt absolvierte *Einheiten*,
die Fitnessdaten den *Zustand*. Auf oberster Ebene kann der Prompt sie
namentlich mit eigenen Regeln ansprechen. Der Block hat vier Ebenen, weil die KI
vier Fragen hat: `aktuell`, `mittelwerte` (7 gegen 28 Tage), `auffaelligkeiten`
(vorverdichtete deutsche Sätze aus `sportscience.wellness_auffaelligkeiten`) und
`tage`. Vorverdichtet, weil Sprachmodelle beim Mitteln von Zahlenreihen
unzuverlässig sind. Die Regeln dazu stehen als Punkt 2 der Trainingsprinzipien
und existieren in **zwei** Fassungen: Ohne verbundenes Konto entfällt der Block,
und der Prompt verweist stattdessen ausdrücklich auf RPE und Morgenpuls — Regeln
zu Daten, die es nicht gibt, laden zum Erfinden ein. Die Schwellen in
`wellness_auffaelligkeiten` und die Zahlen im Prompt müssen zusammen geändert
werden.

**Profilwerte kommen automatisch nach — außer dem Maximalpuls**
(`profile_sync.py`). Gewicht, Körperfett, Ruhepuls, HRV und VO2max werden
übernommen, der Ruhepuls als **Median der letzten sieben Tage**, weil ein
einzelner Ausreißer sonst alle Karvonen-Zonen verschöbe. Der Maximalpuls bleibt
Handarbeit: Garmin schätzt ihn, liegt oft daneben, und er steuert sämtliche
Zonen. Geschrieben wird nur bei relevanter Abweichung, sonst entstünde täglich
ein `ProfileHistory`-Eintrag ohne Erkenntnis. Die History-Logik wurde aus
`routers/profile.py` nach `profile_sync.uebernehme_profilwerte()` gezogen, damit
Handeingabe und Gerät dieselbe Regel benutzen. Garmins `lastNightAvg` ist
übrigens *nicht* rMSSD, sondern ein Nachtmittel — der Spaltenname `hrv_rmssd`
bleibt (Umbenennen wäre eine Migration ohne Gewinn), die Herkunft wird im Profil
und im Export ausgewiesen.

**Schemaänderungen laufen jetzt über einen Migrationshelfer** (`database.py`,
`_NACHGEREICHTE_SPALTEN`). `create_all()` legt fehlende *Tabellen* an, sieht aber
neue *Spalten* nicht. Bisher war „Datenbank löschen" der bewusste Weg; mit
Garmin wird er teuer, weil ein neuer Rückblick Minuten gegen ein fremdes System
mit Anfragegrenze kostet und Passwort samt Bestätigungscode erneut verlangt. Ein
paar Zeilen `ALTER TABLE ADD COLUMN`, idempotent bei jedem Start, sind billiger
als Alembic. Neue Spalten gehören dort eingetragen, sonst brechen bestehende
Datenbanken.

**Der Fortschritt wird abgefragt, nicht geschoben** (`api/client.ts`,
`pollJob`). Erstes Muster dieser Art in der App. Das Intervall ist bewusst träge
(2,5 s, nach zwei Minuten 5 s) — der Abgleich macht ohnehin nur alle paar
Sekunden einen Schritt, und häufigeres Fragen erzeugt nur Last auf einem
Raspberry Pi. Bei `visibilitychange` wird sofort einmal nachgefragt, weil
Telefone Zeitgeber im Hintergrund drosseln und der Balken sonst eingefroren
wirkte. Netzfehler beenden die Schleife nicht: Der Lauf geht im Server weiter.

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
  automatisch einen Eintrag in `ProfileHistory` — über
  `profile_sync.uebernehme_profilwerte()`, gleich ob von Hand oder aus Garmin.
- Neue Felder auf `SessionLog`, die *nicht* vom Nutzer kommen, gehören nur an
  `SessionLogOut` und nicht an `SessionLogIn`: `PUT /api/logs/{id}` überschreibt
  mit `model_dump()` ohne `exclude_unset` alle Eingabefelder und würde die
  Herkunft sonst beim Bearbeiten zurücksetzen.
- Jeder Zugriff auf Garmin-JSON läuft über `mapping.hole()` / `erster_wert()` /
  `als_liste()`, nie über `d["a"]["b"]`: Die API ist undokumentiert, ändert
  Feldnamen ohne Vorwarnung, und ihre Typangaben stimmen nicht (`get_activities`
  deklariert selbst `dict | list`).

## Sportwissenschaftliche Logik (`sportscience.py`)

- **HF-Zonen**: Karvonen (Herzfrequenzreserve), wenn Ruhe- und Maximalpuls
  bekannt sind, sonst % HFmax. Fehlender Maximalpuls wird über
  `211 − 0,64 × Alter` (Nes et al. 2013) geschätzt und im Frontend als Schätzung
  ausgewiesen.
- **TRIMP** nach Banister, geschlechtsspezifisch gewichtet.
- **sRPE-Last** nach Foster (Dauer × RPE) — funktioniert ohne Pulsgurt.
- **ACWR**: Last der letzten Woche gegen den Vier-Wochen-Schnitt. Über 1,3 gilt
  als erhöhtes Überlastungsrisiko.
- **Auffälligkeiten aus den Fitnessdaten** (`wellness_auffaelligkeiten`): HRV
  unter der eigenen Baseline, Schlafdefizit, steigender Ruhepuls, niedrige
  Trainingsreife, kritischer Trainingsstatus, Garmin-ACWR über 1,3, hoher
  Stress, Gewichtsverlust. Die Schwellen stehen als Konstanten am Kopf des
  Abschnitts und entsprechen den Zahlen im Prompt.
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

Punkt 2 der Prinzipien ist der Platzhalter `{fitnessregeln}` und existiert in
zwei Fassungen (`FITNESSREGELN_MIT_DATEN` / `_OHNE_DATEN`) — welche eingesetzt
wird, entscheidet `build_prompt()` daran, ob der Payload einen
`fitnessdaten`-Block trägt. Beide Texte laufen durch `.format()`: geschweifte
Klammern müssten verdoppelt werden.

Änderungen am Antwortformat müssen an drei Stellen zusammenpassen:
`RESPONSE_SCHEMA`, die `AI*In`-Schemas in `schemas.py` und `build_plan()` in
`plan_import.py`.

## Bekannte Grenzen / mögliche nächste Schritte

- Kein Bearbeiten erfasster Trainings im Frontend (die API kann es bereits:
  `PUT /api/logs/{id}`).
- Keine Diagramme — Verlauf und Wochenübersicht sind Tabellen.
- Kein Alembic. Neue Spalten werden im Migrationshelfer in `database.py`
  eingetragen und beim Start ergänzt; für Umbenennungen oder Typänderungen
  bleibt es beim Löschen der Datei.
- Die genaue Form von `get_sleep_daily()` (Zeilen aus `individualStats`) ist
  nicht dokumentiert. Der Mapper liest sie über mehrere Pfade und fällt auf die
  Tagesantwort zurück; **beim ersten echten Rückblick prüfen**, ob Schlafdauer
  und -phasen für den älteren Teil des Zeitraums ankommen.
- Der Rückblick über ein Jahr wurde bisher nur gegen die Nachbildung geprüft,
  nicht gegen ein echtes Konto.
- Die Anmeldung schützt nichts: Jeder, der die App erreicht, kann jedes Konto
  wählen (bewusst — siehe „Anmeldung"). Der Schutz kommt vom Ingress davor.
- Kein Löschen von Konten in der Oberfläche; ein Konto bleibt für immer in der
  Auswahlliste.
- Ein zweites Garmin-Konto im selben Haushalt teilt sich die Anfragegrenze über
  die gemeinsame Herkunftsadresse; das globale Schloss im Runner bremst das ab,
  löst es aber nicht.
- Trainings in die andere Richtung — geplante Einheiten *nach* Garmin schieben —
  gibt es noch nicht. Das Datenmodell trägt es bereits: Mit dem gespeicherten
  Token und den Workout-Endpunkten der Bibliothek ließe sich jede `PlanSession`
  als geplantes Workout auf die Uhr legen.
- Für den Netzbetrieb fehlen HTTPS, eine echte Authentifizierung vor der App,
  gesetzter `TRI_SECRET_KEY` und angepasste CORS-Herkünfte (`config.py`).
