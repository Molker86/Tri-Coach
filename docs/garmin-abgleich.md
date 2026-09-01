# Garmin: Abgleich, Mapping und Profilübernahme

Teil der Kontextdokumentation von Tri-Coach. Überblick, Setup und Konventionen:
[CLAUDE.md](../CLAUDE.md).

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
auch das Datenpaket — die Felder tragen, wo sie stehen, und ihr Fehlen wird
nicht gedeutet. Ein Wochenmittel gibt es bewusst nicht: Bewertet wird ein
Bruchteil der Einheiten (am Testkonto zwei von zwanzig), und ein Schnitt daraus
sähe aus wie eine Aussage über die Woche.

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

**Ein abgelehnter Garmin-Login ist 400, nicht 401** (`routers/garmin.py`). Das
war der Fehler, an dem ein zweiter Benutzer sein Konto nicht verbinden konnte —
und er war von außen unsichtbar. `POST /connect` antwortete auf jeden
`GarminFehler` mit 401, und der Browser-Client wertet 401 als „die eigene
Sitzung ist abgelaufen": Er verwarf den App-Token, meldete den Nutzer ab und
ersetzte Garmins Begründung durch „Sitzung abgelaufen". Der Anmeldedialog
verschwand mitsamt der Meldung, die zu lesen gewesen wäre; zurück blieben zwei
leere Felder und der Eindruck, es sei nichts passiert. Ein falsches
Garmin-Passwort sagt nichts über die Anmeldung *bei dieser App* aus — 401 ist
allein `deps.get_current_user` vorbehalten, erkennbar am Kopf
`WWW-Authenticate`, an dem der Client seither unterscheidet (siehe
`docs/frontend.md`).

**Die eigene Anmeldebremse muss sich als solche zu erkennen geben**
(`client.py`, `pruefe_anmeldeversuche`). Drei Versuche je Stunde und Adresse
bleiben — sie sind die Absicherung gegen Garmins 48-Stunden-Sperre. Die Meldung
sagt jetzt aber, dass *Tri-Coach* bremst und wie viele Minuten noch bleiben:
Vorher las sie sich wie eine Sperre von außen, also wie etwas, das man
aussitzen muss, statt wie ein Riegel, der sich von selbst löst. Und ein Versuch,
der bis zur **MFA-Abfrage** kommt, zählt nicht mehr: Das Passwort war richtig,
sonst gäbe es keinen Code. Drei angefangene Bestätigungen verbrauchten sonst das
Stundenkontingent, ohne dass je etwas falsch war.

**Fehlt der Anzeigename, hilft „verbinde erneut" nicht** (`_pruefe_sitzung`).
Die Sitzungsprüfung besteht darauf, dass Garmin ein Profil zurückgibt — ohne
`display_name` antworten die Endpunkte still mit leeren Ergebnissen. Beim
*Verbinden* ist die alte Meldung aber ein Kreisverkehr: Ein frisch angelegtes
Garmin-Konto hat oft noch keinen Anzeigenamen, und jeder weitere Versuch führt
an dieselbe Stelle. Deshalb `erstanmeldung=True` und ein eigener Text, der sagt,
was zu tun ist — nämlich etwas bei Garmin, nicht hier.

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

