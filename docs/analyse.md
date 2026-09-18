# Trainingsanalyse per KI

Teil der Kontextdokumentation von Tri-Coach. Überblick, Setup und Konventionen:
[CLAUDE.md](../CLAUDE.md). Design-Spec:
[superpowers/specs/2026-09-18-trainingsanalyse-design.md](superpowers/specs/2026-09-18-trainingsanalyse-design.md).

**Die Analyse liest die Original-Aufzeichnungen, nicht die Datenbank**
(`garmin/fitdaten.py`). Alle anderen KI-Aufgaben arbeiten auf `SessionLog` —
Garmins gedeuteten Listendaten aus dem Abgleich. Für ein Urteil über die
Ausführung reicht das nicht: Der geforderte Soll-Ist-Vergleich braucht die
geplanten Workout-Schritte **neben** den gefahrenen Runden, und beides steht
nur in der FIT-Datei der ORIGINAL-ZIP (`download_activity(…ORIGINAL)`, derselbe
Endpunkt wie „Datei exportieren" in Garmin Connect). Geholt wird **live** statt
aus der Datenbank, aus einem zweiten Grund: Wer mittags trainiert und
nachmittags auswertet, hätte über `SessionLog` eine Lücke — der tägliche
Abgleich war längst durch. TCX statt ZIP wurde verworfen (kein Binärparser
nötig, aber TCX trägt keine Workout-Schritte); Claude die Dateien selbst lesen
zu lassen auch — es kehrte die vier Schutzvorkehrungen in `ki/client.py` um.

**Geparst wird mit `garmin-fit-sdk`, dem Rückfall brauchte es nicht.** Garmins
offizielles, aus dem FIT-Profil generiertes Paket liefert am echten Fixture
`workout_step_mesgs`, `session_mesgs`, `lap_mesgs` und `record_mesgs` wie
erwartet; `fitdecode` als geplanter Rückfall blieb ungenutzt. Der Zugriff auf
die dekodierten Nachrichten ist durchweg defensiv (fehlende Nachrichtentypen →
leere Listen) — dieselbe Vorsicht wie `mapping.hole()` beim Connect-JSON.
Zwei Eigenheiten des SDK stecken in eigenen Helfern: `local_timestamp` kommt
als rohe Sekunden seit FIT-Epoche (`_ortszeit_versatz`), und mehrteilige
Notizen kommen als Liste mit Speicherresten dahinter (`_notiz` nimmt nur den
ersten Eintrag).

**Sekundendaten werden auf ~150 Stützpunkte verdichtet**
(`verdichte_stuetzpunkte`). Roh sind es mehrere tausend Records je Stunde;
eine Pulskurve braucht keine Sekundenauflösung, um lesbar zu sein. Je Fenster
das Mittel jedes Zahlenkanals, `None` zählt nicht mit — ein fehlender Pulswert
ist keine 0. Der Wert ist ein Startwert aus dem Design; bei sieben Tagen
Triathlontraining ggf. nachjustieren.

**Eine Aktivität ohne ladbare FIT fällt nicht aus dem Paket** — sie steht mit
ihren Listendaten und dem Vermerk „nur Listendaten" darin (`fit_fehlt`,
häufigster Fall: in Connect von Hand angelegt). Der Prompt weist die KI an,
dort nichts hinzuzuerfinden. Scheitert dagegen die Aktivitätenliste selbst,
scheitert der Lauf: Ohne sie gibt es nichts zu analysieren.

**Eigener Systemprompt, nicht nur eigener Prompt**
(`ai_export.ANALYSE_SYSTEMPROMPT`, Parameter `systemprompt` an `rufe_claude`).
Der Standardtext beschreibt einen Trainings**planer** — er zöge die Antwort in
Richtung Empfehlungen und nächster Einheiten. Hier antwortet ein kritischer
Analyst: Das Training ist gelaufen, es wird bewertet, nicht ersetzt. Kein
bestehender Aufrufer ändert sich (Vorgabe bleibt `SYSTEMPROMPT`).

**Das Antwortgerüst ist minimal erzwungen** (`ANALYSE_STRUKTURSCHEMA`): genau
`kurzfazit` (2–3 Sätze Klartext fürs Widget) und `bericht_html`. Ein Vollschema
je Aktivität nähme dem Bericht die gewünschte Dynamik — mal trägt ein
Pacing-Diagramm, mal ein Satz; purer Text ohne Hülle machte das Kurzfazit zum
Ratespiel. **Kein Reparaturlauf** (anders als bei den Plan-Aufgaben): Bei zwei
Feldern gibt es nichts auszubessern, das ein zweiter Lauf besser wüsste. Der
Rückfall ohne Schema liest das Text-JSON tolerant (`runner._analyse_daten`).

**Der Lauf endet vor Claude, wo Claude nichts beitragen kann.** Kein
Garmin-Konto → 400 schon am `POST /api/ki/analysieren`, ohne Job. Leerer
Zeitraum → Job endet mit klarer Meldung, ohne Kontingent zu kosten. Und ein
`GarminFehler` mitten im Lauf scheitert mit dessen deutscher Meldung, lässt
aber `KiSettings.status` unberührt (eigener Zweig in `_notiere_fehler`): Am
Claude-Zugang liegt es nicht, und die Warnung stünde sonst an jedem KI-Knopf.

