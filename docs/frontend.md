# Frontend und Oberfläche

Teil der Kontextdokumentation von Tri-Coach. Überblick, Setup und Konventionen:
[CLAUDE.md](../CLAUDE.md).

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
KI-Planung (Token, automatische Planung samt Wochentag und Uhrzeit, Modell,
Denktiefe) und Darstellung.

**Uhrzeiten stehen als getrennte Auswahlfelder** (`.uhrzeit-wahl`), Stunde und
Minute nebeneinander, die Minuten in Fünferschritten. Kein `<input type="time">`:
Die Seite besteht sonst aus `<select>` und Häkchen, und ein Feld mit eigener
Tastaturbedienung und eigenem Parsing wäre der einzige Fremdkörper. Fünferschritte,
weil sechzig Einträge zu durchsuchen kein Gewinn an Genauigkeit ist — die Schleife
im Server wacht zwar minütlich auf, aber „so ungefähr um neun" ist die Frage, die
hier beantwortet wird. Der Wochentag kommt aus `WEEKDAYS` (`constants.ts`), das
Montag zuerst zählt und damit zu `date.weekday()` im Backend passt.

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

**Die Tagesanpassung steht in der Garmin-Karte, obwohl sie der KI gehört.** Ihr
Schalter liegt unter der Abgleichzeit, weil dort die Frage steht, die er
beantwortet — „und was passiert, wenn die Daten da sind?". Gespeichert wird er
trotzdem in `KiSettings`, neben den anderen Schaltern, die Claude-Kontingent
kosten; die Karte ist eine Frage der Oberfläche, nicht der Ablage. `GarminKarte`
bekommt dafür `ki` und `onKiAendern` zusätzlich — beides liegt in
`Einstellungen()` ohnehin geladen vor. Ohne hinterlegten Zugang und bei
abgeschaltetem Abgleich ist er gesperrt und sagt in seinem `field-hint`, woran es
liegt: Ein Häkchen, das sich setzen lässt und nichts tut, ist schlimmer als
keins.

**Und inzwischen auch das Anmelden selbst.** Das Formular für Garmin-E-Mail,
Passwort und Bestätigungscode stand auf `/garmin`, die Schalter dazu schon in
den Einstellungen — wer ein Konto einrichtete, musste zwischen zwei Seiten hin
und her. Es liegt jetzt als `components/GarminAnmeldung.tsx` in der
Garmin-Karte der Einstellungen, samt *Trennen*; `/garmin` behält Abgleich,
Rückblick, Fortschritt und Doppeleinträge und zeigt ohne Konto nur einen
Verweis. Der Zustand (Passwort, angefangene Bestätigung) liegt **in** der
Komponente: Er geht niemanden außerhalb etwas an, und die Einstellungsseite
soll ihn nicht mitschleppen. Daneben steht die Bring-Karte, nach demselben
Muster wie der Claude-Zugang — mit dem einen Unterschied, dass das Passwort
wirklich gespeichert wird (siehe [einkaufsliste.md](einkaufsliste.md)).

**Auf der Planungsseite gilt jetzt derselbe Filter für den letzten wie für den
laufenden Lauf** (`PlanExchange.istBlockLauf`). Es gibt genau **einen** KI-Lauf
für alle Aufgaben, und `aktiver_job` wurde deshalb längst auf `manual`/`auto`
gefiltert — `letzter_job` nicht. Das fiel nicht auf, solange eine Einheit oder
ein Ernährungsplan selten dazwischenkam; seit die Tagesanpassung jeden Morgen
läuft, stünde dort täglich „Der heutige Tag bleibt, wie er geplant war" unter dem
Knopf, der einen Block plant.

**Was nachts passiert ist, steht morgens oben auf der Startseite**
(`Dashboard.tagesanpassung`). Die Tagesanpassung läuft, während niemand
hinsieht; ein Fähnchen an der Einheitenkarte wäre für eine Änderung, die der
Athlet nicht bestellt hat, zu leise — er müsste erst eine Einheit anklicken, um
zu erfahren, dass und warum sein Tag anders aussieht als gestern Abend geplant.
In der Karte „Heute" steht deshalb ein `Alert kind="info"` über den Einheiten,
mit der Begründung der KI. Einmal, nicht je Karte: Die Begründung gilt für den
ganzen Tag und steht an jeder angefassten Einheit gleich.