**Was das für den Jahresverlauf im Export heißt.** Seit die Trainingshistorie in
drei Auflösungen ins Paket geht (siehe „Drei Auflösungsebenen" in
[ki-und-prompt.md](ki-und-prompt.md)), speist sich die gröbste Ebene —
`athlet.verlauf`, ein Stützpunkt je Monat über zwölf Monate — aus
`wellness_days`. Sie kann deshalb nur führen, was die **Bereichs**abfragen
liefern: Gewicht, Ruhepuls, HRV, Schlaf und VO2max. Trainingsreife,
Trainingsstatus, Stress, Schlafscore und Garmins ACWR stammen aus der
Tagesschleife und existieren daher nur für die letzten 42 Tage — an einem
gewachsenen Konto beginnen sie schlicht an dem Tag, an dem die App zum ersten
Mal abgeglichen hat. Sie stehen bewusst **nicht** im Monatsverlauf: Eine Spalte,
die für zehn von zwölf Monaten leer ist, stiftet mehr Verwirrung als Nutzen. Für
die Gegenwart steht dieselbe Größe unverändert im `fitnessdaten`-Block.

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
`.sync_minute`, `automatik._abgleichzeit`). Die Stunde war einmal die Konstante
`GARMIN_SYNC_HOUR` und damit im laufenden Prozess unveränderlich — eine
Umgebungsvariable lässt sich in der Oberfläche nicht umstellen. Jetzt steht sie
je Konto in der Datenbank und ist in den Einstellungen wählbar; die Konstante
ist nur noch die Vorgabe für ein neu verbundenes Konto (**9 Uhr**). Der Riegel
wanderte dafür aus dem Kopf von `starte_faellige_syncs` in die Schleife über die
Konten: Jeder Aufwacher öffnet seither eine Sitzung, statt vorher billig
zurückzukehren — bei SQLite auf demselben Rechner folgenlos, und anders geht
„je Nutzer eine Stunde" nicht. Geprüft wird ausdrücklich gegen `None` und
**nicht** mit `or`: Mitternacht ist eine gültige Einstellung, und `0 or 10`
ergäbe zehn.

**Stunde und Minute — die Entscheidung hat sich gedreht.** Hier stand einmal
„volle Stunden, keine Minuten: Die Schleife wacht viertelstündlich auf, eine
Minutenangabe wäre eine Genauigkeit, die es gar nicht gibt." Das stimmte,
solange der Abgleich die einzige Automatik war. Seit die KI-Planung an einer
**eigenen** Uhrzeit hängt und nicht mehr am Ende des Abgleichs, muss ein
eingestellter Zeitpunkt wirklich treffen: Wer 09:05 einstellt und um 09:20 die
erste Anfrage sieht, hat keine Einstellung, sondern einen Vorschlag. Das
Weckintervall ist deshalb von 900 auf **60 Sekunden** gesunken. Der Preis ist
eine kurze Sitzung je Minute statt je Viertelstunde — bei SQLite auf demselben
Rechner unmessbar.

**Die Tagessperre rechnet in Ortszeit.** `last_sync_at` steht in UTC, verglichen
wird gegen das lokale `date.today()`. Ungerechnet fiel ein Lauf kurz nach
Mitternacht Ortszeit als „gestern" in die Datenbank, und die Sperre griff nicht
— bei einer Abgleichstunde am Vormittag folgenlos, bei einer nachts nicht.
`_als_datum()` geht deshalb über `zeit.als_utc()` und `astimezone()`.

**Die Automatik wählt `status != "token_expired"`, nicht `== "connected"`.**
Das ist der stillste Defekt, den die Mehrbenutzer-Durchsicht zutage gefördert
hat. `_notiere_fehler` setzt den Status bei **jedem** Netzfehler auf `"error"`,
zurückgenommen wird er nur von einem erfolgreichen Lauf oder beim Neuverbinden.
Wählte die Schleife nur `"connected"`, nahm ein einziger vorübergehender Fehler
das Konto **dauerhaft** aus dem täglichen Abgleich — bis jemand von Hand „Jetzt
abgleichen" drückte, und ohne dass irgendwo stand, warum. Bei einem Nutzer fällt
das auf; bei zweien trifft es still nur einen. Ausgeschlossen wird deshalb nur,
was wirklich eine Hand verlangt: ein abgelaufenes Token. Eine Anfragesperre
deckt `rate_limited_until` weiterhin gesondert ab, und der Tagesriegel über
`last_sync_at` verhindert, dass ein dauerhaft kaputtes Konto minütlich
weiterprobiert.

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

