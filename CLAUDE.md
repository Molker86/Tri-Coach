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
Block **nach dem täglichen Garmin-Abgleich** von selbst entstehen. Ab Werk ist
er aus, denn jeder Lauf kostet Kontingent; siehe „Geplant wird auf Zuruf — oder
nach dem Abgleich".
Aufgerufen wird **Claude Code headless** als Unterprozess, nicht die API mit
Token-Abrechnung: Das Abo war da, und ein Aufruf am Tag kostet darüber nichts
extra. Der Weg über die Zwischenablage bleibt vollständig erhalten — als
Rückfallebene für einen abgelaufenen Zugang, ein aufgebrauchtes Kontingent oder
eine andere KI.

**Was die App ohne Zutun tut, steht unter „Einstellungen".** Abgleich an/aus
samt Uhrzeit, Übertragung auf die Uhr, Profilübernahme, der Claude-Zugang
(verschlüsselt in der Datenbank statt im Klartext in den Add-on-Optionen),
automatische Planung, Modell und Denktiefe — dazu Hell/Dunkel. Und auf der
Startseite öffnet jede Einheit denselben Dialog wie im Trainingsplan: ansehen,
per Freitext anpassen lassen.

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
cd backend && .venv/bin/python -m pytest tests/ -q # 453 Tests
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
`TRI_GARMIN_SYNC_HOUR` (Ortszeit-Stunde, ab der abgeglichen wird, Vorgabe 10
— nur noch die **Vorgabe** für ein neu verbundenes Konto; maßgeblich ist
`GarminAccount.sync_hour` aus den Einstellungen).

Für die KI-Planung: `CLAUDE_CODE_OAUTH_TOKEN` (der Abo-Zugang; den Namen gibt
Claude Code vor, der Unterprozess liest genau diese Variable) — inzwischen der
**Rückfall**, denn Vorrang hat das Token aus den Einstellungen. Lokal genügt
statt beidem eine angemeldete CLI; geprüft wird nicht die Variable, sondern
`claude auth status`. Dazu `TRI_KI_CLI` (Pfad zum Programm, Vorgabe `claude`),
`TRI_KI_MODELL` (Vorgabe `opus`), `TRI_KI_EFFORT` (Vorgabe `max`) und
`TRI_KI_TIMEOUT_S` (Vorgabe 900). Ein Gegenstück zu `TRI_GARMIN_AUTOSYNC` gibt
es hier **nicht**: Die automatische Planung hängt am Abgleich, hat also keine
eigene Schleife — `TRI_GARMIN_AUTOSYNC=0` legt beides zugleich still.

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

Gelöscht wird deshalb **nur nach einem Abgleich** vollständig. Der Import und der
Übertragungslauf, den er anstößt, räumen nur Blöcke weg, die ganz in der Zukunft
liegen (`Plan.start_date >= heute`): Eine Übertragung importiert nichts und weiß
über die absolvierten Trainings genauso wenig wie der Import selbst
(`runner._raeume_workouts_auf(…, nach_abgleich=False)`). Erst der Abgleich, der
die Aktivitäten gerade geholt und über `finde_offene_planeinheit()` verknüpft hat,
darf urteilen. Der Preis ist ein abgelöster Block, der einen Tag länger unter
„Frühere Pläne" steht — gemessen an einem Aufbau, der für immer weg ist, ist das
nichts. **Ohne verbundenes Konto greift die Schonung nicht**: Dann entstehen nie
Trainings und käme nie ein Garmin-Lauf, der aufräumt — die Blöcke sammelten sich
für immer.

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
RPE ist damit **in aller Regel geschätzt** (`mapping.schaetze_rpe`); `rpe_source`
behält seinen Wert `manual` nur noch als Altwert. Ein Ausweichen aufs Formular
gibt es nicht mehr — **ohne verbundene Uhr hat die App keine
Trainingshistorie**, und der Prompt sagt das der KI ausdrücklich
(`FITNESSREGELN_OHNE_DATEN`). Die eine Ausnahme kommt trotzdem vom Athleten,
aber nicht aus dieser App — siehe „Bewertet der Athlet selbst".

**Bewertet der Athlet selbst, gewinnt seine Zahl** (`mapping.bewertung_aus_detail`,
`SessionLog.garmin_feel`, `rpe_source = "athlet"`). Garmin *berechnet* kein RPE,
aber der Athlet kann in Connect zu jeder Einheit „Anstrengung" und „Wie hast du
dich gefühlt?" eintragen. Das ist damit die einzige Selbstauskunft, die es hier
noch gibt — und sie kommt ohne Formular, weil sie den Weg über die Uhr nimmt.
Das RPE ersetzt deshalb die Schätzung (`rpe_source` hält beides
auseinander): Fosters sRPE-Last rechnet ausdrücklich mit der *empfundenen*
Anstrengung, und beide Zahlen liegen auf derselben Borg-CR10-Skala — anders als
Garmins Trainingslast, die genau deswegen nur zusätzlich mitläuft.

Drei Dinge daran sind nicht offensichtlich. **Beides steht nur im
Aktivitätsdetail**, nicht in der Listenantwort (am echten Konto nachgezählt: 111
Felder je Aktivität, keines davon) — es kostet also eine eigene Anfrage **je
Einheit**. Deshalb `sync.BEWERTUNGSFENSTER_TAGE` = 42: Bei einem Jahresrückblick
wären es sonst dreihundert Anfragen für Zahlen, die der Export gar nicht mehr
liest. **Garmin speichert mal zehn** (`directWorkoutRpe` 10–100,
`directWorkoutFeel` 0–100), bewertet wird aber von 0/1 bis 10; umgerechnet wird
an genau einer Stelle, damit App, Export und Prompt dieselbe Skala zeigen wie
Connect. Die halben Stufen (2,5 / 7,5) stammen von der Uhr, die fünf Stufen
statt der Skala anbietet, und bleiben erhalten — auf 8 gerundet stünde dort eine
Genauigkeit, die niemand angegeben hat. Und **eine Bewertung wird nie durch eine
Schätzung überschrieben** (`sync._speichere_aktivitaet`): Ein Rückblick reicht
weiter zurück als das Bewertungsfenster, und ohne die Sperre nähme er jeder
älteren Einheit ihren echten Wert wieder ab. Der Preis ist derselbe wie überall
sonst im Abgleich — eine in Connect *gelöschte* Bewertung bleibt hier stehen.

Im Export steht das Befinden als `befinden_0_10` an der Einheit, aber **nur wo es
belegt ist**: Ein `null` an den übrigen wäre keine leere Angabe, sondern eine
Behauptung über eine Einheit, zu der der Athlet nichts gesagt hat. Genau das sagt
auch Punkt 11 des Prompts — die Felder tragen, wo sie stehen, und ihr Fehlen wird
nicht gedeutet. Ein Wochenmittel gibt es bewusst nicht: Bewertet wird ein
Bruchteil der Einheiten (am Testkonto zwei von zwanzig), und ein Schnitt daraus
sähe aus wie eine Aussage über die Woche.

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

**Kein UI-Framework.** `styles.css` ist ein kleines Designsystem mit
CSS-Variablen und Hell/Dunkel-Umschaltung.

**Welche Farben gelten, entscheidet JavaScript — nicht die Medienabfrage**
(`theme.ts`, `:root[data-theme='dark']`). Die App folgte einmal allein
`prefers-color-scheme`. Ein Schalter dafür bräuchte im CSS eine **zweite
Fassung aller dunklen Tokens**: einmal in der Medienabfrage für „System",
einmal unter dem Attribut für die ausdrückliche Wahl. Zwei Kopien derselben
Palette laufen irgendwann auseinander, und eine halb dunkle Oberfläche ist
schwer zu bemerken.

Aufgelöst wird deshalb im Browser: Die Wahl (`system` | `light` | `dark`) steht
in `localStorage['tricoach.theme']` — bei „System" fragt `matchMedia`. Das
Ergebnis geht **immer** als ausdrückliches `data-theme` auf `<html>`, und das
CSS kennt nur noch diesen einen Fall. Gesetzt wird es zweimal: von einem
Inline-Skript im `<head>` der `index.html` **vor dem ersten Zeichnen** (sonst
blitzt die helle Fassung auf, bevor React geladen ist — die Logik steht dort
doppelt und gehört mitgezogen), und danach von `theme.ts` bei jeder Änderung.
`beobachteSystemfarbe()` in `main.tsx` hält „System" außerdem am
Systemschalter: Ohne den Beobachter bliebe die App bis zum Neuladen in der
Farbe, die beim Öffnen galt — am Telefon, wo abends automatisch umgeschaltet
wird, der Normalfall. Er steht dort und nicht in einem `useEffect`, weil er so
lange lebt wie die Seite und im StrictMode sonst zweimal anliefe. `color-scheme`
steht ebenfalls an beiden `:root`-Regeln, damit Formularfelder und Scrollbalken
der Seite folgen und nicht der Systemwahl. Am Konto gespeichert wird nichts:
Wer die App auf zwei Geräten öffnet, stellt sie zweimal ein — bei einer Frage
der Darstellung richtig so.

**Was ohne Zutun läuft, steht an einem Ort** (`pages/Einstellungen.tsx`). Die
Schalter dafür gab es teils schon, aber verstreut: die Garmin-Automatik mitten
auf der Verbindungsseite, Modell und Denktiefe der KI **überhaupt nur über die
API** (`api.kiSettings` hatte keinen Aufrufer), und der Claude-Zugang
ausschließlich in den Add-on-Optionen — wofür man die App verlassen, Home
Assistant öffnen und das Add-on neu starten musste. Drei Karten: Garmin
(Abgleich an/aus, Abgleichzeit, Übertragung auf die Uhr, Profilübernahme),
KI-Planung (Token, automatische Planung, Modell, Denktiefe) und Darstellung.

Gespeichert wird **sofort, ohne Speichern-Knopf** — dieselbe Handhabung wie
bisher auf der Garmin-Seite. Die eine Ausnahme ist der Token: Ein Zugang, der
beim Tippen zeichenweise gespeichert würde, stünde die halbe Zeit als
unbrauchbar da. Und solange einer hinterlegt ist, steht das Feld **nicht
offen**: Der Wert lässt sich nicht zurücklesen, ein leeres Feld sähe also aus,
als wäre keiner da — stattdessen „✓ hinterlegt" mit *Ersetzen* und *Entfernen*
(das schickt `token: ""`, was der Router ausdrücklich als Löschen liest).

`POST /api/ki/pruefen` gibt es nur für den Knopf „Verbindung prüfen": Die
Auskunft „angemeldet" wird eine Minute lang gehalten, und ohne einen Weg am
Cache vorbei zeigte der Knopf ausgerechnet nach dem Eintragen eines Tokens
nichts Neues.

Auf der Garmin-Seite stehen die drei Häkchen dafür nicht mehr, nur ein Verweis.
`api.garminSettings` bleibt — es wird jetzt von der Einstellungsseite gerufen.
Dabei überspringt `PUT /api/garmin/settings` neuerdings `None` wie der
KI-Router: Ein ausdrücklich geschicktes `null` löschte sonst die Abgleichstunde,
und das Konto fiele lautlos auf die Vorgabe zurück.

**Die Trainingsvorschau auf der Startseite ist anklickbar** — und teilt sich
dafür die Bauteile mit dem Trainingsplan (`components/SessionCard.tsx`,
`SessionDetail.tsx`, `AnpassungsKarte.tsx`, `useEinheitAnpassung.ts`). Die
„Heute"-Karte war eine als `<div>` **nachgebaute** `SessionCard`: tot, und
nebenbei ohne Zone, Garmin-Marke und „✎ angepasst", weil beim Nachbauen niemandem
auffällt, was fehlt. Wer eine Einheit ansehen oder umschreiben lassen wollte,
musste erst die Seite wechseln.

Das Herausziehen ging ohne Umbau: Die einzige Datenabhängigkeit des Dialogs ist
`session`, alles andere sind Rückrufe — und `api.activePlan()` liefert dasselbe
`PlanSessionOut` wie im Plan (beide gehen durch `_to_plan_out`). Es braucht
also **keine neue API**. An der Seite hing nur die Job-Maschinerie, und die
steht jetzt im Hook; zwei Kopien der Abfrageschleife liefen beim nächsten
Zustand des Laufs auseinander. `AnpassungsKarte` steht auf beiden Seiten
**außerhalb** des Dialogs: Die Begründung der KI ist die einzige Stelle, an der
der Athlet erfährt, ob sie seinem Wunsch gefolgt ist, und sie beim Schließen zu
verschlucken wäre genau der falsche Moment.

In „Als Nächstes" bleibt es bei der kompakten Tabelle; anklickbar ist der Titel
als **echter Knopf** (`.linklike`) und nicht die Zeile mit `onClick` — eine
anklickbare Zeile ist für Tastatur und Vorlesehilfe kein Bedienelement. Das
Dashboard lädt seither über ein `reload()` statt eines einmaligen Effekts:
Nach einer angepassten Einheit steht eine andere Vorgabe im Plan. `garminZustand`
bleibt dort leer — dafür zusätzlich `api.garminWorkoutStatus()` zu holen wäre
eine Anfrage für eine Randnotiz.

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

**Am Telefon trägt die Navigation unten, nicht oben.** Die Kopfleiste mit
sieben Wegen nebeneinander funktioniert am Schreibtisch; auf einem Telefon bräuchte sie
drei Zeilen und stünde bei jedem Scrollen im Weg. Unterhalb von 860 px entfällt
sie deshalb ganz (`.topbar-app`), stattdessen blendet `Layout.tsx` eine feste
Leiste am unteren Rand ein: Übersicht, Plan, Garmin, Verlauf und „Mehr“ —
hinter „Mehr“ liegt ein Blatt mit Garmin-Kalender, Neues Training, Meine Daten,
Einstellungen und Abmelden. Die vier unten sind das Maximum: `.mobile-nav` steht
im CSS auf `repeat(5, 1fr)` (vier Wege plus „Mehr“), ein fünfter spränge die
Leiste. Deshalb liegt „Einstellungen“ hinter „Mehr“ — und es passt dorthin, weil
man die Seite einmal einrichtet und danach selten wieder öffnet. Den Platz, an dem einmal „Erfassen“ stand, hat Garmin bekommen:
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

**„Heute" wird bei jedem Rendern neu bestimmt, nicht beim Laden der App**
(`useHeute()` in `GarminKalender.tsx`). Die Tagesmarkierung im Kalender hing an
einer modulweiten Konstante, und weil alle Routen statisch in `App.tsx` liegen,
war das genau ein Aufruf: der Moment, in dem der Tab aufging. Eine Sitzung über
Mitternacht markierte am Morgen weiter den Vortag — am Telefon der Normalfall,
denn dort schläft ein Tab, statt zu schließen. Kein Zeitzonenfehler: `iso()`
liest die Ortszeitanteile und nicht `toISOString()`.

Der Haken an der naheliegenden Lösung ist, dass ein Wert je Rendern nur hilft,
wenn gerendert wird — ein offener Kalender tut das über Nacht nicht. Deshalb ein
Zeitgeber auf den nächsten Tagesbeginn (feuert genau einmal, statt im Minutentakt
zu fragen) **und** `visibilitychange`, weil Telefone Zeitgeber im Hintergrund
drosseln und nicht nachholen — dieselbe Überlegung wie bei `pollJob`. Ein Aufruf
ohne Tageswechsel kostet nichts: Gleicher Tag heißt gleicher String, und React
verwirft die Zuweisung von selbst.

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

**Die Bereichsantwort benennt dieselben Größen anders als die Tagesantwort** —
und das hat zwei Spalten jahrelang leer gelassen. Beides am echten Konto
nachgesehen und die Nachbildung darauf gezogen:

