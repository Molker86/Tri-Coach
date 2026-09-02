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
stehen und werden zur leeren Zelle. Gefiltert wird nur in den JSON-Köpfen — und
seit dem Umbau auf drei Ebenen fallen Spalten weg, die in **keiner** Zeile etwas
tragen (`_leerspalten_streichen`); das ist verlustfrei und bei einem Athleten
ohne Leistungsmesser fünfzig leere Zellen weniger.

Für dieselbe Regel gilt bei den **aufgefächerten** Feldern ein eigener Schritt.
`zeit_in_hf_zonen_min` wird zu `…z1` bis `…z5`, und aufgefächert wurde je Zeile
— ordnet man danach nach erstem Auftreten, landet ein Unterschlüssel, den erst
eine spätere Zeile trägt, am Ende der Tabelle. An echten Daten stand
`zeit_in_hf_zonen_min.z5` hinter `effizienz` und `rpe_quelle`, weil die erste
Einheit keine Zone 5 hatte. `_faecherschluessel()` sammelt den Schlüsselsatz
deshalb **vorher über alle Zeilen** ein, und jede Zeile bekommt ihn ganz. Erstes
Auftreten und nicht alphabetisch, aus demselben Grund wie bei `_spalten`:
`intensitaetsverteilung_pct` heißt `niedrig`, `mittel`, `hoch`, und alphabetisch
stünde `hoch` vorn.

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

## Drei Auflösungsebenen