**Das Schloss bleibt global, die Auskunft darüber nicht** (`runner.besitzer()`,
`routers/garmin._pruefe_startbar`). Der Riegel ist richtig — zwei gleichzeitige
Läufe erzeugen genau die Anfragedichte, gegen die sich Garmins Grenze richtet,
auch bei zwei Konten im selben Haushalt. Falsch war, was der zweite Nutzer davon
zu sehen bekam: „Es läuft bereits ein Abgleich", während seine eigene
Fortschrittsanzeige daneben nichts zeigte — die ist nach `user_id` gefiltert und
sagte zu Recht, dass nichts läuft. Wer das liest, sucht den Fehler in der App.
Der Runner führt deshalb neben dem aktiven Job dessen Besitzer mit, und die
Meldung unterscheidet den eigenen Lauf vom fremden. Aus demselben Grund wartet
`exklusiver_direktaufruf()` fünf Sekunden auf das Schloss, statt sofort
abzuweisen: Der häufigste Fall ist, dass zwei Nutzer im selben Moment drücken.

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
`letzte_volle_woche` benennt die letzte abgeschlossene Woche als Vergleichsgröße
— der letzte Eintrag der Übersicht taugt dafür nie. (Der Prompt hing daran
einmal eine Steigerungsgrenze von 10 % auf; die ist gefallen, das Feld bleibt
als Datum.)

**Fällig ist, was vor heute lag** (`sportscience.compliance`). Der heutige Tag
ist nicht vorbei; die Einheit von heute Abend als versäumt zu zählen, drückt die
Quote genau dann, wenn der Block frisch ist. An echten Daten wurden aus zwei von
zwei umgesetzten Einheiten 33 %, weil die beiden noch bevorstehenden von heute
mitzählten — und der Prompt machte aus einer niedrigen Quote einmal den Auftrag,
kleiner zu planen.

**Garmins `recoveryTime` sind Minuten** (`WellnessDay.recovery_time_min`). Die
Spalte hieß einmal `recovery_time_h` und übernahm den Wert ungerechnet. Ein
Eintrag von 911 stand damit als „911 Stunden Erholung" im Export und in den
Auffälligkeiten, und der Prompt machte daraus „in diesem Zeitfenster nichts über
Z2" — 38 Tage lang. Die Schwelle `ERHOLUNGSZEIT_HOCH_H = 24` feuerte
entsprechend bei 24 *Minuten*, also fast immer. Der Name sagt jetzt die Einheit,
umgerechnet wird erst zur Anzeige (`sportscience.erholung_stunden`) — sonst liefe
die Umrechnung bei jedem Start erneut über dieselben Werte. Die Umbenennung
läuft über `database._UMZUZIEHENDE_SPALTEN`: ergänzen, kopieren, alte Spalte
löschen, alles idempotent.

**Die Erholungszeit kommt aus dem jüngsten Reife-Eintrag, die Reife selbst vom
Aufwachen** (`sync._juengste_bereitschaft`). `get_training_readiness()` liefert
mehrere Momentaufnahmen je Tag, und die Regel „der Wert nach dem Aufwachen ist
der gültige" stimmt für den Score — spätere Messungen sind vom Tagesgeschehen
gefärbt. Für `recoveryTime` und `acuteLoad` stimmt sie nicht: Das sind laufende
Größen, die das Training des Tages erst hochsetzt. Am echten Konto stand im
Aufwacheintrag `recoveryTime: 1`, im Eintrag nach der Einheit `1890` — die App
schrieb die 1 und meldete „0,0 Stunden Erholung" in den Export, während die Uhr
29 Stunden zeigte. Beide Werte kommen deshalb aus dem jüngsten Eintrag des
Tages, Score, Level, Feedback und die Reifefaktoren weiter vom Aufwachen.
Gewählt wird über den Zeitstempel, nicht über die Listenposition: Garmin
liefert zwar neuestes zuerst, sagt das aber nirgends zu. Für vergangene Tage
heißt der Wert damit „was am Ende des Tages noch ausstand" statt „am Morgen" —
dieselbe Lesart wie beim heutigen Tag, und die einzige, die die Wirkung des
Tagestrainings enthält.

