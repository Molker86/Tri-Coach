# Garmin: Übertragung, Workout-Pool und Kalender

Teil der Kontextdokumentation von Tri-Coach. Überblick, Setup und Konventionen:
[CLAUDE.md](../CLAUDE.md).

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
**ab dem Beginn des aktiven Blocks** (`aktiv.beginn`, nicht `start_date`) — wer
die Folgewoche plant, hat für den Rest dieser Woche weiterhin nur den alten
Block, und dessen Einheiten aus dem Kalender zu werfen ließe ihn bis zum
Blockbeginn ohne Vorgabe dastehen (dieselbe Grenze nennt der Hinweis beim
Übernehmen: „ab dem <Datum> entfallen dort N Tage"). Auf `start_date` gerechnet
fiele sie still auf `heute` zurück, sobald der Block die Vergangenheit seines
Vorgängers übernommen hat — und die Folgewoche stünde ohne Vorgabe da. Und **nicht der Block, der gerade übertragen wird** (`ausser_plan_id`):
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
