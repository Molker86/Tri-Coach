# Tri-Coach — Kontext für Claude Code

## Was das ist

Trainingsplanungs-App für Ausdauersport. Der Nutzer beantwortet einen
Fragebogen, die App erzeugt daraus Prompt + Datenpaket für eine KI, der Nutzer
kopiert das per Hand in eine KI und fügt die Antwort zurück in die App ein. Die
Antwort wird zu einem strukturierten Trainingsblock über wenige Tage. Absolvierte
Trainings werden erfasst und fließen in den nächsten Export ein.

**Asymmetrie merken:** Rückblick ein Jahr, Vorausplanung wenige Tage (Vorgabe 7,
einstellbar 1–14 über `days` am Export). Das ist eine bewusste Entscheidung —
siehe „Planungshorizont".

**Der Rückblick ist eine Auflösung, keine Fensterbreite.** Derselbe Verlauf
steht dreimal im Paket, immer gröber: die letzten **sechs Wochen** Einheit für
Einheit, das letzte **halbe Jahr** Woche für Woche, das letzte **Jahr** Monat
für Monat. Die erste Ebene sagt, wo der Athlet steht, die zweite, wie er
dorthin gekommen ist, die dritte, ob es über die Saison aufwärts geht. Sie
**überlappen absichtlich**, und der Prompt verbietet ausdrücklich, sie zu
addieren. Die Monatsebene kommt aus `wellness_days` und nicht aus
`ProfileHistory` — siehe „Drei Auflösungsebenen".

**Trainings- und Fitnessdaten kommen aus Garmin Connect — und nur von dort.**
Wer ein Konto verbindet, trägt nichts mehr von Hand nach: Trainings, Schlaf,
HRV, Ruhepuls und Garmins Erholungsbewertungen werden geholt und fließen in den
nächsten Export ein — bei Kraft und Mobility samt der Übungen, die die Uhr
gezählt hat. Die Formulare zum Erfassen und Nachtragen gibt es **nicht
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