**Watt- und Tempokorridore kommen mit, nicht nur ihre Schwellenwerte**
(`sportscience.power_zones` / `pace_zones`). Punkt 4 verlangt zu jeder Einheit
ein `target_power` bzw. `target_pace`, lieferte der KI aber nur die nackte FTP —
sie musste die Anteile raten, während `garmin/workouts.py` sie längst festlegt.
Beide lesen jetzt dieselbe Tabelle `FTP_ZONEN_ANTEIL`: Aus denselben Korridoren,
die im Prompt stehen, baut die App anschließend das Workout für die Uhr. Zwei
Tabellen liefen auseinander, und dann stünde im Plan ein anderer Bereich als auf
dem Gerät. **Ohne hinterlegten Schwellenwert fehlt der Block ganz** — geschätzt
wird nichts, denn eine erfundene Schwellenpace stünde als Vorgabe im Plan. Der
Prompt sagt für diesen Fall ausdrücklich, dass die Vorgabe aus Pace und
`hf_schnitt` vergleichbarer Einheiten der Historie abzuleiten ist.

**Was geplant war, steht nicht mehr im Export — die Entscheidung ist
zurückgenommen.** `ai_export._geplant_war` lieferte den Aufbau der zugehörigen
Planeinheit an jede absolvierte mit, damit die KI einen Reiz fortschreiben kann:
Aus 5x1000 m soll 6x1000 m werden. Der Gedanke war richtig, der Preis zu hoch —
das Modell nahm den alten Block als Vorlage, statt aus dem Verlauf neu zu
entscheiden, und eine deutlich unter der Vorgabe liegende Dauer las es als
Auftrag, kleiner zu planen. Maßstab ist jetzt allein, was stattgefunden hat;
siehe „Frühere Blöcke dieser App stehen nicht mehr im Paket" in
[ki-und-prompt.md](ki-und-prompt.md).

**Die Verknüpfung selbst bleibt** (`garmin/matching.py`, `SessionLog.plan_session`).
Sie trägt weiterhin die Umsetzungsquote im Dashboard, das Aufräumen in Garmin und
die Markierung „erledigt" im Trainingsplan — nur der Export liest sie nicht mehr.

**Wie eine Einheit ausgeführt wurde, nicht nur dass sie stattfand**
(`mapping.zonensekunden` / `abschnitte_aus_detail`, `_history_block`). Der Export
beschrieb eine absolvierte Einheit mit Dauer, Strecke und Schnittpuls — und das
sagt über eine Intervalleinheit fast nichts. Die Schlüsseleinheit vom 19.08.2026
stand als „37 min, HF-Schnitt 148" da; geplant waren 60 min mit 3x8 min Schwelle.
Ob die drei Intervalle standen, war nicht abzulesen. Drei
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
Export als „35 min, RPE 5" — welche Übungen darin vorkamen, war allein aus der
*Vorgabe* zu erraten.
`get_activity_exercise_sets()` sagt es: die Übungen mit Garmins Katalognamen
(`HIP_RAISE`/`SINGLE_LEG_HIP_RAISE`), je Satz mit Dauer und Wiederholungen.

**Das war einmal ausdrücklich abgelehnt**, und beide Gründe von damals sind
gefallen. „Steht bei unseren eigenen Workouts ohnehin in der Vorgabe" gilt
nicht — und seit die Vorgabe den Export gar nicht mehr erreicht, erst recht
nicht: Was die Uhr gezählt hat, ist die einzige Auskunft über die Ausführung. Und „bei Mobility durchweg `UNKNOWN`" ist überholt: Seit die App ihre
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
über 232 Sekunden. Verlässlich sind Übungsauswahl und Dauer. Der Wert für die
Planung liegt genau dort,
wo die Beschwerde hängt: Punkt 3 verlangt, Übungsauswahl und Körperregion zu
wechseln, und `kategorie` (`PLANK`, `HIP_RAISE`, `CALF_RAISE`) benennt die
Bewegungsgruppe, an der das zu entscheiden ist.

