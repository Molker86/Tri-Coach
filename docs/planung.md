# Planung: Blöcke, Neuplanung, Einzelanpassung, Disziplin

Teil der Kontextdokumentation von Tri-Coach. Überblick, Setup und Konventionen:
[CLAUDE.md](../CLAUDE.md).

**Planungshorizont: wenige Tage, Rückblick vier Wochen** (`ai_export.py`,
`PLAN_DAYS_DEFAULT = 7` / `HISTORY_WEEKS = 4`). Ein Plan ist nach der ersten
Woche ohnehin überholt, und für die KI ist ein kurzer Block die deutlich
leichtere und präzisere Aufgabe: statt 28 Tagen füllt sie ein paar Tage, die
dafür genau zur aktuellen Belastungslage passen. Die Individualität kommt nicht
aus der Länge des Plans, sondern aus der Historie — die bleibt vier Wochen tief
und wandert vollständig in jeden Export. Ein aktiver Plan kann per Knopfdruck
um die nächsten 7 Tage verlängert werden (oder beliebig oft wiederholt); die
Auswertung bezieht sich weiterhin auf die letzten 4 Wochen, nicht auf die
bisherige Blocklänge — seit `compliance(seit=…)` gilt das auch für die
Umsetzungsquote, die vorher jeden Tag des Blocks zählte. Deshalb liefert `_history_block()` zusätzlich
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
Einheiten — **außer den bereits absolvierten**: Wer morgens läuft und mittags
neu plant, hat eine erledigte Einheit auf dem Starttag liegen, und seit ein Block
die Vergangenheit seines Vorgängers übernimmt, hängt sie an genau dem Plan, den
`_ersatz_block()` durchsieht. Ungefiltert stünde derselbe Lauf zweimal im Payload
(hier „verworfen", in der Historie „absolviert"), und die KI setzte Ersatz für
einen Reiz, den der Athlet längst gesetzt hat. und der Prompt bekommt über `{ersatzhinweis}` einen Absatz dazu —
ausdrücklich als Kontext und **keine Vorgabe**, mit dem Zusatz, dass allein
`trainingshistorie.einheiten` sagt, was tatsächlich stattgefunden hat (geplant
ist nicht absolviert). Ohne Überschneidung fehlen Schlüssel und Absatz, denn beim
Anhängen des nächsten Blocks wird nichts ersetzt.

Zweitens **stapelten sich die abgelösten Blöcke**: Wer täglich neu plant, hatte
nach einem Monat dreißig Pläne unter „Frühere Pläne", von denen jeder genau einen
Tag trug. `raeume_abgeloeste_plaene()` löscht deshalb, was der aktive Block
überdeckt, in die Zukunft ragt und weder ein erfasstes Training noch eine
Garmin-Übertragung trägt — ein abgeschlossener Block bleibt als Verlauf stehen,
ein beiseitegelegter ohne Überschneidung ebenso. Die Garmin-Bedingung ist dabei
zwingend und nicht bloß vorsichtig: Was in Garmin liegt, wird ausschließlich über
`GarminWorkoutLink` wieder aus dem Kalender entfernt, und der stirbt mit dem
Plan; der dauerhafte Pool-Slot bleibt bestehen. Deshalb läuft
dasselbe Aufräumen an **zwei** Stellen — beim Import und am Ende jedes
Garmin-Laufs, wo `raeume_ersetzte_auf()` die Einheiten gerade aus dem fremden
Kalender genommen hat und die Bedingung damit erfüllt ist.

**Erfüllbar ist die Bedingung „trägt kein Training" allerdings erst, seit die
Vergangenheit umzieht** (`uebernimm_vergangenheit`). Sie war der eigentliche
Riegel: An einem Block, der auch nur einen Tag lang getragen hat, klebt ein
`SessionLog` — und wer täglich neu plant, produziert genau das täglich. Gelöscht
werden durfte er trotzdem nie, denn an `PlanSession.id` hängen `_geplant_war`,
die Zuordnung der nächsten Aktivität (`PlanSession.garmin_workout_id`) und die
Umsetzungsquote.

