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

**Und der Weg zurück: Geplante Einheiten gehen als Workout auf die Uhr.** Ein
Knopf im Trainingsplan legt jede Einheit des Blocks als strukturiertes Workout
in Garmin an und terminiert sie im Kalender; beim nächsten Synchronisieren
liegt sie auf dem Gerät und lässt sich dort starten. Die App bringt dafür einen
eigenen Kalender mit — Monatsansicht, verschieben, aus Garmin löschen.

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
cd backend && .venv/bin/python -m pytest tests/ -q # 131 Tests
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
`TRI_GARMIN_SYNC_HOUR` (Ortszeit-Stunde, ab der abgeglichen wird, Vorgabe 9).

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

**Der Kalender ist ein Markup für zwei Größen.** Am Schreibtisch ein
Monatsraster mit sieben Spalten, am Telefon eine Tagesliste — aber nicht zwei
Bausteine, sondern dieselben Zellen: Unterhalb von 700 px fällt das
Spaltenraster auf eine Spalte zusammen, Leerfelder vor dem Monatsersten und
Tage ohne Eintrag werden ausgeblendet (`.kalender-fueller`, `.is-leer`), und
der Wochentag rückt in die Zelle, weil es keine Spaltenüberschrift mehr gibt.
Dieselbe Überlegung wie bei den Tabellen: Eine zweite Darstellung liefe mit der
ersten auseinander.

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

**Jeder Tag wird einmal geholt, die letzten fünf immer wieder**
(`sync.standard_zeitraum`, `GarminAccount.backfill_from` /
`synced_through`). „Jetzt synchronisieren" holt beim ersten Mal ein volles Jahr
(`RUECKBLICK_TAGE` = 365) — die Historie ist der teuerste Teil des Exports und
soll nicht an einem gesondert anzustoßenden Rückblick hängen. Danach holt
derselbe Knopf nur noch das `AKTUALISIERUNGSFENSTER_TAGE` = 5 Tage breite
Fenster: Garmin trägt Schlaf- und Erholungswerte Stunden später nach, und wer
abends synchronisiert, hat den Tag halb offen — fertige Tage dagegen ändern sich
nicht mehr und kosten in der Tagesschleife je vier Anfragen und 5 s. Das schon
Geholte steht als **lückenloses Fenster** am Konto, nicht je Tag: Ein Tag ohne
jeden Messwert hinterlässt keine `WellnessDay`-Zeile und würde sonst für immer
neu angefragt. Der nächste Lauf setzt deshalb an `synced_through + 1` an,
gedeckelt auf das Aktualisierungsfenster — war die App drei Wochen aus, sind es
drei Wochen. Fortgeschrieben wird **nur nach einem erfolgreichen Lauf**: Ein
Abbruch hat seinen Zeitraum nur teilweise geschrieben, und ein Anspruch auf
Daten, die nie ankamen, wäre eine Lücke für immer. Der Preis der kurzen
Überlappung: Was Garmin später als fünf Tage nachträgt, kommt nur noch über
einen ausdrücklichen Rückblick nach — der fragt bewusst *nicht* nach dem
gedeckten Fenster und ist damit der Weg, einen Zeitraum trotz vorhandener Daten
erneut zu holen. Der automatische Abgleich (`automatik.py`) benutzt denselben
Zuschnitt; für bestehende Datenbanken ist `synced_through` leer, der erste
Abgleich nach dem Update holt also einmal das ganze Jahr.

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

**Ein echtes Workout, keine Kalendernotiz** (`garmin/workouts.py`). Garmin führt
im Kalender auch Notizen; die erscheinen in Connect, kommen aber nie auf das
Gerät. Nur ein Workout mit Schrittliste *leitet* die Uhr an — Schrittwechsel,
Zielkorridor, Signal beim Verlassen. Deshalb wird `PlanSession.structure`, ein
Fließtext aus der KI, in Garmins Schritte zerlegt: „15 min Einlaufen Z1-Z2,
5 x 3 min Z4 mit je 2 min Trabpause, 10 min Auslaufen“ wird zu Aufwärmschritt,
Wiederholungsgruppe und Auslaufen, jeweils mit Herzfrequenzkorridor aus den
Karvonen-Zonen des Profils. **Der Parser rät nicht**: Erkennt er nichts, wird
die Einheit *ein* Schritt über die geplante Dauer, und der ganze Aufbautext
steht in der Beschreibung. Ein falsch geratenes Intervalltraining auf der Uhr
ist schlimmer als ein grobes, weil es ungeprüft absolviert wird. Zwei Regeln
sind Konvention und deshalb kommentiert: Der zweite Teil eines Zweierpaars in
einer Wiederholung ist die Pause, und Pausen bekommen bewusst *keinen*
Zielkorridor (ein Alarm in der Erholung triebe genau den Puls hoch, der sinken
soll). Die Kennungen für Sport-, Schritt- und Zieltypen kommen aus
`garminconnect.workout` statt aus eigenen Zahlen — zwei Quellen dafür liefen
auseinander.