**`weight` bleibt ungelesen.** Es stand an jedem geprüften Satz auf `null` —
alle Übungen laufen mit Körpergewicht —, und damit ist die Einheit (Gramm oder
Kilogramm) nicht belegt. Dieselbe Regel wie bei den Kalenderdauern: Eine um
Faktor 1000 falsche Zahl ist schlechter als eine fehlende.

**Zugeordnet wird über die Workout-Kennung, nicht über den Tag**
(`garmin/matching.py`). Die Regel hieß einmal „gleicher Tag, gleiche Sportart,
noch nicht erfasst" und war als das Strenge gedacht — sie war das Gegenteil: Am
25.08.2026 stand eine Radeinheit im Plan, gefahren wurde eine freie Runde ohne
die Vorgabe, und die App zeigte die Einheit als absolviert. Tag und Sportart
stimmen bei jeder Feierabendrunde; was sie nicht sagen, ist, ob die Vorgabe
überhaupt abgearbeitet wurde. Das sagt `metadataDTO.associatedWorkoutId` aus dem
Aktivitätsdetail (am echten Konto an allen drei Einheiten belegt, die aus einem
Tri-Coach-Workout kamen, `None` an jeder frei gestarteten). Maßgeblich ist
deshalb allein sie — und **der Tag fällt damit ganz weg**: Ein Workout liegt auf
der Uhr und wird gestartet, wenn es passt. Am 17.08.2026 stand die
„Grundlagenfahrt Z2" im Plan und wurde einen Tag später gefahren; das ist keine
Nichtumsetzung — die Umsetzungsquote im Dashboard wertet sie
deshalb als erfüllt.

Drei Dinge halten das davon ab, Falsches zu behaupten. Die Vorlage muss **schon
auf der Uhr gelegen haben, als trainiert wurde** — die fünfzehn Pool-Slots
werden wiederverwendet, und dieselbe Kennung trägt nach ein paar Wochen einen
anderen Inhalt; liegen mehrere davor, gewinnt die jüngste. Eine bereits erfasste
Planeinheit bleibt erfasst (`uq_log_plan_session`). Und wo die Kennung trotzdem
danebengreift — die Vorlage lief nur zum Aufzeichnen, und daraus wurde etwas
anderes —, löst der Athlet die Zuordnung im Einheiten-Dialog selbst
(`DELETE /api/plans/sessions/{id}/verknuepfung`). Sein Wort steht danach über
der Kennung: `SessionLog.zuordnung_manuell` hält den nächsten Abgleich davon ab,
sie wieder anzuknüpfen, denn an der Aktivität bleibt sie stehen. Das Training
selbst bleibt vollständig in Wochenlast, sRPE, ACWR und Export — gelöst wird
nicht die Einheit, sondern die Behauptung über sie.

**„Belegt" heißt nicht „das gehört dorthin".** Weil die fünfzehn Slots reihum
gehen, tragen mehrere Einheiten dieselbe Kennung. Die Suche nahm deshalb erst
die jüngste passende und gab auf, sobald an *dieser* schon ein Training hing —
die freie Einheit daneben blieb für immer unverknüpft. Sie geht die Reihe jetzt
weiter abwärts, bis eine freie kommt. Abgeschwächt ist dadurch nichts: Zwei
Trainings an derselben Einheit ließe `uq_log_plan_session` ohnehin nicht zu, und
die Reihenfolge „jüngste zuerst" bleibt die Regel.

**Und der Zeitstempel rückt nur mit einer gesendeten Fassung nach.**
`_merke_uebertragung` setzte ihn bei jedem Lauf auf jetzt, auch im Zweig
`"unveraendert"` — obwohl sein eigener Docstring beschrieb, seit wann *dieser*
Inhalt auf der Uhr liegt. Da `planbare_einheiten` ohne `ab` bei `plan.beginn`
anfängt, also vergangene Tage einschließt, schob eine Übertragung am Tag **nach**
dem Training den Zeitstempel über den Trainingstag hinaus. `garmin_pushed_at <=
Trainingstag` war damit dauerhaft verletzt, und eine tatsächlich absolvierte
Einheit stand für immer als nicht umgesetzt da. Ein Lauf ohne zu Sendendes lässt
ihn deshalb stehen; die Kennung wird trotzdem weiter gesichert, denn sie muss
den Termin überleben.