Deshalb **zieht die Einheit um, statt zu sterben**: Sie behält ihre Kennung, ihren
Log und ihre Garmin-Zuordnung (`GarminWorkoutLink` zeigt auf `plan_session_id`,
nicht auf den Plan), nur ihr Plan ist ein anderer. Zwei Mengen wandern in den
ablösenden Block — alles vor dessen `beginn` (diese Tage plant er gar nicht) und
jede Einheit mit erfasstem Training, auch die von heute (wer morgens läuft und
mittags neu plant, hätte sonst genau einen Block, der ewig stehen bleibt; ihr
`order_in_day` rückt hinter das, was der neue Block für den Tag vorsieht). Danach
hält der abgelöste Block nur noch Tage, die der neue ohnehin beansprucht, und darf
verschwinden. An echten Daten geprüft: sieben Tage tägliche Neuplanung ergeben
**einen** Plan statt sieben, und alle sieben absolvierten Tage behalten den
Aufbau des Blocks, der sie damals geplant hat.

**Das Erbe reicht so weit wie der Rückblick und keinen Tag weiter**
(`verfallene_erbschaft_loeschen`, `HISTORY_WEEKS`). Ohne Grenze schleppte ein
Block nach einem Jahr täglicher Neuplanung 365 vergangene Tage mit — und jenseits
des Fensters liest sie **niemand**: `_geplant_war` läuft ausschließlich über
`recent`, `compliance()` zählt ab `beginn`,
`anpassbare_einheit` lässt nur Tage ab heute zu, `planbare_einheiten()` filtert
auf `beginn`. Übrig bliebe allein die Planansicht, und dort ist die Vergangenheit
eingeklappt. Die Grenze ist deshalb dieselbe Konstante, die auch das Fenster
aufspannt, und nicht eine zweite daneben: Wird der Rückblick je vertieft, wächst
das Erbe von selbst mit.

Drei Bedingungen, jede aus eigenem Grund. **Nur Geerbtes** (`date <
aktiv.beginn`) — seine eigenen Tage behält ein Block für immer, auch ein Block,
den seit Monaten niemand ersetzt hat, soll sich nicht selbst auflösen. **Kein
`GarminWorkoutLink`** — dieselbe zwingende Bedingung wie beim Löschen eines
Blocks; nach vier Wochen hat `raeume_vergangene_auf()` den Termin längst
zurückgenommen, aber „in der Praxis nie" ist kein Grund, einen Termin im fremden
Kalender zurückzulassen. Und **der Log wird gelöst, nicht gelöscht**: Das
absolvierte Training ist der Verlauf, verloren geht nur der Verweis auf den
geplanten Aufbau — und den liest ab dort ohnehin niemand mehr.

An 365 simulierten Tagen gemessen: Der aktive Block läuft auf 35 Einheiten auf
(28 geerbte plus sieben eigene) und bleibt ab Tag 28 dort stehen; `plans` bleibt
bei eins, `GET /api/plans/active` bei 15,3 kB, und alle 29 Historieneinträge des
Exports tragen weiterhin ihren geplanten Aufbau.

Der Preis steht unter „Bekannte Grenzen": Ein gelöschter Plan nimmt die ganze
Kette mit.

**`Plan.geplant_ab` ist die Spalte, die das trägt.** Sobald `start_date` rückwärts
wandert, verliert die App ihre Antwort auf „welche Tage hat *dieser* Block selbst
vorgesehen?" — und die brauchen fünf Stellen: die Kalendergrenze in
`ersetzte_links()`, `planbare_einheiten()`, die Umsetzungsquote
(`compliance(seit=…)`), `aktueller_plan` im Export und `_blockumfeld()` der
Einzelanpassung. Jede ad hoc zu begrenzen hieße fünf verschiedene Grenzen, und
fünf Grenzen laufen auseinander. `geplant_ab` wird einmal in `build_plan()` gesetzt
und nie wieder angefasst; `Plan.beginn` fällt an Blöcken von vor der Spalte auf
`start_date` zurück — dort galten beide noch dasselbe. Dass `start_date` trotzdem
wandert, ist Absicht: Der Plan zeigt, was er zeigt, und die geerbten Tage stehen
in ihm.

