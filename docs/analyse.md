# Trainingsanalyse per KI

Teil der Kontextdokumentation von Tri-Coach. Überblick, Setup und Konventionen:
[CLAUDE.md](../CLAUDE.md). Design-Spec:
[superpowers/specs/2026-09-18-trainingsanalyse-design.md](superpowers/specs/2026-09-18-trainingsanalyse-design.md).

**Eine Analyse gehört zu genau einem Training** (`TrainingsAnalyse.session_log_id`,
eindeutig über `uq_analyse_session_log`). Die erste Fassung bewertete einen
**Zeitraum** von 1–7 Tagen am Stück — ein Bericht über mehrere Einheiten, der
an keiner von ihnen hing. Im Verlauf stand er in einer eigenen Rubrik neben den
Trainings, und die Frage, die man an eine Liste absolvierter Einheiten stellt
(„welche ist schon bewertet?"), ließ sich nicht beantworten. Jetzt hängt der
Bericht an seiner Einheit: Der Knopf steht in ihrer Zeile, das Kurzfazit auch,
und wo keines steht, steht „noch nicht bewertet". Der Zeitraum steckt damit im
Training selbst (`log.date`) — `zeitraum_von`, `zeitraum_bis` und
`aktivitaeten_anzahl` sind entfallen. Die Berichte der alten Fassung sind beim
Update **gelöscht** worden (`database._ZURUECKZUSETZENDE_ALTWERTE`): Welche
Einheit gemeint war, ist aus einem Zeitraum mit mehreren nicht zu erraten, und
eine Analyse ohne Training taucht nirgends mehr auf.

**Ein zweiter Lauf ersetzt den Bericht, statt einen zweiten anzulegen.** Es ist
dasselbe Urteil über dieselbe Einheit, neu gefällt — zwei Fassungen
nebeneinander hätten aus „hat dieses Training eine Analyse?" eine Liste
gemacht. Gefragt wird vorher (`confirm` am Knopf „Neu auswerten"), und
`created_at` wandert mit: Sonst stünde „Analyse vom 12.09." über einem Text von
heute. Dieselbe Regel gilt für den Weg über die Zwischenablage.

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
ersten Eintrag). Eine dritte Eigenheit ist die von Zwift: Zwift schreibt
`local_timestamp = 0`, und daraus wurde ein Versatz von minus 36 Jahren, also
eine Fahrt mit Start am 30.12.1989. Ein Versatz außerhalb der echten Zeitzonen
(UTC−12 bis UTC+14) gilt deshalb als keiner.

**`fitdaten.py` dient inzwischen auch dem Abgleich** (`kennwerte_aus_fit`).
Die Planung bekommt aus jeder Aufzeichnung einmal ein Pulshistogramm und die
Bestwerte (siehe „Die Aufzeichnung wird einmal je Training geholt" in
[garmin-abgleich.md](garmin-abgleich.md)). Dekodieren und die Zuordnung zu
den Sessions teilen sich beide Wege (`_dekodiere`, `_fensterpruefung`), damit
eine Multisport-Datei in Analyse und Planung gleich zerfällt.

**Sekundendaten werden auf ~150 Stützpunkte verdichtet**
(`verdichte_stuetzpunkte`). Roh sind es mehrere tausend Records je Stunde;
eine Pulskurve braucht keine Sekundenauflösung, um lesbar zu sein. Je Fenster
das Mittel jedes Zahlenkanals, `None` zählt nicht mit — ein fehlender Pulswert
ist keine 0. Der Wert ist ein Startwert aus dem Design; bei sieben Tagen
Triathlontraining ggf. nachjustieren.

**Geholt wird genau eine Datei, an ihrer Kennung** (`fitdaten.hole_aktivitaet`,
`SessionLog.garmin_activity_id`). Der Zeitraumabruf über
`get_activities_by_date` ist mit der Zeitraum-Analyse entfallen: Er kostete
eine zusätzliche Anfrage und träfe bei zwei Läufen am selben Tag womöglich den
falschen. Eine Liste kommt trotzdem zurück — eine Multisport-Datei trägt
Schwimmen, Rad und Lauf als eigene Sessions, und das ist **ein** Training mit
drei Abschnitten.

**Ohne ladbare Aufzeichnung wird trotzdem bewertet.** Ein gescheiterter
Download beendet den Lauf nicht: Garmins Listendaten zur Einheit stehen als
`SessionLog` ohnehin im Paket (Block `training`), es fehlen nur die
Sekundendaten — und genau das sagt der Vermerk „nur Listendaten"
(`ai_export.HINWEIS_OHNE_FIT`), samt der Anweisung im Prompt, dort nichts
hinzuzuerfinden. Ein `GarminFehler` dagegen beendet ihn: An einer toten
Verbindung ändert der nächste Versuch nichts, und der Athlet soll sie
reparieren statt einen halbblinden Bericht zu bekommen.

**Das Paket trägt die Einheit zweimal, aus zwei Quellen.** `training` ist
Garmins gedeutete Zusammenfassung (`ai_export._session_eintrag`, derselbe
Block, den die Planung in ihrer Historie sieht) — dort steht, was in der
FIT-Datei nicht steht: das selbst vergebene Befinden, Garmins Trainingslast,
die von der Uhr gezählten Übungen einer Krafteinheit. `aktivitaeten` ist die
Rohaufzeichnung. Dazu `geplante_einheit`, wenn das Training einer Planeinheit
zugeordnet ist: das Soll für den Fall, dass die Aufzeichnung keine
Workout-Schritte trägt. Fehlt der Block, war frei aufgezeichnet — und „Plan
verfehlt" ist dann keine zulässige Kritik.

**Eigener Systemprompt, nicht nur eigener Prompt**
(`ai_export.ANALYSE_SYSTEMPROMPT`, Parameter `systemprompt` an `rufe_claude`).
Der Standardtext beschreibt einen Trainings**planer** — er zöge die Antwort in
Richtung Empfehlungen und nächster Einheiten. Hier antwortet ein kritischer
Analyst: Das Training ist gelaufen, es wird bewertet, nicht ersetzt. Kein
bestehender Aufrufer ändert sich (Vorgabe bleibt `SYSTEMPROMPT`).

**Das Antwortgerüst ist minimal erzwungen** (`ANALYSE_STRUKTURSCHEMA`): genau
`kurzfazit` (2–3 Sätze Klartext für die Trainingszeile) und `bericht_html`. Ein Vollschema
je Aktivität nähme dem Bericht die gewünschte Dynamik — mal trägt ein
Pacing-Diagramm, mal ein Satz; purer Text ohne Hülle machte das Kurzfazit zum
Ratespiel. **Kein Reparaturlauf** (anders als bei den Plan-Aufgaben): Bei zwei
Feldern gibt es nichts auszubessern, das ein zweiter Lauf besser wüsste. Der
Rückfall ohne Schema liest das Text-JSON tolerant (`runner._analyse_daten`).

**Der Lauf endet vor Claude, wo Claude nichts beitragen kann.** Unbekanntes
oder fremdes Training → 404 schon am `POST /api/ki/analysieren`. Kein
Garmin-Konto → 400, aber nur, wenn das Training überhaupt eine Garmin-Kennung
trägt: Ohne sie gab es nie eine Datei, und bewertet wird aus den Listendaten —
die Verbindung braucht es dafür nicht. Den Leerer-Zeitraum-Ausstieg gibt es
nicht mehr; es ist immer genau ein Training. Und ein `GarminFehler` mitten im
Lauf scheitert mit dessen deutscher Meldung, lässt aber `KiSettings.status`
unberührt (eigener Zweig in `_notiere_fehler`): Am Claude-Zugang liegt es
nicht, und die Warnung stünde sonst an jedem KI-Knopf.

**Nur manuell.** Kein Cron-Zweig, kein Schalter in den Einstellungen — jeder
Lauf kostet Kontingent, und anders als Planung oder Tagesanpassung hat eine
Kritik keinen Termin, an dem sie von selbst fällig würde.

**Der Weg über die Zwischenablage besteht auch hier**
(`GET /api/analysen/export?session_log_id=…`, `POST /api/analysen/import` — das
Muster von Plan und Ernährung, `routers/analysen.py`). Der Export ist anders
als dort kein reiner Datenbankgriff: Die Original-Aufzeichnung kommt live von
Garmin, der Aufruf dauert ein paar Sekunden. Beide Wege nennen dasselbe
Training als Kennung; aus der eingefügten Antwort ließe sich das nicht lesen,
sie besteht aus zwei Textfeldern. `model_used` bleibt beim Handweg leer, denn
welche KI geantwortet hat, weiß dort niemand. Knopf und Handweg teilen
**einen** Leser (`analyse_import.lese_analyse_antwort`, tolerant gegen
Codefences und Begleittext) — zwei Parser liefen beim ersten Sonderfall
auseinander.

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
externen Ressourcen (`FORBID_TAGS` + ein Hook, der `href` nur als Anker und
`url()` nur als Verweis ins selbe SVG durchlässt). DOMPurify ist die erste
Frontend-Abhängigkeit neben React — bewusst in Kauf genommen.

**Nicht `ALLOWED_URI_REGEXP` dafür.** Die erste Fassung schränkte die
Adressen mit `ALLOWED_URI_REGEXP: /^#/` ein. DOMPurify wendet die Option aber
auf **jeden** Attributwert an, der nicht auf seiner kurzen Liste
unbedenklicher Attribute steht (`class`, `id`, `style` …), nicht nur auf
URL-Attribute. Jedes Diagramm verlor so `viewBox`, `x`, `y`, `fill` und
`points`, und jeder Text im Diagramm stand schwarz und übereinander in der
Ecke oben links. Die Adressprüfung sitzt deshalb im Hook
`uponSanitizeAttribute` einer eigenen DOMPurify-Instanz.

**Anzeige ohne neue Route, und auf beiden Seiten dieselbe.** Der Verlauf zeigt
alle absolvierten Trainings, die Übersicht die letzten drei direkt unter „Als
Nächstes" — beide über **dieselben** Komponenten: `TrainingsTabelle` (Zeile mit
zwei Knöpfen und dem Kurzfazit), `TrainingDetail` (die Messwerte, aus `History`
herausgezogen), `AnalyseBericht` (der Dialog) und `useAnalysen` (Zuordnung
Training → Analyse, Zugang, Lauf, Fortschritt). Zwei Fassungen liefen beim
ersten neuen Zustand auseinander; die Vorgabe war ausdrücklich, dass sich beide
Seiten gleich verhalten und sich nur in der Zahl der Zeilen unterscheiden.