**Einzelne Einheiten lassen sich nachträglich per Freitext ändern.** Wer im
Trainingsplan eine Einheit öffnet, schreibt in einem Satz hinein, was anders
werden soll („nur 40 Minuten Zeit", „Knie zwickt", „lieber schwimmen") — die KI
bekommt denselben vollen Kontext wie beim Planen eines Blocks, dazu den Block,
in dem die Einheit steht, und schreibt die eine Einheit neu. Der Tag bleibt.
Anschließend geht die neue Fassung von selbst auf die Uhr und ersetzt dort die
alte; wird Ruhe daraus, verschwindet der Termin. Siehe „Eine einzelne Einheit
wird angepasst, nicht ersetzt".

**Und die Mitte kann die App inzwischen selbst: Sie fragt Claude direkt.**
Wer ein Claude-Abo hinterlegt, drückt einen Knopf statt zu kopieren — und wer
will, auch das nicht mehr: Ein Schalter in den Einstellungen lässt den nächsten
Block **einmal pro Woche** von selbst entstehen, an einem wählbaren Wochentag zu
wählbarer Uhrzeit (Vorgabe Sonntag 09:00). Ab Werk ist er aus, denn jeder Lauf
kostet Kontingent; siehe „Geplant wird auf Zuruf — oder einmal die Woche".
Aufgerufen wird **Claude Code headless** als Unterprozess, nicht die API mit
Token-Abrechnung: Das Abo war da, und ein Aufruf am Tag kostet darüber nichts
extra. Der Weg über die Zwischenablage bleibt vollständig erhalten — als
Rückfallebene für einen abgelaufenen Zugang, ein aufgebrauchtes Kontingent oder
eine andere KI.

**Und der geplante Tag wird morgens noch einmal nachgeschärft.** Ein Block deckt
sieben Tage ab — was auf Tag 4 liegt, wurde vier Tage vorher entschieden, auf
einer Erholungslage, die es an dem Morgen noch gar nicht gab. Ein Schalter im
Garmin-Bereich der Einstellungen schließt die Lücke: Sobald der tägliche Abgleich
durch ist, prüft die KI die Einheiten von **heute** gegen Schlaf, HRV, Ruhepuls
und Erholung und nimmt sie zurück, hebt sie an oder lässt sie stehen —
**unverändert ist ausdrücklich der Regelfall**. Der Tag, die Sportart und die
Zahl der Einheiten bleiben; aus einem geplanten Ruhetag wird nie Training, aus
einer Einheit sehr wohl Ruhe. Geänderte Einheiten gehen von selbst auf die Uhr — dieselbe
Vorlage am selben Termin, nur mit neuem Inhalt; wird Ruhe daraus, verschwindet
der Termin. Gesehen wird das auf der Startseite: über der Karte „Heute" steht,
dass angepasst wurde und warum. Der Lauf selbst ist vorbei, bevor jemand die
App öffnet. Ab Werk aus, denn er kostet einen Lauf **pro Tag**; am Planungstag
setzt er aus. Siehe „Die Tagesanpassung hängt am Abgleich".

**Und neben dem Training plant sie inzwischen auch das Essen.** Wer einen
Trainingsblock hat, bekommt auf Knopfdruck den Ernährungsplan dazu — Tag für
Tag, Mahlzeit für Mahlzeit, in Mo–So-Spalten, mit Supplementempfehlung, wo eine
trägt. Die KI bekommt dafür den geplanten Block Tag für Tag, das Ziel aus dem
Fragebogen und die Körperdaten, und antwortet als Fachmann für die gewählte
Disziplin — „Experte für Laufernährung", „für Triathlonernährung". Ein Freitext
im Profil sagt ihr einmal und dauerhaft, was einschränkt: Unverträglichkeiten,
Kantine, Schichtdienst. Siehe „Ernährung wird geplant wie Training".
**Und der Einkauf dazu geht auf die Bring-Liste.** Jede Mahlzeit nennt ihre
Zutaten einzeln — Einkaufsname, Menge, Einheit —, und ein Knopf auf der
Ernährungsseite zählt sie über alle Tage ab heute zusammen und schreibt sie in
die gewählte Bring-Liste. **Was dort schon steht, wird aufgestockt statt doppelt
angelegt**: Bring kennt keine Mengenfelder, also liest die App die vorhandene
Angabe, rechnet und schreibt sie zurück — und hängt an, wo sich nichts rechnen
lässt. Ein Vorschaudialog zeigt vorher, was übertragen wird. Ein Riegel je Tag
verhindert, dass ein zweiter Knopfdruck die Mengen verdoppelt. Erst ab dem
nächsten geplanten Block: Ältere Ernährungspläne haben keine Zutaten. Siehe
„Die Zutaten kommen von der KI, nicht aus der Prosa".
**Was die App ohne Zutun tut, steht unter „Einstellungen".** Dort wird auch das
Garmin-Konto **verbunden und getrennt** — das Anmeldeformular stand einmal auf
der Garmin-Seite, die Schalter dazu schon hier; jetzt liegt beides beieinander,
und `/garmin` behält den Abgleich. Abgleich an/aus samt Uhrzeit **auf die
Minute**, Übertragung auf die Uhr, Profilübernahme, der Claude-Zugang
(verschlüsselt in der Datenbank statt im Klartext in den Add-on-Optionen),
automatische Planung samt Wochentag und Uhrzeit, Modell und Denktiefe — dazu das
Bring-Konto mit der Wahl, in welche Einkaufsliste geschrieben wird, und
Hell/Dunkel. Beide Automatiken laufen **unabhängig voneinander**: Der Abgleich
täglich, die Planung einmal die Woche (Vorgabe Sonntag 09:00). Wer sie nach dem
Abgleich haben will, legt sie später. Und auf der Startseite öffnet jede Einheit
denselben Dialog wie im Trainingsplan: ansehen, per Freitext anpassen lassen.

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
  **Erweitert:** Es sind inzwischen drei Auflösungsebenen bis ein Jahr zurück —
  siehe „Drei Auflösungsebenen".
- Geplant wird jeweils nur der nächste kurze Block (Nachforderung, ersetzt den
  ursprünglichen Vier-Wochen-Plan). Ein aktiver Plan kann per Knopfdruck um
  beliebig viele weitere Blöcke verlängert werden — die Auswertung bezieht sich
  auf den Rückblick, unabhängig davon, wie lange der Block reicht.

## Starten und Testen

```bash
./start.sh                                        # beide Server
cd backend && .venv/bin/python -m pytest tests/ -q # 703 Tests
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

Daneben liegen `Exercises.json` und `Mobility.json` — Garmins Übungskatalog, den
der Abgleich täglich holt (`garmin/katalog.py`). Sie zu löschen ist folgenlos:
Bis zum nächsten Abgleich gilt die Erstausstattung aus
`backend/app/garmin/katalogdaten/`.

Umgebungsvariablen: `TRI_SECRET_KEY` (sonst `backend/.secret_key`, automatisch
erzeugt — ein Wechsel macht gespeicherte Garmin-Token unlesbar und verlangt eine
Neuanmeldung), `TRI_DATABASE_URL`, `TRI_CORS_ORIGINS`, `TRI_GARMIN_AUTOSYNC`
(`0` schaltet den täglichen Abgleich ab; in Tests gesetzt) und
`TRI_GARMIN_SYNC_HOUR` (Ortszeit-Stunde, ab der abgeglichen wird, Vorgabe 9
— nur noch die **Vorgabe** für ein neu verbundenes Konto; maßgeblich sind
`GarminAccount.sync_hour` und `.sync_minute` aus den Einstellungen).

Für die KI-Planung: `CLAUDE_CODE_OAUTH_TOKEN` (der Abo-Zugang; den Namen gibt
Claude Code vor, der Unterprozess liest genau diese Variable) — inzwischen der
**Rückfall**, denn Vorrang hat das Token aus den Einstellungen. Lokal genügt
statt beidem eine angemeldete CLI; geprüft wird nicht die Variable, sondern
`claude auth status`. Dazu `TRI_KI_CLI` (Pfad zum Programm, Vorgabe `claude`),
`TRI_KI_MODELL` (Vorgabe `opus`), `TRI_KI_EFFORT` (Vorgabe `max`) und
`TRI_KI_TIMEOUT_S` (Vorgabe 900). Ein Gegenstück zu `TRI_GARMIN_AUTOSYNC` gibt
es hier **nicht**: Die automatische Planung hat keine eigene Schleife, sondern
wird als zweiter Zweig derselben Weckschleife gerufen — `TRI_GARMIN_AUTOSYNC=0`
legt beides zugleich still. Ausgelöst wird sie inzwischen aber **unabhängig vom
Abgleich**, an ihrer eigenen Uhrzeit.

## Architekturentscheidungen — wo was steht

Warum etwas so ist, wie es ist, steht in `docs/`, nach Themen getrennt. Diese
Dateien werden **nicht** mitgeladen: Lies gezielt die eine, die zum Thema
gehört, statt alle auf Vorrat. Bevor du eine Entscheidung umdrehst, lies erst
den Absatz dazu — vieles darin ist eine teuer bezahlte Lektion und die
Gegenrichtung wurde schon einmal probiert.

Querverweise im Text (`siehe „Planungshorizont"`) meinen einen fett gesetzten
Absatzanfang in einer dieser Dateien; die Titel sind eindeutig und lassen sich
über die Volltextsuche finden.

- [docs/planung.md](docs/planung.md) — Planungshorizont, Überbügeln eines
  laufenden Blocks, Vergangenheitserbe (`Plan.geplant_ab`), Einzelanpassung per
  Freitext, der Tag als zweite Einheit der Anpassung, Disziplinwahl, Fragebogen
  ändern.
  *Bei `ai_export.py`, `plan_import.py`, `plan_aufraeumen.py`,
  `routers/plans.py`, `routers/questionnaire.py`.*
- [docs/ki-und-prompt.md](docs/ki-und-prompt.md) — warum der Prompt die
  Trainingslehre **nicht** vorgibt, erfundene Schwelle gegen gemessene Grenze,
  die drei Auflösungsebenen der Historie, die fünf handwerklichen Vorgaben,
  `RESPONSE_SCHEMA`, Tabellen statt wiederholter Schlüssel, Claude Code als
  Unterprozess, Jobs und Schloss, wöchentliche Planung, Tagesanpassung am
  Abgleich, Tokenablage.
  *Bei `PROMPT_TEMPLATE`, `paketformat.py`, `ki/`, `routers/ki.py`.*
- [docs/ernaehrung.md](docs/ernaehrung.md) — eigener Prompt, gekürzte Historie
  (Positivliste), genau ein Ernährungsplan, `KiJob.ernaehrungsplan_id`, Zutaten
  neben der Beschreibung.
  *Bei `ernaehrung_import.py`, `routers/ernaehrung.py`.*
- [docs/einkaufsliste.md](docs/einkaufsliste.md) — Zutaten von der KI statt aus
  der Prosa, Einheiten beim Import normalisieren, Brings Freitext statt
  Mengenfeld, Aufaddieren gegen Anhängen, der Riegel je Tag, warum synchron
  statt Job, warum das Bring-Passwort gespeichert wird.
  *Bei `einkaufsliste.py`, `bring/`, `routers/bring.py`.*
- [docs/garmin-abgleich.md](docs/garmin-abgleich.md) — Token statt Passwort,
  Bereichsabfragen, Nachlaufzeit, Abgleich im eigenen Thread, Ausführungsdaten,
  Bewertung, Zuordnung von Hand, Zeitzonen, Profilübernahme.
  *Bei `garmin/sync.py`, `mapping.py`, `client.py`, `runner.py`, `matching.py`,
  `profile_sync.py`, `routers/logs.py`.*
- [docs/garmin-workouts.md](docs/garmin-workouts.md) — Bauplan statt Prosa,
  Zerleger als Rückfall, Wiederholungsgruppen, Watt- gegen Pulskorridor,
  Beckenlänge, Übungskennungen und Katalog.
  *Bei `garmin/workouts.py`, `uebungen.py`, `katalog.py`.*
- [docs/garmin-uebertragung.md](docs/garmin-uebertragung.md) — 15 dauerhafte
  Vorlagen, Slotkennung im Namen, Termin statt Vorlage löschen, Kalender lesen,
  Aufräumen des abgelösten Blocks.
  *Bei `garmin/uebertragung.py`, `workout_pool.py`, `kalender.py`,
  `automatik.py`.*
- [docs/frontend.md](docs/frontend.md) — kein UI-Framework, Themenumschaltung,
  Einstellungsseite samt Garmin-Anmeldung, Navigation am Telefon, „Heute" zur
  Laufzeit, Tabellen als Karten, Fortschritt per Abfrage.
  *Bei allem unter `frontend/src/`.*
- [docs/backend.md](docs/backend.md) — passwortlose Anmeldung, FastAPI statt
  Django, toleranter Import, Warnungen statt Ablehnung, Migrationshelfer,
  Home-Assistant-Add-on.
  *Bei `main.py`, `database.py`, `routers/auth.py`, `Dockerfile`,
  `config.yaml`.*
- [docs/grenzen.md](docs/grenzen.md) — was die App nicht kann und nicht prüft.
  *Vor jedem neuen Feature und bei jedem „warum geht das nicht?".*

## Konventionen

- **Alle nutzersichtbaren Texte auf Deutsch**, auch Fehlermeldungen aus der API.
- Code, Bezeichner und Kommentare ebenfalls auf Deutsch gehalten, wo sie
  Fachliches beschreiben.
- Kommentare erklären das *Warum*, nicht das *Was*.
- Frontend-Typen in `src/types.ts` spiegeln die Backend-Schemas. Ändert sich ein
  Pydantic-Schema, muss der Typ mitgezogen werden — es gibt keine Codegenerierung.
- Profil-Updates sind Teil-Updates (`exclude_unset`): Ein Formular, das nur ein
  Feld schickt, darf die anderen nicht löschen.
- Ein Ausgabefeld mit Uhrzeit bekommt `zeit.UtcDatetime`, nie ein blankes
  `datetime` — sonst liest der Browser es als Ortszeit (siehe „Zeitstempel
  verlassen die API mit ihrer Zeitzone").
- Änderungen an Gewicht, Ruhepuls, HRV, VO2max, Maximalpuls oder FTP schreiben
  automatisch einen Eintrag in `ProfileHistory` — über
  `profile_sync.uebernehme_profilwerte()`, gleich ob von Hand oder aus Garmin.
- `SessionLog` hat nur noch ein Schema, `SessionLogOut`: Es gibt keinen
  Anfragekörper mehr, aus dem eine Einheit entstünde. Ein neues Feld gehört
  dorthin *und* in `mapping.aktivitaet_zu_log()` — sonst bleibt die Spalte leer.
  Was nur der Export liest, gehört umgekehrt **nicht** in `SessionLogOut`: Die
  Ausführungsspalten (`hr_zone_seconds`, `garmin_abschnitte`, `garmin_uebungen`)
  und die sechs Messgrößen aus derselben Antwort (`netto_dauer_min`,
  `gap_pace`, `normalisierte_leistung`, `swolf`, `zuege`, `temperatur_c`)
  stehen dort bewusst nicht, sonst zöge jedes neue Feld
  `frontend/src/types.ts` mit. `garmin_compliance` wird weiter befüllt, aber von
  niemandem mehr gelesen — es ist Garmins Bewertung *gegen die Vorgabe* und
  damit ein Planvergleich.
- **Die KI entscheidet, die Pipeline rechnet.** Was sich aus `steps` ableiten
  lässt, wird abgeleitet und überschreibt die Angabe des Modells
  (`plan_import._gerechnete_dauer`) — aber nur, wo es exakt geht. Was zu einer
  Sportart nicht gehört, streicht der Code
  (`schemas.AISessionIn._raeume_fremde_felder`), statt es im Prompt zu
  verbieten. Und die Struktur wird über `--json-schema` erzwungen, nicht
  erbeten. Wer eine neue bedingte Regel in den Prompt schreiben will, prüft
  erst, ob sie nicht in den Code gehört.
- **Der Datenteil des Prompts ist kein JSON mehr**, sondern ein
  Abschnittsdokument aus JSON-Köpfen und CSV-Tabellen
  (`paketformat.paket_als_text()`). `build_payload()` liefert unverändert den
  verschachtelten Dict; ein neues Feld darin wird von selbst zur Spalte. Nur
  eine **verschachtelte** Struktur braucht einen Handgriff in `paketformat.py`
  — sonst steht sie als JSON in einer Zelle. Wer im Prompt oder in einem Test
  auf ein Feld prüft, sucht `feld` als Spaltenname, nicht `"feld":`.
- Ein neues Feld im Antwortformat gehört in `SESSION_SCHEMA` (die Lehrfassung im
  Prompt) **und** ins Datenmodell in `schemas.py`. Das Strukturschema für
  `--json-schema` leitet seine Feldliste daraus ab; `test_antwortschema.py`
  meldet, was auseinanderläuft.
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
  Stress, Gewichtsverlust. **Nur noch für die Ernährung** — der Trainingsprompt
  bekommt die Rohwerte und Garmins gemessene Grenzen und zieht den Schluss
  selbst; siehe „Die vierte Ebene `auffaelligkeiten`".
- **Umsetzungsquote**: Nur Planeinheiten, deren Datum bereits vergangen ist,
  zählen als fällig. Ein Block, der erst morgen startet, hat deshalb
  korrekterweise `rate_pct: null`. Steuert das Dashboard, **nicht** die
  Planung — die KI sah in einer niedrigen Quote den Auftrag, kleiner zu planen.
