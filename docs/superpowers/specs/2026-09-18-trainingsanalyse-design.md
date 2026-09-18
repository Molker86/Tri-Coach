# Trainingsanalyse per KI — Design

Stand: 18.09.2026, im Brainstorming freigegeben. Kein Azure-DevOps-Work-Item
(bewusst ohne ID). Teil der Kontextdokumentation wird nach der Umsetzung eine
eigene `docs/analyse.md`; diese Spec hält den beschlossenen Bauplan fest.

## Zweck

Der Athlet lässt absolvierte Trainings **kritisch bewerten**: Ein Knopfdruck
holt die Original-Aufzeichnungen (ZIP/FIT) der Aktivitäten der letzten 1–7 Tage
direkt von Garmin, legt die Gesundheitsdaten der App daneben und lässt die KI
einen persönlichen, direkten Analysebericht schreiben — was gut war, was nicht,
und was daraus folgt. Nichts läuft automatisch; es gibt keinen Automatik-Zweig.

## Verbindliche Anforderungen

- **Nur manuell.** Ein Lauf entsteht ausschließlich per Knopfdruck. Kein
  Cron-Zweig, kein Schalter in den Einstellungen.
- **Zeitraum:** Eingabe „Tage" 1–7, Vorgabe 1. N Tage heißt: heute bis
  heute−(N−1), auf das Ortsdatum des Nutzers bezogen (`zeit.ortsdatum`).
  Das Label am Eingabefeld erklärt die Interpretation
  („1 = nur heute, 7 = heute und die 6 Tage davor").
- **Datenquelle Aktivitäten:** die ORIGINAL-ZIPs je Aktivität (FIT-Datei),
  **live von Garmin geholt** — nicht aus `SessionLog`. Der Soll-Ist-Vergleich
  kommt aus derselben FIT-Datei: Bei einem aus einem strukturierten Workout
  gestarteten Training stehen die geplanten Schritte mit darin und werden
  **nicht separat angefragt**.
- **Alle Aktivitätstypen zählen:** Was Garmin im Zeitraum als Aktivität
  führt, wird ausgewertet — ohne Filter auf Sportarten.
- **Datenquelle Gesundheit:** `WellnessDay` aus der Datenbank (Schlaf, HRV,
  Ruhepuls, Erholung, Trainingsstatus), samt Datenstand wie im Planungsexport.
- **KI-Einstellungen:** Modell, Denktiefe und Claude-Zugang kommen aus
  `KiSettings` (Einstellungsseite) — derselbe Weg wie bei allen KI-Läufen.
- **Ergebnisform:** freier, kompakter Text mit Formatstandards im Prompt.
  Erlaubt ist, was der Browser nativ darstellt: HTML-Struktur und Inline-SVG
  für Diagramme. Verboten: Script, Event-Handler, iframe, externe Ressourcen.
  Der Bericht soll sich persönlich und zielgerichtet anfühlen, Kritik klar
  benennen und aus den Daten begründen.
- **Anzeige:** Widget auf der Übersicht (Kurzfazit + Absprung), Detail als
  Modal nach Bestandsmuster, Historie als Rubrik im Verlauf. **Keine neue
  Navigation, keine neue Route.**
- **Historie:** Jede Auswertung bleibt gespeichert und ist im Verlauf abrufbar
  und löschbar.

## Entscheidungen und verworfene Alternativen

- **Backend parst FIT (gewählt)** statt:
  - *TCX statt ZIP*: kein Binärparser nötig, aber TCX trägt keine
    Workout-Schritte — der geforderte Soll-Ist-Vergleich aus derselben Datei
    fiele weg. Verworfen.
  - *Claude Code liest die Dateien selbst*: kehrte vier bewusste
    Schutzvorkehrungen in `ki/client.py` um (`--tools ""`, `--safe-mode`,
    leeres Arbeitsverzeichnis, ersetzter Systemprompt), machte Laufzeit und
    Kontingentverbrauch unvorhersehbar. Verworfen.
- **Antwortgerüst minimal erzwungen:** `--json-schema` verlangt genau zwei
  Felder — `kurzfazit` (2–3 Sätze Klartext fürs Widget) und `bericht_html`
  (der freie Bericht). Ein Vollschema je Aktivität nähme dem Bericht die
  gewünschte Dynamik; purer Text ohne Hülle machte das Kurzfazit zum Ratespiel.
- **Parser-Bibliothek: `garmin-fit-sdk`** (Garmins offizielles Python-Paket,
  aus dem offiziellen FIT-Profil generiert). Rückfall `fitdecode`, falls die
  Installation überrascht — PyPI war aus der Design-Umgebung nicht erreichbar,
  die Wahl wird beim ersten Implementierungsschritt verifiziert.
- **Live-Abruf statt `SessionLog`:** Wer mittags trainiert und nachmittags
  auswertet, hätte über die Datenbank eine Lücke, weil der tägliche Abgleich
  längst durch ist. Die Aktivitätenliste kommt deshalb von
  `get_activities_by_date`, die Dateien von `download_activity(...ORIGINAL)`.
  Beides am Quellcode von `garminconnect` 0.3.10 verifiziert: ORIGINAL lädt
  `/download-service/files/activity/{id}` — derselbe Endpunkt wie „Datei
  exportieren" in Garmin Connect — und liefert die ZIP-Bytes.
- **DOMPurify statt Eigenbau-Sanitizer:** Ein selbstgeschriebener
  HTML-Sanitizer ist ein bekanntes Sicherheits-Antimuster. DOMPurify ist klein
  (~22 kB) und wird die erste Frontend-Abhängigkeit neben React — bewusst in
  Kauf genommen.
- **Leerer Zeitraum bricht vor Claude ab:** Findet die Aktivitätenliste
  nichts, endet der Job mit klarer Meldung, ohne Kontingent zu verbrauchen.
- **Modal statt Route:** Detailansichten stellt der Bestand als `ui.Modal`
  dar (`SessionDetail`); der Bericht folgt dem Muster.

## Architektur

### Backend

**Neues Modul `app/garmin/fitdaten.py`** — Download, Entpacken, Parsen,
Verdichten. Je Aktivität entsteht eine Struktur mit:

- Kopf: Sportart, Start (Ortszeit), Dauer, Distanz, Kalorien, Trainingslast,
  aerober/anaerober TE;
- geplante Workout-Schritte (Soll), falls vorhanden: Name, Dauer-/Distanzziel,
  Puls-/Watt-Korridor;
- Runden/Abschnitte (Ist): Zeit, Distanz, Ø/Max-Puls, Ø-Pace bzw. Ø-Watt,
  Kadenz;
- Sekundendaten, verdichtet auf höchstens ~150 Stützpunkte je Aktivität
  (gleitendes Mittel über Puls, Pace/Geschwindigkeit, Watt, Kadenz, Höhe);
- Sportart-Spezifisches: Schwimmen Bahnen/Züge/SWOLF (`length_mesgs`), Kraft
  Übungen/Sätze/Wiederholungen (`set_mesgs`), Pausen-Ereignisse;
- Multisport: Eine Triathlon-Aktivität trägt mehrere Sessions in einer
  FIT-Datei; der Parser weist sie einzeln aus.

Eine Aktivität ohne ladbare FIT (in Connect von Hand angelegt) wird
übersprungen und im Paket als solche vermerkt — die KI weiß, dass sie dort nur
die Listendaten hat. ZIP-Entpacken über `zipfile` (Standardbibliothek).

**Paketbau**: neuer Baustein (bei `ai_export`/`paketformat`), der den
Athleten-Block (`_athlete_block`) und den Fitnessdaten-Block
(`_fitness_block`, Rohwerte, ohne `auffaelligkeiten` — wie beim
Trainingsprompt) wiederverwendet und je Aktivität Kopf, Soll-Schritte, Runden
und Sekundendaten als CSV-Tabellen im Abschnittsformat anfügt
(`paketformat.paket_als_text`-Stil).

**KI-Aufruf**: `rufe_claude` bekommt einen optionalen Parameter `systemprompt`
(Vorgabe: bestehender Planer-Text, kein bestehender Aufrufer ändert sich).
Für die Analyse gilt ein eigener Systemprompt („kritischer, erfahrener
Trainingsanalyst") und ein eigener `ANALYSE_PROMPT` mit den Formatstandards:

- Sprache Deutsch, Anrede persönlich und direkt; Kritik klar benannt und aus
  den Daten begründet; „gut" nur, wo es die Daten tragen;
- empfohlene Gliederung (kein starres Schema): Einordnung je Aktivität —
  Ausführung gegen Soll, Pacing, Zonen —, dann ein Gesamtblick über den
  Zeitraum (Belastung gegen Erholung); Detailgrad der Datenlage angemessen;
- erlaubtes HTML: Überschriften (h2–h4), Absätze, Listen, Tabellen,
  strong/em, figure, Inline-SVG für Diagramme (z. B. Pulskurve,
  Zonenverteilung); Farben über die CSS-Variablen der App (`var(--…)`), damit
  Hell/Dunkel stimmen;
- ausdrücklich verboten: script, Event-Handler, iframe/object, externe
  Ressourcen (Bilder, Fonts, Links nach außen).

**Job und Ablage**:

- `KiJob.kind` erhält den Wert `analyse`; neue Spalte `analyse_id` (analog
  `ernaehrungsplan_id`), damit das Frontend nach dem Lauf zum Ergebnis kommt.
- Neue Tabelle `TrainingsAnalyse`: `id`, `user_id`, `created_at`
  (`zeit.UtcDatetime` in der Ausgabe), `zeitraum_von`, `zeitraum_bis`,
  `aktivitaeten_anzahl`, `kurzfazit` (Text), `bericht_html` (Text),
  `model_used`. Anlage über den bestehenden Migrationshelfer in
  `database.py`.
- Neuer Runner-Zweig `_analyse_lauf` mit Fortschrittsmeldungen; das
  Nutzer-Schloss des `KiRunner` (ein Lauf je Konto) gilt unverändert.

**Ablauf `_analyse_lauf`**:

1. Garmin-Client aus dem gespeicherten Token (bestehender Weg des Abgleichs).
2. `get_activities_by_date(von, heute)`; leere Liste → Job endet mit
   Meldung „Im Zeitraum liegen keine Aktivitäten", **ohne** Claude-Aufruf.
3. Je Aktivität ORIGINAL-ZIP laden, FIT entpacken, parsen, verdichten.
4. Datenpaket bauen (Athlet + Fitnessdaten + Aktivitäten).
5. Claude mit Nutzer-Einstellungen und `--json-schema` rufen.
6. `TrainingsAnalyse` speichern, `analyse_id` an den Job, fertig melden.

### API

- `POST /api/ki/analysieren` mit `{tage: 1–7}` → 202, `KiJobOut`. Liegt im
  ki-Router (Muster `plane_ernaehrung`); bestehende Prüfungen
  (`_pruefe_startbar`, laufender Job) greifen unverändert. Zusätzlich: ohne
  verbundenes Garmin-Konto → 400 mit deutscher Meldung.
- Neuer Router `routers/analysen.py`, Präfix `/api/analysen`:
  - `GET /` → Liste kompakt (id, created_at, zeitraum_von, zeitraum_bis,
    aktivitaeten_anzahl, kurzfazit, model_used) — ohne `bericht_html`.
  - `GET /{id}` → voll, mit `bericht_html`.
  - `DELETE /{id}` → 204.
- Neue Schemas in `schemas.py`: `KiAnalysierenIn` (tage, `ge=1 le=7`),
  `AnalyseOut`, `AnalyseDetailOut`. Zeitstempel als `zeit.UtcDatetime`.

### Frontend

- **`components/AnalyseKarte.tsx`** (Übersicht, Muster `TagesformKarte`):
  Zahlenfeld „Tage" (1–7, Vorgabe 1, klärendes Label), Knopf „Auswerten",
  Job-Fortschritt über die bestehende Abfrageschleife, danach Kurzfazit mit
  Datum/Zeitraum der jüngsten Analyse und „Bericht ansehen".
- **`components/AnalyseBericht.tsx`**: Modal (`ui.Modal`) mit dem bereinigten
  Bericht. Bereinigung mit **DOMPurify**: erlaubt Struktur-HTML + Inline-SVG
  + `style`-Attribut; entfernt Script, Event-Handler, iframe/object und
  externe URLs. Gerendert in einen eigenen Container mit begrenzenden
  CSS-Regeln (Bilderbreite, Tabellen-Scroll).
- **`pages/History.tsx`**: neue Rubrik „Analysen" — Liste (Datum, Zeitraum,
  Kurzfazit), Klick öffnet dasselbe Modal, Löschen je Eintrag.
- **`types.ts`** spiegelt die neuen Schemas; **`api/client.ts`** bekommt
  `startAnalyse`, `listAnalysen`, `getAnalyse`, `deleteAnalyse`.
- Neue Abhängigkeit: `dompurify` (bringt eigene Typen mit).

## Fehlerbehandlung

| Fall | Verhalten |
| --- | --- |
| Kein Garmin-Konto verbunden | 400 beim `POST`, deutsche Meldung, kein Job |
| `tage` außerhalb 1–7 | Validierungsfehler (Pydantic) |
| Kein KI-Zugang / Kontingent / laufender Job | bestehende Prüfungen und Meldungen des ki-Routers |
| Keine Aktivitäten im Zeitraum | Job endet mit klarer Meldung **vor** dem Claude-Aufruf |
| Garmin-Fehler mitten im Lauf | Job scheitert mit übersetzter Meldung (bestehende Fehlerübersetzung) |
| Einzelne Aktivität ohne FIT | überspringen, im Paket vermerken, Lauf geht weiter |
| Claude-Fehler (Token, Kontingent, Timeout, Ablehnung) | bestehende Fehlertaxonomie aus `ki/errors.py` |
| Bösartiges HTML in der Antwort | DOMPurify entfernt es beim Rendern |

## Tests

- `fitdaten.py`: Unit-Tests gegen eine **echte, vom Nutzer exportierte
  Beispiel-ZIP** als Fixture (Exportweg: Aktivität → Zahnrad → „Datei
  exportieren"), dazu reine Funktionstests für das Verdichten.
- Runner-Zweig: Garmin-Client und `rufe_claude` gemockt — Paketinhalt
  (Soll-Schritte, Tabellen, Vermerk übersprungener Aktivitäten), Speicherung,
  Job-Zustände, Leerer-Zeitraum-Abbruch.
- Router: Validierung (0, 8 → Fehler), 400 ohne Konto, Liste/Detail/Löschen,
  Fremdzugriff (fremde `analyse_id` → 404).
- Frontend: `npm run build` (Typecheck).

## In der Implementierung zu verifizieren

1. `garmin-fit-sdk` installierbar und liefert `workout_step_mesgs` wie
   erwartet — sonst Rückfall `fitdecode` (PyPI war aus der Design-Umgebung
   nicht erreichbar).
2. Rauch-Test in der Nutzerumgebung: `download_activity(…ORIGINAL)` gegen das
   echte Konto, eine ZIP entpacken und parsen.
3. Tokenbudget: Die Verdichtung auf ~150 Stützpunkte je Aktivität ist ein
   Startwert; bei sieben Tagen Triathlontraining ggf. nachjustieren.

## Bewusst außen vor

- Keine Automatik (kein Cron-Zweig, kein Einstellungs-Schalter).
- Keine app-eigenen Diagramme aus den FIT-Daten — Diagramme kommen, wenn, als
  Inline-SVG aus der KI.
- Kein Nachbearbeiten oder Neu-Bewerten eines Berichts; nur ansehen und
  löschen.
- Keine Backend-Sanitisierung des HTML — bereinigt wird beim Rendern
  (DOMPurify); gespeichert wird die Antwort unverändert (deckungsgleich mit
  `roh_antwort`-Philosophie).

## Dokumentationspflege (Teil der Umsetzung)

- Neue `docs/analyse.md` mit den Entscheidungen dieses Designs im Stil der
  übrigen `docs/`-Dateien; Eintrag in der Übersicht in `CLAUDE.md` samt
  kurzem Absatz im Kopfteil.
