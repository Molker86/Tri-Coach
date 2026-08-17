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

**Trainings- und Fitnessdaten kommen aus Garmin Connect — und nur von dort.**
Wer ein Konto verbindet, trägt nichts mehr von Hand nach: Trainings, Schlaf,
HRV, Ruhepuls und Garmins Erholungsbewertungen werden geholt und fließen in den
nächsten Export ein. Die Formulare zum Erfassen und Nachtragen gibt es **nicht
mehr** — siehe „Garmin ist die einzige Quelle".

**Und der Weg zurück: Geplante Einheiten gehen als Workout auf die Uhr.** Wer
einen Block übernimmt, findet ihn ohne weiteres Zutun im Garmin-Kalender: Jede
Einheit wird als strukturiertes Workout angelegt und terminiert, beim nächsten
Synchronisieren liegt sie auf dem Gerät und lässt sich dort starten. Derselbe
Lauf räumt den abgelösten Block weg, damit nicht zwei Vorgaben am selben Tag
stehen — und das auch dann, wenn gar nichts hineingeht: **Im Kalender steht
immer nur der aktive Block.** Wer einen Plan löscht, nimmt seine Einheiten
ebenso mit. Der Knopf im Trainingsplan bleibt für alles, was danach kommt
(nachgeschobene Änderungen, ein früherer Block, ein abgeschaltetes Konto). Die
App bringt dafür einen eigenen Kalender mit — Monatsansicht, verschieben, aus
Garmin löschen.

**Und die Mitte kann die App inzwischen selbst: Sie fragt Claude direkt.**
Wer ein Claude-Abo hinterlegt, drückt einen Knopf statt zu kopieren — aber
**immer erst auf Knopfdruck**: Von selbst entsteht kein Block, siehe „Geplant
wird nur auf Zuruf".
Aufgerufen wird **Claude Code headless** als Unterprozess, nicht die API mit
Token-Abrechnung: Das Abo war da, und ein Aufruf am Tag kostet darüber nichts
extra. Der Weg über die Zwischenablage bleibt vollständig erhalten — als
Rückfallebene für einen abgelaufenen Zugang, ein aufgebrauchtes Kontingent oder
eine andere KI.

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
- Nach dem Training Werte erfassen (Puls, Strecke, Zeit …). **Überholt:** Diese
  Werte kommen inzwischen ausschließlich aus Garmin, die Formulare sind
  entfallen — siehe „Garmin ist die einzige Quelle".
- Immer die letzten 4 Wochen plus die Wunschdaten steuern die nächste Planung.
- Geplant wird jeweils nur der nächste kurze Block (Nachforderung, ersetzt den
  ursprünglichen Vier-Wochen-Plan). Ein aktiver Plan kann per Knopfdruck um
  beliebig viele weitere Blöcke verlängert werden — die Auswertung bezieht sich
  immer auf die letzten 4 Wochen, unabhängig davon, wie lange der Block reicht.

## Starten und Testen