*Schlaf.* `get_sleep_daily()` (Bereich) liefert je Nacht ein `values`-Objekt mit
`totalSleepTimeInSeconds`, `deepTime`, `lightTime`, `remTime`, `awakeTime` —
`get_sleep_data()` (Tag) dagegen ein `dailySleepDTO` mit `sleepTimeSeconds`,
`deepSleepSeconds` und so fort. Der Parser kannte nur die Tagesnamen und las an
jeder Bereichszeile `None`. Weil dieselben Felder auch die Tagesschleife
schreibt, sah das nicht nach einem Fehler aus, sondern nach einem Endpunkt, der
schweigt: In der Datenbank stand Schlaf für genau die 42 Tage der Schleife, und
daraus wurde hier einmal die falsche Regel „`get_sleep_daily()` liefert nichts".
Der Endpunkt liefert; über 21 geprüfte Tage 120 Tage in der Vergangenheit kam
Schlaf an **allen** an. In derselben Zeile stehen außerdem `sleepScore` und
`bodyBatteryChange` — beide werden jetzt von dort gelesen und reichen damit so
weit wie der Rückblick statt nur 42 Tage.

*Körperbatterie.* `bodyBatteryValuesArray` ist eine Tabelle ohne Kopfzeile,
und welche Spalte was bedeutet, sagt `bodyBatteryValueDescriptorDTOList`. Am
echten Konto sind es **zwei** Spalten (`timestamp`, `bodyBatteryLevel`); der
Parser griff fest auf Index 2 und traf damit nichts — `body_battery_high`/`_low`
blieben an allen 370 Tagen leer, während Garmin die Werte durchgehend liefert.
Gelesen wird die Spalte deshalb jetzt aus dem Descriptor
(`sync._body_battery_werte`) und nicht geraten: Ein fester Index 1 wäre
derselbe Fehler ein Jahr später. Der Randtag eines Zeitraums kommt mit
belegten Zeitstempeln und leerem Ladestand — er hat dann korrekt keinen
Höchstwert. Die aus dem Bereich gelesenen Extremwerte sind dabei **nicht**
gröber als die Tagesangabe: Garmin gibt zwar nur sechs Punkte je Tag zurück,
über fünf Tage geprüft stimmten Höchst- und Tiefstwert exakt mit
`get_user_summary().bodyBatteryHighestValue`/`LowestValue` überein. Die
Bereichsabfrage bleibt damit die richtige Quelle — eine Anfrage statt einer
je Tag.

Die Lehre für beide: Eine Nachbildung, die der Entwickler nach dem Parser
formt, bestätigt den Parser und sonst nichts. Beide Formen hier stammen aus
abgelesenen Antworten, und `test_koerperbatterie_kommt_an` wie
`test_schlaf_kommt_aus_der_bereichsabfrage` halten sie fest — letzterer, indem
er die Tagesantwort schweigen lässt, weil sie die Bereichszeile sonst verdeckt.

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

**Wann abgeglichen wird, steht am Konto** (`GarminAccount.sync_hour`,
`automatik._abgleichstunde`). Die Stunde war einmal die Konstante
`GARMIN_SYNC_HOUR` und damit im laufenden Prozess unveränderlich — eine
Umgebungsvariable lässt sich in der Oberfläche nicht umstellen. Jetzt steht sie
je Konto in der Datenbank und ist in den Einstellungen wählbar; die Konstante
ist nur noch die Vorgabe für ein neu verbundenes Konto (und wechselte dabei von
9 auf **10 Uhr**). Der Riegel wanderte dafür aus dem Kopf von
`starte_faellige_syncs` in die Schleife über die Konten: Jeder Aufwacher öffnet
seither eine Sitzung, statt vorher billig zurückzukehren — bei SQLite auf
demselben Rechner folgenlos, und anders geht „je Nutzer eine Stunde" nicht.
Geprüft wird ausdrücklich gegen `None` und **nicht** mit `or`: Mitternacht ist
eine gültige Einstellung, und `0 or 10` ergäbe zehn.

Volle Stunden, keine Minuten: Die Schleife wacht viertelstündlich auf, der
Abgleich beginnt also innerhalb der Viertelstunde danach. Eine Minutenangabe
wäre eine Genauigkeit, die es gar nicht gibt.

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

**Die Kennzahlen der Historie werden rollierend gerechnet, nicht in
Kalenderwochen** (`sportscience.acute_chronic_ratio`). Die ACWR nahm ihre
Akutlast einmal aus dem letzten Bucket der `wochenuebersicht` — und der ist die
*laufende* Woche. An einem Dienstag standen dort zwei Tage gegen einen vollen
Vierwochenschnitt: An echten Daten meldete der Export 0.13, wo 0.55 richtig war.
Die Zahl hing damit am Wochentag des Exports statt an der Belastung, und Punkt 1
des Prompts liest einen niedrigen Wert als Freigabe zum Aufbau. Deshalb rechnet
sie jetzt über die Rohdaten: 7 Tage gegen 28 Tage / 4, beides rollierend ab
heute.

Die `wochenuebersicht` bleibt bei Kalenderwochen — der Athlet denkt in ihnen —,
deckt aber das **ganze** Rückblickfenster ab. Vorher zählte sie vier Buckets ab
dem aktuellen Montag zurück, während die Historie 28 Tage vor *heute* beginnt:
Fällt heute nicht auf einen Montag, fielen die Einheiten dazwischen aus der
Übersicht, obwohl sie in `einheiten` standen (an echten Daten fünf Einheiten,
darunter eine über 137 Minuten). Die KI sah zwei widersprüchliche Darstellungen
desselben Zeitraums. Jedem Bucket steht deshalb `ist_vollstaendig` dabei, und
`letzte_volle_woche` benennt den Maßstab, den Punkt 6 für sein „bis zu 10 %
mehr" braucht — der letzte Eintrag der Übersicht taugt dafür nie.

**Fällig ist, was vor heute lag** (`sportscience.compliance`). Der heutige Tag
ist nicht vorbei; die Einheit von heute Abend als versäumt zu zählen, drückt die
Quote genau dann, wenn der Block frisch ist. An echten Daten wurden aus zwei von
zwei umgesetzten Einheiten 33 %, weil die beiden noch bevorstehenden von heute
mitzählten — und Punkt 1 des Prompts macht aus einer niedrigen Quote den Auftrag,
kleiner zu planen.

**Garmins `recoveryTime` sind Minuten** (`WellnessDay.recovery_time_min`). Die
Spalte hieß einmal `recovery_time_h` und übernahm den Wert ungerechnet. Ein
Eintrag von 911 stand damit als „911 Stunden Erholung" im Export und in den
Auffälligkeiten, und der Prompt macht daraus „in diesem Zeitfenster nichts über
Z2" — 38 Tage lang. Die Schwelle `ERHOLUNGSZEIT_HOCH_H = 24` feuerte
entsprechend bei 24 *Minuten*, also fast immer. Der Name sagt jetzt die Einheit,
umgerechnet wird erst zur Anzeige (`sportscience.erholung_stunden`) — sonst liefe
die Umrechnung bei jedem Start erneut über dieselben Werte. Die Umbenennung
läuft über `database._UMZUZIEHENDE_SPALTEN`: ergänzen, kopieren, alte Spalte
löschen, alles idempotent.

**Watt- und Tempokorridore kommen mit, nicht nur ihre Schwellenwerte**
(`sportscience.power_zones` / `pace_zones`). Punkt 10 verlangt zu jeder Einheit
ein `target_power` bzw. `target_pace`, lieferte der KI aber nur die nackte FTP —
sie musste die Anteile raten, während `garmin/workouts.py` sie längst festlegt.
Beide lesen jetzt dieselbe Tabelle `FTP_ZONEN_ANTEIL`: Aus denselben Korridoren,
die im Prompt stehen, baut die App anschließend das Workout für die Uhr. Zwei
Tabellen liefen auseinander, und dann stünde im Plan ein anderer Bereich als auf
dem Gerät. **Ohne hinterlegten Schwellenwert fehlt der Block ganz** — geschätzt
wird nichts, denn eine erfundene Schwellenpace stünde als Vorgabe im Plan. Der
Prompt sagt für diesen Fall ausdrücklich, dass die Vorgabe aus Pace und
`hf_schnitt` vergleichbarer Einheiten der Historie abzuleiten ist.

**Was geplant war, steht an der absolvierten Einheit** (`ai_export._geplant_war`,
Punkt 12 des Prompts). Die Verknüpfung legt der Abgleich über Tag und Sportart
an (`garmin/matching.py`), der Aufbau lag also vor — er wurde nur nie
exportiert. Die KI sah von einem Intervalltraining „29 min, 4,4 km, HF 150" und
konnte es nicht fortschreiben: Aus 5x1000 m wird so nie 6x1000 m. Für einen
Block, der ausdrücklich den *nächsten Schritt* setzen soll, war das die größte
inhaltliche Lücke. Mitgeliefert wird auch die geplante Dauer — weicht die
absolvierte deutlich ab, war die Vorgabe zu ambitioniert, und das sagt mehr als
jede Umsetzungsquote.