**Die Gegenprobe gibt es in beide Richtungen.** Wo gar keine Kennung ankommt —
auf der Uhr wurde ein älterer Kalendereintrag gestartet, oder Garmin rückte das
Aktivitätsdetail nicht heraus —, schreibt der Athlet der Einheit ein Training
von Hand zu (`GET /api/plans/sessions/{id}/zuordenbar` für die Auswahl,
`POST …/verknuepfung` für die Entscheidung). Angeboten wird, was in drei Tagen um
den Plantag herum an keiner Einheit hängt, **ohne** Filter auf die Sportart: Die
Kennung fragt auch nicht danach, und die Uhr zeichnet eine Einheit gern einmal
unter der falschen auf — ein Filter versteckte genau den Fall, für den die
Auswahl gebaut ist. Erfunden wird dabei nichts, es wird ein bereits importiertes
Training benannt; Garmin bleibt die einzige Quelle. `zuordnung_manuell` heißt
danach dasselbe wie beim Lösen, nur in die andere Richtung: Der Athlet hat
entschieden, der Abgleich fasst es nicht wieder an.

**Die Kennung braucht einen Träger, der den Termin überlebt.**
`GarminWorkoutLink` beschreibt, was *jetzt* in Garmin steht, und stirbt, sobald
sein Tag vorbei ist (`uebertragung.raeume_vergangene_auf`) — genau bevor das
Training des Tages hier ankommt. Schlimmer: Eine Übertragung räumt ebenfalls
auf, und wer morgens neu plant, löst eine aus. Beides zusammen ist derselbe
Datenverlust wie am 16.08.2026, nur an anderer Stelle. Deshalb steht der Bezug
ein zweites Mal an der **Planeinheit** selbst (`PlanSession.garmin_workout_id`
und `garmin_pushed_at`, geschrieben in `uebertragung._merke_uebertragung`): Dort
lebt er, solange die Einheit lebt, und stirbt mit ihr. Der Preis ist eine
scheinbar doppelte Angabe — die Alternative wäre, den Link künstlich am Leben zu
halten, und der belegt einen von fünfzehn Pool-Plätzen.

**Der Prompt sagt, bis wann die Daten reichen** (`_datenstand`). Das war wichtig,
solange der Block unmittelbar nach dem Abgleich gebaut wurde — und es ist
wichtiger geworden, seit beide an **eigenen Uhrzeiten** hängen: Wer die Planung
vor den Abgleich legt, plant auf dem Stand von gestern, und die KI hat keine
Möglichkeit, das von selbst zu merken. Sie läse die Lücke als Ruhetag und plante
Aufbau auf einen Tag, an dem hart trainiert wurde.
`trainingshistorie.datenstand` nennt deshalb `garmin_daten_bis` und
`letzter_abgleich`, und der Prompt sagt ausdrücklich, dass alles danach **nicht
geholt** und nicht als Pause zu deuten ist. Ohne
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
die, die Punkt 1 vorziehen soll. Und `tage_seit_letzter_intensiver_einheit: null`
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
namentlich ansprechen. Der Block hat drei Ebenen, weil die KI drei Fragen hat:
`aktuell`, `mittelwerte` (7 gegen 28 Tage) und `tage`. Der Verweis darauf steht
im Aufgabenteil des Prompts und existiert in **zwei** Fassungen: Ohne
verbundenes Konto entfällt der Block, und der Prompt sagt stattdessen
ausdrücklich, dass auch die Trainingshistorie leer ist und der Block allein aus
Fragebogen und Profil entsteht — Regeln zu Daten, die es nicht gibt, laden zum
Erfinden ein.

**`tage` reicht 14 Tage zurück** (`ai_export.WELLNESS_TAGE`), nicht über den
vollen Rückblick. Für einen Block über wenige Tage entscheidet die jüngste
Entwicklung; die Vierwochensicht steht als `mittelwerte.28_tage` daneben. Über
vier Wochen waren die Tageswerte ein Fünftel des gesamten Prompts.

