# Implementierungsplan — Trainingsanalyse per KI

**Lebendes Dokument.** Grundlage:
[docs/superpowers/specs/2026-09-18-trainingsanalyse-design.md](superpowers/specs/2026-09-18-trainingsanalyse-design.md)
(Design aus Phase 1/2, freigegeben 18.09.2026). Kein Azure-DevOps-Work-Item
(bewusst ohne ID). Dieser Plan wird je Slice fortgeschrieben: Status,
Abweichungen, Auswirkungen.

## Ziel

Der Athlet lässt absolvierte Trainings per Knopfdruck kritisch bewerten: Die
App holt die Original-FIT-Dateien der letzten 1–7 Tage live von Garmin, legt
die Gesundheitsdaten daneben und lässt Claude einen persönlichen Analysebericht
schreiben (Kurzfazit + HTML-Bericht). Anzeige als Widget auf der Übersicht,
Detail im Modal, Historie im Verlauf. Nur manuell, kein Automatik-Zweig.

## Slice-Übersicht

| # | Slice | Ergebnis (end-to-end) | Status |
|---|---|---|---|
| 1 | FIT-Pipeline | Aus einer Beispiel-ZIP entsteht der fertige Aktivitäts-Abschnitt fürs Datenpaket: Download-Wrapper, Entpacken, Parsen, Verdichten, Tabellenrendering | ✅ fertig (18.09.2026) |
| 2 | Analyse-Lauf über die API | `POST /api/ki/analysieren` → Job → Garmin-Abruf → Paket → Claude → gespeicherte `TrainingsAnalyse`; Liste/Detail/Löschen unter `/api/analysen` | ✅ fertig (18.09.2026) |
| 3 | Frontend + Doku | AnalyseKarte auf der Übersicht, Bericht-Modal mit DOMPurify, Rubrik im Verlauf; `docs/analyse.md`, CLAUDE.md, README | ✅ fertig (18.09.2026) |

## Reihenfolge und Begründung

1. **Slice 1 zuerst, weil dort das Risiko liegt.** Die Spec nennt als ersten
   Verifikationspunkt, ob `garmin-fit-sdk` installierbar ist und
   `workout_step_mesgs` liefert (PyPI war aus der Design-Umgebung nicht
   erreichbar; Rückfall `fitdecode`). Scheitert das, ändert sich die
   Architektur — das muss vor allem anderen feststehen. Die Pipeline ist
   außerdem als Bündel reiner Funktionen ohne DB und ohne Claude testbar.
2. **Slice 2 baut auf Slice 1 auf:** Der Runner-Zweig konsumiert die
   Datenstrukturen aus `fitdaten.py`; ohne sie gäbe es nichts zu paketieren.
   Nach Slice 2 ist das Feature per API vollständig nutzbar (curl-fähig).
3. **Slice 3 zuletzt:** Das Frontend braucht die fertigen Endpunkte und
   Schemas. Die Doku (`docs/analyse.md`) hält am Ende fest, was tatsächlich
   gebaut wurde — inklusive der in Slice 1 verifizierten Parser-Wahl.