Die Rubrik „Analysen" im Verlauf ist damit **weg**. Sie war die Liste der
Zeitraum-Berichte; jetzt stünde dort dieselbe Trainingsliste ein zweites Mal.

**Ein Dialog für beide Lagen** (`AnalyseBericht`): Gibt es einen Bericht, steht
er darin — samt „Neu auswerten" und „Analyse löschen". Gibt es keinen, steht
darin der Knopf, der ihn schreiben lässt, und der Weg über die Zwischenablage.
Läuft gerade einer, steht darin der Fortschrittsbalken mit Abbruch. Ein
getrennter „Auswerten"-Knopf neben einem „Ansehen"-Knopf hätte je Zeile zwei
Bedienelemente gebraucht, von denen immer eines sinnlos ist.

Ein vor dem Seitenwechsel gestarteter Lauf wird beim Öffnen wieder aufgenommen
(`kiStatus.aktiver_job`) — und findet seine Zeile wieder, weil
`KiJob.session_log_id` auch an einem gescheiterten Lauf steht. Fehler der
Abfrageschleife landen sichtbar an der Seite statt in einem still stehenden
Balken: Wer den Dialog schließt, während der Lauf läuft, sähe sonst nie, dass
er gescheitert ist.

## Grenzen

- **Lauf, Kraft, Becken und Zwift sind an echten Daten getestet, Multisport
  nicht.** Als Fixtures liegen fünf ORIGINAL-ZIPs vor
  (`backend/tests/fixtures/fit/`): `lauf_workout.zip` (Lauf aus strukturiertem
  Workout), `kraft.zip` mit `set_mesgs`, dazu `schwimmen_becken.zip`,
  `rad_indoor_watt.zip` und `lauf_lang.zip`. Die drei neuen sind über die
  bestehende Verbindung geholt und vor dem Ablegen anonymisiert. Positionen,
  Seriennummern und die Texte des Nutzerprofils stehen in den Rohbytes auf dem
  FIT-Wert „ungültig", die Prüfsumme ist neu gerechnet, alles andere ist Byte
  für Byte das Original. Die beiden älteren sind nicht anonymisiert: Beide
  tragen den Profilnamen, der Einstufungslauf dazu seine GPS-Spur. Multisport (mehrere Sessions je Datei) ist defensiv
  mitgeschrieben, aber nur im Leerverhalten getestet. Ein Fixture kann
  nachgereicht werden (Exportweg: Aktivität → Zahnrad → „Datei exportieren",
  Ablage unter `backend/tests/fixtures/fit/`).
