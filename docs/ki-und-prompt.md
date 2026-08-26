# Der Prompt und die KI im Server

Teil der Kontextdokumentation von Tri-Coach. Überblick, Setup und Konventionen:
[CLAUDE.md](../CLAUDE.md).

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

**Wie lang eine Ergänzungseinheit ist, sagt der Prompt nicht mehr.** Er verlangte
einmal „kurz“ — eine Zahl, die weder aus der Belastungslage noch aus der
Beschwerde stammt, sondern aus der Annahme, Kraft und Mobility seien Beiwerk.
Genau diese Annahme steht der Behandlung im Weg: Eine abgeschwächte Muskelgruppe
oberhalb des Gelenks braucht Arbeitszeit, und der Prompt räumte sie nicht ein.
Die Länge leitet die KI deshalb aus Belastungslage, Ziel und Beschwerdebild ab
und trägt sie in `duration_min` ein — dieselbe Linie wie bei den Punkten 3 und 4:
Die Rolle ist ein Trainingswissenschaftler, dem die Daten fehlen und nicht das
Maß. Der Hinweistext im Fragebogen sagt es ebenso wenig
(`SUPPLEMENTAL_OPTIONS` in `frontend/src/constants.ts`) — er stand vor demselben
Feld, das die KI jetzt füllt.

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