**Wann gelöscht werden darf, ist eine Zeitfrage — und sie hat echte Historie
gekostet** (`nur_zukunft`). Die Bedingung „an diesem Block hängt kein Training"
wird beim Import zu einem Zeitpunkt geprüft, an dem sie noch gar nicht stimmen
*kann*: Das Training des Tages liegt auf der Uhr, aber nicht in dieser Datenbank
— es kommt erst mit dem nächsten Abgleich. Am 16.08.2026 wurde um 16:24 neu
geplant, die Mobility desselben Tages kam um 17:41 aus Garmin; dazwischen war der
Block gelöscht, und die Einheit steht bis heute ohne ihren Aufbau im Export. Wer
täglich neu plant, zerstörte so laufend seine eigene Historie — und genau daraus
entstand die Beschwerde, dieselbe Mobility-Einheit zweimal vorgeschlagen zu
bekommen.

**Die Lehre daraus lautet nicht „warte einen Tag", sondern „zerstöre keine
`PlanSession`, an der noch ein Training landen kann".** Das Warten war das Mittel,
solange es kein anderes gab. Seit die Zeile umzieht statt zu sterben, behält sie
ihre Kennung samt Workout-Vermerk, und `finde_planeinheit()` findet sie am Abend
genauso wie vorher — der Schutz ist nicht aufgegeben, sondern durch einen
stärkeren ersetzt.

Gefragt wird deshalb nicht mehr nach `start_date` (der beschreibt nach dem Umzug
eine Vergangenheit, die der Block gar nicht mehr hält), sondern danach, was
**übrig** ist: Kein verbliebener Tag darf vor heute liegen. Damit greift der
Riegel genau dort weiter, wo er soll — löst jemand am Tag nach der Neuplanung eine
Übertragung aus, ohne dass ein Abgleich dazwischenlag, hält der abgelöste Block
noch seinen Tag der Neuplanung, und der verbietet das Löschen
(`runner._raeume_workouts_auf(…, nach_abgleich=False)`). Erst der Abgleich, der
die Aktivitäten gerade geholt und über `finde_planeinheit()` verknüpft hat,
darf urteilen. **Ohne verbundenes Konto greift die Schonung nicht**: Dann entstehen
nie Trainings und käme nie ein Garmin-Lauf, der aufräumt — die Blöcke sammelten
sich für immer.

Im Frontend rechnet `planung.ts` beide Startdaten aus: heute für den Ersatz, der
Tag nach dem Blockende fürs Anhängen — **nie rückwirkend**, ein vor einer Woche
ausgelaufener Block startete sonst in der Vergangenheit. Datiert wird in Ortszeit,
weil `toISOString()` hierzulande abends bereits den Folgetag liefert und ein Block
„ab heute" dann einen Tag zu spät anfinge.

**Eine einzelne Einheit wird angepasst, nicht ersetzt** (`ai_export.erzeuge_einheit_export`,
`plan_import.uebernimm_einheit`, `garmin.automatik.uebertrage_geaenderte_einheit`).
Neben „Block neu planen" fehlte der kleine Eingriff: Der Plan stimmt, nur die
Einheit von heute passt nicht mehr — eine Stunde weniger Zeit, ein zwickendes
Knie, Lust auf eine andere Sportart. Dafür den ganzen Block wegzuwerfen wäre die
teure Antwort auf eine kleine Frage, und die Resttage entstünden neu, obwohl an
ihnen nichts falsch war. Der Athlet schreibt deshalb in einem Satz, was anders
werden soll, und bekommt genau diese eine Einheit zurück.

**Der Kontext ist derselbe wie beim ganzen Block** — Profil, Zonen, vier Wochen
Historie, Fitnessdaten. Eine Anpassung ist eine Trainingsentscheidung wie jede
andere; sie auf die Einheit und den Wunsch zu verkürzen hieße, sie ausgerechnet
dort ohne Belastungslage zu treffen, wo der Athlet vom Plan abweichen will.
Deshalb baut `_lade_kontext()` beide Pakete, und dazu kommt, was nur diese
Aufgabe braucht: der Wunsch im Wortlaut, die bisherige Fassung der Einheit und —
über `_blockumfeld()` — **der ganze Block mit der anzupassenden Einheit
markiert**. Ohne ihn entschiede die KI im luftleeren Raum: `aktueller_plan` in
der Historie nennt nur Titel und Zeitraum, aber woran der Abstand zum letzten
harten Reiz zu bemessen ist, steht am Vortag.