- **Der Zielkorridor der Soll-Schritte** (Puls/Watt samt FIT-Kodierung
  „über 100 = Schläge + 100", „über 1000 = Watt + 1000") ist implementiert,
  aber ungetestet: Das Fixture hat `target_type=open` ohne Korridor.
- Die Verdichtung auf ~150 Stützpunkte ist ein Startwert. Seit eine Analyse
  nur noch **ein** Training umfasst, ist das Tokenbudget kein Thema mehr: Am
  echten Konto gemessen ergab eine Krafteinheit mit 6 Sätzen und 130
  Stützpunkten einen Prompt von rund 2.300 Token.
- **Kein Sammelblick mehr über mehrere Tage.** Die Zeitraum-Analyse konnte
  „Belastung gegen Erholung über die Woche" in einem Zug beurteilen; jetzt
  sieht jeder Bericht nur seine Einheit — samt Fitnessdaten der letzten Wochen,
  aber ohne die Nachbareinheiten. Bewusst in Kauf genommen: Den Wochenblick
  liefert die Planung, die die volle Historie sieht.
- **Ein Training ohne Garmin-Kennung** (Altbestand aus der Zeit des
  Erfassungsformulars) lässt sich bewerten, aber nur aus den Listendaten — es
  gibt keine Aufzeichnung, die man holen könnte. Ungetestet an echten Daten:
  In der Datenbank des Nutzers steht kein solcher Eintrag mehr.
