# Workouts in der iOS-App

Teil der Kontextdokumentation von Tri-Coach. Überblick, Setup und Konventionen:
[CLAUDE.md](../CLAUDE.md).

**Kraft- und Mobility-Einheiten lassen sich in der App absolvieren.** In der
Detailansicht einer solchen Einheit steht „Workout starten“. Die App führt
dann Satz für Satz durch die Einheit: Die Animation der Übung läuft, darunter
steht „Satz 2 von 3 · 1. Seite“. Ein zeitgesteuerter Satz zählt herunter und
schaltet von selbst weiter, ein gezählter wartet auf „Satz fertig“ und hat die
Soll-Wiederholungen vorbelegt (mit − und + änderbar). Zurück, Überspringen,
Pause und vorzeitiges Beenden gibt es jederzeit. Ist das Workout durch, geht es
**von selbst nach Garmin Connect**.

**Derselbe Ablauf wie auf der Uhr** (`garmin/ablauf.py`). Die App bekommt die
Einheit nicht als Text, den sie selbst zerlegen müsste, sondern fertig als
Schrittfolge (`GET /api/training/einheit/{id}/ablauf`). Die entsteht aus
denselben Elementen, aus denen `workouts.baue_workout()` das Workout für die Uhr
baut: erst der Bauplan der KI, dann die Übungsliste aus dem Aufbautext, zuletzt
der Ersatzschritt. „3x15 … je Seite“ sind also auch in der App sechs Durchgänge,
und eine Übung ohne Umfang läuft bis zum Tippen, wie auf der Uhr bis zur
Rundentaste. Zwei Lesarten desselben Plans liefen auseinander, und die App
zählte andere Sätze als die Uhr. Die Seiten werden nur benannt, wenn die Zahl
der Durchgänge gerade ist; sonst stünde der dritte Satz ohne Gegenstück da.

**Keine erfundenen Pausen, aber eine Vorbereitung.** Der Bauplan kennt keine
Pausen zwischen den Sätzen, und die App fügt keine ein. Vor jedem
zeitgesteuerten Satz stehen aber fünf Sekunden „Bereit machen“
(`WorkoutModell.vorbereitungS`, mit „Los“ abkürzbar). Ein Timer, der schon
läuft, während man sich noch auf die Matte legt, stiehlt dem Satz seine Zeit.
Vor gezählten Sätzen braucht es das nicht, dort bestimmt der Athlet den Takt.

**Die Zeiten hängen an Zeitpunkten, nicht an einem Zähler** (`WorkoutModell`).
Jeder Satz hat einen Anfang und ein Ende als Uhrzeit, und der Takt der Ansicht
prüft nur, was inzwischen fällig ist. Wird das Telefon kurz gesperrt, holt der
nächste Takt nach, was abgelaufen ist, auch mehrere Sätze auf einmal. Die
Zeiten in Garmin sind die wirklichen, nicht die geplanten. Solange das Workout
läuft, bleibt der Bildschirm an (`isIdleTimerDisabled`). Die letzten drei
Sekunden piept es und das Telefon vibriert.

**Der Puls zählt hier nicht.** Die App misst keinen und schreibt keinen: Bei
Kraft und Mobility steuert er nichts (siehe `_OHNE_PULSKORRIDOR` in
`schemas.py`), und ein vorgetäuschter Wert fiele in Last und Zonen des Exports.

**Das Ergebnis geht über Garmin, nicht in die Datenbank** (`garmin/app_training.py`).
Trainingsdaten kommen nur aus Garmin (siehe „Garmin ist die einzige Quelle“).
Daran ändert ein Workout aus der App nichts: Das Add-on schreibt daraus eine
FIT-Datei und lädt sie als Aktivität nach Connect. Der nächste Abgleich holt
sie zurück, mitsamt der Sätze, die Connect aus der Datei gelesen hat, und legt
den Trainingseintrag an wie für jede andere Aktivität. So steht das Training an
genau einer Stelle: in Connect, im Export an die KI und in der Umsetzungsquote.
Damit es nicht erst morgen früh als erledigt dasteht, stößt ein geglückter
Upload den Abgleich nach einer Minute selbst an (`ABGLEICH_NACH_S`). Connect
verarbeitet die Datei nicht immer sofort.