Gezeigt wird er nur bei **fehlendem** `anpassungswunsch` — wer selbst angepasst
hat, weiß es und braucht keinen Hinweis. Im Trainingsplan bleibt es beim Badge
an der Karte: Dort stehen alle Tage nebeneinander, und ein Banner je Tag wäre
Lärm statt Hinweis.

**Unverändert ist auch eine Nachricht** (`TagesformKarte`, `useTagesform`). Der
Absatz oben beschreibt den selteneren Fall. Der Prompt der Tagesanpassung nennt
„unverändert" ausdrücklich den Regelfall, und ein unveränderter Tag schreibt an
keine Einheit etwas: kein `angepasst_am`, kein Badge, kein Banner. Ein
geglückter Lauf, der zu dem Schluss kam, dass alles passt, sah damit für den
Athleten **exakt** so aus wie einer, der nie stattgefunden hat — und wie einer,
der an einem Fehler gestorben ist. Sein Kontingent war weg, seine Antwort
nirgends zu sehen; es gab keinen Ort in der Oberfläche, an dem ein
`tagesform`-Job je auftauchte (`useEinheitAnpassung` filtert auf `einheit`,
`PlanExchange` auf `istBlockLauf`, `Ernaehrung` auf `ernaehrung`).

`TagesformKarte` steht deshalb an derselben Stelle über der Karte „Heute" und
zeigt **immer** etwas — außer bei ausgeschaltetem Schalter: Wer ihn bewusst aus
gelassen hat, braucht dazu keine tägliche Erinnerung. Eine tatsächlich geänderte
Einheit hat Vorrang vor allem anderen; darunter kommen „geprüft, alles bleibt",
„läuft gerade", „gescheitert" und „gar nicht gelaufen — und woran es lag". Beim
Knopf „Jetzt prüfen" steht dabei, dass er Kontingent kostet.

Die **Begründung** der KI — warum sie die Einheit von heute angefasst oder
stehen gelassen hat — liegt dabei zugeklappt hinter der Zeile selbst
(`Klappblock`, dasselbe Muster wie bei Ausrichtung und Steuerungshinweisen).
Sichtbar bleiben muss täglich nur, *dass* geprüft wurde; der Fließtext dahinter
wird einmal gelesen. Fehlt er, bleibt es bei der Zeile ohne Reiter — ein leerer
Reiter wäre eine Einladung ins Nichts. Die kurzen Zustandssätze von
„gescheitert" und „nicht gelaufen" stehen weiter offen: Sie sind eine
Handlungsaufforderung, kein Nachschlagetext.

**Ein zweiter Hook neben `useEinheitAnpassung`, mit Absicht.** Der beobachtet
einen Lauf, den der Nutzer gerade selbst angestoßen hat, und dessen Karte er
danach wegklickt. `useTagesform` beobachtet einen *Zustand des Tages*: Er gilt,
ob jemand hinsieht oder nicht, wird nicht weggeklickt, und er ist auch dann eine
Aussage, wenn nichts gelaufen ist. Beides in einen Hook zu ziehen hieße, zwei
verschiedene Fragen mit denselben Feldern zu beantworten. Am Ende eines Laufs
holt er **erst** den Befund neu und ruft **dann** `reload()`: Der Job allein
sagt nicht, ob Claude überhaupt gefragt wurde — das entscheidet der Endpunkt an
`model_used`.

Beide belegen denselben einen Lauf je Konto. Das Dashboard reicht deshalb
`anpassungLaeuft={einLaufAktiv}` an `SessionDetail`, sonst liefe „Einheit
anpassen" in ein 409, während im Server gerade der Tag geprüft wird.