**Die vierte Ebene `auffaelligkeiten` gibt es nur noch für die Ernährung**
(`mit_auffaelligkeiten`). Das sind vorverdichtete deutsche Sätze aus
`sportscience.wellness_auffaelligkeiten` — Schlüsse aus **selbstgesetzten**
Schwellen, und genau die sind aus dem Trainingsprompt verschwunden. Sie dort als
fertige Sätze weiterzureichen wäre derselbe Eingriff durch die Hintertür. Was
stattdessen dasteht, sind die Rohwerte und **Garmins eigene, am Athleten
gemessene Grenzen**: `hrv_normalbereich_ms` (aus `baseline.balancedLow` /
`balancedUpper`) und `training_status.lastfenster` (aus dem
`acuteTrainingLoadDTO`). Der Prompt benennt beide namentlich — ohne die Nennung
übersah die KI sie im Paket. Der Ernährungsprompt behält die Verdichtung: Er
bekommt eine stark gekürzte Historie und keine Einzeleinheiten.

Das Lastfenster wird über `erster_wert()` mit mehreren Namensvarianten gelesen
(`minTrainingLoadAcute`, `minLoadAcute`, `loadTunnelMin` …). Die API ist
undokumentiert, und die Felder heißen je nach Gerätegeneration anders; liefert
keine davon etwas, bleiben die Spalten leer und der Schlüssel fällt aus dem
Export — wie bei jedem anderen unbelegten Garmin-Wert.

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

**Der Schwellenpuls kommt aus einer eigenen Anfrage, nicht aus den Tageswerten**
(`sync.hole_leistungswerte`, `mapping.schwellenpuls`). Er fällt bei Garmin nicht
je Tag an: Es gibt nur den zuletzt erkannten Stand, hinter einem eigenen
Endpunkt (`get_lactate_threshold`). Er landet deshalb **nicht** in
`WellnessDay`, sondern wird am Ende des Laufs eingesammelt und über
`SyncErgebnis.leistungswerte` an die Profil-Nachführung durchgereicht — in
*einem* Zug mit Gewicht und Ruhepuls, weil zwei Übernahmen je Abgleich zwei fast
gleiche `ProfileHistory`-Einträge hinterließen. Am Ende, weil es die billigsten
Anfragen des Laufs sind; und nur, wenn `profile_sync_enabled` gesetzt ist, sonst
hätten die Werte keinen Empfänger. Der Wert wird gegen die Spanne aus
`schemas.ProfileIn` geprüft: Diese Zahlen gehen am Pydantic-Schema vorbei direkt
ins Modell, und weil `ProfileOut` dieselben Grenzen validiert, würde ein
Ausreißer aus der undokumentierten Schnittstelle die Profilseite mit einem
Fehler statt mit Daten beantworten.

**FTP, Schwellenpace Laufen und CSS sind dagegen Handarbeit** — und zwar
ausdrücklich, obwohl Garmin zwei davon liefern würde. Die App holte sie einmal
(`get_cycling_ftp`, dazu das Schwellentempo aus derselben Laktatschwellen-
Antwort) und schrieb sie ins Profil. Das ist zurückgenommen: Diese drei Zahlen
sind die Steuergrößen, aus denen `power_zones()` und `pace_zones()` jeden
Korridor bauen, der anschließend im Plan steht und auf die Uhr geht — und
Garmins FTP ist eine *Erkennung* aus gefahrenen Einheiten, keine gemessene
Schwelle. Wer nach einem Testprotokoll 260 W einträgt, fand am nächsten Morgen
238 W vor, ohne dass irgendwo etwas fehlgeschlagen wäre. Dieselbe Überlegung wie
beim Maximalpuls, nur eine Sportart weiter. `get_cycling_ftp` wird deshalb gar
nicht mehr aufgerufen; `get_lactate_threshold` bleibt, weil der Schwellenpuls
daran hängt. Die CSS führt Garmin ohnehin nirgends.
`test_ftp_und_schwellenpace_bleiben_handarbeit` hält beides fest — auch, dass
der FTP-Endpunkt nicht einmal angefragt wird; der Fake antwortet weiterhin
darauf, damit der Wächter Zähne hat. Der Preis: Was ein früherer Abgleich
einmal geschrieben hat, steht weiter im Profil, bis der Athlet es selbst ändert.