**Zwei Grammatiken, weil derselbe Text Verschiedenes bedeutet**
(`zerlege_uebungsliste()` neben `zerlege_struktur()`). Bei Kraft und Mobility
beschreibt `structure` keinen Zeitverlauf, sondern eine Übungsliste — „3x15 Leg
Raise je Seite / 2x45 s Dehnung je Seite“. Durch die Ausdauer-Grammatik gelesen
wurde daraus Unsinn: „3x15“ eine Wiederholungsgruppe über 15 Sekunden, die
zweite Übung darin die „Pause“, und jede Übung ohne Zeitangabe fiel still weg —
auf der Uhr standen dann zwei Abschnitte, während die Notiz vier nannte. Für die
Sportarten in `UEBUNGSSPORTARTEN` wird deshalb jede Übung *ein* Schritt in der
Reihenfolge des Plans, beendet per **Rundentaste** statt nach Zeit: Die Angabe
„2x45 s je Seite“ gilt je Satz und Seite, sind also vier Haltephasen und nicht
ein 45-Sekunden-Schritt. Getrennt wird nur an „ / “, Zeilenumbruch und
Aufzählungszeichen — nicht am Komma („…, 4 s exzentrisch abgesenkt“ ist ein
Zusatz) und nicht an „mit“ („Monster Walks mit Band“). Unter zwei erkannten
Übungen greift wieder der Ersatzschritt über die geplante Dauer. Diese Einheiten
bekommen außerdem **keinen Herzfrequenzkorridor**: Der Puls springt dort von
Satz zu Satz und fällt in der Dehnung, ein Alarm liefe fast durchgehend.

**Eine benannte Übung wird auf der Uhr vorgemacht** (`garmin/uebungen.py`).
Garmin zeigt zu einem Workout-Schritt eine Bewegungsanimation — aber nur, wenn
der Schritt zwei Felder trägt: `category` (Bewegungsgruppe) und `exerciseName`
(die genaue Variante), beide aus Garmins eigenem Katalog. Ohne sie steht auf
der Fenix bloß die Textzeile „Seitstütz 3x40 s“, und wer die Bewegung nicht
kennt, macht sie falsch. Der Katalog kommt aus `garminconnect.exercises` (1527
Einträge, 47 Kategorien, abgelesen aus dem Übungswähler des Connect-Editors) —
eigene Zahlen kämen nicht in Frage, denn eine unbekannte Kategorie beantwortet
Garmin mit 400, und zwar für das ganze Workout. Das Problem in der Mitte: Der
Katalog ist englisch, der Plan deutsch, und die Übung steht in einer Zeile
voller Beiwerk. Deshalb wird beides auf Wortstämme normalisiert und im Text das
*längste zusammenhängende* Stück gesucht, das im Verzeichnis steht — „Seitstütz“
ergibt Side Plank und nicht Plank, weil zwei Wörter mehr wiegen als eins. Die
deutschen Entsprechungen in `SYNONYME` sind dabei nur ein zweiter Schlüssel auf
denselben Eintrag, keine zweite Datenhaltung.

Zwei Regeln der Normalisierung sind gegen echte Pläne entstanden und stehen
deshalb fest. **Verklebt wird vor dem Kürzen** (`_schluessel`): Im Deutschen ist
die Wortgrenze Geschmackssache — der Plan schreibt „Quadrizeps-Dehnung“, das
Wörterbuch „quadrizepsdehnung“ —, und wer zuerst die Mehrzahl abschneidet,
zerlegt das Kompositum an seiner Fuge und verliert das Fugen-s. Und **„ß“ fällt
auf „ss“**, nicht auf „s“: Sonst verfehlt „Gesäßdehnung“ seinen Wörterbucheintrag
um genau einen Buchstaben.

**Geraten wird auch hier nicht.** Ohne Treffer bleibt der Schritt die Textzeile,
die er vorher war; eine falsch zugeordnete Animation zeigte eine andere Bewegung
als die geplante, und die wird ungeprüft nachgemacht. Daran hängen zwei Sperren.
Die 24 Katalogzeilen, die eine Gruppe benennen statt einer Bewegung (`Core`,
`Warm-up`, `Cardio` …), sind ausgeschlossen — zu einer Schublade gibt es keine
Animation. Und die 47 Bewegungen, die der Katalog unter ihrem *bloßen* Namen
führt („Plank“, „Squat“, „Row“), zählen nur, wenn sie für sich allein stehen
(`_grundform_ok`): Steht direkt davor oder dahinter ein Wort, das keine
Mengenangabe ist, gehört es mit einiger Wahrscheinlichkeit zum Übungsnamen.
„Copenhagen Plank“ ist eine Adduktorenübung und kein Unterarmstütz, „Squat
Jumps“ sind keine Kniebeugen — beide bekämen sonst die Animation der Grundform.