**Der Rückblick ist keine Fensterbreite mehr, sondern eine Auflösung.** Bis
hierher legte der Export genau vier Wochen vor — jede Einheit einzeln, dieselben
vier Wochen daneben noch einmal als Wochenübersicht. Das beantwortete eine
Frage („wo steht er gerade?") und zwei nicht: ob er aus einer Pause kommt und
ob es über die Saison aufwärts geht. Beides ist aus einem Vierwochenfenster
**grundsätzlich** nicht abzulesen, egal wie genau es beschrieben ist.

Seither steht derselbe Verlauf dreimal, immer gröber:

| Ebene | Konstante | Reicht | Form | Zeilen |
|---|---|---|---|---|
| 1 | `HISTORY_WEEKS = 6` | 42 Tage | `trainingshistorie.einheiten`, je Einheit eine Zeile | ~50 |
| 2 | `WOCHENUEBERSICHT_WOCHEN = 26` | ein halbes Jahr | `trainingshistorie.wochenuebersicht`, je Kalenderwoche eine Zeile | ~27 |
| 3 | `VERLAUF_MONATE = 12` | ein Jahr | `athlet.verlauf`, je Monat eine Zeile | ~12 |

**42 Tage sind keine gerundete Zahl.** Es ist genau das Fenster, in dem
`garmin/sync.py` Abschnitte, Übungen, Nettozeit und Befinden überhaupt holt
(`BEWERTUNGSFENSTER_TAGE`, `TAGESSCHLEIFE_TAGE`). Ein weiterer Rückblick auf der
Einzelebene brächte nur noch Einheiten ohne Ausführungsdetail — und die
beschreibt die Wochenzeile kürzer.

**Die Ebenen überlappen, und der Prompt sagt das ausdrücklich.** Die
Wochenübersicht deckt *alle* 26 Wochen ab, die sechs der Einzelebene
eingeschlossen. Sie herauszurechnen wäre naheliegend und falsch:
`letzte_volle_woche` ist der Bezugspunkt der Aufbauregel und liegt genau dort.
Der Preis ist ein Satz im Prompt — „die jüngsten Wochen stehen in mehreren
Ebenen, zähle sie nicht doppelt" —, und der ist nicht verhandelbar: Ohne ihn
addiert das Modell dieselbe Woche zweimal und liest daraus einen Umfang, den es
nie gab. Dafür wurde die Längenbremse in `test_der_anweisungstext_bleibt_kurz`
von 9000 auf 9500 Zeichen angehoben.

**Ebene 3 kommt aus `WellnessDay`, nicht aus `ProfileHistory`** — obwohl die
zweite genau die sechs Größen führt, um die es geht, und obwohl sie vorher die
Quelle war. Sie entsteht ereignisgetrieben: `profile_sync` schreibt nur bei
einer Änderung über einer Schwelle, und das erst, seit es diese App gibt. An
echten Daten standen dort **zwölf Zeilen aus drei Wochen** — der Jahresverlauf
war für elf von zwölf Monaten leer, und niemand hat es gemerkt, weil ein
fehlender Schlüssel kein Fehler ist. `WellnessDay` ist dagegen ein lückenloses
Tagesraster über das ganze Backfill-Jahr (`RUECKBLICK_TAGE = 365`). Von
`ProfileHistory` bleiben nur FTP und Maximalpuls: Die misst Garmin nicht
täglich. Sie stehen deshalb meist an einem einzigen Monat, und die neue
Leerspaltenregel lässt sie ganz weg, wo gar nichts vorliegt.

Aus dem Tagesraster kommt der **Monatsmittelwert**, nicht der jüngste Tageswert
des Monats. Ein einzelner Ruhepuls- oder HRV-Tag ist Rauschen, und Rauschen ist
das Gegenteil dessen, was diese Ebene zeigen soll.

**`effizienz_je_sportart` trägt die Ebene, nicht `vo2max`.** Die naheliegende
Fortschrittsgröße wäre die VO2max — Garmin schätzt sie aber nur bei passenden
Aktivitäten, an echten Daten an 41 von 383 Tagen. Tempo bzw. Leistung je
Herzschlag lässt sich dagegen aus fast jeder Einheit mit Puls und Distanz
rechnen und trennt „langsamer geworden" von „müder geworden". Beide stehen
nebeneinander; wo die VO2max fehlt, bleibt die Effizienz.

**Was die Ebenen kosten.** An echten Daten wuchs der Prompt von 28.513 auf
34.432 Zeichen (+21 %, grob 9k auf 11k Token). Die Einzeleinheiten gingen von 32
auf 48, die Wochenzeilen von 5 auf 27, der Monatsverlauf von **einer** Zeile auf
elf. Die Abschnitts- und Übungstabellen — der größte Einzelposten des Pakets —
wuchsen **gar nicht**, weil Garmin sie ohnehin nur 42 Tage liefert. Gegenfinanziert
wurde ein Teil davon: `kalorien` und `trimp` sind aus der Einheitenzeile
gefallen (das erste trägt keine Planungsentscheidung, das zweite stand als
hergeleitete Größe neben der gemessenen `garmin_trainingslast`), `by_sport` steht
nur noch an den jüngsten sechs Wochen (`BY_SPORT_WOCHEN`), und durchweg leere
Spalten fallen jetzt ganz weg.

`pace` und `wochentag` sind dabei **geblieben**, obwohl beide ableitbar sind: Aus
den Ist-Paces setzt das Modell `target_pace` der neuen Einheiten, und
Datumsarithmetik ist das Unzuverlässigste, was ein Sprachmodell tut. Zusammen
kosten sie über fünfzig Zeilen keine 200 Token.

**Nebenbei mitgewachsen:** `monotonie` und `strain` entstehen nur an
*vollständigen* Wochen. In einem Vierwochenfenster waren das drei von fünf
Buckets, jetzt sind es fünfundzwanzig von siebenundzwanzig — dieselbe Rechnung,
nur mit Datenbasis. Und `plan_aufraeumen.verfallene_erbschaft_loeschen()` hängt
seit jeher an `HISTORY_WEEKS` und reicht damit von selbst sechs statt vier
Wochen zurück; genau so war es dort dokumentiert.

**Die Ernährung bekommt die Wochenübersicht gekürzt** (`ERNAEHRUNG_WOCHEN = 6`).
Sie steht in `ERNAEHRUNG_HISTORIE_FELDER`, und der Energiebedarf von morgen hängt
am aktuellen Umfang — nicht daran, wie im Frühjahr trainiert wurde. Ohne die
Kürzung wären sechsundzwanzig Wochenzeilen in einen Prompt gewandert, der von
vier bis sechs lebt.

---

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
| Wohin geht die Form über Monate? | `WellnessDay` (früher `ProfileHistory`) | wurde **nie** exportiert — und die damalige Quelle war ohnehin leer, siehe „Drei Auflösungsebenen" |
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

**Der Verzicht ist eine Angabe, kein Fehlen** — und das war ein echter Fehler.
`paketformat._ohne_leere()` wirft `None`, `{}` und `[]` aus den JSON-Köpfen; bei
`supplemental: []` fehlte `zusatztraining` im `trainingswunsch`-Kopf also
vollständig. Punkt 3 stand trotzdem unverändert im Prompt und verwies darauf:
„was davon überhaupt in den Block gehört, sagt `trainingswunsch.zusatztraining`".
Ein Verweis auf ein Feld, das nicht dasteht — und die KI füllte die Lücke mit
Kraft- und Mobilityeinheiten, die der Athlet ausdrücklich abgewählt hatte.
Aufgefallen ist es an einem zweiten Konto, weil dort zum ersten Mal jemand
nichts davon wollte.

Zwei Änderungen, beide klein: `_request_block()` schreibt
`ai_export.KEIN_ZUSATZTRAINING` (`"keines"`) statt der leeren Liste — Strings
lässt `_ohne_leere()` ausdrücklich stehen. Und `_prinzip_ergaenzung()` wählt
danach die Fassung: `PRINZIP_KEIN_ERGAENZUNG` verbietet beide Sportarten in
einem Satz, statt eine Anleitung zu geben, die der Block nicht brauchen darf.
Dieselbe Bauform wie `_fitnessregeln()` und `_wettkampfhinweis()`, aus demselben
Grund — und nebenbei kürzer als der Absatz, den es ersetzt.

**Das Verbot hängt am ausdrücklichen `"keines"`, nicht am fehlenden Feld.** Ohne
Fragebogen steht `trainingswunsch` überhaupt nicht im Paket, und das heißt
„nicht gewählt", nicht „abgewählt" — dann gilt weiter die volle Anleitung. Die
gleiche Unterscheidung trägt `plan_import.validate_coverage()`: `None` heißt
„kein Fragebogen, also keine Prüfung", die leere Liste heißt „ausdrücklich
nichts davon" und ist damit die **schärfste** Vorgabe, nicht die schwächste. Wer
die beiden Fälle zusammenwirft, leitet aus einer fehlenden Angabe ein Verbot ab,
das der Athlet nie ausgesprochen hat.

Nachgeprüft wird es trotzdem: `_ungewolltes_ergaenzungstraining()` meldet Kraft-
und Mobilityeinheiten, die nicht im Fragebogen stehen — gemeldet, nicht
gelöscht, dieselbe Linie wie bei `_fremde_sportarten()`. Eine Einheit zu
entfernen risse ein Loch in den Tag, und das ist die teurere Antwort auf etwas,
das der Athlet notfalls selbst anpasst.

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

**Der Lauf ist ein Job, und es läuft einer je Konto.** Er dauerte in zwei
Messungen 85 s und 211 s — der Unterschied kommt aus der Denkzeit, nicht aus
der Prompt-Größe. Hinter dem Ingress wäre eine so lange HTTP-Antwort ein
Risiko, und der Nutzer säße vor einem Balken ohne Rückmeldung. Aufbau und
Zustandsnamen wie bei `GarminSyncJob`, damit `pollJob` im Frontend für beide
gilt.

**Aber nicht derselbe Riegel wie bei Garmin.** Dort läuft ein Job im ganzen
Prozess, und das ist richtig: Dahinter steht Garmins Anfragegrenze an der
Herkunftsadresse, die sich alle Konten teilen. Hier stand einmal dasselbe
globale Schloss — und dahinter nichts Geteiltes. Ein Lauf kostet einen
Unterprozess und das Kontingent des Kontos, das ihn anstößt; beides gehört
diesem Konto allein. Ein zweiter Nutzer bekam trotzdem „Gerade läuft der
Planungslauf eines anderen Kontos". Der Runner hält über den Lauf deshalb gar
kein Schloss mehr, sondern einen Vermerk je Nutzer (`_laeufe: user_id →
job_id`); das eine verbliebene Schloss steht nur um „prüfen, anlegen,
vormerken" und ist nach Millisekunden wieder offen. Was bleibt, ist die
Trennung von Garmin: Der Import am Ende stößt eine Garmin-Übertragung an, die
sonst auf ein Schloss liefe, das der Planungslauf selbst noch hielte.

**Prüfen und Vormerken sind ein Zug.** `_pruefe_startbar` im Router ist nur die
freundliche Vorprüfung, damit die Meldung kommt, bevor die Route ihre übrige
Arbeit tut; verbindlich entscheidet `runner.starte()`, weil erst dort der
`KiJob`-Insert und der Vermerk unter demselben Schloss stehen. Getrennt bliebe
genau das Fenster, das es früher gab: Der Vermerk entstand erst **im** Faden,
nach dem Erwerb des Schlosses, und zwei schnelle Klicks kamen beide durch — der
zweite hing danach unsichtbar am Schloss. Aufgefangen hat das nur dieses
Schloss, als Nebenwirkung. Die Absage ist `LaeuftBereits`, und sie steht
bewusst **nicht** in `errors.py`: Alles dort erbt von `KiFehler`, und
`_notiere_fehler` schriebe sie als Fehlschlag an einen Job.

**Vier Jobarten, ein Runner.** `manual` plant den Block, `einheit` passt eine
Einheit an, `ernaehrung` schreibt den Ernährungsplan, `tagesform` prüft den
heutigen Tag. Alle vier teilen sich Zustände, Fortschrittsleiter, Abbruch und
`GET /api/ki/jobs/{id}` — und **einen Vermerk je Konto**: Ein Nutzer hat
höchstens einen Lauf, quer über alle Jobarten; wer den Ernährungsplan schreiben
lässt, kann nebenher keine Einheit anpassen (der Ernährungsplan liest den
Block, den ein Planungslauf gerade ersetzt). Läufe fremder Konten stören dabei
nicht. Die Verzweigung in `_lauf` ist eine `elif`-Kette mit der Blockplanung
als `else`; wer eine fünfte Art ergänzt, hängt sie **davor**, sonst plant sie
still einen Trainingsblock. Die Anfangsmeldung kommt aus `_STARTMELDUNG` — beim
dritten Fall wurde der Bedingungsausdruck unlesbar.

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
Vorgemerkt wird **vor** dem Start, nicht danach — der Lauf läuft in einem
eigenen Faden und meldet sich nicht zurück, und eine Minute später wäre
derselbe Tag sonst noch einmal fällig. Der Preis ist ein schmales Fenster:
Drückt der Nutzer in derselben Sekunde selbst, wirft `runner.starte()`
`LaeuftBereits`, die Automatik verschluckt es still — und die Woche ist
verbraucht, ohne dass ein Block entstanden wäre. Die Reihenfolge bleibt
trotzdem, weil sie den häufigeren Fall trägt.

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

**Die Tagesanpassung hängt am Abgleich, und zwar mit Absicht**
(`ki/tagesform.py`, `KiSettings.auto_tagesform_enabled`). Ein Block deckt sieben
Tage ab; was auf Tag 4 liegt, wurde vier Tage vorher entschieden — auf einer
Erholungslage, die es an diesem Morgen noch gar nicht gab. Gleichzeitig holt der
tägliche Abgleich genau die Werte, an denen das hängt, und bis zum nächsten
Sonntag liest sie niemand. Der Schalter schließt die Lücke: Ist der Abgleich
durch, wird geprüft, ob die Einheiten von heute noch zum heutigen Tag passen.

**Zwei Absätze weiter oben steht das Gegenteil, und beides stimmt.** Die
*Planung* wurde vom Abgleich gelöst, weil sie nichts von ihm braucht — ihn
abzuwarten kostete sie ihre eigene Uhrzeit. Hier ist der Abgleich der ganze
Gegenstand: Vor ihm gäbe es nichts zu entscheiden, und eine eigene Uhrzeit liefe
seinen Werten entweder hinterher oder voraus. Der Anstoß steht deshalb wieder in
`garmin/runner._fuehre_aus` — aber **außerhalb** des Schlosses, denn am Ende
schiebt der Lauf geänderte Einheiten nach Garmin und liefe sonst in ein Schloss,
das der Abgleich selbst noch hält. Und nur nach `kind == "auto"`: Wer abends
„Jetzt abgleichen" drückt, will seine Historie sehen, nicht seine Einheit
umgeschrieben bekommen. Dass der Lauf **erfolgreich** war, wird nicht
durchgereicht, sondern an `konto.last_sync_at` abgelesen — den setzt nur ein
geglückter Abgleich, und dieselbe Frage („sind die Daten von heute da?")
beantwortet damit denselben Ausdruck.

**Ein vierter Jobtyp, kein aufgebohrter dritter.** Naheliegend wäre gewesen,
`kind="einheit"` mit einem erfundenen Wunsch zu starten — zehn Zeilen. Aber der
Einheitsprompt ist ganz um „Sein Wunsch, im Wortlaut" herum gebaut und räumt ihm
ausdrücklich Vorrang vor der Trainingslehre ein. Einen Wunsch zu erfinden hieße,
dem Modell an genau der Stelle etwas vorzuschreiben, an der es selbst entscheiden
soll, und es bekäme einen Auftrag zu *ändern*, wo der Auftrag lautet:
nachzusehen, ob zu ändern ist. `_lauf` hat seither **vier** Zweige, und der
Auffangfall ist weiterhin die Blockplanung.

**Unverändert ist der Regelfall, und der Prompt sagt es als Erstes.** Ein Modell,
das gefragt wird, ob etwas zu ändern ist, ändert etwas. Der Absatz steht deshalb
vor den Prinzipien und nennt „alles bleibt" ausdrücklich eine **vollständige**
Antwort — samt der Bitte, auch dann zu sagen, woran es festgemacht ist.
Schwellenzahlen stehen keine darin: Gelesen wird der Tageswert gegen die an
diesem Athleten **gemessene** Grenze (`hrv_normalbereich_ms`,
`training_status.lastfenster`), genau wie beim Block. Technisch trägt das
`unveraendert: true` je Eintrag — die Zeile wird dann gar nicht erst angefasst,
und `angepasst_am` bleibt leer.

**Der ganze Tag, nicht eine Einheit.** Ein Tag kann mehrere tragen, und sie
hängen zusammen: Wer den harten Lauf zurücknimmt, entscheidet damit auch über die
Mobility daneben. Ein Lauf je Einheit hätte beides nicht gewusst und zwei bis
drei Opus-Läufe an einem Morgen gekostet. Zugeordnet wird über die `nr` aus
`tagesform.einheiten_heute` und **nicht** über die Position in der Liste: Lässt
das Modell eine Einheit aus, landete die Anpassung der einen sonst auf der
anderen, ohne dass irgendwo etwas fehlschlüge.

**Die Riegel stehen alle in `ist_faellig()`, und jeder aus eigenem Grund.** Der
Schalter muss stehen; der Abgleich muss heute durch sein; einmal am Tag reicht
(der Merker wird **vor** dem Start gesetzt, wie bei der Planung); und **am
Planungstag setzt sie aus** — der frische Block entsteht ohnehin aus denselben
Werten, beides an einem Morgen zahlte zwei Läufe, von denen einer verworfen wird.
Geprüft wird das in beide Richtungen: schon gelaufen und heute noch fällig.
Daneben, in `_passe_an()`: kein Lauf ohne planbare Einheit von heute (ein Ruhetag
ist eine Entscheidung des Blocks über die Woche, kein Mangel an Lust) und keiner,
wenn heute schon **von Hand** angepasst wurde — wer der App gerade gesagt hat,
was er will, bekommt es nicht Stunden später überschrieben. In beiden Fällen
bleibt der Merker aus: Es ist nichts geschehen, was ein zweites Mal geschähe.

**Und ein Ausstieg, bevor es Kontingent kostet.** Trägt der Payload keinen
`fitnessdaten`-Block, endet der Lauf als `done` mit einem Satz dazu — ohne einen
einzigen Aufruf gegen Claude. Der Prompt fragt nach den Werten von heute; ohne
sie bliebe eine Aufgabe ohne Gegenstand übrig, und die Antwort darauf wäre
geraten.

**Die Begründung muss die Nacht überleben** (`PlanSession.anpassungsbegruendung`).
Bei der Anpassung von Hand steht sie in der Meldung des Jobs, und das reichte,
weil der Athlet daneben stand. Hier ist der Lauf um sechs Uhr früh vorbei, bevor
jemand die App öffnet, und die Meldung eines abgeschlossenen Jobs rutscht aus der
Liste — eine Einheit, die ohne sichtbaren Grund anders aussieht als gestern
Abend, wäre der schlechteste aller Zustände. Die Spalte hebt nebenbei auch die
Einzelanpassung, wo der Grund bisher mit dem Wegklicken verschwand.

**`anpassungswunsch` bleibt dabei leer, und das ist die Unterscheidung.** Dort
einen Satz wie „Automatisch angepasst" abzulegen wäre bequem gewesen; die
Ansicht liest das Feld aber als Wunsch („auf den Wunsch ‚automatisch
angepasst'"), und ein Feld, das mal eine Bitte und mal eine Erklärung trägt, ist
keins mehr. Leer heißt jetzt genau eines: Diese Anpassung ging von Messwerten
aus, nicht von einer Bitte. Beides reist als `frueherer_anpassungswunsch` bzw.
`frueherer_anpassungsgrund` in den nächsten Lauf, damit der die bereits
angepasste Einheit nicht für die ursprüngliche Planung hält.

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
