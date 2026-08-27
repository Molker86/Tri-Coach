# Die Einkaufsliste — vom Ernährungsplan nach Bring

Warum das hier so gebaut ist, wie es gebaut ist. Wer eine dieser Entscheidungen
umdrehen will, findet hier, was dagegen schon einmal sprach.

**Die Zutaten kommen von der KI, nicht aus der Prosa.** `ErnaehrungsMahlzeit`
hatte immer schon eine `beschreibung` — „120 g Haferflocken, 300 ml Milch, 1
Banane". Daraus die Einkaufsliste zu parsen wäre naheliegend und falsch: Der
Satz enthält Zubereitungen („in 300 ml Wasser gekocht"), Alternativen („oder
Reiswaffeln") und Zustände („gekochte Haferflocken"), und keine Heuristik
unterscheidet zuverlässig, was davon gekauft werden muss. Die KI weiß das beim
Schreiben. Deshalb liefert sie es mit, in `ErnaehrungsZutat` — und die
`beschreibung` bleibt daneben stehen, weil sie eine andere Frage beantwortet.
Der Preis: Ernährungspläne aus der Zeit davor haben keine Zutaten und lassen
sich nicht übertragen. Die Vorschau sagt das im Klartext, statt eine leere Liste
zu zeigen.

**Umgerechnet wird beim Import, nicht beim Summieren.**
`einkaufsliste.normalisiere()` macht aus „1,5 kg" 1500 g, bevor irgendetwas in
die Datenbank geht. Andernfalls müsste jede Summe raten, ob „1 l Milch" und „500
ml Milch" dasselbe Regal meinen — und zwei Stellen (Vorschau und Übertragung)
müssten dieselbe Rechnung anstellen. Eine unbekannte Einheit bleibt stehen
statt verworfen zu werden: „2 Dosen" ist eine brauchbare Angabe und kein Fehler.

**Gruppiert wird über Name *und* Einheit.** „200 g Tomaten" und „2 Stück
Tomaten" bleiben zwei Zeilen. Sie zusammenzuziehen hieße zu wissen, wie schwer
eine Tomate ist — das weiß niemand, und eine erfundene Umrechnung stünde
unsichtbar in der Summe.

**Bring kennt keine Mengenfelder.** Das ist die Wurzel des halben Moduls: Ein
Eintrag dort hat einen Namen (`itemId`) und einen Freitext (`specification`), in
dem „500 g" ebenso stehen kann wie „fettarm". Wer aufaddieren will, muss den
Freitext lesen, rechnen und zurückschreiben — `parse_menge()` und
`verschmelze()` tun genau das. Passt die Einheit nicht oder steht dort gar keine
Zahl, wird **angehängt** statt gerechnet („fettarm + 500 ml"). Ein sichtbar
doppelter Eintrag ist ärgerlich; eine still falsch summierte Menge ist
schlimmer, weil sie niemandem auffällt.

**Nur die offenen Posten sind Abgleichbasis.** Brings `items.recently` sind die
abgehakten Einträge der letzten Einkäufe. Wer Milch vorige Woche gekauft hat,
will sie diese Woche neu auf der Liste — und nicht als Menge an einem
erledigten Eintrag.

**Bei einem Treffer behält Bring seinen Namen.** Ein Eintrag, dessen `itemId`
sich ändert, wird in der Bring-App erst nach einem vollständigen Neuladen
richtig angezeigt — die Bibliothek rät ausdrücklich vom Umbenennen ab. Also
gewinnt die Schreibweise, die schon dort steht.

**Der Riegel sitzt am Tag, nicht am Plan.** `ErnaehrungsTag.bring_uebertragen_am`
hält fest, was schon drüben ist. Ohne ihn würde ein zweiter Knopfdruck jede
Menge ein zweites Mal draufrechnen — und weil Bring keine Historie zeigt, fiele
das erst im Laden auf. Am Tag und nicht am Plan, weil sich der Plan über Tage
erstreckt, die nacheinander fällig werden: Wer montags überträgt und mittwochs
den Plan verlängert, soll die neuen Tage bekommen und die alten nicht noch
einmal. Wer trotzdem alles will, sagt es ausdrücklich (`?alles=true`).

**Vermerkt wird nach dem Schreiben.** Ein Tag, der als übertragen gilt, ohne es
zu sein, fehlt im Einkauf und fällt niemandem auf. Ein Tag, der zweimal als
offen gilt, kostet einen Blick.

**Synchron und ohne Job.** Garmin und die KI laufen als Job mit
Fortschrittsbalken, weil sie Minuten brauchen. Ein Bring-Lauf ist eine
Anmeldung, ein Lesen und ein Schreiben — Sekunden. Ein Fortschrittsbalken über
drei HTTP-Aufrufe wäre Aufwand ohne Auskunft.

**Die Vorschau fragt Bring gar nicht.** Was auf die Liste ginge, steht schon in
der Datenbank. So lässt sich der Dialog auch ohne verbundenes Konto zeigen, und
die Rechenlogik ist ohne Netz prüfbar (`tests/test_einkaufsliste.py`).

**Lesen und Schreiben liegen in einer Sitzung.** `client.uebertrage()` nimmt
einen Rückruf statt fertiger Aufträge: Worauf aufaddiert wird, muss auf dem
beruhen, was im selben Atemzug dort stand. Zwischen zwei Anmeldungen hätte
jemand anders die Liste ändern können. Nebenbei spart es die zweite Anmeldung —
Bring gibt beim Anmelden ein Token heraus, das die Bibliothek nur im
Arbeitsspeicher hält.

**Das Bring-Passwort wird gespeichert, das Garmin-Passwort nicht.** Kein
Widerspruch, sondern ein Unterschied der beiden Dienste: Garmin stellt einen
dauerhaften Zugangsschlüssel aus, den die App stattdessen behalten kann. Bring
tut das nicht. Ohne gespeichertes Passwort müsste sich der Nutzer vor jeder
Übertragung neu anmelden. Verschlüsselt wird es mit demselben Fernet wie
Garmin-Token und Claude-Zugang (`crypto.py`) — es gibt bewusst **einen**
Schlüssel für alle Geheimnisse, damit ein Wechsel von `TRI_SECRET_KEY` nicht
teilweise wirkt.

**Supplemente gehen nicht mit.** Sie stehen am Plan statt am Tag und haben eine
Dosierung („3 mg/kg Körpergewicht") statt einer Menge. Was daraus einzukaufen
wäre, ließe sich nur raten.

**Die Übertragung läuft nur auf Knopfdruck.** Es gibt bewusst keinen Schalter
wie `auto_push_enabled` bei Garmin: Geschrieben wird in eine Liste, die anderen
Menschen im Haushalt gehört und die sie gerade vor sich haben. Was dort
auftaucht, soll jemand gewollt haben.