**Ob ein Zeitstempel „heute" ist, rechnet `planung.istHeute()`** und nicht die
ersten zehn Zeichen der Zeichenkette. Die stehen in UTC; früh morgens und
abends ist das ein anderer Tag als der, den der Athlet vor sich hat — und
ausgerechnet früh morgens läuft die Anpassung. Gegenstück zu `zeit.ortsdatum()`
im Backend, aus demselben Grund und mit derselben Falle.

**Am Detaildialog hängt der einzige sichtbare Beleg der Tagesanpassung**
(`SessionDetail.tsx`). Der Satz „✎ Diese Einheit wurde angepasst — auf den Wunsch
…" gibt es jetzt in zwei Fassungen, und unterschieden werden sie an einem
**leeren** `anpassungswunsch`: Dann ging die Anpassung von Messwerten aus, nicht
von einer Bitte, und „auf den Wunsch ‚automatisch angepasst'" wäre ein Satz, der
sich selbst widerspricht. Darunter steht in beiden Fällen
`anpassungsbegruendung` — dieselbe, die auf der Startseite über dem Tag steht.
Die Meldung des Jobs trägt sie nicht mehr weit: Sie ist längst aus der Liste
gerutscht, wenn der Athlet die App öffnet.

**Die Einkaufsliste geht über einen Vorschaudialog** (`Ernaehrung.tsx`,
`EinkaufslistenDialog`). Zwei Schritte statt einem, weil sich das Ergebnis nicht
ohne Weiteres zurücknehmen lässt: Der Dialog zeigt erst die summierten Posten
mit genau dem Text, der in Bring landen wird. Er kommt fertig formatiert aus dem
Server (`menge_text`) und wird hier nicht noch einmal gerechnet — zwei
Rundungsregeln für dieselbe Zahl liefen auseinander. Nur die Zutatenanzeige in
der Planansicht formatiert selbst (`mengeText`), weil dort Rohwerte stehen.
Sind Tage schon übertragen, erscheint ein Kasten dafür statt eines stillen
Überspringens.

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

**In der Kopfzeile steht der Datenstand, nicht das heutige Datum**
(`Dashboard.datenstand`). Dort stand einmal „Mittwoch, 26. August" — und
darunter Trainingsreife, HRV, Schlaf und Ruhepuls, die bis zum Abgleich des
Tages noch von gestern stammen (Vorgabe: 10 Uhr Ortszeit). Das Datum behauptete
damit eine Frische, die die Zahlen darunter nicht hatten, und beantwortete
zugleich die einzige Frage nicht, die man an dieser Stelle hat: von wann sie
sind. Es steht deshalb `konto.last_sync_at` da, mit Uhrzeit — im selben Format
wie `AbgleichStand` in `PlanExchange.tsx`. **Ohne Abgleich bleibt es beim
heutigen Datum**: Dann kommt auf der Seite nichts aus der Uhr, und ein Stand
wäre eine Aussage über Daten, die es nicht gibt. Dafür holt `reload()` jetzt
zusätzlich `api.garminStatus()` — anders als `api.garminWorkoutStatus()` (siehe
oben) kostet das nichts gegen Garmin, der Endpunkt liest die eigene Datenbank.

**Die Kilometerkachel klappt nach Sportart auf, und ein hängender Abgleich
sagt das auch.** Beides kommt aus derselben Beschwerde: „Distanz diese Woche
zeigt nichts an, obwohl in Garmin Trainings sind." Die Zahl war beide Male
richtig — erst war der Garmin-Zugang abgelaufen und es kam seit Tagen kein
Training mehr an, danach bestand die Woche aus Indoor-Radfahren ohne
Geschwindigkeitsmesser, Kraft und Mobility: Garmin selbst liefert für solche
Einheiten `distance: 0.0`, auch im Detail. Vier Einheiten, 126 Minuten, null
Kilometer ist dann die Wahrheit. Erklärt hat sie auf der Startseite nur
niemand.

Deshalb zwei Dinge. Erstens steht bei `konto.status !== 'connected'` eine
Warnung oben auf der Seite, mit Garmins eigener Meldung und einem Weg zu
`/garmin` — ein stehengebliebener Abgleich ist der einzige Grund, aus dem
sämtliche Kacheln zugleich auf null stehen können, *ohne* dass die Woche leer
war, und der Datenstand in der Kopfzeile (siehe oben) nennt zwar das Datum des
letzten Abgleichs, aber nicht, dass der nächste gar nicht mehr kommt.