**Der Tag steht fest.** Verschieben kann der Athlet selbst — im Kalender, und
dort zieht die Planeinheit mit um. Geändert wird der Inhalt; `uebernimm_einheit`
liest aus der Antwort deshalb gar kein Datum. Geschrieben wird in **dieselbe
Zeile**, nicht in eine neue: Daran hängt der ganze Weg zurück auf die Uhr, denn
`GarminWorkoutLink` zeigt auf `plan_session_id`. Eine neue Einheit ließe die
alte samt Termin im fremden Kalender zurück.

**Ein eigener Prompt, aber geteilte Punkte 9 und 10.** Beim Block entscheidet die
KI über Zusammensetzung, Reihenfolge und Umfang; hier steht all das fest, und ein
Blockprompt mit angehängter Ausnahme lud zuverlässig dazu ein, den Rest gleich
mitzuplanen. Geteilt wird deshalb nur, woran unmittelbar der Workout-Bau hängt:
`PRINZIP_ERGAENZUNG` (der englische Übungsname in Klammern entscheidet über die
Animation auf der Uhr) und `PRINZIP_STEUERGROESSEN` (aus denselben Korridoren
baut die App das Workout), dazu `SESSION_SCHEMA` als Feldliste beider
Antwortformate. Zwei Kopien liefen auseinander, und dann bekäme dieselbe Einheit
je nach Weg einen anderen Aufbau. Die **Nummer** kommt aus der jeweiligen
Vorlage, der Text steht ohne sie.

Dabei ist eine stille Falle aufgefallen: `.format()` setzt Werte ein, **ohne sie
erneut zu formatieren** — ein Platzhalter in `FITNESSREGELN_*` bliebe wörtlich
stehen. Nötig war das trotzdem, denn beide Fassungen endeten mit „Nenne in
`summary`" bzw. „in `coaching_notes`", und keins der beiden Felder gibt es im
Antwortformat der Einzelanpassung: eine Aufforderung, danebenzuschreiben. Das
Feld heißt jetzt `{begruendungsfeld}` und wird von `_fitnessregeln()` gesetzt,
bevor der Wert in die Vorlage geht.

**Der Wunsch hat Vorrang, ist aber kein Freibrief.** Der Prompt sagt ausdrücklich,
dass der Athlet seinen Tag kennt und die KI seine Belastungslage — und dass ein
schädlicher Wunsch **so weit wie vertretbar** zu erfüllen ist, mit einem Satz
dazu in `begruendung`. Dieses Feld ist die einzige Stelle, an der der Athlet
erfährt, ob die KI ihm gefolgt ist; deshalb steht es in der Meldung des Jobs und
bleibt dort stehen, bis er es wegklickt.

**Aus einer Einheit darf Ruhe werden** — und dann muss der Termin weg. Das ist
der eigentliche Grund für `uebertrage_geaenderte_einheit()`: Bliebe die alte
Vorgabe an einem Tag stehen, an dem ausdrücklich nicht trainiert werden soll,
wäre das der irreführendste aller Zustände. Sonst ersetzt `uebertrage_einheit()`
den Inhalt der Pool-Vorlage an derselben Kennung und behält den Termin — „altes
weg, neues hin" ist im Pool-Betrieb genau das. Läuft alles im Anfrage- bzw.
Planungsthread, nicht als Job: zwei bis drei Anfragen, ein Fortschrittsbalken
dafür wäre Umstand ohne Nutzen. Das globale Schloss wird trotzdem genommen
(nicht blockierend), sonst belegte ein danebenlaufender Übertragungslauf
denselben Slot.