**Warum FIT** (`garmin/fit_schreiben.py`). Nur in einer FIT-Datei übernimmt
Connect Sätze samt Übung und Wiederholungen (`set`-Nachrichten, abwechselnd
aktiv und Pause). Ein von Hand angelegtes Training über die API hätte nur Dauer
und Sportart. Geschrieben wird mit dem Encoder aus `garmin-fit-sdk`, derselben
Bibliothek, mit der `fitdaten.py` liest. Die Tests lesen jede erzeugte Datei
damit wieder ein. Kraft ist `training/strength_training`, Mobility die eigene
Sportart `mobility`; Connect macht daraus die Typen `strength_training` und
`mobility`, die `mapping.py` kennt. Die Übung steht als FIT-Nummer im Satz:
Garmins Katalogname aus dem Workout-Schritt („PLANK“/„SIDE_PLANK“) wird im
FIT-Profil nachgeschlagen. Connect schreibt Namen mit führender Ziffer mit
Unterstrich („_3_WAY_CALF_RAISE“), das Profil ohne.

**Die Aktivität findet ihre Planeinheit über die App, nicht über eine
Workout-Kennung** (`matching.planeinheit_aus_app`). Eine Aktivität von der Uhr
trägt die Kennung der Vorlage, aus der sie gestartet wurde; daran hängt
`finde_planeinheit`. Eine hochgeladene Datei trägt keine. Beim Hochladen
entsteht deshalb eine Zeile `AppTraining` mit der Planeinheit. Nennt Garmin in
der Antwort gleich die neue Aktivitätskennung, wird über sie zugeordnet. Sonst
sucht der Abgleich über die Startzeit (±2 Minuten) und merkt sich die Kennung
für das nächste Mal. Die App-Zuordnung kommt vor `finde_planeinheit`.

**Nichts geht verloren, nichts kommt doppelt an.** Im Keller oder im Studio ist
das Netz oft weg. Die App legt jeden Bericht, der nicht als hochgeladen
quittiert ist, auf dem Telefon ab (`Training/Warteschlange.swift`) und schickt
ihn beim nächsten Laden der Daten erneut, höchstens 14 Tage lang. Das Add-on
speichert den Bericht, auch wenn Garmin gerade nicht will (`zustand:
fehlgeschlagen` samt Grund). Die `kennung` des Berichts vergibt die App: Ein
zweiter Aufruf damit legt nichts neu an, er versucht nur einen gescheiterten
Upload erneut. Meldet Garmin eine Dublette, gilt das als angekommen.

**Die API** (`routers/training.py`):

- `GET /api/training/einheit/{id}/ablauf` liefert Übungen (mit Animation und
  Garmin-Katalognamen) und Schritte in Reihenfolge.
- `POST /api/training/einheit/{id}/abschluss` nimmt den Bericht an: `kennung`,
  `beginn`, `ende`, `pausiert_s`, `saetze`. Antwort ist der Zustand des Uploads.
- `GET /api/training/einheit/{id}` listet, was die App zu dieser Einheit schon
  gemeldet hat.

**Grenzen.** Gewichte erfasst die App nicht; die Pläne sind Körpergewichtsübungen.
Eine Übung, die Garmins Katalog nicht kennt, steht in Connect ohne Namen da (der
Satz zählt trotzdem). Ob Connect jede Mobility-Übung anzeigt, hängt an Garmins
Katalog für diese Sportart. Ein Add-on vor dieser Version kennt die Endpunkte
nicht; die App sagt dann, dass es aktualisiert werden muss.