**Garmins Schwellentempo wird seither doch gelesen — aber in ein eigenes Feld**
(`mapping.schwellenpace_gemessen`, `AthleteProfile.garmin_threshold_pace_run`).
Der Absatz darüber gilt unverändert: `pace_zones()` rechnet weiterhin
ausschließlich mit `threshold_pace_run`, also mit der Handeingabe, und die wird
nie überschrieben. Was sich geändert hat, ist nur, dass der mitgelieferte Wert
nicht mehr weggeworfen wird. Zwei Gründe: Er kostet **keine** Anfrage — er steht
in derselben Antwort wie der Schwellenpuls —, und eine veraltete Handeingabe war
im KI-Paket bis dahin durch nichts zu erkennen. Jetzt stehen beide Zahlen
nebeneinander in `athlet` (`schwellenpace_laufen_min_pro_km` gegen
`schwellenpace_gemessen_garmin`), und der Prompt sagt ausdrücklich, welche die
Zonen trägt. Ein `ProfileHistory`-Eintrag entsteht daraus **nicht**: Dort stehen
die Werte, die tatsächlich steuern, und ein Schattenwert verfälschte den Trend.

**Die FTP kommt aus keiner dieser Antworten.** Naheliegend wäre, das Gegenstück
für das Rad genauso mitzunehmen — geht aber nicht: Der `power`-Block von
`get_lactate_threshold()` trägt Garmins **Lauf**leistung (`powerToWeight`, fest
mit `sport="Running"` angefragt, siehe die Bibliothek), nicht die Rad-FTP. Die
stünde hinter `get_cycling_ftp` und damit hinter einer zusätzlichen Anfrage —
und hinter genau der Entscheidung, die der Absatz darüber begründet. Es gibt
deshalb bewusst keine Spalte `garmin_ftp_watts`: Eine Laufleistung unter einem
Rad-Etikett wäre schlechter als kein Wert.

**Sechs Messgrößen kommen in Antworten mit, die ohnehin geholt werden.** Der
Kommentar an `mapping.py` sagt seit jeher, dass eine Aktivität rund 111 Felder
trägt und die App etwa zwanzig davon liest. Fünf weitere stehen in der
**Listen**antwort, aus der die Einheit ohnehin entsteht — `movingDuration` als
`netto_dauer_min`, `avgGradeAdjustedSpeed` als `gap_pace` (nur Laufen),
`averageSwolf` und `avgStrokes` als `swolf`/`zuege` (nur Schwimmen) und
`maxTemperature` als `temperatur_c`. Die sechste, die normalisierte Leistung,
steht im **Detail**, das für 42 Tage ohnehin geholt wird
(`BEWERTUNGSFENSTER_TAGE`), und wird in `detail_zu_feldern()` gelesen. Keine
kostet eine zusätzliche Anfrage.

Zwei Vorsichtsmaßnahmen: Garmin schreibt die normalisierte Leistung in **zwei**
Schreibweisen — die Bibliothek führt den Alias `normPower`, an echten Antworten
stand auch `normalizedPower` —, deshalb liest `erster_wert()` beide. Und jeder
Wert läuft gegen eine Plausibilitätsspanne, wie beim Schwellenpuls: Die
Schnittstelle ist undokumentiert, und ein Ausreißer stünde sonst ungefiltert im
Prompt. Die normalisierte Leistung wird außerdem **nur beim Rad** übernommen,
aus demselben Grund wie `avg_power`: Laufleistung wäre in derselben Spalte eine
andere Größe. `detail_zu_feldern()` bekommt die Sportart dafür als zweites
Argument; ohne sie liest es die Leistung gar nicht.

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
