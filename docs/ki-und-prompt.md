# Der Prompt und die KI im Server

Teil der Kontextdokumentation von Tri-Coach. Überblick, Setup und Konventionen:
[CLAUDE.md](../CLAUDE.md).

## Der Prompt (`ai_export.py`)

`PROMPT_TEMPLATE` enthält den Auftrag und die handwerklichen Vorgaben,
`_response_schema()` das erwartete Antwortformat. Das Template wird mit
`.format()` gefüllt — neue Platzhalter müssen in `build_prompt()` mitversorgt
werden.

**Der Prompt schreibt die Trainingslehre nicht mehr vor.** Er war einmal rund
22.000 Zeichen lang und bestand aus dreizehn nummerierten „verbindlichen
Trainingsprinzipien": eine Steigerungsgrenze von 10 % gegen
`letzte_volle_woche`, Readiness-Schwellen bei 40 und 65, ACWR über 1.3 als
Auftrag zurückzunehmen, ein Schlafdefizit von 45 Minuten als Auftrag die
intensive Einheit zu streichen, Listen von Zielschlüsseln, die einen Reiz
verlangen oder nicht. Jede dieser Zahlen war einzeln begründet, und in Summe
entschieden sie den Block, bevor das Modell die Daten gelesen hatte.

Die Rolle im Prompt ist ein Ausdauer-Trainingswissenschaftler. Umfang,
Verteilung und Reizwahl bringt er mit — was ihm fehlt, sind die Daten *dieses*
Athleten, und die stehen vollständig im Paket. Der Auftrag sagt deshalb
ausdrücklich: „**Umfang, Intensität und Zusammensetzung entscheidest du.**
Maßstab sind allein das Ziel in `trainingswunsch.ziel`, die absolvierten
Einheiten in `trainingshistorie` und die Gesundheitsdaten in `fitnessdaten`.
Dieses Dokument gibt dir dafür weder Quoten noch Steigerungsgrenzen vor."

`test_der_prompt_gibt_die_trainingslehre_nicht_vor` ist die Bremse gegen den
Rückweg: Es prüft den **Anweisungsteil** (nicht den ganzen Prompt — „1.3" steht
als ACWR-Messwert völlig zu Recht im Datenpaket) darauf, dass keine dieser
Zahlen zurückkehrt. `test_der_anweisungstext_bleibt_kurz` hält die
Größenordnung. Gewachsen ist der Prompt in kleinen Schritten, jeder einzelne
begründet; die Grenze soll nicht den nächsten Absatz verhindern, sondern den
zwanzigsten.

**Erfundene Schwelle gegen gemessene Grenze — das ist die Trennlinie.** „Readiness
unter 40 heißt locker" ist eine Zahl aus diesem Dokument und fällt weg. Der
HRV-Normalbereich, den Garmin an *diesem* Athleten gemessen hat
(`balancedLow`/`balancedUpper` → `hrv_normalbereich_ms`), und das optimale
Lastfenster des Trainingsstatus (`training_status.lastfenster`) sind dagegen
Daten: Sie bleiben im Paket und werden im Prompt **namentlich benannt**, denn
ohne die Nennung übersah die KI sie dort. Gelesen wird der Tageswert gegen seine
Grenze; den Schluss zieht das Modell. Aus demselben Grund fällt
`fitnessdaten.auffaelligkeiten` aus dem Trainingspaket — fertige deutsche
Warnsätze aus genau den Schwellen, die gerade gestrichen wurden, wären derselbe
Eingriff durch die Hintertür. Der Ernährungsprompt behält sie: Er bekommt eine
stark gekürzte Historie und braucht die Verdichtung.

**Der Wettkampf wird wieder benannt** (`WETTKAMPFHINWEIS`,
`_wettkampfhinweis()`). Mit den dreizehn Prinzipien fiel auch Punkt 5
„Spezifität", und danach kam das Wettkampfdatum im Anweisungsteil überhaupt
nicht mehr vor — obwohl der Fragebogen es abfragt und `_request_block()` es
samt `wochen_bis_wettkampf` und `wettkampfdistanz` ins Paket legt. Das ist
dieselbe Lage wie beim HRV-Normalbereich und derselbe Ausweg: Die Felder werden
genannt, der Schluss bleibt beim Modell. Was der Abstand für diesen Block
bedeutet, steht bewusst nicht dort — „ab Woche X wird getapert" wäre wieder eine
Zahl aus diesem Dokument. Der Absatz erscheint nur, wenn ein Wettkampf
eingetragen ist **und noch bevorsteht**: Ein Fragebogen überdauert seinen
Wettkampf, `wochen_bis_wettkampf` wird dann negativ, und ein Auftrag, auf das
Datum hin zu planen, zeigte in die Vergangenheit. Die Felder bleiben in beiden
Fällen im Paket.