Bewusst **kein** dünner Durchstich „erst ohne FIT, dann mit": Der
Soll-Ist-Vergleich aus der FIT-Datei ist die Kernanforderung; eine
Zwischenstufe auf Listendaten wäre Wegwerfarbeit und widerspräche der Spec
(„Datenquelle: ORIGINAL-ZIPs, nicht `SessionLog`").

## Teststrategie-Überblick

- **Strikt test-first** (Red → Green → Refactor) für jeden neuen Baustein;
  Tests laufen mit `cd backend && .venv/bin/python -m pytest tests/ -q`.
- **Reine Funktionen bevorzugen:** Parsen, Verdichten und Tabellenrendering
  arbeiten auf Bytes bzw. Dicts — testbar ohne Netz, DB oder Mocks.
- **Echte Fixtures statt synthetischer FIT-Dateien:** Unit-Tests laufen gegen
  vom Nutzer exportierte Beispiel-ZIPs (`backend/tests/fixtures/fit/`);
  `garmin-fit-sdk` kann nur dekodieren, FIT-Dateien selbst zu bauen wäre ein
  eigenes Projekt. Sport-spezifische Parserpfade (Schwimmen, Kraft,
  Multisport) werden nur mit passendem Fixture getestet — was fehlt, wird im
  Plan vermerkt statt ungetestet behauptet.
- **Gefälschte Ränder:** Garmin-API über den bestehenden Fake in
  `tests/fakes.py` (wird um `get_activities_by_date` /
  `download_activity` erweitert); Claude über gemocktes `rufe_claude` (Muster
  `test_ki.py`); DB wie im Bestand über die Test-Session aus `conftest.py`.
- **Frontend:** `npm run build` (Typecheck) — wie im Bestand, keine
  JS-Testinfrastruktur vorhanden.

## Nutzungsdokumentation (README)

Es existiert ein `README.md` im Wurzelverzeichnis (Feature-Überblick +
C4-Architektur). **Entschieden (18.09.2026): das bestehende README wird
ergänzt** — eine Zeile in der Feature-Tabelle, ggf. ein Pfeil im
C4-Kontextdiagramm, klein gehalten; umgesetzt in Slice 3. Die von der Spec
ohnehin geforderte `docs/analyse.md` + der CLAUDE.md-Eintrag sind ebenfalls
fester Bestandteil von Slice 3.

---

## Slice 1: FIT-Pipeline (`garmin/fitdaten.py`)

- **Status:** ✅ fertig (18.09.2026) — 22 Tests in `test_fitdaten.py`, Suite 755 grün
- **Detailplan:** siehe unten
- **Ergebnisse der Voraussetzungen:**
  - **Fixture:** nicht von Hand exportiert, sondern **live von Garmin geholt**
    (Token aus der App-Datenbank, `download_activity(…ORIGINAL)`): Aktivität
    24040558837 „Einstufungslauf" vom 19.08.2026 — Lauf aus strukturiertem
    Workout, 3 `workout_step_mesgs`, 3 Runden, 540 Records. Abgelegt als
    `backend/tests/fixtures/fit/lauf_workout.zip`.
  - **Parser-Verifikation (Spec-Checkpoint 1):** `garmin-fit-sdk` 21.214.0
    installiert und gegen das Fixture geprüft — liefert `workout_step_mesgs`,
    `session_mesgs`, `lap_mesgs`, `record_mesgs` wie erwartet. Der Rückfall
    `fitdecode` wurde **nicht** gebraucht. Eingetragen in
    `backend/requirements.txt`.
  - **Rauch-Test (Spec-Checkpoint 2):** entgegen der Annahme in der Spec doch
    aus der Sandbox möglich (Garmin-Domain in der Netzwerk-Policy
    freigeschaltet): Aktivitätenliste, ORIGINAL-Download, Entpacken und Parsen
    liefen gegen das echte Konto durch.
- **Abweichungen:** Die Notizen der Workout-Schritte kommen vom SDK als Liste
  mit Speicherresten dahinter — `fitdaten._notiz()` nimmt nur den ersten
  Eintrag. Der Zielkorridor (Puls/Watt) ist implementiert, aber nur sein
  Leerverhalten getestet: Das Fixture hat `target_type=open` ohne Korridor
  (in `docs/analyse.md` unter „Grenzen" vermerkt).
- **Nachtrag (19.09.2026):** Der Kraft-Parserpfad ist inzwischen doch an
  echten Daten getestet — beim abschließenden End-to-End-Rauchtest kam eine
  Krafteinheit mit 6 `set_mesgs` herein; ihre ZIP liegt als zweites Fixture
  (`kraft.zip`), offen bleiben Schwimmen und Multisport. Derselbe Rauchtest
  bestätigte die ganze Kette Abruf → Parsen → Paket → Prompt am echten Konto
  (ohne Claude-Aufruf; Prompt bei einer Aktivität ≈ 1.900 Token).
- **Auswirkungen auf andere Slices:** Fällt `garmin-fit-sdk` durch und
  `fitdecode` übernimmt, ändert sich nur das Innere von `parse_fit`; die
  öffentliche Struktur (`AktivitaetsDaten`) bleibt, Slice 2/3 sind nicht
  betroffen. Da nur das Lauf-Fixture vorliegt, gehen die ungetesteten
  Parserpfade (Schwimmen, Kraft, Multisport) als offene Punkte in die Doku
  (`docs/analyse.md`, „Grenzen") — Slice 2/3 bleiben davon unberührt, weil
  Paketbau und Anzeige sportartneutral sind.

### Voraussetzungen (vor Implementierungsbeginn)

1. **Fixtures vom Nutzer — entschieden (18.09.2026):** Verfügbar ist eine
   ORIGINAL-ZIP eines Laufs, der aus einem **strukturierten Workout**
   gestartet wurde (damit ist `workout_step_mesgs` prüfbar). Schwimmen,
   Kraft und Multisport stehen **nicht** als Fixture zur Verfügung: Diese
   Parserpfade werden defensiv mitgeschrieben (fehlende Nachrichtentypen →
   leere Listen), aber nur ihr Leerverhalten ist getestet — als bekannte
   Lücke in `docs/analyse.md` („Grenzen") zu vermerken; Fixtures können
   später nachgereicht werden. Exportweg in Garmin Connect: Aktivität →
   Zahnrad → „Datei exportieren". Ablage:
   `backend/tests/fixtures/fit/lauf_workout.zip` — **vor Phase 4 vom Nutzer
   abzulegen.**
2. **Parser-Verifikation (Spec-Checkpoint 1):** `garmin-fit-sdk` in die venv
   installieren und gegen das Lauf-Fixture prüfen, dass `workout_step_mesgs`,
   `session_mesgs`, `lap_mesgs`, `record_mesgs` geliefert werden. Ergebnis
   hier im Plan festhalten. Rückfall: `fitdecode`. Das gewählte Paket kommt in
   `backend/requirements.txt` (Laufzeit-Abhängigkeit, gehört ins Docker-Abbild)
   mit Begründungskommentar im Stil der Datei.

### Bausteine und Schritte (test-first, in dieser Reihenfolge)

Neue Testdatei `backend/tests/test_fitdaten.py`; neues Modul
`backend/app/garmin/fitdaten.py`.

1. **`entpacke_fit(zip_bytes) -> bytes`** — `zipfile` aus der
   Standardbibliothek.
   - RED: In-Memory-ZIP mit einer `.fit`-Datei → Bytes zurück; ZIP ohne
     `.fit`-Eintrag → definierter Fehler (`FitDatenFehler`).
   - GREEN: erste `.fit`-Datei aus dem Archiv lesen.
2. **`verdichte_stuetzpunkte(records, max_punkte=150) -> list[dict]`** —
   reine Mathematik, synthetische Eingaben.
   - RED-Fälle: >150 Records → höchstens ~150 Punkte; gleitendes Mittel über
     Puls/Pace/Watt/Kadenz/Höhe stimmt für ein Handbeispiel; ≤150 Records →
     unverändert; fehlende Kanäle (None) werden toleriert und nicht zu 0
     gemittelt.
3. **`parse_fit(fit_bytes) -> list[AktivitaetsDaten]`** — Liste, weil eine
   Multisport-FIT mehrere Sessions trägt. Dataclass mit: Kopf (Sportart,
   Start als Ortszeit, Dauer, Distanz, Kalorien, Trainingslast, aerober/
   anaerober TE), `soll_schritte` (aus `workout_step_mesgs`: Name, Dauer-/
   Distanzziel, Puls-/Watt-Korridor), `runden` (aus `lap_mesgs`: Zeit,
   Distanz, Ø/Max-Puls, Ø-Pace bzw. Ø-Watt, Kadenz), `stuetzpunkte`
   (verdichtete `record_mesgs`), `bahnen` (`length_mesgs`), `saetze`
   (`set_mesgs`), Pausen-Ereignisse (`event_mesgs`).
   - RED gegen das Lauf-Fixture: Kopffelder, Rundenzahl, Soll-Schritte.
     Schwimmen/Kraft/Multisport ohne Fixture: nur Leerverhalten getestet
     (FIT ohne `length_mesgs`/`set_mesgs` → leere Listen, eine Session →
     genau ein Element).
   - Zugriff auf die dekodierten Nachrichten defensiv (`.get`, fehlende
     Nachrichtentypen → leere Listen) — dieselbe Vorsicht wie `mapping.hole()`
     beim Connect-JSON, denn auch FIT-Felder sind optional.
4. **Paketabschnitt:** `fitdaten`-Block als Dict je Aktivität +
   Rendering als CSV-Tabellen im Abschnittsformat. Renderer in
   `paketformat.py` ergänzen (eigener Abschnittstyp neben `_historie`,
   `_fitness` …), damit `paket_als_text()`-Konventionen (Leerspalten
   streichen, Konstanten abtrennen) auch hier gelten.
   - RED: Abschnittstext enthält Kopf-JSON + Tabellen `soll_schritte`,
     `runden`, `stuetzpunkte` mit erwarteten Spaltennamen; eine Aktivität mit
     `fit_fehlt=True` erscheint mit Vermerk „nur Listendaten" statt Tabellen.
5. **`hole_aktivitaeten(api, von: date, bis: date) -> list[AktivitaetsDaten]`**
   — Orchestrierung: `get_activities_by_date`, je Treffer
   `download_activity(id, dl_fmt=ORIGINAL)` → entpacken → parsen; Fehler
   beim Download/Entpacken einer einzelnen Aktivität → Eintrag mit
   `fit_fehlt=True` samt Listendaten (Sportart, Name, Dauer aus der
   Aktivitätenliste), Lauf geht weiter.
   - RED: Happy Path (Fake liefert Fixture-Bytes); leere Liste → `[]`;
     Download wirft → übersprungen + vermerkt, übrige Aktivitäten kommen durch.
6. **Regression:** gesamte Backend-Suite grün; `git`-Stand sauber für Phase 8.

### Testbarkeitsarchitektur (Pflichtangaben)

1. **Was getestet wird:** Entpacken (inkl. Fehlerfall), Verdichtungs-Mathematik,
   Feldextraktion je FIT-Nachrichtentyp gegen echte Fixtures,
   Abschnittsrendering (Spalten, Vermerk bei fehlender FIT), Orchestrierung
   mit Überspringen defekter Aktivitäten.
2. **Wie Testbarkeit hergestellt wird:** Parser, Verdichter und Renderer sind
   reine Funktionen über Bytes/Dicts — kein Netz, keine DB, kein Mock. Der
   Garmin-Zugriff ist auf genau zwei Client-Methoden isoliert
   (`get_activities_by_date`, `download_activity`) und wird per
   Dependency-Injection getestet: `hole_aktivitaeten` nimmt den Client als
   Parameter, wie es `sync.py` vormacht.
3. **Extern zu mocken/faken:** nur die Garmin-API — Erweiterung des
   bestehenden Fakes in `tests/fakes.py` um die zwei Methoden. Claude und DB
   kommen in Slice 1 nicht vor.

### Manueller Verifikationsschritt (Spec-Checkpoint 2, Nutzerumgebung)

**Erledigt (18.09.2026), anders als geplant direkt aus der Sandbox:** Nach
Freischaltung der Garmin-Domain in der Netzwerk-Policy lief der Rauch-Test
gegen das echte Konto — Token aus der Datenbank, `get_activities_by_date`
(27 Aktivitäten über 60 Tage), `download_activity(…ORIGINAL)`, entpacken,
parsen. Nebenprodukt ist das Fixture selbst (Aktivität 24040558837).

---

## Slice 2: Analyse-Lauf über die API

- **Status:** ✅ fertig (18.09.2026) — 12 Tests in `test_analyse.py`, Suite 767 grün
- **Umsetzung:** wie im Umriss unten, dazu drei Festlegungen aus der
  Implementierung:
  - Der Garmin-Client kommt im Runner über `verbindung.garmin_sitzung()` —
    dieselbe Stelle wie Kalender und Einzelaufrufe: Kontozustand prüfen, Token
    entschlüsseln, erneuertes Token zurückschreiben, Fehlschlag am Konto
    vermerken.
  - Ein `GarminFehler` im Lauf lässt `KiSettings.status` unberührt (neuer
    Zweig in `_notiere_fehler`): Am Claude-Zugang liegt es nicht, und die
    Warnung stünde sonst an jedem KI-Knopf.
  - Kein Reparaturlauf für die Analyse: Bei zwei Feldern gibt es nichts
    auszubessern, das ein zweiter Lauf besser wüsste — der Rückfall liest das
    Text-JSON tolerant (`runner._analyse_daten`), Unbrauchbares wird
    `KiAntwortUnbrauchbar`.
- **Umriss (aus dem Design, zur Orientierung):** Tabelle `TrainingsAnalyse` +
  `KiJob.analyse_id` über den Migrationshelfer in `database.py`; Job-`kind`
  `analyse`; `rufe_claude` bekommt optionalen Parameter `systemprompt`
  (Vorgabe: bestehender Planer-Text); eigener `ANALYSE_PROMPT` mit
  Formatstandards + Zweifelder-`--json-schema` (`kurzfazit`, `bericht_html`);
  Runner-Zweig `_analyse_lauf` (Muster `_ernaehrung_lauf`, Leerer-Zeitraum-
  Abbruch **vor** Claude); `POST /api/ki/analysieren` (`KiAnalysierenIn`,
  tage 1–7, 400 ohne Garmin-Konto); neuer Router `routers/analysen.py`
  (Liste ohne `bericht_html`, Detail, Löschen, Fremdzugriff → 404); Schemas
  `AnalyseOut`/`AnalyseDetailOut` mit `zeit.UtcDatetime`.
- **Abweichungen:** —
- **Auswirkungen auf andere Slices:** —

## Slice 3: Frontend + Doku

- **Status:** ✅ fertig (18.09.2026) — `npm run build` (Typecheck + Build) grün
- **Umsetzung:** wie im Umriss unten, dazu drei Notizen:
  - **DOMPurify-Konfiguration:** `USE_PROFILES` html+svg (nimmt Script und
    Event-Handler heraus), zusätzlich `FORBID_TAGS` für alle Wege zu externen
    Ressourcen (a, img, audio, video, link, style, form, input, use) und
    `ALLOWED_URI_REGEXP: /^#/` — nur Anker im Dokument bleiben. Das
    `style`-Attribut bleibt erlaubt (Farben über `var(--…)`).
  - **AnalyseKarte nur mit verbundenem Garmin-Konto** (die Übersicht kennt den
    Kontostand ohnehin) — ohne Konto liefe jeder Knopf in dieselbe 400.
  - **README:** Feature-Zeile und Doku-Tabellenzeile ergänzt; auf einen neuen
    Pfeil im C4-Diagramm wurde verzichtet — die Beziehung „Tri-Coach ↔ Garmin
    in beide Richtungen" steht dort schon, die Analyse fügt keinen neuen
    Nachbarn hinzu.
- **Abweichung (Umgebung, nicht Inhalt):** `dompurify` wurde über
  `npm install --package-lock-only` nur in `package.json`/`package-lock.json`
  aufgenommen; das `node_modules` im Repo stammt vom macOS-Host und wurde aus
  der Linux-Sandbox bewusst nicht angefasst (Typecheck + Build liefen in einer
  Kopie). **Auf dem Host einmal `npm install` ausführen**, bevor `npm run
  dev`/`build` läuft.
- **Umriss:** `AnalyseKarte.tsx` (Muster `TagesformKarte`, Zahlenfeld 1–7 mit
  klärendem Label, Jobverfolgung über `pollJob`), `AnalyseBericht.tsx`
  (`ui.Modal` + DOMPurify, erlaubte Tags/Attribute laut Spec), Rubrik
  „Analysen" in `History.tsx`, `types.ts` + `api/client.ts`
  (`startAnalyse`, `listAnalysen`, `getAnalyse`, `deleteAnalyse`), neue
  Abhängigkeit `dompurify`. Doku: `docs/analyse.md`, CLAUDE.md-Eintrag
  (Kopfabsatz + Übersichtsliste), README gemäß Nutzerentscheidung.
- **Abweichungen:** —
- **Auswirkungen auf andere Slices:** —