**Ein Fehlschlag gegen Garmin wird gemeldet, nicht geworfen** — und zwar für
*jede* Ausnahme, nicht nur die übersetzten: Die Bibliothek lässt auch alles
durch, was `requests` unterwegs auslöst. Die Einheit ist an dieser Stelle längst
angepasst und gespeichert; sie an einem Netzfehler scheitern zu lassen wäre die
falsche Rangfolge, und am Job stünde „fehlgeschlagen" über einer Einheit, die
tadellos angepasst wurde. Wohin der Hinweis verweist, hängt am Fall: auf den
Trainingsplan, wenn die Einheit dort noch steht — und auf den Garmin-Kalender,
wenn Ruhe daraus wurde, denn Ruhetage lässt `planbare_einheiten` aus.

**Ob die Automatik greift, entscheidet die Zuordnung, nicht der Schalter.** Steht
von der Einheit noch nichts in Garmin, gilt `auto_push_enabled` wie bei einem
frisch übernommenen Block. Liegt sie dort schon, wird sie auf jeden Fall
angefasst: Das Wegräumen dessen, was diese App selbst hingelegt hat, hängt nicht
am Schalter fürs Hinlegen — dieselbe Unterscheidung wie beim `cleanup`-Lauf.

**Zwei Grenzen, beide inhaltlich** (`routers.plans.anpassbare_einheit`, geprüft
von beiden Wegen). Vergangene Tage nicht: „Nachträglich ändern" heißt nach der
*Planung*, nicht nach dem Tag — eine Einheit von gestern umzuschreiben änderte
nichts an dem, was stattgefunden hat, verfälschte aber `_geplant_war` im nächsten
Export. Und absolvierte nicht: Hängt ein Training daran, ist sie Vergangenheit,
auch wenn ihr Tag noch läuft.

**Ruhetage lassen sich seit dieser Änderung anklicken** (`SessionCard.onOpen`).
Vorher war ein `rest`-Eintrag tot; jetzt kann aus einer Einheit Ruhe werden, und
ohne den Weg zurück wäre sie unerreichbar — man hätte sich selbst eine Falle
gebaut. Der Dialog lässt bei ihnen den leeren „Vorgaben"-Block und den Satz zum
Erfassen weg.

**Und wie überall: zwei Auslöser, ein Weg.** `POST /api/ki/einheit` startet einen
Lauf im `KiRunner` (`kind = "einheit"`, dieselben Zustände, derselbe Abbruch),
`GET …/anpassung-export` und `POST …/anpassen` bedienen die Zwischenablage. Beide
benutzen dieselben zwei Funktionen — `test_der_handweg_liefert_denselben_prompt`
vergleicht die erzeugten Texte Zeichen für Zeichen, damit sie es bleiben.

**Die gewählte Disziplin entscheidet, was im Block vorkommen darf**
(`schemas.DISZIPLIN_SPORTARTEN`, `ai_export._prinzip_disziplin`,
`_session_schema`). Der Fragebogen kennt vier Disziplinen — Laufen, Schwimmen,
Radfahren, Triathlon —, aber `discipline` steuerte im Backend **nichts**: Der
Wert wanderte als Label in den Payload und wurde sonst nirgends gelesen. Ein
reiner Läufer bekam damit wortgleich denselben Prompt wie ein Triathlet. Punkt 8
hieß „Triathlon" und erklärte ihm, welche der *drei* Disziplinen vorzuziehen sei
und wann eine Koppeleinheit passt; Punkt 13 riet bei Beschwerden, „den Reiz auf
eine Disziplin zu verlegen, die sie nicht berührt — bei drei Disziplinen ist das
fast immer möglich"; und das Antwortformat bot `swim`, `bike`, `brick`,
`swim_location` und `bike_location` gleich mit an. Das ist keine Auslassung,
sondern eine Einladung: Wer Schwimmen im Schema anbietet, bekommt Schwimmen.

**Für Triathlon bleibt der Prompt Wort für Wort derselbe.** Er passt dort gut,
die Tests prüfen seinen Wortlaut, und die Prinzipien tragen die Disziplinenwahl
über `tage_seit_letzter_einheit_je_sportart` bereits sauber. Geändert wird nur,
was *daneben* gilt: Bei einer Einzeldisziplin nennt Punkt 8 sie beim Namen und
schließt die anderen beiden samt `brick` ausdrücklich aus — auch als Ausgleich
oder schonendere Alternative —, und die Abwechslung entsteht innerhalb der
Disziplin statt zwischen Disziplinen. Punkt 13 verliert dort seinen Ausweichsatz:
Der Weg über eine andere Sportart, den Punkt 8 gerade verboten hat, wäre ein
Widerspruch im selben Dokument. Umso mehr hängt am Ergänzungsauftrag, der
zweiten Richtung desselben Punktes.