**Nur manuell.** Kein Cron-Zweig, kein Schalter in den Einstellungen — jeder
Lauf kostet Kontingent, und anders als Planung oder Tagesanpassung hat eine
Kritik keinen Termin, an dem sie von selbst fällig würde.

**Der Weg über die Zwischenablage besteht auch hier**
(`GET /api/analysen/export`, `POST /api/analysen/import` — das Muster von Plan
und Ernährung, `routers/analysen.py`). Der Export ist anders als dort kein
reiner Datenbankgriff: Die Original-Aufzeichnungen kommen live von Garmin, der
Aufruf dauert ein paar Sekunden je Aktivität, und ein leerer Zeitraum ist eine
409 statt eines leeren Prompts. Der Import rechnet den Zeitraum beim Einfügen
(heute − (tage−1) bis heute) — dieselbe Lesart wie beim Start eines Laufs und
die einzige ohne gemerkten Zustand; `aktivitaeten_anzahl` reicht das Frontend
aus dem Export durch, `model_used` bleibt leer, denn welche KI geantwortet
hat, weiß beim Handweg niemand. Knopf und Handweg teilen **einen** Leser
(`analyse_import.lese_analyse_antwort`, tolerant gegen Codefences und
Begleittext) — zwei Parser liefen beim ersten Sonderfall auseinander.

**Der Runner prüft den Zugang selbst, bevor er den Unterprozess startet**
(`_frage_claude`, gilt für **alle** Jobarten). Der Router prüft nur
freundlich; zwischen Knopfdruck und Lauf können Minuten liegen, und die
Automatiken kommen ganz ohne Router. Ohne den Riegel hing ein Lauf ohne
Zugang bis zur Zeitüberschreitung — der Unterprozess kann ohne Terminal
niemanden nach der Anmeldung fragen, eine Viertelstunde Fortschrittsbalken
für einen Fehler, der in Millisekunden feststeht (`ist_angemeldet` ist 60 s
gecacht, der doppelte Blick kostet nichts). Im Frontend sind die KI-Knöpfe
ohne Zugang **gesperrt statt versteckt**, mit dem Grund als Tooltip und Satz
daneben — und der Handweg steht dann aufgeklappt da.

**Gespeichert wird ungefiltert, bereinigt wird beim Rendern**
(`TrainingsAnalyse.bericht_html`, DOMPurify in
`frontend/src/components/AnalyseBericht.tsx`). Ein Eigenbau-Sanitizer im
Backend wäre ein bekanntes Sicherheits-Antimuster, und die Regeln, was ein
Browser gefahrlos darf, gehören dorthin, wo der Browser ist. DOMPurify lässt
Struktur-HTML und Inline-SVG durch (Diagramme kommen, wenn, von der KI — die
App zeichnet keine eigenen) und entfernt alles Aktive samt aller Wege zu
externen Ressourcen (`FORBID_TAGS` + `ALLOWED_URI_REGEXP: /^#/`). DOMPurify
ist die erste Frontend-Abhängigkeit neben React — bewusst in Kauf genommen.

**Anzeige ohne neue Route:** Widget auf der Übersicht (`AnalyseKarte`, nur mit
verbundenem Garmin-Konto), Bericht als Modal (`AnalyseBericht`, Muster
`SessionDetail`), Historie als dritte Rubrik im Verlauf. Ein Bericht wird nur
angesehen oder gelöscht — kein Nachbearbeiten, kein Neu-Bewerten. Ein
laufender Lauf ist abbrechbar (derselbe `kiAbbrechen`-Weg wie überall), ein
vor dem Seitenwechsel gestarteter wird beim Öffnen wieder aufgenommen
(`kiStatus.aktiver_job`), und Fehler der Abfrageschleife landen sichtbar an
der Karte statt in einem still stehenden Balken.

## Grenzen

- **Lauf und Kraft sind an echten Daten getestet, Schwimmen und Multisport
  nicht.** Als Fixtures liegen zwei ORIGINAL-ZIPs vor
  (`backend/tests/fixtures/fit/lauf_workout.zip` — Lauf aus strukturiertem
  Workout — und `kraft.zip` mit `set_mesgs`). Schwimmen (`length_mesgs`) und
  Multisport (mehrere Sessions je Datei) sind defensiv mitgeschrieben, aber
  nur ihr Leerverhalten ist getestet — Fixtures können nachgereicht werden
  (Exportweg: Aktivität → Zahnrad → „Datei exportieren", Ablage unter
  `backend/tests/fixtures/fit/`).
- **Der Zielkorridor der Soll-Schritte** (Puls/Watt samt FIT-Kodierung
  „über 100 = Schläge + 100", „über 1000 = Watt + 1000") ist implementiert,
  aber ungetestet: Das Fixture hat `target_type=open` ohne Korridor.
- Die Verdichtung auf ~150 Stützpunkte ist ein Startwert; das Tokenbudget bei
  sieben Tagen Triathlontraining ist nicht vermessen.