Zweitens klappt die Kachel nach Sportart auf (`DistanzKachel`). Die
Aufschlüsselung zeigt **immer** Schwimmen, Rad und Laufen, auch mit 0,0 km:
Zuerst hingen die Zeilen daran, ob überhaupt Kilometer zusammenkamen — und
damit war die Kachel ausgerechnet in der Woche nicht anklickbar, in der man
fragt, welche Disziplin auf null steht. Sortiert wird fest in
Triathlonreihenfolge statt nach Umfang, sonst sprängen die Zeilen von Woche zu
Woche; Kraft und Mobility bleiben draußen, weil sie nie Strecke haben.
Anklickbar ist die **ganze Kachel**, dort greift die Hand hin — aber als echter
`<button>` (`.stat-toggle`, Geschwister von `.linklike`), und die Kinder sind
`span`, weil ein `div` im Knopf kein gültiges HTML ist. Eine neue API braucht
das nicht: `by_sport` steht längst in jedem `WeeklyBucket`, weil der Export es
ohnehin liest.

**Ausrichtung und Steuerungshinweise stehen auch auf der Startseite**
(`plan.summary` / `plan.coaching_notes`, direkt unter der Überschrift der
„Heute"-Karte und **über** den Einheiten des Tages — die Einordnung gehört vor
die Vorgabe; die Trennlinie steht deshalb darunter). **Zugeklappt** allerdings
(`Klappblock`): Beide gelten für den ganzen Block und ändern sich sieben Tage
lang nicht, während die Einheit von heute der Grund ist, aus dem die Seite
morgens geöffnet wird. Aufgeschlagen schöben zwei Absätze Fließtext sie unter
die Bildschirmkante, und gelesen würden sie trotzdem nur einmal. Die
Überschriften bleiben stehen — sie sagen, dass es die Einordnung gibt und wo
sie liegt. Sie standen bisher nur im Trainingsplan — und genau dorthin geht
niemand, der den Block automatisch erzeugen lässt: Die Uhr trägt das Workout,
die Startseite die Einheit von heute, und *warum* der Block so liegt und woran
zu steuern ist, las man nirgends. Zwei Überschriften, im Wortlaut
wie in der Planansicht — zwei Fassungen desselben Textes liefen auseinander.
Dafür wird „Heute" auf die **ganze Breite** gezogen und „Als Nächstes" darunter
gestellt (`grid grid-2` entfällt): Ein Fließtext von ein paar Sätzen in einer
halbbreiten Spalte neben einer Tabelle liest sich schlecht, und die Reihenfolge
stimmt so auch inhaltlich — heute, dann der Rest des Blocks. Am Telefon ändert
sich nichts; dort standen die beiden Karten schon vorher untereinander.

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
acht Wegen nebeneinander funktioniert am Schreibtisch; auf einem Telefon bräuchte sie
drei Zeilen und stünde bei jedem Scrollen im Weg. Unterhalb von 860 px entfällt
sie deshalb ganz (`.topbar-app`), stattdessen blendet `Layout.tsx` eine feste
Leiste am unteren Rand ein: Übersicht, Plan, Ernährung, Garmin, Verlauf und
„Mehr“ — hinter „Mehr“ liegt ein Blatt mit Garmin-Kalender, Neues Training,
Meine Daten, Einstellungen und Abmelden. Die fünf unten sind das Maximum:
`.mobile-nav` steht im CSS auf `repeat(6, 1fr)` (fünf Wege plus „Mehr“), ein
sechster spränge die Leiste — und bei sechs Spalten musste die Beschriftung auf
0,62 rem, weil auf 360 px nur noch 60 px je Reiter bleiben. Deshalb liegt
„Einstellungen“ hinter „Mehr“ — und es passt dorthin, weil
man die Seite einmal einrichtet und danach selten wieder öffnet. „Ernährung“
steht dagegen zwischen Plan und Garmin: Es ist die Antwort auf denselben Tag,
den der Plan vorgibt, und wird zusammen mit ihm gelesen. Den Platz, an dem einmal „Erfassen“ stand, hat Garmin bekommen:
Von dort kommen die absolvierten Einheiten, also gehört der Abgleich in den
Alltag und nicht hinter „Mehr“. Orientierung geht dabei nicht verloren, weil jede Seite ihre
Überschrift selbst trägt. Zwei Dinge hängen daran: `.page` braucht unten Platz
für die Leiste samt `env(safe-area-inset-bottom)` — dafür steht
`viewport-fit=cover` in der `index.html`, ohne das der Wert auf iOS 0 bleibt —
und Eingabefelder bekommen dort 16 px Schriftgröße, weil iOS darunter beim
Antippen in die Seite hineinzoomt und den Nutzer im vergrößerten Ausschnitt
zurücklässt.