```bash
./start.sh                                        # beide Server
cd backend && .venv/bin/python -m pytest tests/ -q # 220 Tests
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

Für die KI-Planung: `CLAUDE_CODE_OAUTH_TOKEN` (der Abo-Zugang; den Namen gibt
Claude Code vor, der Unterprozess liest genau diese Variable). Lokal genügt
stattdessen eine angemeldete CLI — geprüft wird nicht die Variable, sondern
`claude auth status`. Dazu `TRI_KI_CLI` (Pfad zum Programm, Vorgabe `claude`),
`TRI_KI_MODELL` (Vorgabe `opus`), `TRI_KI_EFFORT` (Vorgabe `max`) und
`TRI_KI_TIMEOUT_S` (Vorgabe 900). Ein Gegenstück zu `TRI_GARMIN_AUTOSYNC` gibt
es hier **nicht**: Die Planung hat keine Schleife, die man abschalten müsste.

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

**Ein laufender Block darf jederzeit überbügelt werden** (`ai_export._ersatz_block`,
`plan_aufraeumen.py`). „Neu planen ab heute" erzeugt einen frischen Block ab dem
heutigen Tag, während der bisherige noch läuft — der Fall tritt häufiger ein als
das Anhängen: Eine Erkältung, eine verschobene Dienstreise oder ein spontanes
Rennen machen die Resttage wertlos, lange bevor der Block ausläuft. Der Fragebogen
wird dafür nicht erneut ausgefüllt; der Export nimmt ohne `request_id` ohnehin den
zuletzt gespeicherten. Technisch konnte die App das immer (jeder Import legt einen
neuen Plan an und legt den bisherigen still) — gefehlt haben zwei Dinge.

Erstens **weiß die KI sonst nichts davon**: Sie sähe unter
`trainingshistorie.aktueller_plan` einen Block über dieselben Tage und schriebe
ihn fort, statt neu zu entscheiden. Überschneiden sich die Zeiträume, trägt
`planungszeitraum` deshalb `ersetzt_laufenden_block` samt der verworfenen
Einheiten, und der Prompt bekommt über `{ersatzhinweis}` einen Absatz dazu —
ausdrücklich als Kontext und **keine Vorgabe**, mit dem Zusatz, dass allein
`trainingshistorie.einheiten` sagt, was tatsächlich stattgefunden hat (geplant
ist nicht absolviert). Ohne Überschneidung fehlen Schlüssel und Absatz, denn beim
Anhängen des nächsten Blocks wird nichts ersetzt.

Zweitens **stapeln sich die abgelösten Blöcke**: Wer täglich neu plant, hätte nach
einem Monat dreißig Pläne unter „Frühere Pläne", von denen neunundzwanzig nie eine
Einheit getragen haben. `raeume_abgeloeste_plaene()` löscht deshalb, was der aktive
Block überdeckt, in die Zukunft ragt und weder ein erfasstes Training noch eine
Garmin-Übertragung trägt — ein abgeschlossener Block bleibt als Verlauf stehen,
ein beiseitegelegter ohne Überschneidung ebenso. Die Garmin-Bedingung ist dabei
zwingend und nicht bloß vorsichtig: Was in Garmin liegt, wird ausschließlich über
`GarminWorkoutLink` wieder aus dem Kalender entfernt, und der stirbt mit dem
Plan; der dauerhafte Pool-Slot bleibt bestehen. Deshalb läuft
dasselbe Aufräumen an **zwei** Stellen — beim Import und am Ende jedes
Garmin-Laufs, wo `raeume_ersetzte_auf()` die Einheiten gerade aus dem fremden
Kalender genommen hat und die Bedingung damit erfüllt ist.

Im Frontend rechnet `planung.ts` beide Startdaten aus: heute für den Ersatz, der
Tag nach dem Blockende fürs Anhängen — **nie rückwirkend**, ein vor einer Woche
ausgelaufener Block startete sonst in der Vergangenheit. Datiert wird in Ortszeit,
weil `toISOString()` hierzulande abends bereits den Folgetag liefert und ein Block
„ab heute" dann einen Tag zu spät anfinge.

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

**Garmin ist die einzige Quelle für absolvierte Trainings** (`routers/logs.py`).
Es gibt keinen Weg mehr, eine Einheit von Hand einzutragen oder zu bearbeiten:
Die Seite `LogSession` samt `/training-erfassen` und `/training-nachtragen` ist
weg, `POST /api/logs` und `PUT /api/logs/{id}` ebenso. Angelegt werden Einheiten
ausschließlich in `garmin/sync.py`. Der Grund ist nicht Aufräumen, sondern
Zählbarkeit: Bei zwei Quellen steht dieselbe Einheit zweimal in der Datenbank —
einmal von Hand, einmal aus der Uhr —, und sie zählt dann doppelt in
Wochenübersicht, sRPE-Last, ACWR und Umsetzungsquote. Genau dafür gab es
`/api/garmin/dubletten`, das die Doppelten nur benennen konnte, weil sie
automatisch zu löschen übergriffig gewesen wäre. Der Endpunkt **bleibt**: Was
vor dieser Entscheidung von Hand eingetragen wurde, steht weiter in der
Datenbank, und `DELETE /api/logs/{id}` ist der Weg, es loszuwerden.

Was daran hängt: Die **subjektiven Felder** (`feeling`, `soreness`,
`sleep_quality`, `morning_hr`, `morning_hrv`, `conditions`, `sleep_hours`) kann
niemand mehr füllen — Garmin liefert sie nicht. Sie sind deshalb **ganz weg**,
Spalte samt Feld: Was sie beschrieben, misst die Uhr Nacht für Nacht und für
jeden Tag statt nur für Trainingstage (`WellnessDay`, im Export der
`fitnessdaten`-Block). Eine leere Spalte mit Gesundheitsdaten in jedem
Home-Assistant-Backup liegen zu lassen, wäre der bequeme und nicht der richtige
Weg — das Löschen übernimmt `database._ENTFALLENE_SPALTEN`. Das
RPE ist damit **immer geschätzt** (`mapping.schaetze_rpe`); `rpe_source` behält
seinen Wert `manual` nur noch als Altwert, und die Schutzregeln im Abgleich, die
eine Handeingabe vor dem Überschreiben bewahrten, sind mit ihr entfallen. Ein
Ausweichen aufs Formular gibt es nicht mehr — **ohne verbundene Uhr hat die App
keine Trainingshistorie**, und der Prompt sagt das der KI ausdrücklich
(`FITNESSREGELN_OHNE_DATEN`).

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

Dieselbe Linie gilt für **unbrauchbare Steuerungsgrößen**
(`AISessionIn._raeume_zielwerte`). Der Prompt verlangt zu jeder Einheit
Steuerungsgrößen; bei Kraft, Mobility und Ruhe gibt es weder einen sinnvollen
Pulskorridor noch eine geplante Anstrengung, und das Modell füllt die Lücke dann
mit einer 0. Als bloße Feldgrenze (`ge=40` bzw. `ge=1`) war das ein harter
Validierungsfehler: Ein vollständiger Block starb an zwei Zahlen, die ohnehin
niemand liest — `workouts.py` überspringt eine 0 als falsy, es gäbe also so oder
so keinen Korridor auf der Uhr. Über den KI-Knopf war das teuer, weil die Antwort
nirgends gespeichert wird und der Lauf damit ganz verloren war. Jetzt fällt der
Wert heraus und wird über `verworfene_zielwerte` als Hinweis gemeldet.
**Zurechtgebogen wird nichts** — ein erfundener Korridor stünde ungeprüft auf der
Uhr. Punkt 10 des Prompts und `RESPONSE_SCHEMA` sagen die Regel zusätzlich
ausdrücklich; das senkt die Häufigkeit, ersetzt das Aufräumen aber nicht.

Welche Felder so behandelt werden, steht in `_ZIELWERT_SPANNEN`: `target_hr_low`,
`target_hr_high` und `rpe_target`. **Dauer und Distanz gehören bewusst nicht
dazu** — dort ist 0 ein zulässiger Wert, und eine stillschweigend verworfene
Dauer nähme dem Workout auf der Uhr seinen einzigen Anhaltspunkt für die Länge
(der Ersatzschritt in `workouts.py` läuft über `duration_min`). Wer ein weiteres
Zahlenfeld einträgt, prüft vorher, ob ein fehlender Wert wirklich harmloser ist
als ein abgelehnter Block.

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

**Am Telefon trägt die Navigation unten, nicht oben.** Die Kopfleiste mit sechs
Wegen nebeneinander funktioniert am Schreibtisch; auf einem Telefon bräuchte sie
drei Zeilen und stünde bei jedem Scrollen im Weg. Unterhalb von 860 px entfällt
sie deshalb ganz (`.topbar-app`), stattdessen blendet `Layout.tsx` eine feste
Leiste am unteren Rand ein: Übersicht, Plan, Garmin, Verlauf und „Mehr“ —
hinter „Mehr“ liegt ein Blatt mit Garmin-Kalender, Neues Training, Meine Daten
und Abmelden. Den Platz, an dem einmal „Erfassen“ stand, hat Garmin bekommen:
Von dort kommen die absolvierten Einheiten, also gehört der Abgleich in den
Alltag und nicht hinter „Mehr“. Orientierung geht dabei nicht verloren, weil jede Seite ihre
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
Durchschnittspuls; `rpe_source` hält fest, woher der Wert stammt, und geht so
in den Export, damit die KI die Belastbarkeit der Zahl einordnen kann. Seit dem
Wegfall der Handeingabe ist **jedes** RPE geschätzt — `manual` steht dort nur
noch an Alteinträgen, und der Abgleich nimmt darauf keine Rücksicht mehr.
Garmins `activityTrainingLoad` läuft nur *zusätzlich* mit (`total_garmin_load`)
und ersetzt die sRPE-Last **nicht**: Beide sind unterschiedlich skaliert, und
eine Übergangswoche aus alten manuellen und importierten Einheiten ergäbe sonst
Unsinn. Eine einheitliche Skala über den Übergang ist mehr wert als die
theoretisch bessere Metrik.

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
und der Prompt sagt stattdessen ausdrücklich, dass auch die Trainingshistorie
leer ist und der Block allein aus Fragebogen und Profil entsteht — Regeln
zu Daten, die es nicht gibt, laden zum Erfinden ein. Die Schwellen in
`wellness_auffaelligkeiten` und die Zahlen im Prompt müssen zusammen geändert
werden.

**Ein echtes Workout, keine Kalendernotiz** (`garmin/workouts.py`). Garmin führt
im Kalender auch Notizen; die erscheinen in Connect, kommen aber nie auf das
Gerät. Nur ein Workout mit Schrittliste *leitet* die Uhr an — Schrittwechsel,
Zielkorridor, Signal beim Verlassen. Deshalb wird `PlanSession.structure`, ein
Fließtext aus der KI, in Garmins Schritte zerlegt: „15 min Einlaufen Z1-Z2,
5 x 3 min Z4 mit je 2 min Trabpause, 10 min Auslaufen“ wird zu Aufwärmschritt,
einer Wiederholungsgruppe aus Belastung und Pause und Auslaufen, jeweils mit
Herzfrequenzkorridor aus den Karvonen-Zonen des Profils. **Der Parser rät
nicht**: Erkennt er nichts, wird
die Einheit *ein* Schritt über die geplante Dauer, und der ganze Aufbautext
steht in der Beschreibung. Ein falsch geratenes Intervalltraining auf der Uhr
ist schlimmer als ein grobes, weil es ungeprüft absolviert wird. Zwei Regeln
sind Konvention und deshalb kommentiert: Der zweite Teil eines Zweierpaars in
einer Wiederholung ist die Pause, und Pausen bekommen bewusst *keinen*
Zielkorridor (ein Alarm in der Erholung triebe genau den Puls hoch, der sinken
soll). Die Kennungen für Sport-, Schritt- und Zieltypen kommen aus
`garminconnect.workout` statt aus eigenen Zahlen — zwei Quellen dafür liefen
auseinander.

**Eine Serie bleibt eine Wiederholungsgruppe** (`_als_block`). Garmin führt sie
als `RepeatGroupDTO` — eine Zeile „Wiederholen 4ד mit Belastung und Pause
darunter —, und genau so steht sie auch in der App. Es gab hier einmal den
umgekehrten Weg: Jede Runde wurde ausgeschrieben, damit in der Schrittliste
nicht eine zusammengeklappte Zeile für vier Belastungen steht. Das ist
zurückgenommen; die Gruppe ist die Form, die der Athlet aus Connect kennt, und
sie bleibt bei zwanzig Wiederholungen genauso lesbar wie bei drei. Damit
entfällt auch `MAX_SCHRITTE`, die Obergrenze, die nur das Ausschreiben brauchte.

**Die Zahl der Wiederholungen wird an zwei Stellen gesucht** — am Anfang eines
Abschnitts *und* am Anfang jedes Teils darin. Geprüft wurde einmal nur der
Abschnittsanfang, und ein echter Plan brachte das zum Einsturz: „15 min
Einrollen Z1-Z2 / 4x6 min bei 195-210 W, dazwischen 3 min bei 110-130 W /
10 min Ausrollen Z1“. Die Serie steht dort hinter einem Schrägstrich, also fiel
das „4ד still weg — auf der Uhr stand *eine* Belastung, wo vier gemeint waren,
und der Athlet hätte nach dem ersten Intervall ausgerollt.

Zwei Regeln halten die Gruppe zusammen. Die **Serienpause steht oft hinter dem
Komma** und damit im nächsten Abschnitt („…, dazwischen 3 min bei 110-130 W“);
sie wandert deshalb in die zuletzt eröffnete Gruppe *hinein* statt dahinter —
aber nur, solange diese erst einen Schritt hat und die Zeile sich selbst als
Pause zu erkennen gibt. Dafür kennt `_ART_SCHLUESSELWOERTER` „dazwischen“ und
„lockeres Kurbeln“: Auf dem Rad heißt die Pause selten „Pause“. Und **Ein- und
Ausrollen gehören nie in eine Serie**: Enthält der Rumpf einen Warmup- oder
Cooldown-Schritt („4x6 min Z4 / 10 min Ausrollen Z1“), wird die Zeile als Block
ganz abgelehnt und Teil für Teil neu gelesen — viermal ausrollen ergibt keine
Einheit.

**Auf dem Rad steuert die Leistung, nicht der Puls — und zwar in jedem Schritt**
(`_leistung`, `_ziel`). Bei `bike` gewinnt Watt vor jeder Herzfrequenzvorgabe:
Auf dem Smarttrainer regelt Garmin das Gerät danach, und im Freien zeigt die
Leistung sofort an, ob das Tempo stimmt, während der Puls Minuten
hinterherzieht. Zuerst zählt die Angabe im **Schritttext**, denn Belastung und
Erholung haben je einen eigenen Korridor; danach das Feld `target_power`, und
das nur über Arbeitsschritten — auf das Einrollen gelegt stünden dort die
Intervallwatt; zuletzt die **Zone im Text**, umgerechnet über
`_ZONE_ZU_FTP_ANTEIL` (Coggan, Z1 nach unten auf 45 % gedeckelt statt auf 0,
weil eine Null für die Rolle keine Anweisung ist). Der letzte Schritt kam
nachträglich dazu: Ein- und Ausrollen nennen keine Watt und standen deshalb als
einzige Abschnitte mit Pulsziel im Workout — die Rolle fiel dort aus der
Regelung, mitten in derselben Einheit. Eben weil ein Wattkorridor eine Anweisung
an die Rolle ist und kein Alarm, gilt er **auch über einer Pause** und ist damit
die Ausnahme von „Pausen ohne Zielkorridor“. Ein Prozentwert im Fließtext zählt
nur, wenn „FTP“ danebensteht — dort kann er auch „% HFmax“ meinen, im Feld
`target_power` dagegen nicht.

**Der verdrängte Puls wandert in die Beschreibung** (`_pulshinweis`). Er
verschwindet nicht, er wechselt die Rolle: Statt Zielkorridor steht er als
„(Zielpuls 120-140 bpm)“ hinter dem Schritttext, den die Uhr unter dem Abschnitt
anzeigt — die Steuerung übernimmt die Leistung, den gewünschten Pulsbereich
sieht der Athlet trotzdem. Berechnet wird er aus derselben Quelle wie zuvor das
Ziel (`_herzfrequenz`: Zone im Text vor Vorgabe der Einheit, letztere nur über
Arbeitsschritten). Angehängt wird er **nicht**, wenn der Aufbautext den Puls
schon selbst nennt (`_PULS_IM_TEXT`) — die KI schreibt ihn oft dazu, und zwei
Korridore nebeneinander lesen sich wie ein Widerspruch. Er wird zuerst bemessen,
damit er beim Kürzen auf Garmins Feldgrenze nicht als Erstes fällt.
**Ohne bekannte FTP bleibt es beim Pulsziel**: Eine Leistung, die niemand
ausrechnen kann, ist keine.

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

**Die Kennung allein genügt nicht — die Uhr braucht die ganze Schrittform.**
Das war der Fehlschlag beim ersten Versuch am echten Gerät: `category` und
`exerciseName` standen korrekt in Connect (mit `get_workout_by_id`
zurückgelesen), die Fenix zeigte trotzdem keine Animation. Der Vergleich mit
einem Workout aus *Garmins eigener* Bibliothek („Ganzkörper-Mobilitäts-Warm-up“,
Workout 1336531040) zeigte vier fehlende Felder je Schritt: `weightValue: -1`
samt `weightUnit` (Garmins Marke für „ohne Zusatzgewicht“ — nicht 0, das wäre
eine Hantel ohne Scheiben), `strokeType`, `equipmentType` und vor allem ein
**nicht leerer `endConditionValue`**. Garmins eigene Schritte enden ebenfalls
per Rundentaste, tragen dort aber durchweg die Zahl 10 — auch über einem
Schritt, dessen Beschreibung „5 Brustöffner“ lautet. Der Wert ist also Beiwerk
und keine Vorgabe; `None` dagegen ließ die Uhr den Schritt nicht als Übung
erkennen. Wer die Schrittform anfasst, prüft sie gegen dieses Workout und nicht
gegen die Vermutung.

Derselbe Vergleich hat die Sportart bestätigt und den Katalog relativiert:
`sportTypeId 11` wird angenommen und speichert die `WARM_UP`-Kennungen — unter
`mobility` führt Garmin aber **mehr** Kategorien, als der Kraftkatalog kennt
(`POSE`, `MOVE`, dazu `WARM_UP`-Einträge wie `CHEST_OPENERS`, die im Wähler des
Krafteditors fehlen). Sie sind nirgends abrufbar; erreichbar ist nur, was in
`garminconnect.exercises` steht.

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
Animation. Und die Bewegungen, die der Katalog unter ihrem *bloßen* Namen führt,
zählen nur, wenn sie für sich allein stehen (`_grundform_ok`): Steht direkt davor
oder dahinter ein Wort, das keine Mengenangabe ist, gehört es mit einiger
Wahrscheinlichkeit zum Übungsnamen. „Copenhagen Plank“ ist eine Adduktorenübung
und kein Unterarmstütz, „Squat Jumps“ sind keine Kniebeugen — beide bekämen sonst
die Animation der Grundform. **Ein bloßer Name ist dabei zweierlei**
(`_ist_grundform`): die Grundübung der eigenen Kategorie („Plank“ in `PLANK`,
„Calf Raise“ in `CALF_RAISE`), *und* jeder einwortige Name, auch aus fremder
Kategorie. Am zweiten hing ein echter Fehlgriff: „Walk“ steht unter `RUN`, steckt
aber in „Lateral Band Walk“, und die Bandübung eines echten Plans bekam die
Animation eines Spaziergangs. Zwanzig solcher Namen führt der Katalog („Jog“,
„Sprint“, „Burpee“, „Step-up“ …).

**Die Klammer trennt, sie verbindet nicht** (`_KLAMMER` in `finde()`). Punkt 9
des Prompts verlangt hinter der deutschen Bezeichnung den geläufigen englischen
Namen in Klammern — über die Klammergrenze hinweg gelesen stand der eine
unmittelbar neben dem anderen, und für `_grundform_ok` sah „Unterarmstütz (Front
Plank)“ damit aus wie ein qualifizierter Unterarmstütz. Der Zusatz, der die
Trefferquote erhöhen sollte, verhinderte genau den Treffer. Gesucht wird deshalb
je Klammerabschnitt getrennt; der längste Treffer gewinnt, bei Gleichstand der
erste — also die deutsche Bezeichnung vor der englischen Klammer. Aus demselben
Grund kennt das Verzeichnis die Dehnungsnamen **auch ohne ihr angehängtes
„Stretch“**: Der Katalog hängt es an fast jede Dehnung, die geläufige
Bezeichnung kommt ohne aus, und genau die steht in der Klammer („Child's Pose“,
„Pigeon Pose“). Zwei verbleibende Wörter sind Bedingung — „Hamstring Stretch“
fiele sonst auf „hamstring“ zusammen und zöge jede Zeile an sich, in der das Wort
vorkommt.

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
`GarminWorkoutPoolSlot`, `GarminWorkoutLink`). In Garmin liegt das Workout in
der Bibliothek und ein Zeitplaneintrag verweist darauf. Tri-Coach verwaltet je
Nutzer **genau 15 dauerhafte Vorlagen**; ein Link belegt einen Slot nur für die
aktuelle Planeinheit und ihren Termin. Bestehende App-IDs werden beim ersten
Lauf übernommen, fehlende Slots aufgefüllt. Danach ersetzt `update_workout`
den Inhalt an derselben Kennung. Neue IDs entstehen nur beim ersten Aufbau oder
als Ersatz für eine mit 404 bestätigte, manuell gelöschte Pool-Vorlage. Ein
voller Pool bricht vor der ersten Teilübertragung ab, statt eine 16. ID oder
einen halben Block anzulegen.

**Der Kalender ist das Ziel, die Bibliothek nur der Weg dorthin**
(`workouts.name_der_einheit`). Deshalb trägt der Workout-Name **kein Datum**: Im
Kalender steht der Tag schon in der Spalte, in der die Einheit hängt, und
„16.08. Lockerer Dauerlauf“ am 16.08. las sich dort wie ein Fehler. Das Datum
stand einmal voran, um die Bibliothek sortierbar zu halten — das war der Blick
auf den falschen Ort, denn dort liegen nur die fünfzehn wiederverwendbaren
Pool-Slots. Was am Datum hing, muss der
Rückfall auf „Training“ jetzt selbst leisten: Garmin lehnt ein Workout ohne
Namen ab, und bis hierher war der Name durch den Datumsteil zwangsläufig nicht
leer. **Ganz ohne Bibliothekseintrag geht es nicht** — `schedule_workout` nimmt
eine `workoutId` und sonst nichts, einen Termin mit eingebettetem Inhalt kennt
Garmin nicht. Pool-Vorlagen werden deshalb im normalen Lebenszyklus nie
gelöscht.

**Was vorbei ist, gibt seinen Slot frei**
(`uebertragung.raeume_vergangene_auf`). Die App entfernt den Kalendertermin
und löst `GarminWorkoutLink`, behält aber die Pool-Vorlage. So wächst die
Connect-Bibliothek nicht über fünfzehn App-IDs hinaus. Die absolvierte Aktivität
ist ein eigener Datensatz und bleibt; auch die Umsetzungsquote hängt nicht am
Link, weil `matching` über Tag und Sportart verknüpft. Die verfügbare
Connect-API kennt **keinen Fern-Löschbefehl für bereits auf eine Fenix
synchronisierte Workouts**. Vor dem ersten Poolbetrieb müssen alte verwaiste
Tri-Coach-Workouts deshalb einmalig manuell auf der Uhr entfernt werden. Garmin
nennt für die meisten Geräte höchstens 25 benutzerdefinierte Workouts inklusive
vorinstallierter; fünfzehn Pool-Slots lassen bewusst Reserve. **An der Fenix 8
bestätigt:** Wird eine bestehende Workout-ID in Connect umbenannt und inhaltlich
geändert, synchronisiert die Uhr den neuen Inhalt in den vorhandenen lokalen
Eintrag. Dessen Name unter „Trainings“ bleibt zwar alt, der Kalender zeigt am
Termin aber den aktuellen Namen und startet den aktualisierten Inhalt. Das ist
für Tri-Coach die maßgebliche Ansicht; künstlich stabile Slotnamen sind deshalb
nicht nötig. **Davon getrennt bleibt der Sportartwechsel ungeprüft:** Der
generische `PUT` sendet zwar das vollständige neue `sportType`, aber weder
Garmins Oberfläche noch die Bibliothek belegen, dass etwa
`strength_training` zu `swimming` werden darf. Dafür liegt
`scripts/garmin_workout_typwechsel.py` im Abbild; `--aus-datenbank` verwendet
das verschlüsselt gespeicherte Token, legt genau eine temporäre Vorlage an,
liest den Typ vor und nach dem Wechsel zurück und löscht sie im `finally`.

**Die Übertragung ist ein Job, der Kalender nicht.** Ein Block kostet zwei
Anfragen je Einheit und läuft deshalb durch denselben Runner und dasselbe
globale Schloss wie ein Abgleich — Garmins Grenze unterscheidet nicht, ob
gelesen oder geschrieben wird. Einzelne Aufrufe (Monat laden, ein Workout
löschen, eine Einheit nachschieben) gehen dagegen über `garmin/verbindung.py`
direkt im Anfrage-Thread: Für eine einzelne Anfrage einen Fortschrittsbalken
zu bauen wäre Umstand ohne Nutzen. Die Einzelübertragung nimmt dabei dasselbe
globale Schloss nicht blockierend; läuft schon ein Garmin-Vorgang, antwortet
sie mit 409, statt parallel denselben Pool-Slot zu belegen. Beide Wege behandeln
die Anfragesperre
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

**Ein übernommener Block geht von selbst auf die Uhr**
(`automatik.starte_uebertragung_fuer_neuen_plan`, ausgelöst am Ende von
`POST /api/plans/import`). Ein Block reicht nur wenige Tage weit; einer, der
erst nach einem zusätzlichen Handgriff im Kalender landet, hat seine erste
Einheit oft schon hinter sich. Abschaltbar über `auto_push_enabled` am Konto,
Vorgabe **an** — wer ein Garmin-Konto verbindet, will seinen Plan dort haben.
Die Antwort wartet nicht auf den Lauf: Sie gibt seine `garmin_job_id` zurück,
und die Planansicht hängt sich beim Laden an einen laufenden Übertragungsjob
(`api.garminStatus()` in `PlanView.reload()`), damit der Fortschritt auch ohne
Knopfdruck sichtbar wird. Anders als der Knopf prüft die Automatik **nicht**, ob
gerade ein Lauf läuft: Wer selbst drückt, kann es gleich nochmal versuchen; ein
Import, der zufällig in den täglichen Abgleich fällt, hätte niemanden, der das
nachholt — der Job wartet stattdessen auf das globale Schloss. Was den Nutzer
davon abhält (abgelaufene Anmeldung, Anfragesperre), kommt als `garmin_hinweis`
mit der Import-Antwort und reist über den Router-Zustand in die Planansicht.

**Ein abgelöster Block wird aus Garmin geräumt, bevor der neue hineingeht**
(`uebertragung.raeume_ersetzte_auf`, gerufen aus `runner._raeume_ersetzte_vorab`).
Der nächste Block entsteht als *neuer* Plan, der bisherige wird nur stillgelegt
— seine übertragenen Einheiten blieben aber stehen. Weil beide Blöcke dieselben
Tage abdecken, stünden auf der Uhr zwei Trainings je Tag, und welches überholt
ist, sähe der Athlet vor dem Start nicht. **Die Reihenfolge ist Absicht:** Am
Ende des Laufs geräumt (wie das Vergangene), bliebe nach einem Abbruch auf halbem
Weg — eine Anfragesperre genügt — der alte Block neben dem halben neuen stehen.
Vorher geräumt ist der schlimmste Fall ein Tag ohne Vorgabe: ärgerlich, aber
nicht irreführend.

Drei Grenzen dabei. Geräumt wird nur, was in der **Zukunft** liegt und zu einem
**inaktiven** Plan gehört; Vergangenes erledigt `raeume_vergangene_auf`. Erst
**ab dem Beginn des aktiven Blocks** — wer die Folgewoche plant, hat für den
Rest dieser Woche weiterhin nur den alten Block, und dessen Einheiten aus dem
Kalender zu werfen ließe ihn bis zum Blockbeginn ohne Vorgabe dastehen (dieselbe
Grenze nennt der Hinweis beim Übernehmen: „ab dem <Datum> entfallen dort N
Tage"). Und **nicht der Block, der gerade übertragen wird** (`ausser_plan_id`):
Auch ein stillgelegter Plan lässt sich gezielt auf die Uhr legen, und ohne die
Ausnahme löschte derselbe Lauf am Ende wieder, was er eben hochgeladen hat.

**Im Kalender darf nur der aktive Block stehen — auch wenn nichts hineingeht**
(`runner.starte_uebertragung(…, "cleanup")`). Das Aufräumen hing bisher an einer
Übertragung oder einem Abgleich; wer die automatische Übertragung abgeschaltet
hatte, behielt nach dem Neuplanen den *überholten* Block allein im Kalender —
die neue Vorgabe ging nicht hin, die alte blieb liegen und galt auf der Uhr
weiter. Deshalb stößt `automatik.starte_uebertragung_fuer_neuen_plan` jetzt in
beiden Fällen einen Lauf an: `push`, wenn etwas zu senden ist, sonst `cleanup` —
ein Job, der nichts hochlädt und nur aus dem Nachlauf besteht. Dass ein Block
nicht von selbst auf die Uhr geht, ist eine Entscheidung über das *Hinlegen*;
das Wegräumen dessen, was diese App selbst einmal hingelegt hat, hängt nicht
daran. Ob sich der Lauf lohnt, beantwortet `uebertragung.ersetzte_links()` ohne
eine einzige Anfrage an Garmin. Und weil dieser Job kein zweites Ziel hat,
hinter dem ein Fehlschlag verschwinden dürfte, meldet er ihn: Ein Nachlauf, der
nicht durchkommt, macht ihn `failed` statt „done" (`Aufraeumbilanz`).

**Ein gelöschter Plan nimmt seine Einheiten mit** (`plans._nimm_aus_garmin`).
Die Reihenfolge ist die ganze Pointe: In Garmin fasst diese App nur an, was in
`GarminWorkoutLink` steht, und der stirbt mit der Planeinheit; der Pool-Slot
bleibt für spätere Pläne bestehen. Wer den Plan zuerst löschte — so war es —,
ließ seine Einheiten für immer im fremden
Kalender stehen, und dort galt dann eine Vorgabe weiter, die es in der App gar
nicht mehr gibt. Deshalb läuft das Entfernen **vor** dem Löschen, und zwar im
Anfrage-Thread statt als Job: Es sind zwei Anfragen je Einheit und höchstens
eine Handvoll (Vergangenes hat der letzte Abgleich schon geräumt), und ein
Löschen, das erst später wirkt, wäre schwerer zu verstehen als eines, das ein
paar Sekunden dauert. **Scheitert der Zugang, wird nicht gelöscht:** Ein Plan
ist schnell noch einmal gelöscht, ein verwaister Termin im fremden Kalender
nie mehr — der Nutzer bekommt den Grund und darf mit `garmin_uebergehen` darauf
bestehen. Ohne verbundenes Konto und ohne Zuordnungen bleibt alles wie zuvor:
kein Aufbau, keine Anfrage.

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
und `SessionLog.sleep_hours` je Einheit ist mit dem Erfassungsformular
verschwunden. Die Trainingserfahrung in Jahren sagt
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

**Und in die Gegenrichtung: `_ENTFALLENE_SPALTEN`.** Eine Spalte, die aus dem
Modell fällt, könnte in der Datei liegen bleiben — SQLAlchemy stört sich nicht
an etwas, das es nicht kennt. Bei Gesundheitsdaten ist das keine Option: Die
Datei wandert in jedes Home-Assistant-Backup und von dort auf NAS oder
USB-Stick, und was niemand mehr liest und niemand mehr füllen kann, hat dort
nichts verloren. `DROP COLUMN` beherrscht SQLite seit 3.35 (2021) und nur,
solange die Spalte in keinem Index und keiner Bedingung steht — trifft beides
zu; ein älteres SQLite lässt sie liegen, statt den Start scheitern zu lassen.
**Eine Spalte darf nie in beiden Listen stehen**: Sie würde bei jedem Start
ergänzt und wieder gelöscht, deshalb bricht `database.py` beim Import ab, wenn
sich die Listen überschneiden.

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
- `SessionLog` hat nur noch ein Schema, `SessionLogOut`: Es gibt keinen
  Anfragekörper mehr, aus dem eine Einheit entstünde. Ein neues Feld gehört
  dorthin *und* in `mapping.aktivitaet_zu_log()` — sonst bleibt die Spalte leer.
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

## Die KI im Server (`ki/`)

**Claude Code als Unterprozess, nicht die API.** Der Haushalt hat ein Abo, und
ein Aufruf am Tag trägt sich darüber ohne Abrechnung nach Token. Kein
`claude-agent-sdk`: Es umhüllt dieselbe CLI, und ein Prompt hinein, ein Text
heraus braucht keine zweite Abhängigkeit. Der Aufruf liegt an genau einer Stelle
(`ki/client.py`), die Fehlerübersetzung ins Deutsche daneben (`ki/errors.py`) —
derselbe Zuschnitt wie bei `garmin/`.

**Vier Vorkehrungen, damit dort ein Trainingsplaner antwortet und kein
Programmieragent** — alle am echten Programm geprüft (Version 2.1.233):
`--tools ""` schaltet sämtliche Werkzeuge ab; `--safe-mode` nimmt CLAUDE.md,
Skills, Plugins, Hooks und MCP aus dem Spiel **und lässt die Anmeldung
unberührt**; der Systemprompt wird über `--system-prompt` *ersetzt* statt
ergänzt (der Standardtext beschreibt einen Programmieragenten und kostete im
Versuch allein 3049 Token); und gearbeitet wird in einem leeren
Verzeichnis. **`--bare` sieht passend aus, ist aber eine Falle:** Es liest OAuth
ausdrücklich *nie* und verlangt einen API-Schlüssel, den es hier nicht gibt.

**Opus bei `--effort max`, und kein `--fallback-model`.** Die Antwort trägt den
ganzen Block, deshalb die teuerste Einstellung. Ein stiller Rückfall auf ein
schwächeres Modell wäre schlimmer als ein Fehlschlag: Der Block sähe genauso
aus. Stattdessen hält `KiJob.model_used` fest, **welches Modell tatsächlich
geantwortet hat**. Abgelesen wird das aus `modelUsage` über den **Preis**, nicht
über die Tokenzahl — die CLI zieht nebenher ein Hilfsmodell heran, das im
gemessenen Lauf mehr Eingabetoken verbrauchte als das eigentliche (21584 gegen
2), aber ein Zwanzigstel kostete.

**Die JSON-Hülle wird ausgewertet, bevor `result` weitergereicht wird.** Sonst
landete eine Fehlermeldung im Planparser und käme als „unlesbares JSON" heraus.
Geprüft werden `is_error`, `api_error_status` und `stop_reason` — ein
`refusal` bekommt eine eigene Meldung.

**Der Lauf ist ein Job mit eigenem Schloss.** Er dauerte in zwei Messungen 85 s
und 211 s — der Unterschied kommt aus der Denkzeit, nicht aus der Prompt-Größe.
Hinter dem Ingress wäre eine so lange HTTP-Antwort ein Risiko, und der Nutzer
säße vor einem Balken ohne Rückmeldung. Aufbau und
Zustandsnamen wie bei `GarminSyncJob`, damit `pollJob` im Frontend für beide
gilt. Aber **nicht dasselbe Schloss** wie bei Garmin: Die beiden Gegenstellen
haben nichts miteinander zu tun, ein Planungslauf dürfte nicht hinter einem
Jahresrückblick warten — und der Import am Ende stößt seinerseits eine
Garmin-Übertragung an, die sonst auf ein Schloss liefe, das der Planungslauf
selbst noch hält.

**Ein Weg für beide Auslöser.** `ai_export.erzeuge_export()` und
`plan_import.uebernimm_plan()` sind aus den Routen herausgezogen und werden vom
Knopf wie vom Handweg über die Zwischenablage gleichermaßen benutzt. Damit erbt
der Knopf ohne eine Zeile Wiederholung, was am Übernehmen hängt: der abgelöste
Block wird weggeräumt, und der neue geht über
`garmin.automatik.starte_uebertragung_fuer_neuen_plan` von selbst auf die Uhr.

**Kein `--json-schema`, obwohl die CLI es könnte.** `parse_ai_response` fängt
Codefences, Begleittext und `weeks`-Ebenen bereits ab und ist getestet; im
Versuch mit dem echten Prompt kam die Antwort ohne Fence und ohne Vorrede und
lief mit **null Warnungen** durch. Ein striktes Schema wäre ein zweiter, eigener
Fehlerpfad — und eine Fessel für genau das Modell, von dem hier die beste
Antwort erwartet wird. Bleibt in der Hinterhand.

**Geplant wird nur auf Zuruf.** Es gab hier einmal eine Automatik: eine zweite
Viertelstundenschleife neben der von Garmin (`ki/automatik.py`), die den
nächsten Block anlegte, sobald der alte auslief. Sie ist **ganz entfernt** —
Schleife, `TRI_KI_AUTOPLAN`, `TRI_KI_PLAN_HOUR`, der Schalter je Nutzer und
seine Tests. Der Grund ist nicht technisch: Ein Trainingsblock ist eine
Entscheidung, und ein Plan, der über Nacht von selbst entsteht, steht am Morgen
auf der Uhr, ohne dass ihn jemand bestellt hätte — und hat dabei stillschweigend
vom Kontingent des Abos genommen, das man daneben selbst braucht. Geblieben sind
der Knopf („Block jetzt planen") und der Weg über die Zwischenablage. Der Preis
ist ausdrücklich in Kauf genommen: **Läuft ein Block aus, geschieht nichts.**
Das Dashboard weist darauf hin (`blockStatus()`), mehr nicht.

Was davon in der Datenbank bleibt, ist Absicht: `auto_plan_enabled`,
`plan_days` und `last_auto_plan_on` stehen weiter an `KiSettings`, weil sie in
bestehenden Datenbanken NOT NULL sind — aus dem Modell entfernt, ohne die Spalte
zu löschen, schlüge das Anlegen einer Einstellungszeile fehl. Gelesen wird
nichts davon mehr, und aus `KiSettingsOut`/`KiSettingsIn` sind sie heraus.
`test_es_gibt_keine_automatische_planung` schreibt die Regel fest: Der Test
verlangt, dass sich `app.ki.automatik` nicht importieren lässt — eine Schleife,
die wieder einzöge, fiele sonst erst am aufgebrauchten Kontingent auf.

**Die Umgebung des Unterprozesses wird zusammengestellt, nicht geerbt**
(`_umgebung()`). Beim ersten Ende-zu-Ende-Lauf aufgefallen: Wer die App aus
einer laufenden Claude-Code-Sitzung heraus startet — in der Entwicklung der
Normalfall —, hat ein Dutzend `CLAUDE_CODE_*`-Variablen in der Umgebung,
darunter Sitzungskennung und Meldungssocket. Vererbt hängt sich der
Unterprozess daran und kehrt **nicht zurück**; der Lauf endete nach fünfzehn
Minuten in der Zeitüberschreitung statt nach anderthalb in einer Antwort.
Durchgereicht wird deshalb eine feste Liste. Zwei Einträge darin sind nicht
offensichtlich: **`USER`** — ohne die Variable findet die CLI auf macOS ihre im
Schlüsselbund abgelegte Anmeldung nicht und meldet „Not logged in", obwohl der
Nutzer angemeldet ist — und die Proxy- und Zertifikatsvariablen, ohne die
niemand hinter einem Firmenproxy hinauskäme. Ein herumliegender
`ANTHROPIC_API_KEY` wird bewusst **nicht** durchgereicht: Gelten soll das Abo.

**Verfügbarkeit wird am Programm geprüft, nicht an der Umgebung.**
`ist_angemeldet()` ruft `claude auth status` auf, statt nachzusehen, ob eine
Variable gesetzt ist. Im Add-on kommt der Zugang als Token, bei der lokalen
Entwicklung aus der Anmeldung der CLI selbst — die Frage ist in beiden Fällen
dieselbe, die Antwort steht nur an verschiedenen Orten. Das Ergebnis wird eine
Minute lang gehalten, damit nicht jedes Laden der Seite einen Prozess startet.

## Bekannte Grenzen / mögliche nächste Schritte

- **Ohne Garmin gibt es keine Trainingshistorie.** Die App kann eine Einheit
  weder erfassen noch nachtragen; wer keine Uhr verbindet, bekommt Blöcke
  allein aus Fragebogen und Profil. Ebenso fehlt jede Möglichkeit, eine
  importierte Einheit zu korrigieren — was Garmin falsch liefert, wird in
  Connect berichtigt und beim nächsten Abgleich nachgezogen, oder der Eintrag
  wird im Verlauf gelöscht.
- Die **subjektiven Werte** (Befinden, Muskelkater, Schlafqualität, Morgenpuls,
  Morgen-HRV, Bedingungen, Schlaf je Einheit) haben damit keine Quelle mehr und
  sind ersatzlos aus Modell, Schema, Export und Datenbank entfernt. Das RPE
  bleibt als einziger und wird geschätzt. Wer eines dieser Felder je
  zurückholen will, braucht wieder ein Formular — die Spalte ist weg, die
  Historie damit auch.
- Was ein Athlet **vor** dieser Umstellung von Hand eingetragen hat, bleibt
  liegen und zählt weiter mit. `/api/garmin/dubletten` zeigt, was dabei doppelt
  ist; entfernt wird es über den Verlauf, einzeln und von Hand.
- Keine Diagramme — Verlauf und Wochenübersicht sind Tabellen.
- Kein Alembic. Neue Spalten werden im Migrationshelfer in `database.py`
  eingetragen und beim Start ergänzt, entfallene über `_ENTFALLENE_SPALTEN`
  beim Start gelöscht; für Umbenennungen oder Typänderungen bleibt es beim
  Löschen der Datei. Die Tabelle `garmin_workout_links` legt
  `create_all()` beim Start an; die zwei Zählwerke an `garmin_sync_jobs`,
  `athlete_profiles.garmin_personal_bests` sowie
  `garmin_accounts.synced_through` und `garmin_accounts.auto_push_enabled`
  kommen über den Helfer.
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
- Die **automatische Übertragung wartet nicht ab, sondern stellt sich an.** Wer
  mehrere Blöcke hintereinander übernimmt, während ein Jahresrückblick läuft,
  hat ebenso viele Fäden am globalen Schloss stehen. Bei einer Handvoll
  Einheiten je Block ist das folgenlos; eine Warteschlange mit Zusammenfassen
  gleicher Aufträge gibt es aber nicht.
- Die **Bahnlänge für Schwimm-Workouts** liegt fest bei 25 m
  (`workouts.POOL_LAENGE_M`) — die App fragt sie nirgends ab. Im 50-m-Becken
  stimmen die Strecken, nur die Bahnzahl auf der Uhr nicht.
- Der **Wattkorridor aus der Zone** ist eine Umrechnung über feste
  FTP-Anteile und damit die gröbste der drei Leistungsquellen: Er trifft das
  Ein- und Ausrollen, ersetzt aber keine Wattangabe der KI. Wer im Profil
  **keine FTP** stehen hat, bekommt auf dem Rad weiterhin Pulsziele — dann
  regelt der Smarttrainer in diesen Schritten nicht. Die FTP kommt aus Garmin
  (`sync.hole_leistungswerte`) oder von Hand aus der Profilseite.
- **Kraft- und Mobility-Schritte tragen keine Wiederholungszahl**: Jede Übung
  ist ein Schritt bis zur Rundentaste, „3x15 je Seite“ steht nur als Text
  darin. Garmin könnte mehr (`create_strength_set`, also Wiederholungsgruppe
  mit `endCondition: reps` und Satzpause), und die Übungskennung liegt jetzt
  vor — was fehlt, ist die Regel für „je Seite“: Sie verdoppelt die Sätze, und
  eine Haltedauer („2x45 s“) ist keine Wiederholungszahl. Die Animation hängt
  *nicht* daran — Garmins eigene Übungsworkouts enden ebenfalls per
  Rundentaste.
- Die **Zuordnung zum Übungskatalog** deckt ab, was in Kraft- und
  Mobilityplänen für Ausdauersportler üblich ist, nicht den ganzen Katalog.
  Gemessen ist sie an den bis dahin erzeugten Blöcken: Alle 23 Übungen der
  vier Kraft- und Mobility-Einheiten in der Datenbank werden zugeordnet. Was
  `uebungen.finde()` nicht erkennt, bleibt ohne Animation — sichtbar wird
  das nur auf der Uhr, die App meldet es nirgends. Wer eine Lücke bemerkt,
  trägt sie in `SYNONYME` nach; `test_garmin_uebungen.py` prüft, dass jede
  Entsprechung im Katalog existiert.
- Ein paar Bewegungen führt der Katalog **nur mit Gerät**, obwohl der Plan sie
  ohne meint: Für „Single-Leg Romanian Deadlift“ gibt es keinen Eintrag ohne
  Hantel oder Schlingen, weshalb dort das zweibeinige „Romanian Deadlift“
  animiert wird — dieselbe Hüftbeuge, nur auf zwei Beinen. „Bulgarian Split
  Squat“ und „Nordic Hamstring Curl“ bleiben aus demselben Grund ganz ohne
  Animation.
- **Yogaposen fehlen ganz.** Garmins Posenkatalog steckt hinter dem
  angemeldeten Connect-Editor und wird nirgends öffentlich ausgeliefert
  (`web-data/exercises/Yoga.json` ist ein 404). Deshalb laufen Mobility-
  Einheiten als Garmins „Mobility“ über den Kraftkatalog statt als Yoga.
- Die Sportart `mobility` (11) und die Übungskennungen sind am echten Konto
  bestätigt (Garmin speichert und liefert beides zurück). **Offen bleibt, ob
  die Animation auf dem Gerät erscheint** — die Schrittform wurde erst danach
  an Garmins eigenes Workout angeglichen und ist am Gerät noch ungeprüft.
- Eine **Koppeleinheit** ohne erkennbare Teilung im Aufbautext wird 2:1 auf Rad
  und Lauf geschätzt; die Beschreibung des Workouts weist das aus.
- Workouts landen über den Kalender auf der Uhr — beim nächsten Synchronisieren
  des Geräts. Ein Direktversand an ein bestimmtes Gerät
  (`push_workout_to_device`) ist nicht eingebaut; er kostete zusätzliche
  Anfragen für die Gerätesuche.
- Das Aufräumen vergangener Einheiten lässt sich nicht abschalten und hängt an
  einem Abgleich oder einer Übertragung; wer beides nie auslöst, behält seine
  alten Vorlagen.
- Ein überbügelter Block, dessen Einheiten schon in Garmin liegen, bleibt so
  lange in der Planliste stehen, bis das Aufräumen dort **durchgekommen** ist —
  vorher darf er nicht gelöscht werden, sonst käme niemand mehr an seine
  Workouts heran. Im Normalfall ist das derselbe Handgriff (der Aufräumlauf
  hängt am Übernehmen); scheitert er an einer Anfragesperre, bleibt der Block
  bis zum nächsten Lauf sichtbar.
- Das **Löschen eines Plans wartet auf Garmin** und läuft dabei im
  Anfrage-Thread, nicht als Job: Bei einem Block mit vielen übertragenen
  Einheiten dauert die Antwort entsprechend (je Einheit zwei Anfragen und eine
  Sekunde Pause). Es hält auch **nicht das globale Schloss** des Runners —
  derselbe Zuschnitt wie beim Löschen einer einzelnen Einheit, aber mit mehr
  Anfragen dahinter.
- Wer beim Löschen `garmin_uebergehen` setzt (die Rückfrage „Trotzdem
  löschen?"), behält verwaiste Workouts in Garmin: Mit dem Plan stirbt die
  Zuordnung, und ohne sie fasst die App dort nichts mehr an. Der Kalender in
  der App zeigt sie weiterhin zum Entfernen an — das ist dann der einzige Weg.
- Der Bestandsabgleich prüft nur die Monate, in denen die App ihre Einheiten
  vermutet. Wer ein Workout in **Connect** auf einen anderen Monat schiebt, wird
  dort nicht gefunden; die Vorlage besteht aber noch, also wird die Zuordnung
  nicht gelöscht, sondern nur ihr Termin vergessen — die nächste Übertragung
  legt einen zweiten Termin auf dem Plantag an, ohne den verschobenen zu
  kennen. Innerhalb der App verschieben (Kalenderansicht) hat das Problem
  nicht: Dort zieht die Planeinheit mit um.
- Für den Netzbetrieb fehlen HTTPS, eine echte Authentifizierung vor der App,
  gesetzter `TRI_SECRET_KEY` und angepasste CORS-Herkünfte (`config.py`).
- Das **Claude-Token liegt im Klartext** in `/data/options.json` und wandert
  damit in jedes Home-Assistant-Backup — anders als das Garmin-Token, das genau
  deshalb verschlüsselt wird (`crypto.py`). Bewusst so: Für Add-on-Optionen ist
  das der übliche Weg, die Oberfläche maskiert das Feld (`password?`), und ein
  zweiter Ablageort wäre ein zweiter Weg, die Anmeldung zu verlieren. Wer das
  nicht will, lässt die Option leer und plant weiter über die Zwischenablage.
- **Das Kontingent teilt sich mit der eigenen Claude-Nutzung.** Ein Lauf mit
  Opus bei `max` verbraucht spürbar vom Fünf-Stunden-Fenster des Abos; ein Lauf
  am Tag ist unkritisch, wer daneben viel mit Claude arbeitet, kann trotzdem ins
  Limit laufen. Dann scheitert der Lauf mit deutscher Meldung, und der Block
  fehlt an dem Tag.
- **Der Zugang läuft irgendwann ab.** Die App kann das nur melden, nicht
  erneuern — die Meldung nennt deshalb ausdrücklich `claude setup-token`.
- **Ein ausgelaufener Block bleibt ausgelaufen.** Seit dem Wegfall der Automatik
  entsteht der nächste erst, wenn jemand plant — bis dahin steht auf der Uhr
  nichts Neues, und im Kalender bleibt der letzte übertragene Block liegen, bis
  ein Abgleich seine vergangenen Tage abräumt.
- Die Zuordnung von Fehlertexten der CLI zu eigenen Fehlern (`_ordne_fehler_ein`)
  geht über **Textbausteine**, weil es für Anmelde- und Kontingentfehler kein
  maschinenlesbares Feld gibt — `api_error_status` bleibt leer, wenn die Anfrage
  gar nicht erst hinausging. Ein unbekannter Fall landet als allgemeiner Fehler
  **mit Originaltext** in der Meldung, statt still eingeordnet zu werden.
- **Das Add-on-Abbild ist mit Claude Code ungeprüft**: Der native Installer
  bedient laut Manifest `linux-arm64` und `linux-x64`, gebaut wurde er hier
  aber nicht (kein Docker in der Entwicklungsumgebung). Das `claude --version`
  am Ende der Docker-Stufe lässt den Build scheitern, statt ein Abbild ohne die
  Funktion auszuliefern.
- Der Planungslauf hängt an einem Abbild, das die CLI **zur Bauzeit aus dem Netz
  holt** (`curl … | bash`). Ein Build ohne Netz schlägt fehl, und zwei Builds zu
  verschiedenen Zeiten können verschiedene Versionen enthalten — dasselbe gilt
  aber schon für `npm ci` im Frontend.