**Frühere Blöcke dieser App stehen nicht mehr im Paket.** Es gab dafür vier
Stellen — `geplant_war` an jeder absolvierten Einheit, `aktueller_plan` mit dem
`summary` des letzten Laufs, `umsetzung_aktueller_plan` mit der Quote und
`ersetzt_laufenden_block` mit den verworfenen Einheiten — und einen eigenen
Prinzipienpunkt („Fortschreiben statt neu erfinden"), der daraus las, ob eine
Vorgabe „zu ambitioniert" war. Der Gedanke war gut: Aus 5x1000 m soll 6x1000 m
werden. Der Preis war, dass das Modell den alten Block als Vorlage nahm, statt
aus dem Verlauf neu zu entscheiden — und dass eine niedrige Umsetzungsquote als
Auftrag gelesen wurde, kleiner zu planen. Wer zwei Wochen krank war, bekam so
immer kleinere Blöcke. **Maßstab ist jetzt allein, was stattgefunden hat.**

Was von der Ausführung erhalten bleibt, sind die **gemessenen** Felder:
`zeit_in_hf_zonen_min`, `absolvierte_abschnitte` und `absolvierte_uebungen`.
Sie sagen, was der Athlet getan hat, nicht was er tun sollte. Nur
`workout_einhaltung_pct` ist mitgegangen — Garmins Bewertung *gegen die
Vorgabe* ist ein Planvergleich. `sportscience.compliance()` bleibt bestehen und
füttert die Kachel unter `/api/logs/stats`; sie verlässt nur den Export.

**Fünf handwerkliche Vorgaben, keine dreizehn Prinzipien.** Was bleibt, ist das,
was die App technisch braucht — die Nummern haben sich dabei verschoben, und
Kommentare wie Tests wurden mitgezogen:

| # | Was | Warum es bleibt |
|---|---|---|
| 1 | Disziplin (`_prinzip_disziplin()`) | Der Fragebogen kennt vier; ein Laufblock darf kein `swim` enthalten |
| 2 | Verfügbare Tage, Zeitbudget | Steht im Fragebogen und ist keine Trainingsentscheidung |
| 3 | Ergänzungstraining (`PRINZIP_ERGAENZUNG`) | Übungsliste, Abwechslung, **englische Übungsnamen** |
| 4 | Steuerungsgrößen (`_prinzip_steuergroessen()`) | Zonen, Schwimm-/Radort, Bauplan — daraus baut die App das Workout |
| 5 | Beschwerden | Der einzige Freitext, den kein Gerät gemessen hat |

**Punkt 1 existiert in zwei Fassungen**, je nach gewählter Disziplin — beide
sagen dasselbe in zwei Richtungen: welche Sportschlüssel dieser Block tragen
darf. Die Einzeldisziplin schließt die anderen und `brick` aus, die
Triathlonfassung stellt alle offen und verweist auf
`tage_seit_letzter_einheit_je_sportart`. Trainingslehre steht in keiner: Die
Triathlonfassung trug einmal welche („Schwimmen mit Technikschwerpunkt, Rad als
Träger des Grundlagenumfangs") und verlor sie mit den dreizehn Prinzipien; was
danach eine Weile dort stand — „Nutze die Bestpractise" — delegierte an eine
Stelle, die der Prompt zwei Absätze weiter oben schon vollständig delegiert,
und ließ den Listenpunkt ohne Aussage zurück. Punkt 5 verliert dabei seinen
Ausweichsatz, und `_session_schema()` nimmt die Sportarten aus dem
Antwortformat. Siehe „Die gewählte Disziplin entscheidet, was im Block vorkommen
darf".

Der Absatz zur Erholungslage ist der Platzhalter `{fitnessregeln}` und existiert
in zwei Fassungen (`FITNESSREGELN_MIT_DATEN` / `_OHNE_DATEN`) — welche eingesetzt
wird, entscheidet `build_prompt()` daran, ob der Payload einen
`fitnessdaten`-Block trägt. Regeln zu Daten, die es nicht gibt, laden zum
Erfinden ein. Beide Texte laufen durch `.format()`: geschweifte Klammern müssten
verdoppelt werden.

**Der Bauplan steht nur noch einmal.** `_STEUER_BAUPLAN` schrieb dieselben sechs
`steps`-Regeln aus, die `SESSION_SCHEMA["steps"]` schon trägt — zusammen rund
5.500 Zeichen für einen Sachverhalt. Geblieben ist die Fassung im Schema (sie
steht direkt am Feld, wo das Modell sie beim Ausfüllen liest, und trägt die drei
Beispiele); der Prompt verweist in einem Satz darauf.

**Kompaktes JSON statt Einrückung.** `json.dumps(..., separators=(",", ":"))`
für Schema und Payload spart rund ein Viertel des Prompts, ohne dass eine
Information verlorenginge. Gelesen wird das Paket von einem Modell — auch auf
dem Weg über die Zwischenablage, wo der Mensch es nur kopiert. Wer nach einem
Feld sucht, sucht im `payload`-Teil der Antwort, der weiterhin strukturiert
zurückkommt.

**Tabellen statt wiederholter Schlüssel.** Der Datenteil ist seither kein
einziges JSON-Objekt mehr, sondern ein Abschnittsdokument
(`paketformat.paket_als_text()`): Unregelmäßiges bleibt kompaktes JSON, alles
Gleichförmige wird eine CSV-Tabelle mit einer Kopfzeile. Zwei Kostentreiber
verschwinden damit, beide reine Mechanik ohne Informationsgehalt — die
dreißigmal wiederholten Schlüsselnamen je Einheit und die `null`-Felder, die
sich durch fast jede Zeile zogen. An einem echten Paket gemessen:

| Block | vorher | als Tabelle |
|---|---:|---:|
| `trainingshistorie.einheiten` (33 Einheiten) | 15.345 | 6.068 |
| `fitnessdaten.tage` (29 Tage) | 6.001 | 1.587 |
| `trainingshistorie.wochenuebersicht` | 1.799 | 1.145 |
| `herzfrequenzzonen` | 593 | 287 |
| **das ganze Paket** | **30.491** | **14.181** |

Vier Entscheidungen halten das **verlustfrei**, und verlustfrei ist die
Bedingung — `test_paketformat.py` baut den Text zurück in den Payload und
vergleicht:

- **Die Überschriften sind die JSON-Pfade** (`### trainingshistorie.einheiten`).
  Deshalb musste am Anweisungsteil keine Zeile geändert werden, obwohl er
  durchgehend mit Feldpfaden argumentiert (`wochenuebersicht`,
  `athlet.verlauf`, `training_status.lastfenster`).
- **Konstante Spalten wandern in die Überschrift.** `basis=HFR (Karvonen)`
  stand fünfmal da, `status=completed` dreißigmal. Nie die erste Spalte: Sie
  trägt die Kennung der Zeile, und eine Tabelle ohne Spalten wäre keine mehr.
- **Verschachteltes bekommt eine eigene Tabelle**, verknüpft über eine
  Bezugsspalte — `by_sport`, `absolvierte_abschnitte`, `absolvierte_uebungen`.
  In der Zelle wären sie wieder JSON mit wiederholten Schlüsseln, und ihre
  Anführungszeichen zwängen die Zelle selbst in Anführungszeichen. Der Bezug
  läuft über die laufende Nummer `nr` und nicht über Datum und Sportart: Zwei
  Radeinheiten an einem Tag sind keine Seltenheit.
- **Keine erfundene Kurzschrift.** Ein `aufwaermen:3x11@139` spart mehr, aber
  es ist eine Notation, die der Prompt erklären müsste — und jede erklärte
  Notation ist eine Gelegenheit zur Fehldeutung. Gespart werden Klammern und
  Namen, keine Werte.

Die Spaltenreihenfolge hängt bewusst **nicht** davon ab, welche Zeile zufällig
als erste einen Wert trägt: In den Tabellenzeilen bleiben die `None`-Schlüssel
stehen und werden zur leeren Zelle. Gefiltert wird nur in den JSON-Köpfen.

`build_payload()` liefert weiterhin denselben verschachtelten Dict — daran
hängen `ExportOut.payload`, die Anzeige im Frontend und die Frage, ob ein
Zurückkopieren die Antwort war. Nur der Weg **in den Prompt** führt durch das
neue Modul, und `paket_als_text()` arbeitet auf einer Kopie.

**Das eingefügte Datenpaket wird am Rohtext erkannt.** Wer den ganzen Prompt
zurückkopiert, soll „das ist das Datenpaket, nicht ihre Antwort" lesen und
keine Feldliste. Solange der Datenteil JSON war, genügten dafür seine obersten
Schlüssel (`athlet`, `trainingswunsch`); jetzt ist er kein JSON-Objekt mehr,
und das einzige lesbare Objekt im Prompt wäre ausgerechnet das Antwortformat —
also eine Tagesliste. `paketformat.ist_datenpaket()` sucht deshalb die Legende
im Text, und beide Importeure fragen sie, bevor sie Feldnamen aufzählen.

**Die Fitnessdaten reichen 14 Tage zurück** (`WELLNESS_TAGE`), nicht vier
Wochen. Für einen Block über wenige Tage entscheidet die jüngste Entwicklung,
und die Vierwochensicht steht als `mittelwerte.28_tage` daneben. Über den vollen
Rückblick waren die Tageswerte ein Fünftel des gesamten Prompts.

**Kapazität und Richtung stehen neben der Erholungslage.** Das Paket beschrieb
sehr genau, wie *erholt* der Athlet ist — HRV samt gemessenem Normalbereich,
Schlafphasen, Readiness, Trainingsstatus mit Lastfenster — und sehr wenig
darüber, was er *kann* und wohin es geht. Vier Fragen, die ein Trainer als
erstes stellt, waren aus dem Paket nicht zu beantworten, obwohl ihre Rohdaten
längst in der Datenbank lagen:

| Frage | Rohdaten | Fehlte, weil |
|---|---|---|
| Wie verteilt sich die Intensität? | `SessionLog.hr_zone_seconds` | je Einheit exportiert, nie zur Woche summiert |
| Wie lang war die längste Einheit? | `duration_min` | `weekly_summary()` kannte nur Summe und Schnitt |
| Wohin geht die Form über Monate? | `ProfileHistory` | wurde **nie** exportiert |
| Kostet dasselbe Tempo mehr Puls? | Tempo und `avg_hr` | wurde nie ins Verhältnis gesetzt |

Dazu `monotonie` und `strain` nach Foster: Zwei Wochen mit identischer Summe
können sich in ihrer Gleichförmigkeit vollständig unterscheiden, und die Summe
allein zeigt das nicht.

**Aggregiert und nicht roh** — das ist der Punkt. Die Zonenzeiten standen schon
je Einheit im Paket; was fehlte, war die Addition, und genau die ist es, an der
ein Sprachmodell scheitert. Dieselbe Überlegung beim Verlauf: `ProfileHistory`
bekommt bei *jeder* Wertänderung eine Zeile, der tägliche Abgleich erzeugt also
fast täglich eine. Ungefiltert stünde ein Jahr mit dreihundert Zeilen im Prompt
und verdrängte die Historie, um die es geht — `verlauf_stuetzpunkte()` dünnt auf
einen Stützpunkt je Monat aus.

**Genannt wird, wo die Größe steht — nicht, was sie bedeuten soll.** Der
Anweisungsteil zählt die neuen Felder auf, weil die KI ein ungenanntes Feld
übersieht (dieselbe Lektion wie beim HRV-Normalbereich). Was dort ausdrücklich
**nicht** steht, ist eine Zielverteilung, eine Monotoniegrenze oder eine
Richtung für die Effizienz: Das wären wieder Zahlen aus diesem Dokument, und
genau die sind mit den dreizehn Prinzipien geflogen. Der Absatz kostet rund 500
Zeichen; `test_der_anweisungstext_bleibt_kurz` hat danach noch gut 600 Zeichen
Luft, die Grenze blieb unangetastet.

**Die Effizienz ist bewusst unbewertet.** Tempo bzw. Leistung je Herzschlag
trennt „langsamer geworden" von „müder geworden" — beide senken das Tempo, aber
nur die Ermüdung hebt dabei den Puls. Vergleichbar ist der Wert allerdings
**nur zwischen ähnlichen Einheiten**: Ein Intervalltraining und ein langer
Dauerlauf ergeben verschiedene Zahlen, ohne dass sich an der Form etwas
geändert hätte. Er steht deshalb je Einheit neben Dauer, Zonen und Puls, und
der Prompt sagt die Einschränkung ausdrücklich dazu.

**Garmins gemessene Schwellenpace steht neben der Handeingabe, nicht in ihr**
(`athlet.schwellenpace_gemessen_garmin`). Maßgeblich für `pace_zones()` bleibt,
was der Athlet einträgt — das war eine Entscheidung und bleibt eine. Verworfen
wurde Garmins Wert bis hierher trotzdem zu Unrecht: Er kommt in **derselben**
Antwort mit, aus der schon der Schwellenpuls gelesen wird, kostet also keine
Anfrage, und eine veraltete Handeingabe ist im Paket durch nichts anderes zu
erkennen. Ein Gegenstück für die FTP gibt es nicht — siehe „Die FTP kommt aus
keiner dieser Antworten" in `docs/garmin-abgleich.md`.

Punkt 3 verlangt bei `strength` und `mobility` eine **Übungsliste** in
`structure` und hinter jeder deutschen Bezeichnung den geläufigen englischen
Namen in Klammern („Seitstütz (Side Plank) 3x40 s je Seite"). Das ist kein
Schönheitswunsch: Der englische Name ist der Schlüssel in Garmins Übungskatalog
und entscheidet darüber, ob auf der Uhr die Bewegungsanimation erscheint
(`garmin/uebungen.py`). Das Wörterbuch dort fängt den Fall ohne Klammer ab —
beide Wege führen zum selben Eintrag, der Prompt erhöht nur die Trefferquote.

**Wie lang eine Ergänzungseinheit ist, sagt der Prompt nicht.** Er verlangte
einmal „kurz" — eine Zahl, die weder aus der Belastungslage noch aus der
Beschwerde stammt, sondern aus der Annahme, Kraft und Mobility seien Beiwerk.
Genau diese Annahme steht der Behandlung im Weg: Eine abgeschwächte Muskelgruppe
oberhalb des Gelenks braucht Arbeitszeit. Der Hinweistext im Fragebogen sagt es
ebenso wenig (`SUPPLEMENTAL_OPTIONS` in `frontend/src/constants.ts`).

**„Regelmäßig" heißt dort ausdrücklich nicht „dasselbe noch einmal".** Punkt 3
sagte einmal nur „Mobility kurz und regelmäßig" — und genau das hat die KI
getan: Am 18.08.2026 verordnete sie eine Mobility-Einheit für Hüfte und
lateralen Oberschenkel, am 19.08. eine für Hüfte, Gesäß und
Oberschenkelaußenseite. Sie hat dabei nichts übersehen: Die Einheit vom Vortag
lag mitsamt Übungsliste im Export, und `tage_seit_letzter_einheit_je_sportart`
sagte `mobility: 1`. **Die Wiederholung war eine Prompt-Lücke, kein
Datenmangel** — die naheliegende Diagnose „sie weiß zu wenig" war hier die
falsche. Der Punkt verlangt deshalb, in `trainingshistorie.einheiten` nach der
letzten Ergänzungseinheit zu sehen und Übungsauswahl wie Körperregion zu
wechseln — zuerst in `absolvierte_uebungen`, was die Uhr gezählt hat, sonst in
`notiz`.

Daran hing eine Falle, die `test_der_prompt_nennt_nur_felder_die_es_gibt`
gefangen hat: Der Verweis lautete zunächst auf `summary`, und das Antwortformat
der Einzelanpassung hat keins. `PRINZIP_ERGAENZUNG` geht deshalb wie
`FITNESSREGELN_*` durch ein eigenes `.format()` (`_prinzip_ergaenzung()`) —
`.format()` formatiert eingesetzte Werte **nicht** erneut, der Platzhalter muss
also gefüllt sein, bevor der Text in die Vorlage geht.

**Punkt 5 ist die Beschwerde des Athleten, und sie wirkt in zwei Richtungen.**
`athlet.verletzungen_einschraenkungen` reiste lange im Payload mit, ohne dass
ein Punkt darauf zeigte. Beim Ausdauerteil las das Modell den Freitext von
selbst; die Ergänzungseinheiten dagegen **wichen der betroffenen Region aus**,
weil die Abwechslungsregel den Wechsel der Körperregion verlangte und nichts
dagegenstand. Genau umgekehrt ist es richtig: Ein Läuferknie wird in Kraft und
Mobility behandelt, nicht umgangen. Deshalb **Bremse** (Umfang, Intensität,
Untergrund) *und* **Auftrag** (die wahrscheinliche Ursache ableiten und die
Übungen planen, die sie angehen).

Die Abwechslungsregel gilt seither ausdrücklich **nur für gesunde Regionen** —
als bloße Erlaubnis formuliert („eine Region, die akut zwickt, darf wiederholt
werden") war sie zu schwach. Aber die Ausnahme gilt der **Region, nicht der
Einheit**: Zwei aufeinanderfolgende Tage an derselben Region müssen sich in
Form, Übungsauswahl oder Progression unterscheiden, sonst kam dieselbe
Dehneinheit drei Tage hintereinander — ausdrücklich gedeckt durch die Ausnahme,
die sie behandeln sollte.

**Vorgeschrieben wird dabei nichts.** Dass ein Läuferknie Kräftigung der
Hüftabduktoren braucht, steht nicht im Prompt: Welche Übung zu welcher
Beschwerde gehört, ist die Fachkenntnis des Modells. Der Prompt sagt nur, *dass*
die Beschwerde behandelt gehört und dass Aussparen die falsche Antwort ist.

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

**Drei Jobarten, ein Runner.** `manual` plant den Block, `einheit` passt eine
Einheit an, `ernaehrung` schreibt den Ernährungsplan. Alle drei teilen sich
Zustände, Fortschrittsleiter, Abbruch und `GET /api/ki/jobs/{id}` — und **ein**
Schloss: Es läuft immer nur einer. Die Verzweigung in `_lauf` ist deshalb eine
`elif`-Kette mit der Blockplanung als `else`; wer eine vierte Art ergänzt, hängt
sie **davor**, sonst plant sie still einen Trainingsblock. Die Anfangsmeldung
kommt aus `_STARTMELDUNG` — beim dritten Fall wurde der Bedingungsausdruck
unlesbar.

**Ein Weg für beide Auslöser.** `ai_export.erzeuge_export()` und
`plan_import.uebernimm_plan()` sind aus den Routen herausgezogen und werden vom
Knopf wie vom Handweg über die Zwischenablage gleichermaßen benutzt. Damit erbt
der Knopf ohne eine Zeile Wiederholung, was am Übernehmen hängt: der abgelöste
Block wird weggeräumt, und der neue geht über
`garmin.automatik.starte_uebertragung_fuer_neuen_plan` von selbst auf die Uhr.

**Doch `--json-schema` — die Hinterhand ist gezogen.** Hier stand einmal das
Gegenteil, und die Begründung war zum Zeitpunkt richtig: `parse_ai_response`
fängt Codefences, Begleittext und `weeks`-Ebenen ab und ist getestet, und im
ersten Versuch mit dem echten Prompt lief die Antwort mit null Warnungen durch.
Was das umgestoßen hat, sind Fehlschläge im Betrieb — mal ein Komma zu viel, mal
eine fehlende `summary`, mal Steuerungsgrößen an der falschen Sportart. **Eine
Antwort, die mal stimmt und mal nicht, ist kein Parserproblem.** Der Prompt
verlangt `summary` an vier Stellen; wenn das nicht reicht, hilft eine fünfte
nicht.

Drei Dinge am echten Programm gemessen (Version 2.1.233), bevor der Absatz
gedreht wurde:

* Die CLI setzt `--json-schema` intern als **erzwungenen Tool-Use** um — die
  Antwort kommt mit `"stop_reason": "tool_use"` zurück. Das ist genau der
  API-Mechanismus, für den es sonst einen Wechsel weg vom Abo hin zur
  Token-Abrechnung bräuchte. Das Abo bleibt.
* Die Hülle trägt zusätzlich **`structured_output`**: die Antwort schon geparst.
  `plan_import.plan_aus_objekt()` nimmt sie direkt; im Text noch einmal nach
  Klammern zu suchen wäre ein Umweg über die Fehlerquelle, die gerade beseitigt
  wurde.
* **`$defs`/`$ref` funktionieren**, auch rekursiv. Das war die eigentliche
  Frage: `AIStepIn` verweist auf sich selbst, sonst ließe sich keine
  Wiederholungsgruppe ausdrücken.

Die Fessel, vor der der alte Absatz warnte, gibt es trotzdem nicht:
`strukturschema()` setzt **kein** `additionalProperties: false` und **keine**
`if/then`-Bedingung je Sportart. Pflicht ist nur, was die App zum Bauen eines
Workouts braucht, plus `summary` und `coaching_notes`. Und der Textweg bleibt:
Scheitert ein Lauf aus einem Grund, der nicht am Zugang liegt, wiederholt
`client.rufe_claude` ihn genau einmal **ohne** Schema.

**Zwei Fassungen desselben Formats, und das ist Absicht.** `SESSION_SCHEMA` ist
die Lehrfassung — Prosa am Feld, die der Weg über die Zwischenablage genauso
braucht wie der Knopf, denn dort reist kein Schema mit. `strukturschema()` ist
die Strukturfassung. Die Feldnamen werden aus `_session_schema()` **abgeleitet**
statt abgeschrieben, `test_antwortschema.py` hält Enums, Grenzen und Pydantic
zusammen. Eine Grenze, die das Schema erlaubt und Pydantic ablehnt, wäre die
schlimmste Sorte: Sie käme durch die Erzwingung und stürbe erst im Import.

Genau eine Regel steht bewusst in **beiden**: „genau ein Maß je Schritt". Ohne
sie im Strukturschema gab Opus im Versuch an fast jedem Schritt zwei Maße —
das Modell liest beim Ausfüllen die Feldbeschreibung, nicht den Prompt fünf
Bildschirmseiten weiter oben. Erzwingen ließe sie sich nur über `oneOf`, und
daran stürbe ein sonst brauchbarer Block; `AISessionIn._raeume_masse` bleibt das
Netz darunter.

**Das Schema reist am `Export` mit** (`Export.schema`), nicht als eigener
Parameter. Sonst müsste der Aufrufer die Disziplin ein zweites Mal bestimmen,
und Prompt und Schema kämen aus zwei Rechnungen, die auseinanderlaufen können.

**Die Rohantwort wird gespeichert, bevor sie geprüft wird**
(`KiJob.roh_antwort`). Bis hierher war ein Lauf, dessen Antwort nicht durch den
Import kam, ersatzlos verloren — samt der zweieinhalb bis vier Minuten, die er
gedauert hat. Genau darauf beruft sich der Import an mehreren Stellen als Grund,
lieber zu warnen als abzulehnen („Ein abgelehnter Block wäre die teuerste
denkbare Antwort"). Geschrieben wird mit **eigenem Commit vor** dem Übernehmen:
Scheitert es, rollt `_lauf` die Sitzung zurück, und alles danach Geschriebene
wäre wieder weg. `KiJobOut` gibt nur `roh_antwort_vorhanden` heraus — zwanzig
Kilobyte gehören nicht in eine Abfrage, die im Sekundentakt läuft; der Text
kommt über `GET /api/ki/jobs/{id}/rohantwort` und landet im Einfügefeld.

**Und genau ein Reparaturlauf.** Scheitert der Import trotz Schema, geht ein
zweiter, kurzer Aufruf hinaus: nur die deutschen Fehlermeldungen und das kaputte
JSON, dasselbe Schema, `--effort low`, 180 s (`REPARATUR_PROMPT`,
`KiRunner._mit_reparatur`). **Kein Datenpaket und keine Trainingslehre** — ein
voller Prompt lüde dazu ein, neu zu planen, und der Block ist längst
entschieden; es fehlt eine Formalie. Ein zweiter *vollständiger* Lauf wäre die
teuerste Antwort auf ein fehlendes Feld: Er dauert Minuten, kostet Kontingent
und plante dabei einen anderen Block. Genau ein Versuch, sonst liefe die App im
Kreis; scheitert auch er, endet der Lauf wie bisher — aber mit erhaltener
Antwort.

**Geplant wird auf Zuruf — oder einmal die Woche, wenn man darum bittet**
(`ki/automatik.py`, `KiSettings.auto_plan_enabled`). Es gab hier einmal eine
Automatik mit einer **eigenen Viertelstundenschleife**, die den nächsten Block
anlegte, sobald der alte auslief; sie wurde entfernt, weil ein Plan, der über
Nacht von selbst entsteht, am Morgen auf der Uhr steht, ohne dass ihn jemand
bestellt hätte. Zurück ist die Funktion, nicht die Bauart.

**Einmal die Woche, nicht täglich.** Die Automatik plante zuerst nach *jedem*
automatischen Abgleich, also jeden Tag. Ein Block deckt aber sieben Tage ab:
Täglich neu geplant wurde von jedem Block nur der erste Tag je erreicht, und
was die KI auf Tag 3 legte, fand nie statt — der Prompt brauchte einen eigenen
Absatz, um sie darauf hinzuweisen. Dazu kostete jeder Lauf Kontingent. Wochentag
und Uhrzeit stehen jetzt je Nutzer in `KiSettings` (`auto_plan_weekday` nach
`date.weekday()`, `auto_plan_hour`, `auto_plan_minute`; Vorgabe **Sonntag
09:00**).

**Kein zweiter Loop — aber auch nicht mehr am Abgleich.** Der Weckruf kommt aus
`garmin/automatik.starte_faellige_planung()`, dem zweiten Zweig derselben
Schleife: Es gibt weiterhin genau **einen** Zeitgeber im Prozess. Ausgelöst
wurde die Planung dagegen einmal am Ende eines erfolgreichen automatischen
Abgleichs, aus `garmin/runner._fuehre_aus` heraus. Das garantierte die
Reihenfolge „erst die Daten, dann der Block", band die Planung aber an die
Uhrzeit des Abgleichs: Wer ihn auf 06:00 legte und die Planung auf Sonntag
09:00, bekam nie einen Block — und wer den Abgleich abschaltete, auch nicht.
Beide Zweige sind deshalb unabhängig. Die Reihenfolge trägt jetzt die Uhrzeit
(die Oberfläche sagt es dazu), und dass die Daten einen Tag alt sein können,
steht der KI ohnehin als `trainingshistorie.datenstand` zur Verfügung.

**Und der Schalter steht je Nutzer, ab Werk aus.** Nicht in der Umgebung: Ein
Wert aus `config.py` ließe sich ohne Neustart nicht ändern, und was Kontingent
verbraucht, schaltet der Nutzer selbst ein (Einstellungen → KI-Planung). Die
Riegel stehen in `ist_faellig()` und daneben: `auto_plan_enabled` muss stehen,
Wochentag und Uhrzeit erreicht sein, ein Fragebogen vorliegen (sonst scheiterte
der Lauf sicher und kostete trotzdem), und der Zugang tragen. Geplant wird dann
**ab heute** mit `PLAN_DAYS_DEFAULT` — der laufende Block wird ersetzt, wie bei
„Neu planen ab heute". Ein Fehlschlag wird protokolliert und verschluckt: Der
Aufrufer ist eine Schleife, die weiterlaufen muss.

**Die Wochensperre zählt Tage, nicht Wochentage.** `(heute - last).days >= 7`
statt „an diesem Wochentag noch nicht gelaufen": Sonst liefe ein zweiter Block
in derselben Woche, sobald jemand den Wochentag mitten in der Woche umstellt.
Vorgemerkt wird **vor** dem Start, nicht danach — der Lauf hängt an einem
eigenen Schloss und meldet sich nicht zurück, und eine Minute später wäre
derselbe Tag sonst noch einmal fällig.

`plan_days` bleibt Altlast an `KiSettings` (NOT NULL in bestehenden
Datenbanken); die Blocklänge kommt aus `ai_export.PLAN_DAYS_DEFAULT`.

**Die alte Zustimmung zählt nicht.** `auto_plan_enabled` stand in echten
Datenbanken auf 1 — von damals. Die Spalte wieder zu lesen hätte die Planung
bei genau den Nutzern anspringen lassen, die sie vor Monaten einmal
eingeschaltet hatten. `database._ZURUECKZUSETZENDE_ALTWERTE` setzt sie deshalb
genau einmal zurück: in dem Lauf, der `ki_settings.token_encrypted` ergänzt —
dessen Fehlen kennzeichnet die Datenbanken von vor dieser Änderung. Danach
greift nichts mehr, sonst stünde der Schalter nach jedem Neustart wieder auf
aus.

`test_die_planung_hat_keine_eigene_schleife` hält fest, was gilt: kein
`automatik_schleife` im Modul, kein `KI_AUTOPLAN`/`KI_PLAN_HOUR` in der
Konfiguration, und **genau ein** `asyncio.create_task` in `main.py` — eine
Weckschleife, die wieder einzöge, fiele sonst erst am aufgebrauchten Kontingent
auf, und dann an einem Tag ohne Plan.

**Der Zugang steht in der App, verschlüsselt** (`KiSettings.token_encrypted`,
`client.token_aus`). Er kam einmal ausschließlich aus den Add-on-Optionen —
dafür musste man die App verlassen, ihn in Home Assistant eintragen und das
Add-on neu starten, und er lag als Klartext in `/data/options.json` und damit
in jedem Backup. Jetzt liegt er je Nutzer in der Datenbank, mit demselben
Verfahren gesichert wie das Garmin-Token (`crypto.py`); die Umgebungsvariable
bleibt als Rückfall, die Anmeldung der CLI als letzter. Herausgegeben wird er
**nie** — `KiSettingsOut` trägt nur `token_status` (`fehlt` | `hinterlegt` |
`unlesbar`). Der dritte Wert ist kein Luxus: Nach einem Wechsel von
`TRI_SECRET_KEY` ist der Geheimtext unlesbar, und das sieht sonst aus wie „kein
Token" — heilbar ist es aber nur durch erneutes Eintragen. `token_aus()` gibt
dafür `None` zurück statt zu werfen, damit ein unlesbarer Eintrag den Rückfall
nicht blockiert. Und der Cache in `ist_angemeldet()` hängt seither **am Token**:
Ein einziger Eintrag beantwortete die Frage für Nutzer B mit dem Ergebnis von
Nutzer A, und ein frisch eingetragener Token gälte eine Minute lang als
ungültig.

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
Variable gesetzt ist. Der Zugang kommt aus den Einstellungen des Nutzers, aus
der Add-on-Option oder aus der Anmeldung der CLI selbst — die Frage ist in allen
drei Fällen dieselbe, die Antwort steht nur an verschiedenen Orten. Das Ergebnis
wird eine Minute lang gehalten, damit nicht jedes Laden der Seite einen Prozess
startet, **je Token** und nicht global (siehe „Der Zugang steht in der App").
`POST /api/ki/pruefen` geht mit `erzwinge=True` daran vorbei.