**Streng, und zwar auch bei Beschwerden.** Ein Läuferknie auf das Rad
auszuweichen wäre trainingswissenschaftlich naheliegend — aber der Athlet hat
„Laufen" gewählt, und ob überhaupt ein Rad im Haus steht, sagt der Fragebogen
nur beiläufig über `equipment`. Ausgewichen wird deshalb über Umfang,
Intensität, Untergrund und Bewegungsform. Die **Einzelanpassung** ist die eine
Ausnahme: Sagt der Athlet ausdrücklich „lieber schwimmen", folgt die KI ihm und
vermerkt es in `begruendung` — von sich aus wechselt sie die Sportart dort nie.
Der Wunsch hat Vorrang, das ist der ganze Zweck dieser Aufgabe; was er nicht
sagt, bleibt bei der gewählten Disziplin.

**Das Schema wird schmaler, nicht das Feldverzeichnis.** `SESSION_SCHEMA` bleibt
die kanonische Feldliste — wer ein Feld ergänzt, ergänzt es dort und nirgends
sonst. `_session_schema(disziplin)` gibt für Triathlon genau diese Liste zurück
und sonst eine Kopie, in der fünf Dinge schmaler werden: `sport`, `type` (ohne
`brick`), `target_pace` (nur die Einheit dieser Sportart), die
Zusatzfeld-Zeile von `steps` und die Ortsfelder — `swim_location` gehört zum
Schwimmen, `bike_location` zum Rad. Aus demselben Grund zerfällt
`PRINZIP_STEUERGROESSEN` in vier Stücke: Basis und Bauplan gelten überall,
Beckenlänge und Wattsteuerung auf der Rolle nur dort, wo es die Sportart gibt.

**Die Tabellen stehen in `schemas.py`**, nicht im Prompt-Modul: Drei Stellen
müssen dasselbe wissen — `TrainingRequestIn.discipline` validiert die
Schlüssel, `ai_export` baut daraus den Prompt, `plan_import` prüft die Antwort
dagegen. `DISCIPLINE_LABEL` ist dafür aus `ai_export` dorthin gezogen. Die
Disziplin kommt in `build_prompt()` **aus dem Payload**
(`trainingswunsch.disziplin_key`) und nicht aus der Signatur: So erben beide
Auslöser sie ohne Zutun — der Knopf wie der Weg über die Zwischenablage, Block
wie Einzelanpassung. Ohne Fragebogen fehlt der Schlüssel, und dann bleibt alles
erlaubt: Ein Block, der nichts über die Wünsche des Athleten weiß, soll sich
nicht zusätzlich auf eine Sportart festlegen.

**Die neuen Bausteine gehen fertig in die Vorlage** — dieselbe Falle wie bei
`FITNESSREGELN_*` und `PRINZIP_ERGAENZUNG`: `.format()` setzt Werte ein, **ohne
sie erneut zu formatieren**. Das `{tage}` in `PRINZIP_TRIATHLON` füllt deshalb
`_prinzip_disziplin()` selbst, bevor der Text als Platzhalterwert weitergereicht
wird. `test_kein_platzhalter_bleibt_stehen` hält das für alle vier Disziplinen
fest.

**Der Import meldet eine fremde Sportart, lehnt sie aber nicht ab**
(`plan_import._fremde_sportarten`). Dieselbe Linie wie überall dort: Ein
abgelehnter Block wäre die teuerste denkbare Antwort auf eine Einheit, die der
Athlet notfalls einzeln anpasst. Die Disziplin holt
`disziplin_des_fragebogens()` über denselben Fragebogen, an dem der Plan hängt —
mit `request_id`, sonst über `_letzter_fragebogen()`, also genau die Wahl, die
auch der Export trifft. Der Vorschau-Endpunkt `POST /api/plans/validate` macht
dieselbe Abfrage, sonst tauchte die Warnung erst auf, wenn der Block schon
steht. Kraft, Mobility und Ruhe zählen nie mit: Sie hängen am
Ergänzungswunsch, nicht an der Disziplin.

