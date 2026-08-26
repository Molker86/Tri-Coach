# Backend, Import und Betrieb

Teil der Kontextdokumentation von Tri-Coach. Überblick, Setup und Konventionen:
[CLAUDE.md](../CLAUDE.md).

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

**FastAPI statt Django.** Der Kern der App ist Schema-Arbeit: Ein- und Ausgabe
gegenüber der KI müssen streng validiert werden. Pydantic macht das direkt zum
Typsystem; Djangos Stärken (Admin, ORM-Migrationen, Templates) hätten hier
wenig beigetragen und viel Rahmenwerk gekostet.

**Strings statt DB-Enums** in `models.py`. Validierung passiert in den
Pydantic-Schemas. So kostet eine neue Sportart oder ein neuer Einheitentyp keine
Migration — relevant, weil die KI die Werte liefert.

**Toleranter Import** (`plan_import.py`). KI-Antworten kommen in der Praxis mit
Codefences, Begleittext oder als flaches Objekt ohne `plan`-Wurzel. Der Parser
sammelt **alle** vollständigen JSON-Objekte des Textes (klammerzählend, Strings
werden dabei übersprungen) und normalisiert Sprachvarianten
(`"Laufen"`/`"run"`/`"Rad"`). Abgeschnittene Antworten bekommen eine eigene
Fehlermeldung, weil das der häufigste Fall ist. `_flatten_weeks()` zieht
Antworten, die trotzdem eine `weeks`-Ebene mitbringen, auf die flache Tagesliste
herunter — Modelle greifen gern auf diese vertraute Struktur zurück.

**Welches Objekt der Plan ist, entscheidet die Form — nicht die Reihenfolge**
(`_json_objekte`, `_plan_darin`). Gelesen wurde einmal die *erste* Codefence und
darin das *erste* Objekt, und was dabei herauskam, wurde ungeprüft als Plan
gedeutet: Was keinen `plan`-Schlüssel trug, bekam einfach einen umgehängt.
Schrieb die KI vorweg eine kurze Notiz als JSON — oder hängte sie eine hinterher,
oder benannte die Hülle `trainingsplan` statt `plan` —, endete das in
„plan → start_date: Field required / plan → days: Field required" über einem
Text, in dem der Block vollständig dastand. Gesucht wird deshalb nach der Form:
Ein Objekt mit nicht leerer `days`- oder `weeks`-Liste ist der Plan, egal unter
welchem Namen und an welcher Stelle (zwei Hüllen tief). Die Zäune der Codefences
tragen keine Klammern, also braucht es sie beim Suchen gar nicht mehr — das
Herausschneiden ist ersatzlos entfallen.

**Ein fehlendes `start_date` wird abgelesen, nicht bemängelt**
(`AIPlanBody._startdatum_aus_den_tagen`). Das Feld ist redundant: Ein Block
beginnt an dem Tag, mit dem seine Tagesliste anfängt. Daran einen vollständigen
Block scheitern zu lassen wäre dieselbe teuerste denkbare Antwort wie beim
verworfenen Zielpuls — über den KI-Knopf ist die Antwort danach weg, der Lauf
also verloren. Gemeldet wird es trotzdem (`startdatum_abgeleitet`): Fehlen
zugleich die ersten Tage, verdeckt der abgeleitete Beginn die Lücke, und nur
noch die Zahl der Tage fällt auf. Ohne brauchbare Tagesliste bleibt es beim
Pflichtfeld — dann fehlt nicht ein ablesbarer Wert, sondern der Block.