**Oben am Schreibtisch entscheidet die Breite, nicht die Zahl.** In `NAV_ITEMS`
stand einmal „sieben Einträge ist die Obergrenze“; das war die Zählung eines
Symptoms. `.nav` bricht um, sobald die Beschriftungen nicht mehr nebeneinander
passen — mit „Ernährung“ sind es acht, und die Leiste blieb einzeilig, weil
zugleich zwei Labels kürzer wurden: „Trainingsplan“ → „Plan“ (so heißt der
Reiter am Telefon ohnehin) und „Neues Training“ → „Fragebogen“ (was die Seite
trifft). Zusammen sind die acht Beschriftungen kürzer als die sieben davor. Wer
einen neunten Weg braucht, misst wieder — oder kürzt weiter.

**Der Kalender ist ein Markup für zwei Größen.** Am Schreibtisch ein
Monatsraster mit sieben Spalten, am Telefon eine Tagesliste — aber nicht zwei
Bausteine, sondern dieselben Zellen: Unterhalb von 700 px fällt das
Spaltenraster auf eine Spalte zusammen, Leerfelder vor dem Monatsersten und
Tage ohne Eintrag werden ausgeblendet (`.kalender-fueller`, `.is-leer`), und
der Wochentag rückt in die Zelle, weil es keine Spaltenüberschrift mehr gibt.
Dieselbe Überlegung wie bei den Tabellen: Eine zweite Darstellung liefe mit der
ersten auseinander.

**„Heute" wird bei jedem Rendern neu bestimmt, nicht beim Laden der App**
(`useHeute()` in `components/useHeute.ts`). Die Tagesmarkierung im Kalender hing
an einer modulweiten Konstante, und weil alle Routen statisch in `App.tsx`
liegen, war das genau ein Aufruf: der Moment, in dem der Tab aufging. Eine
Sitzung über Mitternacht markierte am Morgen weiter den Vortag — am Telefon der
Normalfall, denn dort schläft ein Tab, statt zu schließen. Kein Zeitzonenfehler:
Gerechnet wird über `planung.heuteIso()`, das die Ortszeitanteile liest und nicht
`toISOString()` — dieselbe Regel, die auch die Startdaten neuer Blöcke bestimmt.
Der Hook steht in einem eigenen Modul, seit die Planansicht ihn ebenfalls
braucht: Ihn aus einer *Seite* zu importieren zöge deren ganzes Modul mit.

Der Haken an der naheliegenden Lösung ist, dass ein Wert je Rendern nur hilft,
wenn gerendert wird — ein offener Kalender tut das über Nacht nicht. Deshalb ein
Zeitgeber auf den nächsten Tagesbeginn (feuert genau einmal, statt im Minutentakt
zu fragen) **und** `visibilitychange`, weil Telefone Zeitgeber im Hintergrund
drosseln und nicht nachholen — dieselbe Überlegung wie bei `pollJob`. Ein Aufruf
ohne Tageswechsel kostet nichts: Gleicher Tag heißt gleicher String, und React
verwirft die Zuweisung von selbst.