**Wie eine Einheit ausgeführt wurde, nicht nur dass sie stattfand**
(`mapping.zonensekunden` / `abschnitte_aus_detail`, `_history_block`). Der Export
beschrieb eine absolvierte Einheit mit Dauer, Strecke und Schnittpuls — und das
sagt über eine Intervalleinheit fast nichts. Die Schlüsseleinheit vom 19.08.2026
stand als „37 min, HF-Schnitt 148" da; geplant waren 60 min mit 3x8 min Schwelle.
Ob die drei Intervalle standen, war nicht abzulesen, und Punkt 12 („Fortschreiben
statt neu erfinden") schrieb damit die *Vorgabe* fort statt die Ausführung. Drei
Größen schließen die Lücke, und **keine davon kostet eine zusätzliche Anfrage**
(die vierte, die Übungsliste, kostet eine — siehe „Was in einer Krafteinheit
wirklich passiert ist"):

*Die Zonenverteilung* (`hrTimeInZone_1..5`) stand immer schon in derselben
Listenantwort, aus der die Einheit entsteht. `schaetze_rpe()` las sie, schätzte
daraus das RPE und warf sie weg. Sie geht jetzt als `zeit_in_hf_zonen_min` mit —
ein Schwellentraining ohne nennenswerte Zeit in Z4 war keins, gleich was der
Durchschnittspuls sagt. Gelesen wird sie an **einer** Stelle (`zonenzeiten()`),
weil zwei Stellen mit denselben fünf Feldnamen irgendwann verschiedene fänden.

*Die absolvierten Abschnitte* kommen aus `splitSummaries` im Aktivitätsdetail —
und das holt `sync._hole_detail()` für jede Einheit der letzten 42 Tage ohnehin,
bisher für genau zwei Felder. An derselben Schlüsseleinheit standen dort ein
Aufwärmabschnitt über 9 min, **sechs** Arbeitsabschnitte über zusammen 16,6 min
bei HF 163, sechs Pausen und ein Ausrollen von 1:48 statt der geplanten 9 min.
Übernommen wird nur, was die Trainingsstruktur beschreibt (`INTERVAL_*`): Garmin
mischt in dieselbe Liste den Untergrund (`SURFACE_TYPE_PAVED`) und seine
Geh-Lauf-Erkennung (`RWD_RUN`/`RWD_WALK`), und beides trägt keine
Planungsentscheidung. **Ein einzelner Arbeitsabschnitt über die ganze Einheit ist
keine Gliederung** und fällt weg — so meldet Garmin jeden freien Dauerlauf, und
als „absolvierte Abschnitte" behauptete das eine Struktur, die es nicht gab.

*Garmins eigene Einhaltungsbewertung* (`directWorkoutComplianceScore`, 0–100)
steht daneben im selben `summaryDTO`. An der Schlüsseleinheit: **48**. Keine
andere Zahl im Export sagte, dass die Einheit nach zwei Dritteln abbrach.

Alle drei fehlen, wo sie nicht belegt sind — dieselbe Regel wie bei
`befinden_0_10`: Ein `null` wäre keine leere Angabe, sondern eine Behauptung.
Und für bestehende Einheiten bleiben die Spalten leer: Der tägliche Abgleich holt
nur fünf Tage zurück, wer sie für die Historie will, stößt einen Rückblick an.

**Was im Aktivitätsdetail steht, ist abgelesen und nicht vermutet**
(`scripts/garmin_aktivitaetsdetail_probe.py`). Dieselbe Lehre wie bei Schlaf und
Körperbatterie: Eine Nachbildung, die der Entwickler nach dem Parser formt,
bestätigt den Parser und sonst nichts. Das Skript ist **rein lesend** — anders
als die Freiwasser-Probe legt es nichts an — und druckt je Sportart die
Schlüsselliste, `splitSummaries` im Wortlaut, die belegten Felder von
`summaryDTO`, den Rückbezug aufs Workout und — bei Kraft und Mobility — die
gezählten Sätze im Wortlaut. Ein Nebenbefund daraus, der bewusst *nicht*
eingebaut wurde: `normalizedPower` und `maxPower` sind belegt, aber nur dort, wo
ohnehin ein Powermeter misst.

**Was in einer Krafteinheit wirklich passiert ist**
(`mapping.uebungen_aus_saetzen`, `SessionLog.garmin_uebungen`, im Export
`absolvierte_uebungen`). Für Ausdauereinheiten schließt `absolvierte_abschnitte`
die Lücke zwischen Vorgabe und Ausführung; bei Kraft und Mobility klaffte sie
weiter, denn dort beschreibt `structure` keinen Zeitverlauf, und
`splitSummaries` meldet nur einen Sammelabschnitt. Eine Krafteinheit stand im
Export als „35 min, RPE 5" — welche Übungen darin vorkamen, war allein aus
`geplant_war.aufbau` zu erraten, also aus der *Vorgabe*.
`get_activity_exercise_sets()` sagt es: die Übungen mit Garmins Katalognamen
(`HIP_RAISE`/`SINGLE_LEG_HIP_RAISE`), je Satz mit Dauer und Wiederholungen.

**Das war einmal ausdrücklich abgelehnt**, und beide Gründe von damals sind
gefallen. „Steht bei unseren eigenen Workouts ohnehin in `geplant_war`" gilt
nicht: Genau der Unterschied zwischen Vorgabe und Ausführung ist der Punkt —
sonst bräuchte es `absolvierte_abschnitte` und `workout_einhaltung_pct` auch
nicht. Und „bei Mobility durchweg `UNKNOWN`" ist überholt: Seit die App ihre
Workouts mit Übungskennungen überträgt (`garmin/uebungen.py`), zählt die Uhr
**benannte** Sätze, statt sie zu raten. An der Mobility-Einheit vom 20.08.2026
kamen `STRETCH_PIGEON_POSE`, `STRETCH_LUNGING_HIP_FLEXOR`, `STRETCH_PIRIFORMIS`
und `STRETCH_LYING_SPINAL_TWIST` zurück — dieselben Kennungen, die diese App
hingeschickt hat. Die Übungserkennung ist damit ein Rückkanal des eigenen
Workout-Baus und keine fremde Erkennung mehr.

Was bleibt, ist der Preis: **eine eigene Anfrage je Einheit.** Deshalb nur für
`workouts.UEBUNGSSPORTARTEN` und nur innerhalb des Detailfensters — bei einem
Lauf wäre der Endpunkt leer, und `BEWERTUNGSFENSTER_TAGE` = 42 gilt ohnehin
schon fürs Detail.

Drei Formen darin sind abgelesen und tragen den Parser. `exercises` nennt
dieselbe Übung **dreimal** mit identischer `probability` — es sind keine
Alternativen, also genügt der erste Eintrag. Eine Pause ist ein eigener Satz
mit leerem `exercises` und `setType: "REST"`; sie zählt nicht als Übung, sonst
stünden an der Mobility-Einheit achtundzwanzig Sätze statt vierzehn. Und
`repetitionCount` ist mal `null`, mal **0** — beides heißt „nicht gezählt", die
0 stand an drei von sechs Übungen der Krafteinheit vom 17.08.2026. Als
Wiederholungszahl exportiert wäre sie eine Behauptung.

Zusammengefasst wird je (Kategorie, Name): Vier Runden Taubenstellung stehen als
eine Zeile mit `saetze: 4`, nicht als vier. Bei den **Wiederholungen** gewinnt
die Liste über den Mittelwert, wenn die Sätze auseinandergehen — dass der letzte
nicht mehr aufging, *ist* die Aussage —, und sie fällt ganz weg, wenn nicht
jeder Satz gezählt wurde: Eine Liste über drei von fünf Sätzen läse sich wie
drei Sätze. Bei der **Haltedauer** ist es umgekehrt, dort mittelt der Parser:
38/40/41 s sind Messrauschen.

Zwei Dinge sagt der Prompt der KI deshalb ausdrücklich dazu, und beide sind an
echten Daten gemessen. `saetze` zählt, was die Uhr **aufgezeichnet** hat: Läuft
eine Übung als ein Workout-Schritt bis zur Rundentaste, stehen drei Sätze dort
als *einer* über die volle Dauer — so kam die Krafteinheit vom 17.08. zurück,
sechs Übungen zu je einem Satz. Und `wiederholungen` stammt aus Garmins
Bewegungserkennung am Handgelenk und zählt bei Körpergewichtsübungen zu
niedrig: An derselben Einheit standen für `CLAM_BRIDGE` **3** Wiederholungen
über 232 Sekunden. Verlässlich sind Übungsauswahl und Dauer; was vorgesehen war,
steht weiter in `geplant_war.aufbau`. Der Wert für die Planung liegt genau dort,
wo die Beschwerde hängt: Punkt 9 verlangt, Übungsauswahl und Körperregion zu
wechseln, und `kategorie` (`PLANK`, `HIP_RAISE`, `CALF_RAISE`) benennt die
Bewegungsgruppe, an der das zu entscheiden ist.

**`weight` bleibt ungelesen.** Es stand an jedem geprüften Satz auf `null` —
alle Übungen laufen mit Körpergewicht —, und damit ist die Einheit (Gramm oder
Kilogramm) nicht belegt. Dieselbe Regel wie bei den Kalenderdauern: Eine um
Faktor 1000 falsche Zahl ist schlechter als eine fehlende.

**Der geplante Aufbau findet auch dann zurück, wenn der Tag nicht stimmt**
(`ai_export._aufbau_je_workout`). `plan_session_id` entsteht über Tag **und**
Sportart (`garmin/matching.py`), und diese Strenge bleibt: An ihr hängt die
Umsetzungsquote, und eine unscharfe Zuordnung würde sie schönfärben. Sie
verfehlt aber den Alltag — ein Workout liegt auf der Uhr und wird gestartet,
wenn es passt. Am 17.08.2026 stand die „Grundlagenfahrt Z2" im Plan und wurde
einen Tag später gefahren; die Zuordnung fiel aus, obwohl der Block danebenlag.
Das Aktivitätsdetail trägt deshalb `metadataDTO.associatedWorkoutId` bei (am
echten Konto an allen drei Einheiten belegt, die aus einem Tri-Coach-Workout
kamen, `None` an jeder frei gestarteten), und über `GarminWorkoutLink` führt das
**ohne jeden Bezug auf den Tag** zur Planeinheit. Zwei Grenzen halten das davon
ab, Falsches zu behaupten: Die Vorlage muss **schon auf der Uhr gelegen haben,
als trainiert wurde** (`pushed_at <= date`) — die fünfzehn Pool-Slots werden
wiederverwendet, und dieselbe Kennung trägt nach ein paar Wochen einen anderen
Inhalt. Und der **Plantag kommt mit**, wo er abweicht (`geplant_fuer`): Dass der
Athlet die Donnerstagseinheit am Montag gemacht hat, ist eine eigene Aussage und
keine Ungenauigkeit — Punkt 12 sagt ausdrücklich, dass das keine Nichtumsetzung
ist.

**Der Prompt sagt, bis wann die Daten reichen** (`_datenstand`, Punkt 2). Der
Block wird täglich nach dem Abgleich gebaut. Läuft die Reihenfolge einmal
andersherum, fehlt das Training des Tages schlicht — und die KI hat keine
Möglichkeit, das zu merken: Sie liest die Lücke als Ruhetag und plant Aufbau auf
einen Tag, an dem hart trainiert wurde. `trainingshistorie.datenstand` nennt
deshalb `garmin_daten_bis` und `letzter_abgleich`, und Punkt 2 sagt ausdrücklich,
dass alles danach **nicht geholt** und nicht als Pause zu deuten ist. Ohne
verbundenes Konto fehlt der Schlüssel ganz. Im Frontend steht derselbe Stand über
dem Planungsknopf (`AbgleichStand` in `PlanExchange.tsx`) — als Hinweis, nicht
als Sperre: Den Planungslauf einen Abgleich anstoßen zu lassen hieße, ihn hinter
das Garmin-Schloss zu stellen, und die beiden Sperren sind bewusst getrennt.

**`erzeugt_am` trägt die Uhrzeit, nicht nur das Datum.** Wer täglich neu plant,
plant den ersten Tag oft an einem Abend, von dem eine halbe Stunde übrig ist. Als
blankes Datum las die KI dort einen vollen Trainingstag und legte eine Einheit
hinein — am 19.08.2026 um 20:47 eine Mobility-Einheit auf denselben Abend. In
Ortszeit aus demselben Grund wie in `frontend/src/planung.ts`: UTC liefert
hierzulande abends bereits den Folgetag.

**Ein leerer Messblock wird weggelassen, nicht mit `null` gefüllt**
(`_fitness_block`). Dieselbe Regel wie beim `fitnessdaten`-Block selbst und bei
`befinden_0_10`: `{"hoechstwert": null, "tiefstwert": null}` liest sich wie ein
Gerät, das Null misst, statt wie eine Größe, die es nicht gibt. Betrifft in der
Praxis die Körperbatterie (siehe „Bekannte Grenzen"). Einzelne Nullwerte neben
belegten Geschwistern bleiben stehen — dort ist „nicht gemessen" die
naheliegende Lesart.

**Eine Aktivität ohne Dauer und ohne Strecke ist kein Training**
(`ai_export._ist_einheit`). Garmin liefert gelegentlich solche Einträge — ein
versehentlich gestarteter und sofort beendeter Timer. Als Einheit gezählt hoben
sie die Wochenzahl und setzten `tage_seit_letzter_einheit_je_sportart` auf 0:
Die KI plante daraufhin keine Radeinheit mehr, obwohl seit Tagen keine
stattgefunden hatte. Gefiltert wird **einmal** am Kopf von `_history_block`,
damit Einheitenliste, Wochenübersicht, ACWR und Abstände dieselbe Menge sehen.

**Die Abstände zählen über die ganze Historie, nicht über vier Wochen**
(`_days_since_by_sport`, `_days_since_hard_session`). Eine Sportart, die länger
ruht als das Fenster reicht, verschwand sonst aus dem Ergebnis — ausgerechnet
die, die Punkt 8 vorziehen soll. Und `tage_seit_letzter_intensiver_einheit: null`
hieß sowohl „seit über vier Wochen nichts Hartes" als auch „keine Daten",
während Punkt 4 des Prompts genau an dieser Zahl hängt — er schreibt keinen
Abstand mehr vor, verlangt aber, dass die KI ihn kennt.

**RPE wird geschätzt, ACWR bleibt sRPE-basiert** (`mapping.schaetze_rpe`).
Garmin liefert kein RPE, aber `weekly_summary`, `acute_chronic_ratio` und
`_days_since_hard_session` rechnen alle damit — ohne Schätzung fiele die halbe
Steuerung für importierte Trainings aus. Geschätzt wird aus der Zeitverteilung
über die Herzfrequenzzonen, ersatzweise aus dem Trainingseffekt oder dem
Durchschnittspuls; `rpe_source` hält fest, woher der Wert stammt, und geht so
in den Export, damit die KI die Belastbarkeit der Zahl einordnen kann. Seit dem
Wegfall der Handeingabe ist **fast jedes** RPE geschätzt — `manual` steht nur
noch an Alteinträgen, `athlet` an den wenigen Einheiten, die der Athlet in
Connect selbst bewertet hat (siehe „Bewertet der Athlet selbst").
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

**Zeitstempel verlassen die API mit ihrer Zeitzone** (`zeit.UtcDatetime`). Die
Spalten stehen ohne Zeitzone in der Datei und meinen UTC; Pydantic gab sie
genauso heraus — `"2026-08-20T04:10:12"` ohne `Z`. JavaScript liest eine
Datum-*Zeit*-Angabe ohne Versatz aber als **Ortszeit**, und damit stand ein
Abgleich, der zwei Minuten zurücklag, in der Oberfläche als „vor 2 Stunden": der
Sommerzeitversatz, auf die Minute. Der Fehler war unauffällig, weil er wie ein
nicht gelaufener Abgleich aussieht — der Nutzer drückt „Jetzt synchronisieren",
der Lauf gelingt, und die Anzeige rührt sich scheinbar nicht.

Geheilt wird das an der Serialisierungsgrenze und nicht im Frontend: Betroffen
war jedes der fünfzehn Zeitstempelfelder, nicht nur `last_sync_at`, und eine
Umrechnung je Anzeigestelle liefe irgendwann auseinander. **Jedes Ausgabefeld
mit Uhrzeit trägt deshalb `UtcDatetime` statt `datetime`** — `date`-Felder
ausdrücklich nicht, ein Geburtstag hat keine Uhrzeit und keinen Versatz.
`test_zeitstempel_tragen_ihre_zeitzone` geht dafür über *alle* Schemas, damit
ein neu ergänztes Feld nicht still in denselben Fehler zurückfällt; geprüft
wird über das echte Modell, weil Pydantic die Anmerkungen eines Pflichtfelds
nach `FieldInfo.metadata` herauszieht und ein nachgebauter `TypeAdapter` den
Serialisierer gerade dort verlöre.

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

**Die KI liefert den Bauplan mit, statt ihn in Prosa zu verstecken**
(`AIStepIn` in `schemas.py`, `workouts.aus_schrittliste`,
`PlanSession.steps_json`). Der Zerleger oben rechnet aus dem Fließtext zurück,
was die KI ohnehin wusste — und **jede** seiner Sonderregeln entstand
nachträglich, an einem echten Plan, nachdem auf der Uhr still etwas Falsches
stand: das „4ד hinter dem Schrägstrich, die Serienpause hinter dem Komma,
„Trudeln" als Pausenwort, die verschwundene Variantenzeile, Ein- und Ausrollen
in der Serie, drei erkannte Umfangsschreibweisen, und im Übungskatalog
`_grundform_ok`, `_MIT_ROLLE`, `_KLAMMER`. Das ist kein Mangel an Sorgfalt,
sondern strukturell: Der Fließtext ist eine verlustbehaftete Kodierung der
Absicht, der Erzeuger ist ein Sprachmodell mit unbegrenzter
Formulierungsfreiheit, und eine Grammatik dafür kann nie fertig werden. Ein
Feld dagegen schon. Der Prompt verlangt deshalb neben `structure` eine
Schrittliste `steps`, die `workouts.Schritt` und `workouts.Block` spiegelt:
`kind`, `duration_s`/`distance_m`/`reps`, `zone`, `text`, `exercise_en`, und
eine Serie als *ein* Eintrag mit `repeat` und den Schritten darin.

**Der Bauplan ist die wörtliche Fassung, nicht die ungefähre.** Ein Screenshot
aus Connect hat gezeigt, wozu „ungefähr" reicht: Über „Seitstütz 3x40 s je
Seite" stand dort **4:00** — arithmetisch richtig (sechs Durchgänge zu 40 s,
weil „je Seite" verdoppelt), und trotzdem las der Athlet einen Widerspruch,
weil die ganze Übungszeile als Beschreibung *eines* 40-Sekunden-Schritts
danebenstand. Punkt 10 nennt deshalb sechs Regeln, und jede nimmt der App eine
Entscheidung ab, die ihr nicht zusteht:

* **Genau ein Maß je Eintrag.** `_schritt_json()` nimmt Distanz vor Zeit vor
  Wiederholungen und lässt den Rest still fallen — bei Kraft die falsche Wahl,
  denn „3x12 in 30 s" ist eine Wiederholungszahl. Was doppelt kommt, räumt
  `AISessionIn._raeume_masse()` **nach der Sportart** auf (bei `strength` und
  `mobility` gewinnt `reps`, sonst `distance_m`) und meldet es.
* **`repeat` zählt die Durchgänge, wie die Uhr sie zählt** — drei Sätze je
  Seite sind `repeat: 6`. Verdoppelt wird im Bauplanweg nichts mehr; das tut
  nur noch der Zerleger, der aus „je Seite" zurückrechnen muss.
* **Pausen sind eigene Einträge** (`kind: "rest"` in der Gruppe). Ohne sie ist
  die angezeigte Abschnittszeit reine Arbeitszeit — genau die Lücke, die
  bisher als bekannte Grenze in diesem Dokument stand.
* **`text` beschreibt einen Schritt**, nie die ganze Übung: Satzzahl und
  Haltedauer zeigt die Uhr darüber schon selbst.
* **Teilsegmente werden ausgeschrieben.** „Im 8-min-Einrollen 4x 10 s hohe
  Trittfrequenz" ist eine Gruppe aus Einrollen und Antritt, keine Beschreibung
  — als Prosa kam davon auf der Uhr nichts an.
* **`duration_min` ist die Summe der Schritte.** Läuft beides auseinander,
  beschreiben Text und Bauplan zwei verschiedene Einheiten.

Nur **eine** Gruppenebene: Garmin verschachtelt `RepeatGroupDTO` nicht. Kommt
trotzdem eine zweite, schreibt `_gruppenkinder()` ihre Schritte aus, statt sie
als Blattschritt zu lesen — so war es, und ohne eigenes Maß fiel der ganze
Teilblock stumm weg.

**Der Zerleger bleibt, er rückt nur auf Platz zwei.** `baue_workout()` nimmt
den Bauplan, sonst den Fließtext, sonst den Ersatzschritt. Löschen ginge nicht
und soll es auch nicht: In der Datenbank stehen Blöcke aus der Zeit vor dem
Feld, und über die Zwischenablage — die ausdrückliche Rückfallebene — antwortet
womöglich eine KI, die den Prompt nie gesehen hat. Der Gewinn ist deshalb nicht
„weniger Code", sondern **„die Grammatik hört auf zu wachsen"**: Eine
Formulierung, die sie nicht kennt, kostet keinen Fehlgriff mehr auf der Uhr.
Die Reihenfolge macht den zweiten Kanal außerdem folgenlos, wenn er ausfällt —
schlechter als vorher kann es nicht werden.

**Was hier ausdrücklich *nicht* passiert**, ist der eigentliche Punkt: keine
Schrittart aus dem Wortlaut, keine Regel „der zweite Teil eines Paars ist die
Pause", kein geratener Umfang, kein Herausfischen des Übungsnamens aus einer
Zeile voller Beiwerk. Die KI sagt es, und was sie nicht sagt, bleibt leer. Ein
Eintrag ohne jedes Maß fällt weg statt als leerer Abschnitt im Workout zu
stehen — außer bei Kraft und Mobility, wo ein Schritt bis zur Rundentaste
zulässig ist. Bleibt nichts übrig, ist das die Antwort „kein Bauplan".

**Eine fehlende Schrittliste wird gemeldet, nicht verschwiegen**
(`validate_coverage`, `pruefe_einheit`). Dieselbe Linie wie überall beim Import
— Warnung statt Ablehnung —, aber hier aus einem eigenen Grund: Ohne den
Hinweis fiele nie auf, dass der zweite Kanal gar nicht trägt. Der Block sähe
gut aus, die Uhr bekäme weiter zerlegte Prosa, und niemand wüsste es. Genau so
ist es passiert: In Plan 4 kam **jede** Kraft- und Mobility-Einheit mit
`"steps": null`, und der beanstandete Workout entstand deshalb aus dem
Fließtext. Neben der fehlenden Liste melden beide Wege inzwischen drei weitere
Dinge — mehrfach bemaßte Schritte, eine Serie in der Serie, und eine
Schrittsumme, die nicht zu `duration_min` passt. Letzteres nur, wenn *jeder*
Schritt eine Dauer trägt: Bei einer Streckeneinheit hängt die Zeit an der Pace,
und eine Abweichung wäre der Normalfall statt ein Befund.

**Zwei Beschreibungen derselben Einheit können auseinanderlaufen** — das ist
der Preis, und er ist bewusst bezahlt. `structure` bleibt, weil der Athlet es
in Dashboard und Planansicht liest; `steps` ist, was die Uhr bekommt. Der
Prompt sagt ausdrücklich, dass beide dieselbe Einheit beschreiben müssen. Ein
Auseinanderlaufen wäre aber ohnehin die bessere Lage als heute: Jetzt läuft der
Text gegen die Uhr auseinander, und zwar unsichtbar.

**Die Bahnlänge gehört ans Becken, nicht an jede Schwimmeinheit**
(`workouts.schwimmort`, `PlanSession.swim_location`). `poolLength` stand einmal
an *jedem* Schwimm-Workout, und damit ging auch die Freiwasserrunde als
Beckentraining auf die Uhr: Dort zählt das Gerät Bahnen, statt Strecke zu
messen, und „4x150 m mit 25 s Pause" meint im See etwas anderes als auf der
25-m-Bahn. Am echten Konto ist das kein Randfall — der Athlet schwimmt den
halben Sommer im Freiwasser (sieben von zehn Einheiten im Juli/August).

**Woher der Ort kommt, ist der eigentliche Punkt: Die KI sagt ihn.** Aus Titel
und Aufbau ist er nicht sicher abzulesen, und die Ausrüstung im Fragebogen
nennt nur, was *möglich* ist — welche Einheit wohin gehört, entscheidet die
Planung. `SESSION_SCHEMA` trägt deshalb `swim_location` (`pool` |
`open_water`), verlangt es in `PRINZIP_STEUERGROESSEN` für jede
Schwimmeinheit, und die Spalte hängt an der Einheit statt am Plan. Unbekannte
Werte fallen in `normalize_swim_location()` weg statt den Block zu kippen: Ein
falscher Ort wäre schlimmer als keiner, denn dann greift der Rückfall.

**Der Rückfall liest nur den Titel** — für Blöcke, die vor dem Feld entstanden
sind, und für die Zwischenablage, wo eine KI antwortet, die den Prompt nicht
kennt. Er suchte zuerst auch in Beschreibung, Zweck und Aufbau, und das ging an
einem echten Plan sofort schief: „Ruhiges Schwimmen mit Orientierungsblick"
kippte ins Freiwasser, weil in der Beschreibung „Orientierungsblick fürs
Freiwasser" stand — eine Beckeneinheit über 4x50 m und 4x150 m mit 20 s Pause,
die eine Freiwasserfertigkeit *übt*. So steht das Wort dort meistens: als
Zweck, nicht als Ort. Gesucht wird deshalb nur im Titel, und nur in eine
Richtung — ohne Hinweis bleibt es beim Becken, wie bisher.

**Was im Freiwasser mitgeht, ist wenig — und das ist am echten Konto
nachgemessen** (`scripts/garmin_freiwasser_probe.py`, je Variante ein
temporäres Workout, zurückgelesen und im `finally` gelöscht). Ein
Schwimm-Workout **ohne** `poolLength` nimmt Garmin an und gibt es unverändert
zurück. Ein `subSportType` dagegen wird abgelehnt, und zwar beide plausiblen
Kennungen: `open_water_swimming` (5) und der FIT-Untertyp `open_water` (18)
quittiert der Dienst mit **500** — nicht mit einer Fehlermeldung, sondern mit
einem Serverfehler für das ganze Workout. Einen Freiwasser-Untertyp führt
Garmins Workout-Format also nicht; strukturierte Workouts sind dort
Beckensache. Es fällt deshalb nur die Bahnlänge weg, und die Beschreibung sagt
in ihrer ersten Zeile „Freiwasser — auf der Uhr im Freiwassermodus starten":
Den Aufzeichnungsmodus wählt das Gerät nicht selbst, und niemand sonst sagt es
dem Athleten. Wer hier eine Kennung nachtragen will, probiert sie mit dem
Skript und nicht im Betrieb — ein geratener Wert nimmt das *ganze* Workout mit.

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
Pause zu erkennen gibt. **Daran hängt die Vollständigkeit der Serie**, und die
Pause heißt je nach Sportart anders: `_ART_SCHLUESSELWOERTER` kennt deshalb
neben „dazwischen“ auch „lockeres Kurbeln“ (Rad), „locker traben“ (Lauf) und
„Treiben“/„Trudeln“ (Wasser) — als Belastung gelesen fällt die Pause aus der
Gruppe heraus, und auf der Uhr steht „6 ד über einem einzigen Schritt. Die
beiden Wasserwörter tragen ein führendes Leerzeichen, sonst zöge „antreiben“
mit; „locker schwimmen“ fehlt bewusst, weil das ebenso oft der Hauptteil ist. Und **Ein- und
Ausrollen gehören nie in eine Serie**: Enthält der Rumpf einen Warmup- oder
Cooldown-Schritt („4x6 min Z4 / 10 min Ausrollen Z1“), wird die Zeile als Block
ganz abgelehnt und Teil für Teil neu gelesen — viermal ausrollen ergibt keine
Einheit.

**Eine Zahl ohne Maß zählt Runden, nicht Schritte** (`_als_variante`,
`_verteile_varianten`). „6x1 min Technik: 2x Abschlagschwimmen (Catch-up),
2x Fingerspitzen ziehen (Fingertip Drag), 2x einarmig (Single-Arm)“ — die drei
Zahlen hinter dem Doppelpunkt verteilen Übungen auf die sechs Runden, sie zählen
keine Schritte. Als Schritt gelesen ergaben sie keinen: `_baue_schritt()` fand
weder Zeit noch Strecke und gab `None` zurück, und die Zeile fiel **still weg**
— auf der Uhr stand sechsmal die erste Übung, die beiden anderen kamen im ganzen
Workout nicht mehr vor. Erkannt wird deshalb als *Variante*, was eine
Wiederholungszahl trägt, aber kein Maß, und einer offenen Serie folgt. Die erste
Übung steckt dabei meist im Schritt der Serie selbst („1 min Technik:
2x Abschlagschwimmen“) und wird von `_variante_im_text()` herausgelöst — nicht
gierig, damit die Dauer im vorderen Teil bleibt.

**Verteilt wird nur, wenn die Rechnung aufgeht**: 2 + 2 + 2 = 6, und dann ist die
Lesart eindeutig — aus einer Serie über sechs Runden werden drei über je zwei,
jede mit ihrer Übung im Schritttext und jede mit der Serienpause, die zu jeder
Runde gehört. Stimmt die Summe nicht, ist nicht belegt, welche Übung in welcher
Runde läuft, und geraten wird hier so wenig wie sonst. **Verschluckt wird
trotzdem nichts**: Die Übungen stehen dann im Wortlaut im Schritttext, so wie
der Plan sie schreibt. Genau das war der Fehler — nicht die fehlende Verteilung,
sondern die verschwundene Zeile.

**Auf dem Rad steuert die Leistung — aber nur, wo sie gemessen wird**
(`leistungssteuerung`, `radort`, `_leistung`, `_ziel`). Bei `bike` gewinnt Watt
vor jeder Herzfrequenzvorgabe: Auf dem Smarttrainer regelt Garmin das Gerät
danach, und im Freien zeigt die Leistung sofort an, ob das Tempo stimmt, während
der Puls Minuten hinterherzieht. Ein Zielkorridor steuert allerdings nur, was die
Uhr auch misst, und dafür braucht sie eine Quelle: ein **Powermeter am Rad**
(`powermeter` im Fragebogen) — dann überall — oder die **Rolle**
(`smart_trainer`), die ihre Leistung selbst meldet. Fehlt beides, steuert
draußen der Puls.

Das war der Fehler, der die Regel eingeschränkt hat: Ein Athlet mit Rolle, aber
ohne Powermeter bekam auf einer Schlüsseleinheit über Schwellenintervalle *im
Freien* an jedem Schritt ein Wattziel — aus der Zone hochgerechnet, weil die FTP
im Profil stand (sie kommt ja von der Rolle). Auf der Uhr stand damit ein
Korridor ohne Messwert, während der Puls — die einzige Größe, die dort
tatsächlich vorliegt — als bloßer Text in die Beschreibung gewandert war. Der
Plan hatte die Einheit sauber über die Herzfrequenz beschrieben, bis auf die Uhr
kam sie unsteuerbar an. **Ohne bekannte Ausrüstung** (kein Fragebogen am Plan)
bleibt es beim bisherigen Verhalten: Nichts zu wissen ist kein Beleg dafür, dass
kein Powermeter am Rad sitzt. Eine **leere** Ausrüstungsliste ist dagegen eine
Aussage — wer nichts angekreuzt hat, hat nichts.

Entschieden wird **einmal je Einheit**, nicht je Schritt (`watt_steuerbar` durch
`baue_workout` hindurch): Ein Workout, dessen Intervalle über Watt und dessen
Ein- und Ausrollen über den Puls liefen, wechselte mitten in der Einheit die
Steuergröße — genau der Zustand, gegen den die Regel unten überhaupt entstanden
ist.

Innerhalb dieser Grenze gilt die alte Reihenfolge unverändert. Zuerst zählt die Angabe im **Schritttext**, denn Belastung und
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
ausrechnen kann, ist keine. Wo die Leistung gar nicht erst gemessen wird, gibt es
umgekehrt nichts zu verdrängen — der Puls ist dann das Ziel, und die Wattzahlen
der KI bleiben als Teil des Aufbautexts in der Beschreibung stehen.

**Wo die Radeinheit stattfindet, sagt die KI** (`PlanSession.bike_location`,
`workouts.radort`) — dieselbe Bauart wie `swim_location` und aus demselben Grund:
Aus Titel und Aufbau ist der Ort nicht sicher abzulesen, und die Ausrüstung im
Fragebogen nennt nur, was *möglich* ist. `SESSION_SCHEMA` trägt deshalb
`bike_location` (`indoor` | `outdoor`), `PRINZIP_STEUERGROESSEN` verlangt es für
jede Radeinheit und sagt der KI zugleich, dass Wattvorgaben ohne `powermeter`
draußen nichts steuern. Unbekannte Werte fallen in `normalize_bike_location()`
weg statt den Block zu kippen.

**Der Rückfall liest nur den Titel**, für Blöcke von vor dem Feld und für
Antworten über die Zwischenablage — und er läuft nur in eine Richtung: ohne
Hinweis bleibt es bei „draußen". Auch diese Richtung ist Absicht. Sie kostet im
Zweifel eine Pulssteuerung statt einer Wattsteuerung; umgekehrt stünde auf einer
Straßenausfahrt ein Wattziel, das niemand messen kann. Gesucht wird mit
**Wortgrenzen** (`_INDOOR_TITEL`), sonst zöge „rolle" aus *ein*rollen und
*aus*rollen jede zweite Radeinheit auf die Rolle — die beiden Wörter, mit denen
fast jeder Radaufbau anfängt und aufhört.

**Die Ausrüstung kommt über den Plan an die Einheit**
(`workouts.ausruestung_der_einheit`: Einheit → Plan → Anfrage → `equipment`),
nicht als Parameter durch die halbe Übertragung. Sie hängt am Fragebogen und
damit am Plan, nicht am Aufrufer, und so bekommt jeder Weg auf die Uhr dieselbe
Antwort — Block, Einzelübertragung und der Fingerabdruckvergleich, der über
„geändert" entscheidet. Daran hing eine stille Lücke: Ohne ausdrückliche
`request_id` nahm der Export den zuletzt gespeicherten Fragebogen, der Plan
behielt aber `request_id = NULL` und war damit von genau dem Fragebogen getrennt,
aus dem er entstanden war. Aufgefallen ist das erst, als die Ausrüstung anfing,
über den Inhalt des Workouts zu entscheiden. `plan_import._letzter_fragebogen()`
trifft jetzt dieselbe Wahl wie der Export, für beide Auslöser.

**Zwei Grammatiken, weil derselbe Text Verschiedenes bedeutet**
(`zerlege_uebungsliste()` neben `zerlege_struktur()`). Bei Kraft und Mobility
beschreibt `structure` keinen Zeitverlauf, sondern eine Übungsliste — „3x15 Leg
Raise je Seite / 2x45 s Dehnung je Seite“. Durch die Ausdauer-Grammatik gelesen
wurde daraus Unsinn: „3x15“ eine Wiederholungsgruppe über 15 Sekunden, die
zweite Übung darin die „Pause“, und jede Übung ohne Zeitangabe fiel still weg —
auf der Uhr standen dann zwei Abschnitte, während die Notiz vier nannte. Für die
Sportarten in `UEBUNGSSPORTARTEN` steht deshalb jede Übung für sich, in der
Reihenfolge des Plans. Getrennt wird nur an „ / “, Zeilenumbruch und
Aufzählungszeichen — nicht am Komma („…, 4 s exzentrisch abgesenkt“ ist ein
Zusatz) und nicht an „mit“ („Monster Walks mit Band“). Unter zwei erkannten
Übungen greift wieder der Ersatzschritt über die geplante Dauer. Diese Einheiten
bekommen außerdem **keinen Herzfrequenzkorridor**: Der Puls springt dort von
Satz zu Satz und fällt in der Dehnung, ein Alarm liefe fast durchgehend.

**Und der Umfang der Übung steuert die Uhr, statt bloß danebenzustehen**
(`_uebungsumfang`). „2x45 s je Seite“ wird eine Wiederholungsgruppe über vier
Durchgängen mit einem Schritt von 45 s, „3x15“ eine über drei Durchgängen mit
fünfzehn gezählten Wiederholungen (`ConditionType.REPS`). Vorher war jede Übung
*ein* Schritt bis zur Rundentaste, und Satzzahl wie Haltedauer standen nur als
Text darin: Die Uhr zählte und stoppte nichts, obwohl beides im Plan steht, und
der Athlet zählte selbst. Dieselbe Form führt Garmin in seinen eigenen Workouts
(Serie über einem zeitgesteuerten Kind, nachgesehen an Workout 1037036157).
Erkannt werden nur drei Schreibweisen — „3x40 s“ / „4x2 min“, „3x15“ und der
einzelne Satz („10 Wiederholungen“, „90 s“, „3 min“) —, und die **Satzform geht
vor**: In „3x8 Step-Downs je Seite, 4 s exzentrisch abgesenkt“ ist „3x8“ der
Umfang und „4 s“ ein Zusatz zur Ausführung. Nennt eine Zeile gar keinen Umfang,
bleibt es beim Schritt bis zur Rundentaste — geraten wird auch hier nicht.

**„je Seite“ verdoppelt die Durchgänge**, denn die Angabe gilt je Satz *und*
Seite: „2x45 s je Seite“ sind vier Haltephasen, nicht zwei. Dieselbe
Verdopplung gilt für „pro Bein“, „je Richtung“ und „beidseitig“. An den
Schritttext hängt dabei „— je Durchgang eine Seite“, sonst stünde
„Wiederholen 4×“ über einer Zeile, die von zwei Sätzen spricht.

**Und der Umfang fällt aus dem Schritttext heraus** (`_ohne_umfang`, gespeist
aus demselben `_umfangstreffer()` wie die Zerlegung selbst — zwei Stellen, die
dieselbe Angabe suchen, fänden irgendwann verschiedene). Die Durchgänge zählt
die Gruppe, die Sekunden hält der Timer; bliebe „3x40 s je Seite“ zusätzlich im
Text stehen, läse der Athlet auf der Uhr „3x40 s“ unter einer Zeile, die 4:00
anzeigt. Genau das stand im beanstandeten Screenshot. Bleibt nach dem Kürzen
nichts übrig (eine Zeile, die nur „3x40 s“ sagt), bleibt die ganze Zeile
stehen: Eine leere Beschriftung wäre schlechter als eine doppelte.

**Eine benannte Übung wird auf der Uhr vorgemacht** (`garmin/uebungen.py`).
Garmin zeigt zu einem Workout-Schritt eine Bewegungsanimation — aber nur, wenn
der Schritt zwei Felder trägt: `category` (Bewegungsgruppe) und `exerciseName`
(die genaue Variante), beide aus Garmins eigenem Katalog. Ohne sie steht auf
der Fenix bloß die Textzeile „Seitstütz 3x40 s“, und wer die Bewegung nicht
kennt, macht sie falsch. Der Katalog kommt aus Garmins eigenen JSON-Dateien
(`garmin/katalog.py`) — eigene Zahlen kämen nicht in Frage, denn eine
unbekannte Kategorie beantwortet Garmin mit 400, und zwar für das ganze
Workout. Das Problem in der Mitte: Der
Katalog ist englisch, der Plan deutsch, und die Übung steht in einer Zeile
voller Beiwerk. Deshalb wird beides auf Wortstämme normalisiert und im Text das
*längste zusammenhängende* Stück gesucht, das im Verzeichnis steht — „Seitstütz“
ergibt Side Plank und nicht Plank, weil zwei Wörter mehr wiegen als eins. Die
deutschen Entsprechungen in `SYNONYME` sind dabei nur ein zweiter Schlüssel auf
denselben Eintrag, keine zweite Datenhaltung.

**Der Katalog kommt täglich von Garmin, in zwei Ausführungen**
(`garmin/katalog.py`, `web-data/exercises/Exercises.json` und `Mobility.json`).
Er stand einmal in `garminconnect.exercises` — einer statisch erzeugten Liste
in der Bibliothek, die mit *ihr* altert statt mit Garmin. Geholt wird jetzt als
letzter Schritt des Abgleichs: Der ist der einzige tägliche Lauf, den es gibt,
und eine zweite Weckschleife für zwei öffentliche JSON-Dateien wäre Aufwand
ohne Gegenwert. Es ist zugleich der einzige Schritt, der **nicht** gegen
Garmins API geht — er braucht keine Anmeldung und zählt auf keine
Anfragegrenze.

**Zwei Kataloge, weil Garmin zwei führt.** In Connect lässt sich eine Yogapose
nicht in ein Krafttraining legen, und eine dort unbekannte Kategorie kostet das
**ganze** Workout (400). `finde()` bekommt deshalb die Sportart mit
(`workouts._SPORT_ZU_KATALOG`), und `Mobility.json` bringt dafür `POSE`
(43 Yogaposen) und `MOVE` (24 Dehnungen) mit — genau die Kategorien, die hier
einmal als unerreichbar dokumentiert waren.

**Verschmolzen wird, weil die JSON keine Anzeigenamen trägt.** Dort stehen nur
Enum-Schlüssel; „Side Plank“ oder „Banded Ab Twist“ ist Garmins UI-Übersetzung
und kommt nirgends mit. Die Texterkennung sucht aber über den Namen. Also
entscheidet die **JSON über den Bestand** — nur der geht auf die Uhr —, und den
**Namen liefert `garminconnect.exercises`**, wo das Paar dort bekannt ist. Aus
dem Schlüssel allein abgeleitet verlören 835 von 1527 Namen ihren Qualifizierer
(„Ab Twist“ statt „Banded Ab Twist“); für die rund hundert Einträge, die nur
die JSON kennt, wird er trotzdem so gebildet — deren Schlüssel sind
beschreibend genug (`DOWNWARD_FACING_DOG`). Gemessen an allen Katalognamen und
allen `SYNONYME`-Schlüsseln zusammen ändert die Umstellung **keinen einzigen**
Treffer; sie fügt nur hinzu. Die Grundübung einer Kategorie trägt dabei
`exercise == category` und nicht den Leerstring: Der Wert geht unverändert als
`exerciseName` auf die Uhr.

**Geprüft wird vor dem Überschreiben, nicht danach.** Eine HTML-Fehlerseite oder
ein abgerissener Rumpf, der eine gute Datei ersetzt, nähme jeder Kraft- und
Mobility-Einheit ihre Animation — unbemerkt, bis jemand auf die Uhr sieht. Das
ist der einzige Weg, auf dem dieser Mechanismus dauerhaft schaden könnte, und
deshalb hängt alles an `_pruefe()`: Ohne plausible Kategorie- und Übungszahl
wird nicht geschrieben, und geschrieben wird atomar. Schlägt der Abruf fehl,
gilt der gespeicherte Stand und der Hinweis wandert über `ergebnis.hinweise` in
die Meldung des Laufs. Abgelegt wird neben der Datenbank (`config.KATALOG_DIR`,
im Add-on `/data`) — nur dort überlebt eine Datei ein Update; die
Erstausstattung im Abbild (`app/garmin/katalogdaten/`) springt ein, solange noch
nichts geholt wurde. Eine Versionierung gibt es nicht.

Zwei Kleinigkeiten, die am echten Dienst gemessen sind und beide nicht
offensichtlich: Auf Pythons Vorgabe-Kennung „Python-urllib/3.12“ antwortet
Garmin mit **403** (auf so ziemlich jede andere mit 200), und der Abruf braucht
`certifi` — Pythons OpenSSL bringt auf macOS keinen Zertifikatsspeicher mit.

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
Krafteditors fehlen). Daraus stand hier einmal die Regel „sie sind nirgends
abrufbar“ — **überholt**: `Mobility.json` liefert genau sie, und seit der
Katalog von dort kommt, sind sie erreichbar.

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

**Wer mit der Rolle arbeitet, dehnt nicht** (`_MIT_ROLLE`). Garmins Katalog
kennt kein Faszienrollen — die einzigen Treffer mit „Foam Roller“ sind Übungen
*auf* der Rolle. Ohne Sperre zog „Faszienrolle lateraler Oberschenkel (Foam
Roll IT Band)“ die „Standing IT Band Stretch“ an sich, weil deren Schlüssel
„it band“ mitten im Text steht: Auf der Uhr lief die Animation einer Dehnung im
Stand, während der Plan Ausrollen im Liegen meint. Nennt eine Zeile Rolle oder
Massageball, gilt ein Treffer deshalb nur, wenn der Katalogeintrag die Rolle
selbst nennt. Der Preis ist der bekannte: kein Titel, keine Animation — dafür
keine falsche.

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

**Oben deutsch, unten englisch — jede Sprache genau einmal**
(`workouts._beschriftung`). Die Überschrift eines Übungsschritts ist **kein
freies Feld**: Sie kommt allein aus `category`/`exerciseName`, und Garmin
übersetzt den Katalognamen in die Sprache seiner App. Bei einem Treffer steht
die deutsche Bezeichnung also bereits oben, und der Aufbautext darunter
wiederholte sie — „Taubenstellung (Pigeon Pose) 2x45 s je Seite“ unter einer
Überschrift, die schon „Taubenstellung“ sagt. Der deutsche Name fällt deshalb
aus der Beschreibung, der englische aus der Klammer rückt an seine Stelle. Über
alle Kraft- und Mobility-Einheiten der Datenbank betrifft das 61 von 71
Schritten.

**Ohne Treffer bleibt die Zeile unangetastet** — und das ist der Kern der Regel.
Der Titel ist dann „--“ (siehe „Bekannte Grenzen“), und der deutsche Name in der
Beschreibung ist das Einzige, was die Übung überhaupt noch benennt; ihn dort
gegen den englischen zu tauschen nähme dem Schritt seine letzte lesbare
Bezeichnung. Zwei Proben halten den Tausch zusätzlich davon ab, mehr
wegzunehmen als den Namen: Ein **Umlaut** in der Klammer verrät den deutschen
Ausführungshinweis („Wandsitz (Rücken flach an der Wand)“), und der **Umfang
muss die Zeile unverändert überstehen** — „3x12 Liegestütze (Push-Up)“ nennt ihn
*vor* der Klammer und stünde sonst ohne. Was trotzdem durchrutscht, kostet nur
die Beschriftung: Welche Bewegung gemeint ist, sagen Titel und Animation.

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

**Die Vorlage trägt Slotkennung und Trainingsnamen**
(`workout_pool.slot_name`, `stempel_kennung`, `workouts.mit_kennung`). In Garmin
steht „TC01-Schwellentraining Rad": vier Zeichen Kennung, Bindestrich,
Trainingsname. Beides muss in dieses **eine** Feld, weil ein Kalendertermin
keinen eigenen Namen tragen kann (siehe übernächsten Absatz) — was nicht im
`workoutName` steht, steht nirgends.

Die Kennung sagt, welcher der fünfzehn Slots das ist. Sie steht **vorn**, weil
die Uhr lange Namen am Ende kürzt: hinten angehängt fiele als Erstes weg, worauf
es ankommt. Aus demselben Grund schneidet `MAX_NAME` hinten ab. Die Slots hießen
einmal „TriCoach Slot 01"…„15" — vierzehn identische Zeichen am Anfang, fünfzehn
Einträge, die gekürzt alle gleich aussehen. „TC01" trennt beim dritten Zeichen.

**Zwei Zwischenstände, beide verworfen, und der Grund lohnt das Festhalten.**
Der Name hieß erst „TC03 · Lockerer Dauerlauf" und dann nur noch „TC03" — die
Beweisführung dafür war, dass die Uhr den Namen beim ersten Synchronisieren
einfriert: Weil derselbe Slot laufend neuen Inhalt bekommt, stünde dort ab dem
zweiten Durchlauf ein Trainingsname, der nicht mehr stimmt, und ein Name, der
etwas Falsches behauptet, ist schlechter als gar keiner. In der Fassung mit
bloßer Kennung wanderte der Trainingsname deshalb in die erste Zeile der
Beschreibung. **Die Prämisse war falsch** — siehe „Was vorbei ist, gibt seinen
Slot frei". Veraltet dort nichts, gibt es auch nichts zu vermeiden; der
Trainingsname steht wieder im Namen und aus der Beschreibung ist er wieder
heraus, wo er nur doppelt stünde.

**Der Termin kann keinen eigenen Namen tragen** — deshalb teilen sich Kennung
und Trainingsname ein Feld, und das ist am echten Konto abgelesen
(`scripts/garmin_kalendername_probe.py`). Die Vorlage „TC03" zu nennen **und**
den Trainingsnamen an den *Kalendereintrag* zu hängen, wäre die saubere Trennung
gewesen: die Kennung dort, wo sie etwas ordnet, der Trainingsname dort, wo man
ihn liest.
`schedule_workout` schickt aber ausschließlich `{"date": …}`, und das
Terminobjekt führt zwar `nameChanged` und `newName` — Felder, die genau danach
aussehen —, doch keiner von **neun** geprüften Wegen setzt sie. Die Probe deckt
ab: `newName` im POST; `PUT` auf `/workout-service/schedule/{id}` mit knappem
Rumpf, mit `newName` allein, mit `date` daneben, mit dem ganzen zurückgelesenen
Objekt, mit geändertem Namen im *eingebetteten* Workout und mit `title` am
Termin; `POST` auf dieselbe Adresse; sowie `/calendar-service/item/{id}` und
`/workout-service/schedule/workout/{id}`.

Aufschlussreich sind dabei die Fehlschläge selbst. Der `PUT` auf
`/workout-service/schedule/{id}` **existiert**: Mit knappem Rumpf antwortet
Garmin mit **500** samt Stackframe (`WorkoutScheduleServiceImpl:71`), mit dem
vollständigen Objekt mit **204**. Der Endpunkt wird also erreicht und nimmt an —
er ändert nur nichts von dem, was hier gebraucht wird; vermutlich verlegt er
bloß das Datum. Die anderen beiden Adressen gibt es nicht (404), der `POST`
lehnt ab (400). `newName`/`nameChanged` gehören mit einiger Wahrscheinlichkeit
zu Garmins eigenen Trainingsplänen — im selben Objekt stehen `atpPlanTypeId`,
`tpType` und `itp`.

**Wer das noch einmal aufmachen will**, prüft es mit dem Skript und glaubt nicht
dem Statuscode — vier der neun Wege quittieren mit 2xx und tun nichts. Und er
klärt vorher die eine Frage, die das Skript nicht beantworten kann: ob Garmin
Connect im Browser überhaupt anbietet, einen *terminierten* Workout umzubenennen.
Kann die eigene Oberfläche es nicht, gibt es den Endpunkt nicht zu finden.

**Die Kennung entsteht erst, wenn der Slot feststeht** — `baue_workout()` kennt
ihn nicht, `uebertrage_einheit()` wählt ihn danach. Deshalb setzt
`workout_pool.stempel_kennung()` sie unmittelbar vor dem Aufruf an Garmin ein.
Der **Fingerabdruck** bleibt davon unberührt und wird weiter über den
*ungestempelten* Namen gerechnet: Beide Wege, die ihn bilden
(`uebertrage_einheit()` und `zustand_der_einheiten()`), sehen damit dasselbe.
Den Namen dort ganz auszuklammern liegt nahe und ist falsch — eine Einheit, an
der sich nur der Titel ändert, käme dann nie mehr auf die Uhr. In der App
dagegen steht der Trainingsname **ohne** Kennung: `link.title` speist die
Fortschrittsmeldungen, und dort sagt „TC03" niemandem etwas.

**Bestehende Vorlagen holen die Kennung einmalig nach**
(`workout_pool._ziehe_kennungen_nach`, am Ende von `stelle_pool_sicher`). Ohne
diesen Schritt käme sie nur tröpfchenweise an: An einer unveränderten Einheit
rührt sich der Fingerabdruck nicht, ihre Vorlage wird also nicht neu
geschrieben, und der alte Name bliebe stehen, bis der Slot irgendwann
wiederverwendet wird — in Connect stünden eine Weile lang zwei
Benennungsschemata nebeneinander. Weil Garmin beim Aktualisieren das *ganze*
Workout ersetzt, kostet das zwei Anfragen je betroffenem Slot. Der bisherige
Name bleibt dabei erhalten, die Kennung rückt nur davor; die Ausnahme ist der
alte Platzhaltername eines nie belegten Slots, denn „TC07-TriCoach Slot 07"
sagt zweimal dasselbe. Selbstbegrenzend: Danach trägt jede Vorlage ihre
Kennung, und die Schleife kostet keine Anfrage mehr.

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
vorinstallierter; fünfzehn Pool-Slots lassen bewusst Reserve.

**An der Fenix 8 nachgemessen:** Wird eine bestehende Workout-ID in Connect
umbenannt und inhaltlich geändert, synchronisiert die Uhr **beides** in den
vorhandenen lokalen Eintrag — Inhalt *und* Name. Unter „Trainings“ steht danach
der neue Name.

Hier stand jahrelang das Gegenteil („Dessen Name unter ‚Trainings‘ bleibt zwar
alt"), und dieser eine Satz hat zwei Umbauten getragen: erst die Slotkennung als
Vorsilbe, damit wenigstens sie zuordenbar bleibt, wenn der Rest veraltet, dann
den Wegfall des Trainingsnamens überhaupt. **Beide Male war die Prämisse
falsch**, und aufgefallen ist es erst, als jemand nachgefragt hat, wie das
Workout im zweiten Zyklus eigentlich heißt. Die Lehre ist dieselbe wie bei
Schlaf, Körperbatterie und dem Aktivitätsdetail — nur eine Ebene höher: **Eine
einzelne Beobachtung am Gerät ist eine Messung, keine Regel.** Wer auf ihr
aufbaut, prüft sie vorher noch einmal nach.

**Davon getrennt bleibt der Sportartwechsel ungeprüft:** Der
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

**Und er lässt sich monatsweise leeren** (`uebertragung.raeume_monat_auf`). Das
Einzellöschen gab es von Anfang an; was fehlte, war der Griff für „räum das alles
weg". Der Umfang ist bewusst **der angezeigte Monat** und nicht „alles ab heute":
Der Kalender zeigt ohnehin einen Monat, die Kosten bleiben absehbar (eine Anfrage
je Termin), und der Nutzer sieht vor dem Druck genau, was verschwindet — für die
Folgemonate blättert er weiter und drückt erneut. „Alles ab heute" müsste
stattdessen Monat für Monat blind nachladen, bis nichts mehr kommt.

Drei Grenzen halten den Knopf davon ab, zu viel wegzuräumen. Es fällt nur der
**Termin**, nie die Vorlage — die fünfzehn Pool-Kennungen sind der Kern der
ganzen Übertragung, und genau sie will der Nutzer behalten. Was „eigen" ist,
entscheidet die **Kennung und nicht der Titel** (`eigene_workout_ids`): die
Pool-Vorlagen dieses Nutzers und der Altbestand aus `GarminWorkoutLink`; was der
Athlet in Connect selbst eingeplant hat, bleibt stehen. Und **gelesen wird der
Monat aus Garmin, nicht die eigene Zuordnungstabelle** — ein Termin, dessen Link
mit `garmin_uebergehen` gestorben ist, steht nur noch dort, und er ist der
Hauptgrund, warum es diesen Knopf überhaupt gibt.

`vergiss_termin()` behält dabei die Zuordnung und löscht nur ihren Termin: Die
Vorlage liegt weiter im Pool, die Einheit gilt im Plan wieder als zu übertragen.
Den Link zu löschen ließe sie auf „offen" zurückfallen, und der nächste Lauf
legte eine zweite Vorlage neben die bestehende. Der Lauf selbst arbeitet im
Anfrage-Thread wie das Löschen eines Plans, nimmt aber anders als das
Einzellöschen das **globale Schloss** (nicht blockierend, sonst 409): Hier läuft
eine Reihe von Schreibaufrufen, und ein daneben laufender Übertragungslauf legte
Termine an, die dieser Lauf gerade wegräumt.

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
  Ausführungsspalten (`hr_zone_seconds`, `garmin_abschnitte`,
  `garmin_uebungen`, `garmin_compliance`) stehen dort bewusst nicht, sonst zöge
  jedes neue Feld `frontend/src/types.ts` mit.
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
und beim Triathlon Disziplinenwahl nach dem längsten
Abstand statt „alle drei pro Woche". Das Template wird mit `.format()` gefüllt —
neue Platzhalter (`{tage}`, `{start}`, `{ende}`) müssen in `build_prompt()`
mitversorgt werden.

**Die Punkte 3 und 4 sagen, woran — nicht wie viel.** Sie schrieben einmal
„polarisiert, der Großteil in Z1/Z2", „höchstens eine intensive Einheit je drei
Tage" und „mindestens 48 h zwischen zwei intensiven Einheiten" vor. Das sind
Trainerentscheidungen und keine Datenlage: Die Rolle im Prompt ist ein
Ausdauer-Trainingswissenschaftler, der sie mitbringt — was ihm fehlt, sind die
Daten *dieses* Athleten. Beide Punkte nennen sie deshalb weiterhin namentlich
(`wochenuebersicht`, `zeit_in_hf_zonen_min`,
`tage_seit_letzter_intensiver_einheit`) und geben die Entscheidung ausdrücklich
zurück.

Zwei Dinge hängen daran und sind beim Kürzen ausdrücklich stehen geblieben.
`_days_since_hard_session()` rechnet über die **ganze** Historie statt über vier
Wochen, weil Punkt 4 diese Zahl liest — der Block beginnt nicht bei null, und
ohne den Namen im Prompt verlöre das Feld seinen einzigen Leser. Und die Punkte
bleiben **an ihrer Nummer**: „Punkte 1 bis 4 und 13" steht im Prompt an zwei
Stellen, in diesem Dokument an mehreren, und `test_flow.py` prüft den Wortlaut.
Der Einzelanpassungsprompt wurde mitgezogen (Punkt 1 und der Aufgabentext) —
zwei Wege mit zwei Maßstäben wären schlechter als ein strenger.

**Punkt 8 existiert in zwei Fassungen**, je nach gewählter Disziplin
(`_prinzip_disziplin()`) — für Triathlon wörtlich der alte Text, sonst eine
Fassung, die die anderen Disziplinen und `brick` ausschließt. Punkt 13 verliert
dabei seinen Ausweichsatz, und `_session_schema()` nimmt die Sportarten aus dem
Antwortformat. Siehe „Die gewählte Disziplin entscheidet, was im Block vorkommen
darf". Die **Nummern bleiben**, wie überall im Prompt.

**Der Preis, offen gesagt:** Punkt 6 existiert nur, weil ein Regelwerk aus
lauter Bremsen das Modell zu sicheren Z2-Wochen treibt (siehe gleich). Die
Bremsen zu lockern verschiebt das Gleichgewicht in die andere Richtung, und
nichts in der App prüft das Ergebnis nach. Ob es trägt, zeigt sich nur an den
Blöcken.

**Punkt 6 ist das Gegengewicht zu allen anderen.** Die Prinzipien 1 bis 4 sind
Bremsen — sie beschreiben ausschließlich, wann zurückgenommen wird (ACWR, HRV,
Trainingsreife, der Abstand zum letzten harten Reiz). Ein Regelwerk, das nur bremst, liest sich für ein
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

**„Regelmäßig" heißt dort ausdrücklich nicht „dasselbe noch einmal".** Punkt 9
sagte nur „Mobility kurz und regelmäßig" — und genau das hat die KI getan: Am
18.08.2026 verordnete sie eine Mobility-Einheit für Hüfte und lateralen
Oberschenkel, am 19.08. eine für Hüfte, Gesäß und Oberschenkelaußenseite. Sie hat
dabei nichts übersehen: Die Einheit vom Vortag lag mitsamt vollständiger
Übungsliste im Export, und `tage_seit_letzter_einheit_je_sportart` sagte
`mobility: 1`. **Die Wiederholung war eine Prompt-Lücke, kein Datenmangel** — die
naheliegende Diagnose „sie weiß zu wenig" war hier die falsche. Punkt 9 verlangt
deshalb jetzt, in `trainingshistorie.einheiten` nach der letzten Ergänzungseinheit
zu sehen und Übungsauswahl wie Körperregion zu wechseln — zuerst in
`absolvierte_uebungen`, was die Uhr gezählt hat, erst dann in
`geplant_war.aufbau` oder `notiz`; dieselbe Region an zwei
aufeinanderfolgenden Tagen ist ein Fehler. Die Ausnahme davon war zunächst als
bloße Erlaubnis formuliert („eine Region, die akut zwickt, darf wiederholt
werden") und hat sich genau darin als zu schwach erwiesen — siehe „Punkt 13 ist
die Beschwerde des Athleten" weiter unten: Die Abwechslungsregel gilt jetzt
ausdrücklich nur für gesunde Regionen.

Daran hing eine Falle, die der bestehende Test
`test_der_prompt_nennt_nur_felder_die_es_gibt` sofort gefangen hat: Der Verweis
lautete zunächst auf `summary`, und das Antwortformat der Einzelanpassung hat
keins. `PRINZIP_ERGAENZUNG` geht deshalb jetzt wie `FITNESSREGELN_*` durch ein
eigenes `.format()` (`_prinzip_ergaenzung()`) — `.format()` formatiert
eingesetzte Werte **nicht** erneut, der Platzhalter muss also gefüllt sein, bevor
der Text in die Vorlage geht.

Punkt 12 liest neben `geplant_war` jetzt auch, **wie** die Einheit ausgeführt
wurde — `zeit_in_hf_zonen_min`, `absolvierte_abschnitte`,
`workout_einhaltung_pct` und, bei Kraft und Mobility, `absolvierte_uebungen` —
und schreibt von dort aus fort statt von der Vorgabe. Zu den Übungen nennt er
zwei Einschränkungen, die aus echten Daten stammen (aufgezeichnete statt
absolvierte Sätze, zu niedrig gezählte Wiederholungen) — siehe „Was in einer
Krafteinheit wirklich passiert ist".
Dazu `geplant_fuer`: Eine an einem anderen Tag absolvierte Einheit ist erfüllt,
nur verschoben, und ausdrücklich keine Nichtumsetzung. Auch hier gilt die Sperre
aus Punkt 11: Die Felder fehlen an vielen Einheiten, und ihr Fehlen ist keine
Aussage.

**Punkt 13 ist die Beschwerde des Athleten — und sie war die ganze Zeit da,
ohne dass eine Regel darauf zeigte.** `athlet.verletzungen_einschraenkungen`
steht seit jeher im Payload (`_athlete_block`), aber keines der zwölf Prinzipien
nannte den Schlüssel. Dass der Ausdauerteil trotzdem darauf einging, war
Eigeninitiative des Modells: Im Block vom 20.08.2026 („leichtes Läuferknie
rechts + leichte muskuläre Probleme auf der rechten Po-Seite") lag die
Schlüsseleinheit knieschonend auf dem Rad, der Koppellauf war gekürzt und die
Coaching-Notes trugen ein Abbruchkriterium. **Die Ergänzungseinheiten desselben
Blocks wichen der Region dagegen ausdrücklich aus** — „ohne zusätzliche Belastung
des rechten Knies", „ohne die zuletzt trainierte Hüft-/Gesäßregion erneut zu
belasten" — und planten stattdessen Schultergürtel und Brustwirbelsäule. Für ein
Läuferknie mit begleitenden Gesäßbeschwerden ist das die Umkehrung des Richtigen:
Die Gesäß- und Hüftabduktorenarbeit *ist* die Behandlung.

Auch das war kein Aussetzer, sondern eine Prompt-Lücke — dieselbe Sorte wie bei
der doppelten Mobility-Einheit oben. Punkt 9 verlangt, Übungsauswahl und
Körperregion zu wechseln, und die betroffene Region war am 17./18.08. dran
gewesen; die Ausnahme („eine Region, die akut zwickt") stand als *Erlaubnis zur
Wiederholung* mitten in einem Absatz, dessen Hauptaussage das Gegenteil sagt, und
verwies obendrein auf den „Fragebogen", während der Text unter `athlet` liegt.
Die Abwechslungsregel hat also gegen die Beschwerde gewonnen.

Drei Änderungen, die zusammengehören. Punkt 13 nennt den Schlüssel und trennt
die **zwei Richtungen**: als *Bremse* auf die betroffene Belastung (Reiz auf eine
andere Disziplin verlegen statt streichen) und als *Auftrag* ans
Ergänzungstraining (Ursache ableiten — typisch eine abgeschwächte Muskelgruppe
oberhalb des Gelenks — und die Übungen dagegen planen). Der Satz „auszusparen ist
die falsche Antwort" steht ausdrücklich da, weil genau das passiert ist; bei
akuter Reizung wird schmerzfrei geplant (isometrisch, kleinerer Bewegungsumfang),
nicht gar nicht. In `PRINZIP_ERGAENZUNG` gilt die Abwechslungsregel jetzt
ausdrücklich nur für **gesunde** Regionen — eine genannte Beschwerde ist der
Grund, ihre Region zu behalten, und abgewechselt wird um sie herum. Und Punkt 6
zählt 13 zu den **Bremsen**: Sonst läse „greift keine der Bremsen aus 1 bis 4,
also wird aufgebaut" über die Beschwerde hinweg.

Punkt 13 steht **hinten**, obwohl er inhaltlich zu den Bremsen 1 bis 4 gehört:
Einfügen hieße alle Querverweise im Prompt umnummerieren, und die Nummern stehen
an einem guten Dutzend Stellen — im Prompt selbst wie in diesem Dokument. Der
Einzelanpassungsprompt hat denselben Punkt als **Nummer 8**, kürzer gefasst: Dort
steht der Block fest, und der Auftrag ans Ergänzungstraining kommt ohnehin über
den geteilten Punkt 5 mit. Der Zusatz „unabhängig davon, ob der Wunsch sie
erwähnt" ist dort das Entscheidende — wer „nur 40 Minuten Zeit" schreibt, nimmt
sein Knie damit nicht zurück.

**Und dann kam dieselbe Dehneinheit drei Tage hintereinander.** Am laufenden
Betrieb aufgefallen, mit eingeschalteter Automatik und einem Läuferknie im
Freitext: drei Blöcke in Folge, jeder mit einer Mobility-Einheit auf dieselbe
Region, während die medizinische Lage bei diesem Bild Kräftigung verlangt. Wieder
**keine Datenlücke** — `tage_seit_letzter_einheit_je_sportart` meldete
`mobility: 1`, `absolvierte_uebungen` nannte die gezählten Übungen. Der Prompt
hat die Wiederholung angefordert, und zwar an vier Stellen zugleich:

*Punkt 9 behandelte die beiden Formen ungleich.* „Falls gewünscht, Kraft (…) —
nie unmittelbar vor einer Schlüsseleinheit. Mobility kurz und regelmäßig": eine
Bedingung samt Sperre gegen die eine Form, ein unbedingter Wiederholungsauftrag
für die andere. Bei täglicher Neuplanung liest sich „regelmäßig" als „heute
wieder". Beide stehen jetzt gleichrangig, beide unter
`trainingswunsch.zusatztraining`, und die Terminierungsregel ist als solche
benannt: Passt Kraft an einem Tag nicht, steht sie an einem anderen — sie wird
nicht durch Mobility **ersetzt**.

*Die Beschwerde-Ausnahme deckte zu viel.* Sie war die Antwort auf den umgekehrten
Fehler (siehe oben) und bleibt richtig, unterschied aber nicht zwischen
*derselben Region* und *derselben Einheit* — womit dieselbe Übungsliste am
Folgetag ausdrücklich gedeckt war. Sie gilt jetzt der Region: Zwei
aufeinanderfolgende Tage daran müssen sich in **Form, Übungsauswahl oder
Progression** unterscheiden.

*Punkt 12 zog auf die zuletzt gewählte Form zurück.* „Ein Satz mehr, zehn
Sekunden länger, eine schwerere Variante derselben Bewegung" — gestern gedehnt
hieß damit heute länger dehnen. Der Formwechsel steht jetzt daneben: derselben
Region mit der nächsten Form begegnen, erst mobilisieren, dann belasten.

*Punkt 13 stellte beide Zweige gleich stark auf.* „Eine abgeschwächte **oder
verkürzte** Muskelgruppe" — und bei sonst gleichem Text gewinnt die kürzere,
überall zulässige Form. Die abgeleitete Ursache entscheidet jetzt ausdrücklich
auch über die *Form* der Arbeit, und eine Beschwerde, die über mehrere Blöcke
dieselbe Antwort bekommt, ohne nachzulassen, ist ein Grund zum Wechseln statt
zum Wiederholen.

**Vorgeschrieben wird dabei nichts.** Dass ein Läuferknie Kräftigung braucht,
steht nirgends im Prompt — dieselbe Linie wie bei den Punkten 3 und 4: Die Rolle
ist ein Trainingswissenschaftler, der das mitbringt. Entfernt wurde nur die
Schieflage, die ihn zur kürzeren Form gedrängt hat. Was bleibt, ist eine Zusage
der KI; nachrechnen kann die App sie nicht.

**Der eigentliche Verstärker stand gar nicht im Prompt: Nur der erste Tag wird je
erreicht** (`NEUPLANUNGSHINWEIS`, `planungszeitraum.taegliche_neuplanung`). Bei
eingeschalteter Automatik entsteht morgen früh ein frischer Block ab dann — die
Tage ab dem zweiten sind vergeben, bevor der Block überhaupt gebaut ist. Die KI
wusste davon nichts und verteilte ihre Einheiten sinnvoll über sieben Tage; was
Punkt 9 vom ersten Tag wegdrängte (Kraft nicht unmittelbar vor einer
Schlüsseleinheit), landete auf Tag 3 und fand **nie** statt. Auf Tag 1 blieb die
kurze, überall zulässige Mobility — dreimal hintereinander.

Der Hinweis sagt deshalb ausdrücklich **nicht**, Tag 1 finde sicher statt: Ob
trainiert wird, entscheidet der Athlet. Sicher ist nur die Gegenrichtung, und
genau die ist die Aussage. Maßgeblich ist der **Schalter, nicht der Auslöser**
(`KiSettings.auto_plan_enabled`, gelesen in `_lade_kontext()`): Steht die
Automatik an, wird auch ein von Hand angestoßener Block morgen ersetzt. Der
Schlüssel steht nur, wenn er wahr ist — dieselbe Regel wie bei
`ersetzt_laufenden_block`, denn ein `false` wäre eine Aussage über einen Zustand,
der die KI nichts angeht. Die Einzelanpassung bekommt ihn nicht: Dort wird nichts
verdrängt.

Daran hing ein Fehler, den `test_der_geteilte_punkt_nennt_keine_punktnummer` jetzt
festhält: Die neue Formwahl in Punkt 9 verwies zunächst auf „Punkt 13" — und
Punkt 9 ist mit der Einzelanpassung geteilt, wo die Beschwerderegel **Punkt 8**
heißt. Die Nummer kommt aus der Vorlage, der Text steht ohne sie; das gilt für
`PRINZIP_ERGAENZUNG` und die `_STEUER_*`-Stücke gleichermaßen.

`ERSATZ_HINWEIS` behauptete bei alledem „Der Athlet plant ihn **bewusst** neu" —
bei der Automatik hat ein Zeitgeber entschieden. Der Satz trägt jetzt beide
Auslöser.

Der Kopf der Aufgabe sagt außerdem, dass `erzeugt_am` **Datum und Uhrzeit**
trägt und der erste Tag womöglich schon halb vorbei ist — samt der Folgerung,
dass Ruhe die richtige Antwort ist, wenn zu wenig übrig bleibt. Eine Einheit, die
nicht mehr stattfinden kann, verfälscht ab morgen die Umsetzungsquote.

Punkt 11 ordnet die **Selbstauskunft** ein: `rpe_quelle: "athlet"` und
`befinden_0_10` stammen vom Athleten und wiegen schwerer als jede Schätzung und
als die gemessene Last; alles andere ist geschätzt und wird gegen `hf_schnitt`,
`trimp` und `garmin_trainingslast` gelesen. Der wichtigere Teil des Punktes ist
die Sperre dahinter: Beide Felder **fehlen an den meisten Einheiten**, und das
ist keine Aussage über sie. Ohne den Satz deutet ein Sprachmodell die Leerstelle
— entweder als „hat sich nicht gemeldet, also war es hart" oder als stille
Bestätigung — und richtet den Block an einer einzelnen bewerteten Einheit aus.

Punkt 9 und Punkt 10 stehen **nicht** in der Vorlage, sondern als
`PRINZIP_ERGAENZUNG` und `PRINZIP_STEUERGROESSEN` daneben: Der Prompt für die
Einzelanpassung setzt dieselben Texte an anderer Stelle ein (siehe „Eine
einzelne Einheit wird angepasst"). Wer sie ändert, ändert beide Aufgaben — das
ist die Absicht. Die Nummer gehört in die Vorlage, nicht in den Text.

Punkt 10 verlangt außerdem die **Schrittliste** `steps` — den Bauplan der
Einheit für die Uhr, neben `structure` als Text für den Athleten. Wer den einen
ändert, prüft den anderen mit: Der Prompt verlangt, dass beide dieselbe Einheit
beschreiben. Die sechs Regeln dazu (ein Maß je Eintrag, `repeat` wie die Uhr
zählt, Pausen als eigene Einträge, `text` je Schritt, Teilsegmente
ausgeschrieben, `duration_min` als Summe) stehen im Absatz „Der Bauplan für die
Uhr“ und noch einmal ausführlicher in `SESSION_SCHEMA["steps"]` — beide Texte
gehören zusammen geändert. Nachrechnen kann die App davon nur die Summe, und
auch die nur, wenn jeder Schritt eine Dauer trägt (`plan_import._schrittzeit`);
alles Übrige bleibt eine Zusage der KI, die `validate_coverage()` bestenfalls
melden kann.

Änderungen am Antwortformat müssen an drei Stellen zusammenpassen:
`RESPONSE_SCHEMA`, die `AI*In`-Schemas in `schemas.py` und `build_plan()` in
`plan_import.py`. Die Felder einer Einheit stehen dafür einmal in
`SESSION_SCHEMA` und werden von `RESPONSE_SCHEMA` wie
`EINHEIT_RESPONSE_SCHEMA` benutzt; ein neues Feld muss zusätzlich in
`AISessionIn` und in `plan_import.uebernimm_einheit()` — sonst kommt es beim
Anpassen einer einzelnen Einheit nicht an.

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

**Geplant wird auf Zuruf — oder nach dem Abgleich, wenn man darum bittet**
(`ki/automatik.py`, `KiSettings.auto_plan_enabled`). Es gab hier einmal eine
Automatik mit einer **eigenen Viertelstundenschleife**, die den nächsten Block
anlegte, sobald der alte auslief; sie wurde entfernt, weil ein Plan, der über
Nacht von selbst entsteht, am Morgen auf der Uhr steht, ohne dass ihn jemand
bestellt hätte. Zurück ist die Funktion, nicht die Bauart — und beide
Unterschiede sind der Punkt.

**Kein zweiter Loop.** Ausgelöst wird am Ende eines erfolgreichen
*automatischen* Abgleichs, aus `garmin/runner._fuehre_aus` heraus. Das ist
nicht bloß sparsamer: Es garantiert die Reihenfolge, die `_datenstand` und
Punkt 2 des Prompts ohnehin voraussetzen — erst die Daten, dann der Block.
Zwei unabhängige Wecker könnten sie vertauschen, und die KI läse die Lücke als
Ruhetag und plante Aufbau auf einen Tag, an dem hart trainiert wurde. Gerufen
wird **nach** dem Schloss des Garmin-Runners, nicht darin: Der Planungslauf
stößt an seinem Ende selbst eine Übertragung an, die sonst gegen ein Schloss
liefe, das derselbe Faden noch hält. Der Import steht in der Funktion, weil
`ki/runner` über `garmin.automatik` zurückgreift.

**Und der Schalter steht je Nutzer, ab Werk aus.** Nicht in der Umgebung: Ein
Wert aus `config.py` ließe sich ohne Neustart nicht ändern, und was Kontingent
verbraucht, schaltet der Nutzer selbst ein (Einstellungen → KI-Planung). Fünf
Riegel, jeder mit eigenem Grund: der Abgleich muss `kind="auto"` **und** `done`
sein (ein Abgleich per Knopfdruck will Daten, nicht ungefragt Kontingent),
`auto_plan_enabled` muss stehen, `last_auto_plan_on` nicht heute sein, ein
Fragebogen vorliegen (sonst scheiterte der Lauf sicher und kostete trotzdem),
und der Zugang tragen. Geplant wird dann **ab heute** mit `PLAN_DAYS_DEFAULT` —
der laufende Block wird ersetzt, wie bei „Neu planen ab heute". Ein Fehlschlag
wird protokolliert und verschluckt: Der Aufrufer ist ein Abgleich, der gerade
erfolgreich war, und der darf daran nicht nachträglich scheitern.

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

## Bekannte Grenzen / mögliche nächste Schritte

- **Ohne Garmin gibt es keine Trainingshistorie.** Die App kann eine Einheit
  weder erfassen noch nachtragen; wer keine Uhr verbindet, bekommt Blöcke
  allein aus Fragebogen und Profil. Ebenso fehlt jede Möglichkeit, eine
  importierte Einheit zu korrigieren — was Garmin falsch liefert, wird in
  Connect berichtigt und beim nächsten Abgleich nachgezogen, oder der Eintrag
  wird im Verlauf gelöscht.
- Die **subjektiven Werte** (Muskelkater, Schlafqualität, Morgenpuls,
  Morgen-HRV, Bedingungen, Schlaf je Einheit) haben damit keine Quelle mehr und
  sind ersatzlos aus Modell, Schema, Export und Datenbank entfernt. Wer eines
  dieser Felder je zurückholen will, braucht wieder ein Formular — die Spalte ist
  weg, die Historie damit auch. Anstrengung und **Befinden** sind die Ausnahme:
  Sie sind zurück, aber über Garmin Connect statt über ein Formular, und deshalb
  nur an den Einheiten, die der Athlet dort bewertet.
- Die **Bewertung kostet eine Anfrage je Einheit** und reicht nur 42 Tage zurück
  (`sync.BEWERTUNGSFENSTER_TAGE`). Wer eine ältere Einheit nachträglich in
  Connect bewertet, bekommt das hier nie zu sehen — auch ein Rückblick holt das
  Detail für diese Tage nicht. Wer eine Bewertung dort *löscht*, behält sie hier:
  Der Abgleich fasst einen einmal gesetzten Wert nicht wieder an.
- Was ein Athlet **vor** dieser Umstellung von Hand eingetragen hat, bleibt
  liegen und zählt weiter mit. `/api/garmin/dubletten` zeigt, was dabei doppelt
  ist; entfernt wird es über den Verlauf, einzeln und von Hand.
- `training_status.weeklyTrainingLoad` ist an **allen** 370 Tagen leer, und das
  ist kein Lesefehler: Am echten Konto steht der Schlüssel im JSON und trägt
  `null` (ebenso `loadTunnelMin`/`loadTunnelMax`). Garmin füllt ihn schlicht
  nicht. Was die Wochenlast tatsächlich beschreibt, steht daneben in
  `acuteTrainingLoadDTO.dailyTrainingLoadAcute` — die App speichert es längst
  als `garmin_load_acute`. Die Spalte `weekly_training_load` bleibt als
  Altlast stehen; wer sie füllen will, holt sie von dort.
- **Die Beschwerde ist Freitext, und die Ursache dahinter rät die KI.** Punkt 13
  verlangt, aus „Läuferknie rechts" die wahrscheinliche Ursache abzuleiten und
  die Übungen dagegen zu planen — das ist eine Vermutung aus einem Satz, keine
  Untersuchung. Die App kann daran nichts prüfen: Sie weiß nicht, ob die
  gewählten Übungen zur Beschwerde passen, ob die Beschwerde noch besteht oder ob
  sie überhaupt behandelbar ist. Der Freitext ist außerdem der einzige Ort, an
  dem sie steht — er veraltet nur, wenn der Athlet ihn selbst ändert, und ein
  vergessener Eintrag lenkt das Ergänzungstraining monatelang weiter. Was
  hilft, ist der Nachweis im Begründungsfeld: Dort steht seit dieser Änderung,
  welche Beschwerde der Block angeht, und daran ist eine überholte Angabe zu
  erkennen.
- **Auch die *Form* der Behandlung ist eine Zusage, keine Prüfung.** Seit der
  Dehneinheit an drei Tagen hintereinander sagt der Prompt, dass die abgeleitete
  Ursache über mobilisieren oder belasten entscheidet und dieselbe Region an zwei
  Tagen sich unterscheiden muss. Nachrechnen kann die App weder das eine noch das
  andere: Sie weiß nicht, welche Übung welche Region trifft, und `kategorie` aus
  `absolvierte_uebungen` steht nur für Einheiten, die aus einem Workout mit
  Übungskennung liefen. Der einzige Nachweis ist wieder das Begründungsfeld —
  dort steht seither auch, *warum in dieser Form*.
- **Die Disziplin ist eine Zusage der KI, keine Prüfung.** Der Prompt sagt einem
  Laufblock, dass er nur Laufeinheiten enthält; nachrechnen kann die App das
  nicht, sie meldet beim Import nur, was danebensteht. Und die Disziplin hängt
  am Fragebogen: Ein Plan von vor dieser Änderung oder einer ohne Fragebogen
  (`request_id = NULL`) fällt auf die Triathlonfassung zurück und bekommt
  weiterhin alle drei Sportarten angeboten. Wer eine Einzeldisziplin will,
  füllt den Fragebogen neu aus — der nächste Block greift.
- **Ein Wechsel der Disziplin ändert den laufenden Block nicht.** Er zeigt auf
  den Fragebogen, aus dem er entstanden ist (dieselbe Lage wie bei der
  Ausrüstung). Wer aus einem Triathlonblock heraus auf „Laufen" umstellt, plant
  neu — die bestehenden Schwimm- und Radeinheiten bleiben stehen, samt ihrer
  Workouts auf der Uhr.
- **Die Einzelanpassung ändert nur den Inhalt, nie den Tag.** Verschieben geht
  über den Garmin-Kalender der App (dort zieht die Planeinheit mit um), und
  mehrere Einheiten auf einmal gibt es nicht — dafür ist „Neu planen ab heute"
  da. `Plan.raw_json` bleibt dabei bewusst die ursprüngliche KI-Antwort: Was
  gilt, steht in den Einheiten; die Anpassung dorthin zu schreiben machte aus
  dem Original ein Gemisch aus zwei Antworten.
- Ein **Sportartwechsel an einer bereits übertragenen Einheit** („mach lieber
  Schwimmen draus") schickt über `update_workout` ein neues `sportType` an eine
  bestehende Kennung — genau der Weg, der laut „Vorlage und Termin sind zwei
  Dinge" gegen ein echtes Konto ungeprüft ist. Bisher trat er nur beim
  Wiederverwenden eines freien Pool-Slots auf; mit der Einzelanpassung ist er
  ein Alltagsfall. Lehnt Garmin ihn ab, bleibt die Anpassung in der App stehen
  und der Hinweis nennt den Grund — der Termin trägt dann noch die alte
  Sportart.
- Eine angepasste Einheit **kostet ein eigenes Kontingent** aus dem Abo — ein
  Lauf mit Opus bei `max`, wie beim ganzen Block. Wer an einem Tag mehrere
  Einheiten einzeln anpasst, zahlt das mehrfach; die Aufgabe ist kleiner, der
  Prompt aber fast gleich groß, weil derselbe Kontext mitgeht.
- Wird aus einer Einheit **Ruhe** und Garmin nimmt den Termin nicht zurück,
  taucht sie im Trainingsplan nicht mehr auf (Ruhetage lässt
  `planbare_einheiten` aus). Der verwaiste Termin steht dann nur noch im
  Garmin-Kalender der App und ist dort von Hand zu entfernen; der Hinweis am
  Lauf sagt das.
- **Die Schrittliste ist gegen einen echten Lauf bestätigt** (Opus,
  `--effort max`, 288 s, 0,64 USD): Alle zehn Einheiten des Blocks kamen mit
  `steps`, ohne eine einzige Warnung, und `swim_location` traf beide Fälle —
  `pool` fürs Becken, `open_water` für die Freiwasserrunde. Die Koppeleinheit
  benannte ihre Disziplin je Abschnitt und wurde deshalb nicht geschätzt.
  `--json-schema` bleibt trotzdem in der Hinterhand: Fällt `steps` einmal aus,
  sagt es der Hinweis „Ohne Schrittliste geliefert" beim Übernehmen, und die
  Einheiten gehen über den Zerleger auf die Uhr wie zuvor.
- **Ein Lauf kann sofort und folgenlos scheitern.** Beim ersten Versuch kam
  nach zwei Sekunden `is_error` mit `stop_reason: "stop_sequence"` und null
  Eingabetoken zurück — der unmittelbar folgende Versuch mit demselben Prompt
  lief durch. Das ist keine Kontingent- und keine Anmeldefrage, sondern eine
  vorübergehende Störung der Gegenseite; sie landet über `_ordne_fehler_ein`
  als allgemeiner Fehler mit Originaltext. Eine Wiederholung baut die App
  bewusst nicht ein — was zweimal hintereinander losläuft, kostet auch zweimal
  Kontingent.
- **`steps` steht nicht in `PlanSessionOut`.** Der Athlet sieht in der App
  `structure`; ob die Schrittliste dasselbe sagt, zeigt sich erst auf der Uhr.
  Wer das prüfen will, braucht das Feld in der Ausgabe und eine Darstellung
  dafür — beides gibt es nicht.
- Keine Diagramme — Verlauf und Wochenübersicht sind Tabellen.
- Kein Alembic. Neue Spalten werden im Migrationshelfer in `database.py`
  eingetragen und beim Start ergänzt, entfallene über `_ENTFALLENE_SPALTEN`
  beim Start gelöscht; für Umbenennungen oder Typänderungen bleibt es beim
  Löschen der Datei. Die Tabelle `garmin_workout_links` legt
  `create_all()` beim Start an; die zwei Zählwerke an `garmin_sync_jobs`,
  `athlete_profiles.garmin_personal_bests`, `session_logs.garmin_feel`, die fünf
  Ausführungsspalten an `session_logs` (`hr_zone_seconds`, `garmin_abschnitte`,
  `garmin_uebungen`, `garmin_compliance`, `garmin_workout_id`) sowie
  `garmin_accounts.synced_through` und `garmin_accounts.auto_push_enabled`
  kommen über den Helfer — ebenso `garmin_accounts.sync_hour` und
  `ki_settings.token_encrypted`.
- **Die fünf Ausführungsspalten bleiben an bestehenden Einheiten leer.** Die
  Zonenzeiten stehen zwar in der Listenantwort, drei weitere im
  Aktivitätsdetail und die Übungen hinter einer eigenen Anfrage — nichts davon
  wird für zurückliegende Tage noch einmal geholt
  (`AKTUALISIERUNGSFENSTER_TAGE` = 5). Wer sie für die Historie will,
  stößt einen **Rückblick** an; für Einheiten außerhalb von
  `BEWERTUNGSFENSTER_TAGE` = 42 kommen Abschnitte, Einhaltung,
  Workout-Kennung und Übungen auch dann nicht nach, weil dort kein Detail
  geholt wird.
- **Die Übungsliste kostet eine eigene Anfrage je Kraft- und
  Mobility-Einheit** (`get_activity_exercise_sets`), anders als die drei
  Nachbarn aus dem Detail. Bei einem Rückblick über ein Jahr betrifft das nur
  die Einheiten der letzten 42 Tage, im Alltag also eine Handvoll — spürbar
  wird es erst, wer sehr viel Kraft trainiert.
- **Was die Uhr nicht erkennt, steht nicht da.** Garmin meldet `UNKNOWN`, und
  das fällt heraus statt als Übung zu erscheinen. Betroffen ist alles, was
  nicht aus einem Workout mit Übungskennung gestartet wurde — eine frei
  begonnene Krafteinheit erkennt die Uhr nur zum Teil, und genau die Übungen,
  die `garmin/uebungen.py` nicht zuordnen kann (Faszienrolle, „World's Greatest
  Stretch" …), kommen deshalb auch hier nicht zurück. Dieselbe Lücke, zweimal.
- **`saetze` und `wiederholungen` sind nicht, was der Athlet gemacht hat.**
  `saetze` zählt die *aufgezeichneten* Sätze — drei Sätze in einem
  Workout-Schritt bis zur Rundentaste stehen als einer —, und `wiederholungen`
  kommt aus der Bewegungserkennung am Handgelenk und zählt bei
  Körpergewichtsübungen zu niedrig (an einer echten Einheit: 3 Wiederholungen
  über 232 s). Der Prompt sagt das der KI; nachrechnen kann die App es nicht.
  Verlässlich sind Übungsauswahl und Dauer.
- Ein **Zusatzgewicht** wird nicht gelesen: `weight` stand an jedem geprüften
  Satz auf `null`, damit ist die Einheit (Gramm oder Kilogramm) nicht belegt.
- **Der Weg über `associatedWorkoutId` funktioniert nur, solange die Zuordnung
  lebt.** `GarminWorkoutLink` stirbt mit dem Plan; ein gelöschter Block nimmt
  auch den nachträglichen Weg zum Aufbau mit. Für die Einheiten vor dieser
  Änderung ist beides verloren — die betroffenen Pläne sind weg.
- **`geplant_fuer` sagt nur, dass der Tag abwich, nicht warum.** Ob der Athlet
  die Einheit vorgezogen oder eine andere ausgelassen hat, steht nirgends; die
  Umsetzungsquote zählt weiterhin streng über Tag und Sportart und sieht eine
  verschobene Einheit als versäumt.
- Was Garmin **später als fünf Tage** nachträgt (nachgeladene Aktivität aus
  einem zweiten Gerät, korrigierter Schlaf), holt kein Abgleich mehr von
  allein — dafür gibt es den Rückblick. Ebenso kann ein Lauf, der mitten im
  Zeitraum scheitert, nicht teilweise als geholt gelten: `synced_through` rückt
  nur im Erfolgsfall vor, der nächste Lauf wiederholt den ganzen Zeitraum.
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
- **Eine Freiwassereinheit geht ohne Bahnlänge nach Garmin, sonst unverändert.**
  Dass Garmin sie so annimmt, ist am echten Konto geprüft; dass sie sich auf
  der Uhr im *Freiwassermodus* starten lässt, ist es nicht — Garmin führt für
  Workouts keinen Freiwasser-Untertyp, das Workout bleibt formal ein
  Schwimm-Workout. Der Hinweis dazu steht in seiner Beschreibung, den Modus
  wählt der Athlet selbst.
- Der **Wattkorridor aus der Zone** ist eine Umrechnung über feste
  FTP-Anteile und damit die gröbste der drei Leistungsquellen: Er trifft das
  Ein- und Ausrollen, ersetzt aber keine Wattangabe der KI. Wer im Profil
  **keine FTP** stehen hat, bekommt auf dem Rad weiterhin Pulsziele — dann
  regelt der Smarttrainer in diesen Schritten nicht. Die FTP kommt aus Garmin
  (`sync.hole_leistungswerte`) oder von Hand aus der Profilseite.
- **Ob die Radeinheit drinnen oder draußen stattfindet, kann die App nicht
  nachprüfen** — sie glaubt `bike_location` bzw. dem Titel. Plant die KI eine
  Einheit als `indoor`, die der Athlet dann doch auf der Straße fährt, steht
  dort ein Wattziel ohne Messwert; umgekehrt fährt er auf der Rolle ohne
  Regelung. Korrigieren lässt sich das nur über die Einzelanpassung („mach das
  auf der Rolle"), nicht mit einem Schalter an der Einheit.
- Die **Ausrüstung stammt aus dem Fragebogen des Plans**, und jeder Fragebogen
  ist eine neue Zeile. Wer sich ein Powermeter kauft und den Fragebogen neu
  ausfüllt, ändert damit **nicht** den laufenden Block: Der zeigt weiter auf die
  alte Zeile und bleibt draußen pulsgesteuert. Erst der nächste Block greift.
- **Pläne von vor dieser Änderung tragen `request_id = NULL`** und gelten
  deshalb als „Ausrüstung unbekannt" — sie bekommen auf dem Rad weiterhin
  Wattziele. Wer das für einen laufenden Block korrigieren will, trägt die
  `request_id` von Hand nach; danach meldet der Abgleich die Radeinheiten als
  „geändert" und lädt sie neu hoch.
- **Die Satzpause kommt von der KI oder gar nicht.** Der Prompt verlangt sie
  jetzt als eigenen `rest`-Eintrag in der Serie; liefert die KI keine, bleibt
  die Serie die Übung allein, und der Athlet drückt zwischen den Durchgängen
  weiter selbst weiter. Geraten wird nach wie vor nichts — ein erfundener Wert
  stünde als Vorgabe auf der Uhr. Der **Zerlegerweg** hat gar keine: Aus
  „3x40 s je Seite“ lässt sich keine Pause ablesen, Blöcke von vor dieser
  Änderung und Antworten über die Zwischenablage bleiben deshalb ohne. Ebenso
  bleibt ein **Zusatzgewicht** ungelesen: `weightValue` steht fest auf „ohne“
  (-1), auch wenn „mit 8 kg Kurzhantel“ in der Zeile steht.
- **Der Prompt verlangt den Bauplan, erzwingen kann ihn niemand.** `steps` ist
  Pflicht laut Punkt 10, aber die Antwort geht durch keinen Schemazwang
  (`--json-schema` liegt weiter „in der Hinterhand“). Fehlt die Liste, greift
  der Zerleger und der Hinweis sagt es — die Einheit geht dann ohne
  Satzpausen und mit verdoppelten Durchgängen auf die Uhr, so wie vorher.
- **Der Umfang wird nur in drei Schreibweisen erkannt** (`_uebungsumfang`):
  „3x40 s“, „3x15“ und die einzelne Angabe mit Einheit. Wer „45 s halten,
  3 Durchgänge“ schreibt, bekommt einen Durchgang; „Wiederholen bis zur
  Erschöpfung“ bleibt die Rundentaste. Das ist Absicht — die Zahl der
  Durchgänge zu raten, hieße die Einheit zu verändern.
- Die **Zuordnung zum Übungskatalog** deckt ab, was in Kraft- und
  Mobilityplänen für Ausdauersportler üblich ist, nicht den ganzen Katalog.
  Gemessen ist sie an den erzeugten Blöcken: Von den 48 Übungen der acht
  Kraft- und Mobility-Einheiten in der Datenbank werden 42 zugeordnet. Die
  sechs übrigen führt Garmin nicht (dreimal Faszienrolle, „World's Greatest
  Stretch“, „Plank Shoulder Tap“, Zwerchfellatmung), und sie bleiben deshalb
  leer. Am ersten Block mit `exercise_en` waren es 18 von 22 — offen blieben
  zwei Faszienrollen und „Band Shoulder Pass-Through“; „Hip Flexor Stretch“
  und „Supine Spinal Twist“ sind dabei als Synonyme nachgetragen worden. Das
  eigene Feld erleichtert das Nachtragen erheblich: Der Name steht für sich
  statt in einer Zeile voller Beiwerk, eine Lücke ist damit sofort sichtbar. Was
  `uebungen.finde()` nicht erkennt, bleibt ohne Animation — **und ohne Titel**:
  Die Überschrift des Schritts kommt in Connect wie auf der Uhr allein aus
  `category`/`exerciseName`, ein Feld für einen eigenen Namen gibt es im
  Schritt-DTO nicht (an einem zurückgelesenen Workout nachgezählt). Ein
  namenloser Schritt steht dort als „--“ über seiner Beschreibung — die deshalb
  in diesem Fall den deutschen Namen behält (siehe „Oben deutsch, unten
  englisch“). Wer eine
  Lücke bemerkt, trägt sie in `SYNONYME` nach; `test_garmin_uebungen.py` prüft,
  dass jede Entsprechung im Katalog existiert.
- Ein paar Bewegungen führt der Katalog **nur mit Gerät**, obwohl der Plan sie
  ohne meint: Für „Single-Leg Romanian Deadlift“ gibt es keinen Eintrag ohne
  Hantel oder Schlingen, weshalb dort das zweibeinige „Romanian Deadlift“
  animiert wird — dieselbe Hüftbeuge, nur auf zwei Beinen. „Bulgarian Split
  Squat“ und „Nordic Hamstring Curl“ bleiben aus demselben Grund ganz ohne
  Animation.
- **Yogaposen laufen als `POSE`, nicht als Yoga.** Einen eigenen
  *Yoga*-Posenkatalog gibt es weiterhin nicht öffentlich
  (`web-data/exercises/Yoga.json` ist ein 404) — die 43 Posen aus
  `Mobility.json` (`POSE`) decken den Bedarf aber ab, und Mobility-Einheiten
  laufen wie bisher als Garmins „Mobility“ (11). **Ob `POSE` und `MOVE` am
  echten Konto angenommen werden, ist offen**: Bisher hat diese App nur
  `WARM_UP`-Kennungen übertragen, und eine abgelehnte Kategorie kostet das
  ganze Workout. Fällt es durch, genügt es, beide Kategorien in
  `katalog.eintraege()` auszulassen.
- Die Sportart `mobility` (11), die Übungskennungen und die Serienform sind am
  echten Konto bestätigt: Ein temporäres Workout aus Einheit 24 kam mit
  Wiederholungsgruppe, Timer (`time`), Wiederholungszählung (`reps`) und
  Übungskennung unverändert zurück. **Offen bleibt, ob die Animation auf dem
  Gerät erscheint** — das zeigt sich erst auf der Uhr.
- Eine **Koppeleinheit** ohne erkennbare Teilung im Aufbautext wird 2:1 auf Rad
  und Lauf geschätzt; die Beschreibung des Workouts weist das aus.
- Workouts landen über den Kalender auf der Uhr — beim nächsten Synchronisieren
  des Geräts. Ein Direktversand an ein bestimmtes Gerät
  (`push_workout_to_device`) ist nicht eingebaut; er kostete zusätzliche
  Anfragen für die Gerätesuche.
- **Die Slotkennung steht im Namen, nicht am Termin.** Im Garmin-Kalender liest
  sich eine Einheit deshalb als „TC01-Schwellentraining Rad" statt bloß als
  „Schwellentraining Rad" — vier Zeichen Beiwerk in einer Ansicht, die sie
  nicht braucht. Sie loszuwerden hieße, dem Kalendereintrag einen eigenen Namen
  zu geben, und den gibt Garmin nicht her (siehe „Der Termin kann keinen
  eigenen Namen tragen"). Der Trainingsplan der App zeigt unverändert nur den
  Trainingsnamen.
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
- Das **Leeren des Kalenders wirkt nur auf den angezeigten Monat**. Wer Termine
  über mehrere Monate liegen hat, blättert weiter und drückt erneut. Ohne
  Fortschrittsanzeige: Bei einer Handvoll Terminen dauert die Antwort ein paar
  Sekunden (eine Anfrage und eine Sekunde Pause je Termin).
- Der Bestandsabgleich prüft nur die Monate, in denen die App ihre Einheiten
  vermutet. Wer ein Workout in **Connect** auf einen anderen Monat schiebt, wird
  dort nicht gefunden; die Vorlage besteht aber noch, also wird die Zuordnung
  nicht gelöscht, sondern nur ihr Termin vergessen — die nächste Übertragung
  legt einen zweiten Termin auf dem Plantag an, ohne den verschobenen zu
  kennen. Innerhalb der App verschieben (Kalenderansicht) hat das Problem
  nicht: Dort zieht die Planeinheit mit um.
- Für den Netzbetrieb fehlen HTTPS, eine echte Authentifizierung vor der App,
  gesetzter `TRI_SECRET_KEY` und angepasste CORS-Herkünfte (`config.py`).
- Das **Claude-Token aus der Add-on-Option liegt weiterhin im Klartext** in
  `/data/options.json` und wandert damit in jedes Home-Assistant-Backup. Wer das
  nicht will, lässt die Option leer und trägt den Zugang stattdessen unter
  Einstellungen → KI-Planung ein — dort liegt er verschlüsselt (`crypto.py`).
  Gedeckt ist damit dieselbe Lage wie beim Garmin-Token: die Kopie der Datenbank
  ohne den Schlüssel. **Nicht** gedeckt ist Zugriff auf die Maschine selbst.
  Und ein Wechsel von `TRI_SECRET_KEY` macht ihn unlesbar; das meldet
  `token_status`, heilbar ist es nur durch erneutes Eintragen.
- **Das Kontingent teilt sich mit der eigenen Claude-Nutzung.** Ein Lauf mit
  Opus bei `max` verbraucht spürbar vom Fünf-Stunden-Fenster des Abos; ein Lauf
  am Tag ist unkritisch, wer daneben viel mit Claude arbeitet, kann trotzdem ins
  Limit laufen. Dann scheitert der Lauf mit deutscher Meldung, und der Block
  fehlt an dem Tag.
- **Der Zugang läuft irgendwann ab.** Die App kann das nur melden, nicht
  erneuern — die Meldung nennt deshalb ausdrücklich `claude setup-token`.
- **Ohne den Schalter bleibt ein ausgelaufener Block ausgelaufen.** Ab Werk ist
  die automatische Planung aus; bis jemand plant, steht auf der Uhr nichts Neues,
  und im Kalender bleibt der letzte übertragene Block liegen, bis ein Abgleich
  seine vergangenen Tage abräumt. Das Dashboard weist auf den Zustand hin
  (`blockStatus()`), mehr nicht.
- **Mit dem Schalter wird der laufende Block täglich überbügelt.** Das ist
  gewollt — der Export trägt `ersetzt_laufenden_block`, `raeume_abgeloeste_plaene`
  räumt hinterher auf. Wer ihn setzt und drei Tage nicht hinsieht, hat trotzdem
  drei Blöcke geplant bekommen, von denen zwei nie eine Einheit trugen. Und es
  kostet **jeden Tag** einen Opus-Lauf aus demselben Kontingent, das man daneben
  selbst benutzt. Der Prompt weiß davon (`NEUPLANUNGSHINWEIS`) und plant den
  ersten Tag entsprechend — aber nur, solange der Schalter steht: Wer ihn abends
  ausschaltet, hat morgen früh einen Block, dessen späte Tage plötzlich zählen,
  und der Hinweis von heute stand umsonst darin. Umgekehrt genauso.
- **Die automatische Planung hängt am Abgleich.** Ohne verbundenes Garmin-Konto
  gibt es keinen, und damit auch keinen Auslöser — dann bleibt es beim Knopf.
  Ebenso, wenn `TRI_GARMIN_AUTOSYNC=0` steht oder der Abgleich scheitert: Ein
  Block auf dem Datenstand von gestern wäre schlechter als keiner.
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