**Mobility geht als Garmins „Mobility“, nicht mehr als Yoga**
(`SPORT_ZU_GARMIN`, `SportType.MOBILITY` = 11). Der Übungskatalog hängt an der
Sportart des Workouts — Garmin lässt in Connect nicht einmal zu, eine Yogapose
in ein Krafttraining zu legen. Für Yoga führt Garmin einen eigenen Posenkatalog,
den es nirgends öffentlich gibt; die Dehn- und Mobilisationsübungen der App
(Child's Pose, Cat Cow, Pigeon Pose, 90/90 …) liegen dagegen alle in der
`WARM_UP`-Kategorie des Kraftkatalogs. Unter Yoga bekämen sie deshalb keine
Animation. Der Preis: **Diese Sportart ist gegen ein echtes Konto ungeprüft** —
lehnt Garmin die Kategorie dort ab, steht die Meldung an der Einheit und die
übrigen gehen trotzdem durch. Dazu gehört zwingend `"mobility": "mobility"` in
`mapping.TYPKEY_ZU_SPORT`: Die App überträgt jetzt unter einer Sportart, die
sie vorher nur nicht kannte — ohne den Eintrag fiele die absolvierte Einheit
beim Abgleich stillschweigend heraus.

**Vorlage und Termin sind zwei Dinge** (`garmin/uebertragung.py`,
`GarminWorkoutLink`). In Garmin liegt das Workout in der Bibliothek und ein
Zeitplaneintrag verweist darauf; entsprechend hält jede übertragene Einheit
beide Kennungen fest. Dazu einen `fingerabdruck` des zuletzt gesendeten
Inhalts — **damit der Knopf gefahrlos zweimal gedrückt werden darf**:
Unverändertes wird übersprungen (null Anfragen), Geändertes über
`update_workout` an Ort und Stelle ersetzt, wodurch die Vorlage ihre Kennung
und der Kalendertermin seine Gültigkeit behält. Nach jedem Schritt wird
festgeschrieben, denn zwischen „Vorlage angelegt“ und „Termin eingetragen“
liegt eine zweite Anfrage: Ginge die Kennung dazwischen verloren, entstünden
bei jedem Versuch neue Karteileichen in einem fremden Konto. Wer eine Vorlage
in Connect von Hand löscht, bekommt sie neu — ein 404 löst die Zuordnung, statt
für immer gegen eine tote Kennung zu laufen (`verbindung.verschwunden`).

**Was vorbei ist, wird weggeräumt** (`uebertragung.raeume_vergangene_auf`).
Weil ein Kalendertermin ohne Vorlage nicht existieren kann, legt jede übertragene
Einheit zwangsläufig einen Eintrag in Garmins Bibliothek ab — bei einem Block je
Woche wären das nach einem Jahr dreihundert, zwischen denen der Athlet seine
eigenen Trainings nicht mehr fände. Deshalb löscht die App Vorlage *und* Termin
jeder Einheit, deren Tag vorbei ist: am Ende jedes Abgleichs und am Ende jeder
Übertragung — den beiden Zeitpunkten, an denen der Zugang ohnehin steht und das
Schloss gehalten wird. Die Liste kommt aus `GarminWorkoutLink`, **nie** aus
Garmins Bibliothek: Angefasst wird ausschließlich, was diese App selbst angelegt
hat. Die absolvierte Aktivität ist ein eigener Datensatz und bleibt; auch die
Umsetzungsquote hängt nicht daran, weil `matching` über Tag und Sportart
verknüpft, nicht über die Garmin-Kennung. Ein Fehlschlag beim Aufräumen wertet
den Lauf nicht um — er hat sein eigentliches Ziel schon erreicht —, aber die
Anfragesperre wird festgehalten, und zwar **nach** dem Festschreiben des
Ergebnisses: Der Erfolgspfad setzt sie eine Zeile vorher zurück.

**Die Übertragung ist ein Job, der Kalender nicht.** Ein Block kostet zwei
Anfragen je Einheit und läuft deshalb durch denselben Runner und dasselbe
globale Schloss wie ein Abgleich — Garmins Grenze unterscheidet nicht, ob
gelesen oder geschrieben wird. Einzelne Aufrufe (Monat laden, ein Workout
löschen, eine Einheit nachschieben) gehen dagegen über `garmin/verbindung.py`
direkt im Anfrage-Thread: Für eine einzelne Anfrage einen Fortschrittsbalken
zu bauen wäre Umstand ohne Nutzen. Beide Wege behandeln die Anfragesperre
gleich, und beide fangen sie **auch in ihrer Form aus der Bibliothek** ab
(`GarminConnectTooManyRequestsError`) — sonst liefe die Übertragung stur weiter
und triebe eine Stunde Sperre auf zwei Tage. Ein Fehlschlag bei *einer* Einheit
stoppt die anderen nicht; er wird benannt und an der Einheit vermerkt.

**Der Kalender wird gelesen, nicht gespiegelt** (`garmin/kalender.py`). Ein
Monat kostet genau eine Anfrage und liefert alles, was in Connect steht. Eine
Kopie in der Datenbank wäre nach der ersten Änderung in Connect falsch — womit
die Ansicht ihren einzigen Zweck verlöre, den echten Stand zu zeigen.
**Absolvierte Aktivitäten sind dort schreibgeschützt**: Sie zu löschen hieße,
die Trainingsdaten zu vernichten, aus denen diese App ihre Planung ableitet.
Gelöscht werden nur geplante Workouts, und zwar in zwei Stufen — nur der Termin
(die Vorlage bleibt zum erneuten Einplanen) oder beides. Vergangene Tage werden
gar nicht erst übertragen: Ein Workout von gestern im Kalender ist Altpapier,
das der Athlet von Hand wegräumen müsste. Antwortet Garmin in einer Form, die
`_rohliste()` nicht kennt, ist das ein **Fehler** und kein leerer Monat: Beides
sähe sonst gleich aus — ein leerer Kalender ohne ein Wort dazu —, und der
Bestandsabgleich schlösse aus dem Nichts, dass die eigenen Workouts weg sind.

**Der Kalenderdienst zählt in anderen Einheiten als der Aktivitätsdienst.** Bei
absolvierten Aktivitäten steht `duration` dort in **Millisekunden** und
`distance` in **Zentimetern**, während dieselbe Ausfahrt über `get_activities`
in Sekunden und Metern ankommt (`mapping.aktivitaet_zu_log`). Ungerechnet wurden
aus 32:25 min „32417 min" und aus 9,34 km „933,66 km" — sichtbar nur in der
Kalenderansicht, denn diese Werte werden nie gespeichert und gehen deshalb auch
nicht in den Export. Bei geplanten Workouts liest `_dauer_sekunden()` /
`_distanz_meter()` ausschließlich die selbstbeschreibenden Felder
(`estimatedDurationInSecs`, `estimatedDistanceInMeters`): Was ein nacktes
`duration` dort bedeutet, ist nicht belegt, und eine um Faktor 1000 falsche
Dauer wäre schlechter als die dann entfallende Zeile.

**`GarminWorkoutLink` ist eine Behauptung und wird nachgeprüft**
(`uebertragung.gleiche_mit_garmin_ab`). Die Zuordnung sagt „liegt in Garmin",
weil die App es einmal hingelegt hat — auch dann noch, wenn der Athlet es in
Connect gelöscht hat oder es nie ankam. Ohne Nachprüfen stand im Plan „6 von 8
Einheiten liegen in Garmin" neben einem leeren Kalender, und der Knopf half
nicht: Diese sechs galten als aktuell und wurden übersprungen. Nachgeprüft wird
an den beiden Stellen, an denen es nichts extra kostet — die Kalenderansicht hat
ihren Monat ohnehin geholt und reicht ihn als `bekannt` durch, die Übertragung
holt vorweg die ein bis zwei Monate ihres Blocks. Was der Kalender nicht
erklärt, wird einzeln nachgefragt: **Nur ein 404 auf `get_workout_by_id` gilt
als Beweis**, dass eine Vorlage weg ist. Jeder andere Fehlschlag lässt die
Zuordnung stehen — sie fälschlich zu löschen legte beim nächsten Übertragen eine
zweite Vorlage neben die erste. Aus demselben Grund bleibt der Knopf im
Frontend anklickbar, wenn alles als aktuell gilt („Mit Garmin abgleichen"): Ein
toter Knopf ließe den Nutzer genau dann sitzen, wenn der Stand falsch ist.

**Ein Termin ohne Kennung ist kein Erfolg** (`_terminiere`). Gibt Garmin auf
`schedule_workout` keine `workoutScheduleId` zurück, wurde der Termin zwar
angelegt, ist für die App aber unerreichbar — weder verschiebbar noch
zurücknehmbar. Das wandert deshalb als Fehler an die Einheit, statt als „N
Einheiten übertragen" gemeldet zu werden; sonst legte jeder weitere Druck auf
den Knopf einen zweiten Termin daneben. Der nächste Lauf heilt es von selbst:
Der Bestandsabgleich findet den Termin im Kalender und trägt seine Kennung nach.

**Ein abgelöster Block wird aus Garmin geräumt**
(`uebertragung.raeume_ersetzte_auf`). Der nächste Block entsteht als *neuer*
Plan, der bisherige wird nur stillgelegt — seine übertragenen Einheiten blieben
aber stehen. Weil beide Blöcke dieselben Tage abdecken, stünden auf der Uhr zwei
Trainings je Tag, und welches überholt ist, sähe der Athlet vor dem Start nicht.
Geräumt wird nur, was in der Zukunft liegt und zu einem **inaktiven** Plan
gehört; Vergangenes erledigt `raeume_vergangene_auf`. Ein *gelöschter* Plan
bleibt davon unberührt — mit ihm sind die Zuordnungen weg, und ohne sie fasst
diese App in Garmin nichts an.

**Verschieben im Kalender verschiebt die Planeinheit mit**
(`verschiebe_kalendereintrag`). Wer dort einen Tag ändert, entscheidet über
seinen Plan und nicht bloß über einen Kalendereintrag. Bliebe `PlanSession.date`
stehen, liefe beides auseinander: Die nächste Übertragung sähe einen
abweichenden Termin und schöbe ihn wortlos auf den Plantag zurück.

**Profilwerte kommen automatisch nach — außer dem Maximalpuls**
(`profile_sync.py`). Gewicht, Körperfett, Ruhepuls, HRV und VO2max werden
übernommen, der Ruhepuls als **Median der letzten sieben Tage**, weil ein
einzelner Ausreißer sonst alle Karvonen-Zonen verschöbe. Der Maximalpuls bleibt
Handarbeit: Garmin schätzt ihn, liegt oft daneben, und er steuert sämtliche
Zonen. Geschrieben wird nur bei relevanter Abweichung, sonst entstünde täglich
ein `ProfileHistory`-Eintrag ohne Erkenntnis. Die History-Logik wurde aus
`routers/profile.py` nach `profile_sync.uebernehme_profilwerte()` gezogen, damit
Handeingabe und Gerät dieselbe Regel benutzen. **HRV ist HRV** — ein Wert in ms,
so beschriftet und so exportiert (`hrv_ms` im Athleten- wie im Fitnessblock).
Die frühere Unterscheidung „Garmins Nachtmittel ist nicht rMSSD“ stand in
Oberfläche und Prompt und stiftete mehr Verwirrung als Nutzen; der Spaltenname
`hrv_rmssd` ist nur noch ein Altname (Umbenennen wäre eine Migration ohne
Gewinn).

**Die Schwellenwerte kommen aus eigenen Anfragen, nicht aus den Tageswerten**
(`sync.hole_leistungswerte`, `mapping.ftp_watt` / `schwellenpace_laufen` /
`schwellenpuls`). FTP, Laktatschwellentempo und Schwellenpuls fallen bei Garmin
nicht je Tag an: Es gibt jeweils nur den zuletzt erkannten Stand, hinter je
einem Endpunkt (`get_cycling_ftp`, `get_lactate_threshold`). Sie landen deshalb
**nicht** in `WellnessDay`, sondern werden am Ende des Laufs eingesammelt und
über `SyncErgebnis.leistungswerte` an die Profil-Nachführung durchgereicht — in
*einem* Zug mit Gewicht und Ruhepuls, weil zwei Übernahmen je Abgleich zwei fast
gleiche `ProfileHistory`-Einträge hinterließen. Am Ende, weil es die billigsten
Anfragen des Laufs sind; und nur, wenn `profile_sync_enabled` gesetzt ist, sonst
hätten die Werte keinen Empfänger. Jeder Wert wird gegen die Spanne aus
`schemas.ProfileIn` geprüft: Diese Zahlen gehen am Pydantic-Schema vorbei direkt
ins Modell, und weil `ProfileOut` dieselben Grenzen validiert, würde ein
Ausreißer aus der undokumentierten Schnittstelle die Profilseite mit einem
Fehler statt mit Daten beantworten. Die Tempo-Spanne prüft dabei vor allem die
*Einheit* (m/s, nicht km/h). **Die kritische Schwimmgeschwindigkeit (CSS) fehlt
bewusst**: Garmin führt sie nirgends — weder als Endpunkt noch in den
Profileinstellungen —, und aus den Trainingsdaten wäre sie nur zu raten. Sie
bleibt Handarbeit, und die Profilseite sagt das bei verbundenem Konto auch.

**Bestzeiten kommen aus Garmin, aber nur fürs Laufen** (`mapping.bestzeiten`,
`AthleteProfile.garmin_personal_bests`). `get_personal_record()` kostet eine
Anfrage und läuft im selben Schritt wie die Schwellenwerte. Der Haken: Jeder
Eintrag trägt nur eine Kennziffer (`typeId`) und einen nackten `value` — was die
Zahl bedeutet, sagt Garmin nirgends. Bei den Streckenrekorden sind es Sekunden,
beim längsten Lauf Meter, bei den Schrittrekorden Schritte. Deshalb dreifach
abgesichert, statt der Kennziffer zu glauben: nur die sechs Laufstrecken, die
Connect seit jeher als Bestzeiten führt; der Eintrag muss an einer `activityId`
hängen (Schritt- und Streak-Rekorde tun das nicht); und der Wert muss als Zeit
über seine Strecke ein menschenmögliches Tempo ergeben
(`BESTZEIT_PACE_SPANNE`) — eine fehlgedeutete Zahl fällt so heraus, statt als
absurde Bestzeit in den Prompt zu wandern. Rad- und Schwimmrekorde bleiben
ungelesen, weil ihre Kennziffern nicht sicher zuzuordnen sind und eine falsch
beschriftete Bestzeit schlechter ist als keine. Deshalb **zwei** Felder im
Profil und zwei Schlüssel im Export: `bestzeiten` ist der Freitext des Athleten
(Schwimmen, Rad, alte Wettkämpfe), `bestzeiten_aus_garmin` die erkannte Liste.
Ein Abgleich ohne deutbaren Eintrag schreibt `None` statt einer leeren Liste —
sonst löschte ein Fehlschlag der Gegenseite die bisherigen Bestzeiten.

**Trainingserfahrung und Schlafstunden sind aus dem Profil verschwunden.** Beide
waren Selbsteinschätzungen, die nichts trugen: Den Schlaf misst Garmin je Nacht
(`fitnessdaten`, samt 7-gegen-28-Tage-Mittel und Schlafdefizit-Auffälligkeit),
und ohne verbundenes Konto fragt ihn das Erfassungsformular je Einheit ab
(`SessionLog.sleep_hours` — das bleibt). Die Trainingserfahrung in Jahren sagt
über den nächsten Kurzblock nichts, was `wochenuebersicht`, ACWR und die
Historie nicht genauer sagen; für die KI war sie vor allem eine Einladung, den
Block an einer Zahl statt an der Belastungslage auszurichten. Die Spalten
`experience_years` und `sleep_hours` stehen als Altlasten weiter im Modell
(Entfernen wäre eine Migration ohne Gewinn), werden aber nirgends mehr gelesen
oder geschrieben.

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

**Home-Assistant-Integration: Das Add-on-Verzeichnis *ist* die Repo-Wurzel**
(`repository.yaml`, `config.yaml`, `run.sh`, Root-`Dockerfile`). Der Supervisor
klont den Default-Branch, sucht mit `**/config.*` nach Add-ons und baut jedes
lokal — **mit dem Verzeichnis des `Dockerfile` als Build-Context, und der lässt
sich nicht verstellen.** Genau daran hängt die Entscheidung: Läge das Add-on
nach Lehrbuch in einem Unterordner, käme sein `Dockerfile` nicht mehr an
`backend/` und `frontend/`. Der Glob findet die Wurzel mit, also liegt es dort,
und der Context umfasst das ganze Repo (`.dockerignore` hält `.git` und
`node_modules` heraus). Ein `build.yaml` gibt es **nicht mehr**: Seine Schlüssel
`context`/`dockerfile` hat der Supervisor nie gelesen (sein Schema wirft
Unbekanntes still weg), und seit Supervisor 2026.04 wird die Datei überhaupt
nicht mehr ausgewertet — Basis-Abbild, Labels und Build-Argumente gehören in den
`Dockerfile`. `version` in `config.yaml` ist der **einzige** Auslöser für ein
Update im Store; ohne Erhöhung bleibt ein Push unsichtbar. Das zentrale `run.sh`
setzt die Supervisor-spezifischen Umgebungsvariablen: `TRI_SECRET_KEY`
(aus `options.json`, sonst selbst erzeugt und unter `/data/.secret_key`
abgelegt — **nicht** relativ zum Arbeitsverzeichnis, das überlebt kein Update)
und `TRI_DATABASE_URL` → `/data/tricoach.db`. Nachteil des lokalen Builds: Er
dauert auf dem Raspberry Pi ~15–20 Min (Node-Frontend wird mitkompiliert).
Zugriff über **Ingress** (kein offener LAN-Port, authentifiziert via
HA-Session). Der `Dockerfile` nutzt `python:3.12-slim` — kein S6-Overlay oder
Bashio nötig (nur ein Uvicorn-Prozess), deshalb bleibt `init` auf der Vorgabe.

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

**Punkt 6 ist das Gegengewicht zu allen anderen.** Die Prinzipien 1 bis 4 sind
Bremsen — sie beschreiben ausschließlich, wann zurückgenommen wird (ACWR, HRV,
Trainingsreife, 48-h-Abstand). Ein Regelwerk, das nur bremst, liest sich für ein
Sprachmodell als Auftrag zur Vorsicht: Es plante zuverlässig sichere
Z2-Wochen und nie den Reiz, aus dem Anpassung entsteht. Punkt 6 dreht die
Beweislast um — greift keine Bremse, ist Aufbau die Vorgabe, mit mindestens
einem gezielten Reiz und bis zu ~10 % mehr Wochenlast. Weil ein Block nur wenige
Tage weit reicht und jeder Export bei null anfängt, entsteht Progression nicht
aus einem Zyklusplan, sondern allein daraus, dass jeder einzelne Block sie
enthält.

Punkt 6 spricht die **Zielschlüssel namentlich an** („Standardplan", „Aufbau",
„Bestzeit", „Wettkampfvorbereitung" verlangen einen Reiz; „Grundlagenausdauer",
„Gesundheit", „Gewichtsreduktion", „Erstfinish", „Wiedereinstieg" stellen
Regelmäßigkeit voran). „Standardplan" hat zusätzlich einen eigenen Absatz, weil
er das einzige Ziel ohne äußeren Bezugspunkt ist: kein Wettkampf, kein
Schwerpunkt — Maßstab ist allein die Best Practice, und die Reizwahl kommt aus
der Lücke in der Historie. Ohne diesen Absatz füllte das Modell die Leerstelle
mit dem Sichersten, also Z2. Der Absatz zählt bewusst **keine Einheitentypen
auf**: Eine Liste („Schwelle, VO2max, Z1 …") wäre wieder eine Vorgabe und würde
genau die Ableitung ersetzen, die hier den Sinn des Ziels ausmacht. Und er sagt
ausdrücklich, dass er kein Freibrief ist — „bestmöglich" ohne diesen Satz liest
sich als Erlaubnis, die Bremsen aus Punkt 1 bis 4 zu übergehen. Die Schlüssel stehen in `GOAL_OPTIONS`
(`frontend/src/constants.ts`) und gehen unverändert als `trainingswunsch.ziel`
in den Payload — ein neues Ziel oder ein umbenannter Schlüssel muss deshalb im
Prompt mitgezogen werden, sonst fällt es dort stillschweigend in keine der
beiden Gruppen.

Punkt 2 der Prinzipien ist der Platzhalter `{fitnessregeln}` und existiert in
zwei Fassungen (`FITNESSREGELN_MIT_DATEN` / `_OHNE_DATEN`) — welche eingesetzt
wird, entscheidet `build_prompt()` daran, ob der Payload einen
`fitnessdaten`-Block trägt. Beide Texte laufen durch `.format()`: geschweifte
Klammern müssten verdoppelt werden.

Punkt 9 verlangt bei `strength` und `mobility` eine **Übungsliste** in
`structure` und hinter jeder deutschen Bezeichnung den geläufigen englischen
Namen in Klammern („Seitstütz (Side Plank) 3x40 s je Seite“). Das ist kein
Schönheitswunsch: Der englische Name ist der Schlüssel in Garmins Übungskatalog
und entscheidet darüber, ob auf der Uhr die Bewegungsanimation erscheint
(`garmin/uebungen.py`). Das Wörterbuch dort fängt den Fall ohne Klammer ab —
beide Wege führen zum selben Eintrag, der Prompt erhöht nur die Trefferquote.

Änderungen am Antwortformat müssen an drei Stellen zusammenpassen:
`RESPONSE_SCHEMA`, die `AI*In`-Schemas in `schemas.py` und `build_plan()` in
`plan_import.py`.

## Bekannte Grenzen / mögliche nächste Schritte

- Kein Bearbeiten erfasster Trainings im Frontend (die API kann es bereits:
  `PUT /api/logs/{id}`).
- Keine Diagramme — Verlauf und Wochenübersicht sind Tabellen.
- Kein Alembic. Neue Spalten werden im Migrationshelfer in `database.py`
  eingetragen und beim Start ergänzt; für Umbenennungen oder Typänderungen
  bleibt es beim Löschen der Datei. Die Tabelle `garmin_workout_links` legt
  `create_all()` beim Start an; die zwei Zählwerke an `garmin_sync_jobs`,
  `athlete_profiles.garmin_personal_bests` und
  `garmin_accounts.synced_through` kommen über den Helfer.
- Was Garmin **später als fünf Tage** nachträgt (nachgeladene Aktivität aus
  einem zweiten Gerät, korrigierter Schlaf), holt kein Abgleich mehr von
  allein — dafür gibt es den Rückblick. Ebenso kann ein Lauf, der mitten im
  Zeitraum scheitert, nicht teilweise als geholt gelten: `synced_through` rückt
  nur im Erfolgsfall vor, der nächste Lauf wiederholt den ganzen Zeitraum.
- Die genaue Form von `get_sleep_daily()` (Zeilen aus `individualStats`) ist
  nicht dokumentiert. Der Mapper liest sie über mehrere Pfade und fällt auf die
  Tagesantwort zurück; **beim ersten echten Rückblick prüfen**, ob Schlafdauer
  und -phasen für den älteren Teil des Zeitraums ankommen.
- Der Rückblick über ein Jahr wurde bisher nur gegen die Nachbildung geprüft,
  nicht gegen ein echtes Konto.
- Auch die Antwortform von `get_cycling_ftp()` und `get_lactate_threshold()` ist
  nicht dokumentiert. Der Mapper liest beide über mehrere Pfade und verwirft,
  was außerhalb der Profilspannen liegt; **beim ersten echten Abgleich prüfen**,
  ob FTP, Schwellenpace und Schwellenpuls tatsächlich ankommen — bleiben sie
  leer, steht der Grund als Hinweis in der Meldung des Laufs.
- Die Kennziffern in `get_personal_record()` sind ebenfalls nirgends
  dokumentiert; die Zuordnung in `BESTZEIT_STRECKEN` ist aus Garmin Connect
  abgelesen und über die Tempo-Spanne abgesichert, nicht bestätigt. **Beim
  ersten echten Abgleich prüfen**, ob die Strecken zu den Zeiten passen. Rad-
  und Schwimmbestzeiten fehlen deshalb ganz — sie bleiben Freitext.
- Die **kritische Schwimmgeschwindigkeit (CSS)** bleibt das einzige
  Handarbeitsfeld unter den Leistungswerten: Garmin führt sie nicht. Aus den
  Trainingsdaten ließe sie sich nur schätzen — die Dauer eines importierten
  Trainings steht auf ganze Minuten gerundet in `SessionLog`, was für einen
  200-m-Testabschnitt schon 10 % Fehler bedeutet.
- Die Anmeldung schützt nichts: Jeder, der die App erreicht, kann jedes Konto
  wählen (bewusst — siehe „Anmeldung"). Der Schutz kommt vom Ingress davor.
- Kein Löschen von Konten in der Oberfläche; ein Konto bleibt für immer in der
  Auswahlliste.
- Ein zweites Garmin-Konto im selben Haushalt teilt sich die Anfragegrenze über
  die gemeinsame Herkunftsadresse; das globale Schloss im Runner bremst das ab,
  löst es aber nicht.
- Die Übertragung wurde bisher nur gegen die Nachbildung geprüft, nicht gegen
  ein echtes Konto. Der Aufbau der Workout-JSON folgt den Modellen der
  Bibliothek; sollte Garmin eine Einheit ablehnen, steht die Meldung an der
  Einheit und die anderen gehen trotzdem durch.
- Die **Bahnlänge für Schwimm-Workouts** liegt fest bei 25 m
  (`workouts.POOL_LAENGE_M`) — die App fragt sie nirgends ab. Im 50-m-Becken
  stimmen die Strecken, nur die Bahnzahl auf der Uhr nicht.
- **Kraft- und Mobility-Schritte tragen keine Wiederholungszahl**: Jede Übung
  ist ein Schritt bis zur Rundentaste, „3x15 je Seite“ steht nur als Text
  darin. Garmin könnte mehr (`create_strength_set`, also Wiederholungsgruppe
  mit `endCondition: reps` und Satzpause), und die Übungskennung liegt jetzt
  vor — was fehlt, ist die Regel für „je Seite“: Sie verdoppelt die Sätze, und
  eine Haltedauer („2x45 s“) ist keine Wiederholungszahl. Ob die Animation die
  `reps`-Endbedingung überhaupt braucht, ist offen: **beim ersten echten
  Versuch prüfen**, ob sie auch an einem Rundentasten-Schritt erscheint.
- Die **Zuordnung zum Übungskatalog** deckt ab, was in Kraft- und
  Mobilityplänen für Ausdauersportler üblich ist, nicht den ganzen Katalog.
  Was `uebungen.finde()` nicht erkennt, bleibt ohne Animation — sichtbar wird
  das nur auf der Uhr, die App meldet es nirgends. Wer eine Lücke bemerkt,
  trägt sie in `SYNONYME` nach; `test_garmin_uebungen.py` prüft, dass jede
  Entsprechung im Katalog existiert.
- **Yogaposen fehlen ganz.** Garmins Posenkatalog steckt hinter dem
  angemeldeten Connect-Editor und wird nirgends öffentlich ausgeliefert
  (`web-data/exercises/Yoga.json` ist ein 404). Deshalb laufen Mobility-
  Einheiten als Garmins „Mobility“ über den Kraftkatalog statt als Yoga.
- Die **Sportart `mobility` (11) ist gegen ein echtes Konto ungeprüft**, ebenso
  die Übungskennungen selbst. Beides wurde nur gegen die Nachbildung geprüft.
- Eine **Koppeleinheit** ohne erkennbare Teilung im Aufbautext wird 2:1 auf Rad
  und Lauf geschätzt; die Beschreibung des Workouts weist das aus.
- Workouts landen über den Kalender auf der Uhr — beim nächsten Synchronisieren
  des Geräts. Ein Direktversand an ein bestimmtes Gerät
  (`push_workout_to_device`) ist nicht eingebaut; er kostete zusätzliche
  Anfragen für die Gerätesuche.
- Das Aufräumen vergangener Einheiten lässt sich nicht abschalten und hängt an
  einem Abgleich oder einer Übertragung; wer beides nie auslöst, behält seine
  alten Vorlagen.
- Wird ein Plan gelöscht, verschwindet nur die Zuordnung — was schon in Garmin
  steht, bleibt dort. Das Aufräumen erreicht diese Vorlagen nicht mehr: Es geht
  ausschließlich über `GarminWorkoutLink`, und der ist mit dem Plan gelöscht
  worden. Ungefragt in einem fremden Konto zu löschen wäre
  übergriffig; der Kalender in der App zeigt es weiterhin zum Entfernen an.
- Der Bestandsabgleich prüft nur die Monate, in denen die App ihre Einheiten
  vermutet. Wer ein Workout in **Connect** auf einen anderen Monat schiebt, wird
  dort nicht gefunden; die Vorlage besteht aber noch, also wird die Zuordnung
  nicht gelöscht, sondern nur ihr Termin vergessen — die nächste Übertragung
  legt einen zweiten Termin auf dem Plantag an, ohne den verschobenen zu
  kennen. Innerhalb der App verschieben (Kalenderansicht) hat das Problem
  nicht: Dort zieht die Planeinheit mit um.
- Für den Netzbetrieb fehlen HTTPS, eine echte Authentifizierung vor der App,
  gesetzter `TRI_SECRET_KEY` und angepasste CORS-Herkünfte (`config.py`).