**Die Planansicht zeigt ab heute** (`PlanView.tsx`). Ein Block trägt seit der
Übernahme der Vergangenheit die Tage seiner Vorgänger mit, und die wächst mit
jeder Neuplanung — nach einem Monat Automatik stünden dreißig erledigte Tage über
dem, was noch kommt. Vergangenes ist deshalb eingeklappt, darüber „Vergangene
Tage anzeigen (N)". Zwei Ausnahmen, beide nötig: Ein Block, der **ganz vorbei**
ist, zeigt alle Tage — sonst stünde die Seite unter „Frühere Pläne" leer, und das
ist dort der Normalfall. Und die **Wochensumme zählt alle Einheiten der Woche**,
auch die ausgeblendeten: Eine Bilanz, die sich mit einem Anzeigeschalter ändert,
wäre keine.

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

**Der Fortschritt wird abgefragt, nicht geschoben** (`api/client.ts`,
`pollJob`). Erstes Muster dieser Art in der App. Das Intervall ist bewusst träge
(2,5 s, nach zwei Minuten 5 s) — der Abgleich macht ohnehin nur alle paar
Sekunden einen Schritt, und häufigeres Fragen erzeugt nur Last auf einem
Raspberry Pi. Bei `visibilitychange` wird sofort einmal nachgefragt, weil
Telefone Zeitgeber im Hintergrund drosseln und der Balken sonst eingefroren
wirkte. Netzfehler beenden die Schleife nicht: Der Lauf geht im Server weiter.

**Abgemeldet wird nur bei einem 401 der eigenen Sitzungsprüfung**
(`api/client.ts`). Der Client wertete jedes 401 als „Token abgelaufen", räumte
die Anmeldung ab und ersetzte die Meldung des Endpunkts durch „Sitzung
abgelaufen". Das traf genau einen Fachendpunkt — `POST /api/garmin/connect` —
und machte dessen Fehlschlag unsichtbar: Der Anmeldedialog verschwand samt der
Begründung, zurück blieben zwei leere Felder. Der Server sagt seither 400
(siehe `docs/garmin-abgleich.md`), und der Client prüft zusätzlich den Kopf
`WWW-Authenticate`, den allein `deps.get_current_user` setzt. Er ist im
Backend ausdrücklich über `expose_headers` freigegeben, sonst läse ihn der
Browser bei getrennten Ursprüngen — in der Entwicklung 5173 gegen 8000 — gar
nicht.

**Der Kontowechsel muss in allen Tabs ankommen** (`auth/AuthContext.tsx`). Der
Anmeldezustand steht in React, das Token in `localStorage`. Waren zwei Tabs als
Nutzer A offen und wechselte einer auf B, zeigte der andere weiter A's Namen und
A's geladene Daten, schickte seine Anfragen aber schon mit B's Token: Ein
„Speichern" im Profil schrieb dann die angezeigten Werte des einen Kontos in das
andere. Ein `storage`-Ereignis auf `TOKEN_KEY` baut den Zustand deshalb neu auf
— ohne Token abmelden, sonst `api.me()`. Der Schlüssel wird aus `client.ts`
exportiert statt wiederholt; zwei Zeichenketten, die dasselbe meinen müssen,
laufen sonst auseinander.

**Die Einstellungsseite lädt ihre drei Karten unabhängig** (`Promise.allSettled`
statt `Promise.all`). `GET /api/bring/status` fragt bei hinterlegtem Konto
synchron das Netz. Fiel dieser eine Aufruf aus, blieben alle drei Zustände
`null` — und weil die Garmin-Karte bei `konto === null` das Anmeldeformular
zeigt, sah ein längst verbundenes Konto so aus, als wäre die Verbindung weg. Ein
Timeout bei Bring darf nicht wie ein verlorenes Garmin-Konto aussehen.

**„Konto wechseln" führt direkt zur Kontoauswahl** (`Layout.tsx`). Bis dahin gab
es nur „Abmelden" → Landingpage → „Anmelden". Da die Anmeldung ohnehin nur eine
Auswahl ist, ist der Umweg reine Reibung — der zweite Knopf ruft dasselbe
`logout()` und landet auf `/login`.