**Im Fragebogen verschwindet die Tagesbelegung, und ihre Reste mit ihr**
(`NewTraining.waehleDisziplin`, `constants.DISCIPLINE_SPORTS`). Der Schritt
„Welche Sportart geht an welchem Tag?" erschien schon immer nur beim Triathlon —
er hängt jetzt an der Zahl der Sportarten statt am Literal `'triathlon'`, und
die Chips kommen aus derselben Tabelle. Der eigentliche Fehler saß aber
woanders: Wer erst Triathlon wählte, die Tage belegte und dann auf „Laufen"
zurückging, schickte `day_sport_map` mit Schwimm- und Radtagen ab — und Punkt 7
verlangt, sich **strikt** an die Sportart-Zuordnung je Tag zu halten. Der
Disziplinwechsel dampft die Belegung deshalb auf die Sportarten der neuen
Disziplin ein und wirft leer gewordene Tage ganz heraus; dieselbe Aufräumregel
wie beim Abwählen eines Tages.

**Der Fragebogen wird angepasst, nicht ersetzt** (`routers/questionnaire.py`,
`NewTraining.tsx?request=<id>`). Es gab nur „neu ausfüllen", und jede Runde legte
eine neue Zeile an — der laufende Block zeigte weiter auf die alte. Wer sich ein
Powermeter kaufte oder von Triathlon auf Laufen umstellte, erreichte damit genau
den Block nicht, an dem er gerade trainierte. Im Trainingsplan steht deshalb
„Fragebogen anpassen"; ganz von vorn geht es weiter über „Neues Training" in der
Navigation.

**Dieselbe Zeile, damit jeder Plan seinen Verweis behält.** `PUT` statt `POST`,
und `PlanOut` trägt jetzt `request_id`, damit die Oberfläche überhaupt weiß,
welche Zeile gemeint ist. Bei Altbestand (`request_id = NULL`) fällt sie auf
`api.latestRequest()` zurück — dieselbe Wahl, die auch `_letzter_fragebogen()`
trifft. Den Knopf dort auszublenden wäre die schlechtere Antwort: Der Fragebogen
existiert ja, er ist nur nicht verlinkt, und der Athlet stünde vor einem leeren
Formular statt vor seinen Antworten.

**Überschrieben wird vollständig, ohne `exclude_unset`** — die bewusste
Gegenentscheidung zum Profil. Der Wizard ist **ein** Formular und schickt immer
alle Antworten; bei einem Teil-Update wäre „ich will kein Ergänzungstraining
mehr" (`supplemental: []`) nicht von „dieses Feld war nicht dabei" zu
unterscheiden, und ein abgewählter Wunsch stünde weiter im nächsten Prompt.

**`created_at` wandert dabei nicht**, und daran hängt eine Falle:
`_letzter_fragebogen()` sortiert danach. Liegt neben der bearbeiteten Zeile eine
jüngere, griffe der Export daneben — die Anpassung wirkte nie, ohne dass
irgendwo etwas fehlschlüge, der unangenehmste aller Fehlerfälle. Den Zeitstempel
hochzusetzen wäre eine Zeile und machte die Spalte zur Lüge (die Liste sortiert
danach, und „wann habe ich den ausgefüllt" hätte keine Antwort mehr).
Durchgereicht wird stattdessen die **Kennung**: `planErzeugenPfad()` hängt sie an
(beide Planungsknöpfe geben `plan.request_id` mit), und `ki/automatik` nimmt die
des aktiven Blocks statt `None`. Damit trägt sich die Wahl fort — `uebernimm_plan`
schreibt sie an den neuen Plan, der nächste Lauf liest sie dort.

**Der laufende Block ändert sich nicht**, und der Wizard sagt das im letzten
Schritt ausdrücklich: Die Änderung gilt ab dem nächsten Block. Ohne den Satz wäre
„Fragebogen anpassen" ein Versprechen, das die App nicht hält.
