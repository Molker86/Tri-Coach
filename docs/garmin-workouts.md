# Garmin: Workout-Bau, Zerleger und Übungskatalog

Teil der Kontextdokumentation von Tri-Coach. Überblick, Setup und Konventionen:
[CLAUDE.md](../CLAUDE.md).

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