**Und wer das Falsche einfügt, liest das statt einer Feldliste**
(`_falsche_antwort`, `_ohne_tagesliste`). Zwei Verwechslungen sind naheliegend
und ergaben bis dahin *dieselbe* Meldung wie eine misslungene Antwort: das
Datenpaket, das an die KI geht (erkennbar an `athlet`/`trainingswunsch`), und
die Antwort auf eine Einzelanpassung, die an der Einheit im Trainingsplan
übernommen wird und nicht hier (`einheit`/`session`, oder ein nacktes
Einheitenobjekt). „Field required" beschreibt, was fehlt — der Athlet muss
wissen, was dasteht, denn der nächste Handgriff ist in beiden Fällen ein
anderer. Bleibt die Form unbekannt, nennt die Meldung wenigstens die Felder der
obersten Ebene. Steht ein `plan` da, der bloß unvollständig ist, bekommt
Pydantic weiter das Wort: Dort ist die Feldliste die genauere Auskunft.

**Und wo das JSON schon am Zeichen scheitert, steht die Fundstelle im
Wortlaut** (`_fehlerstelle`). „Zeile 1, Spalte 2318: Expecting ',' delimiter"
war für den Athleten unbrauchbar: Eine KI-Antwort steht oft in einer einzigen
Zeile, und 2318 Zeichen zählt niemand ab. Die Meldung hängt deshalb rund 45
Zeichen um die Fundstelle an — meist sieht man der Stelle die Ursache sofort
an, denn genau diese Meldung heißt fast immer, dass ein Anführungszeichen
mitten in einem Aufbautext steht, das die KI nicht maskiert hat
(`"4x400 m zügig ("Renntempo")"`). Repariert wird nichts: Ein automatisch
maskiertes Zeichen änderte den Text, den der Athlet auf der Uhr liest, und die
Antwort liegt ihm ja vor.

Der dritte Fall ist der zurückkopierte **Prompt**, und er ist der Grund, warum
diese Prüfung nicht vor der Suche nach dem Plan läuft: Am Ende des Prompts steht
das Antwortformat als Beispiel, mit einer Tagesliste darin — nach der Form ist
das ein Planobjekt, und der Athlet läse „days → 0 → date: YYYY-MM-DD ist kein
Datum". Gefragt wird deshalb erst, wenn der Kandidat durch die Validierung
fällt: Ein gültiger Block soll nie an einem Objekt scheitern, das zufällig
danebensteht.

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

**Schemaänderungen laufen jetzt über einen Migrationshelfer** (`database.py`,
`_NACHGEREICHTE_SPALTEN`). `create_all()` legt fehlende *Tabellen* an, sieht aber
neue *Spalten* nicht. Bisher war „Datenbank löschen" der bewusste Weg; mit
Garmin wird er teuer, weil ein neuer Rückblick Minuten gegen ein fremdes System
mit Anfragegrenze kostet und Passwort samt Bestätigungscode erneut verlangt. Ein
paar Zeilen `ALTER TABLE ADD COLUMN`, idempotent bei jedem Start, sind billiger
als Alembic. Neue Spalten gehören dort eingetragen, sonst brechen bestehende
Datenbanken.

**Und ein dritter Fall: `_ZURUECKZUSETZENDE_ALTWERTE`.** Manchmal genügt es
nicht, eine Spalte zu ergänzen — manchmal steht in einer alten schon ein Wert,
den erst die neue Fassung wieder bedeutsam macht. Der Anlass war
`ki_settings.auto_plan_enabled`: Die Spalte stammt aus einer automatischen
Planung, die später entfernt wurde und deren Zustimmung von damals in echten
Datenbanken stehen blieb. Wieder gelesen spränge die Planung bei genau den
Nutzern von selbst an, die sie vor Monaten einmal eingeschaltet hatten — ein
Opus-Lauf am Tag aus ihrem Abo-Kontingent, den niemand bestellt hat.

Ausgelöst wird über die **neu ergänzte Spalte**: `_ergaenze_spalten()` gibt
zurück, was dieser Start tatsächlich angelegt hat, und `token_encrypted`
kennzeichnet genau die Datenbanken von vor der Änderung. Der Schritt läuft
damit exakt einmal — bei jedem Start zu greifen hieße, die Einstellung des
Nutzers nach jedem Neustart wieder umzulegen.

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
