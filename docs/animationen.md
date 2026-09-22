# Übungsanimationen

Teil der Kontextdokumentation von Tri-Coach. Überblick, Setup und Konventionen:
[CLAUDE.md](../CLAUDE.md).

**Zu jeder Kraft- und Mobility-Übung gibt es eine Animation — in der iOS-App.**
Wer im Kalender einen Tag öffnet und eine Kraft- oder Mobility-Einheit antippt,
sieht deren Übungen in der Reihenfolge des Plans; jede spielt eine kurze,
endlose Bewegungsschleife ab. Die Weboberfläche zeigt sie bewusst **nicht** —
am Rechner turnt niemand, das Telefon liegt beim Training neben der Matte.

**Eigene Animationen statt Videos aus dem Netz** (`backend/app/animation/`).
Geprüft wurde zuerst der naheliegende Weg: zu jedem Übungsnamen ein Video oder
GIF suchen. Er scheitert an drei Stellen zugleich. Die brauchbaren Sammlungen
sind lizenziert und dürfen nicht in eine Datenbank kopiert werden; was frei
ist, ist uneinheitlich (andere Person, andere Kamera, Musik, Werbung, mal
Zeitlupe, mal Wiederholungen im Akkord); und ein Treffer über den Namen ist
kein Treffer über die Übung — „Side Plank with Leg Lift" findet drei
verschiedene Bewegungen. Die App zeichnet deshalb **eine** Figur in **einem**
Stil, und die Bewegung ist Daten: ein paar Kilobyte Gelenkwinkel je Übung statt
Megabyte Video, auf dem Telefon in jeder Größe scharf, im Hell- und Dunkelmodus
gleich lesbar.

**Zwei Stufen: Rezept und Bewegung** (`animation/format.py`). Das *Rezept*
schreibt, wer eine Übung beschreibt — die kuratierte Bibliothek oder die KI:
ungefähre Winkel, dazu was aufliegt (`boden`), was vom vorigen Bild stehen
bleibt (`halten`), wo ein Gelenk hin soll (`ziele`) und was der Löser dafür
verändern darf (`frei`). Die *Bewegung* liest die App: nur fertige Posen,
Kamera, betonte Muskeln, Requisiten. Die App rechnet nichts außer
Vorwärtskinematik und Überblenden — ein Löser in Swift wäre die zweite Stelle,
an der dieselbe Physik stimmen muss.

**Die Genauigkeit kommt vom Löser, nicht vom Autor** (`animation/loeser.py`).
Gelenkwinkel so zu wählen, dass eine Ferse auf den Zentimeter aufliegt, schafft
weder ein Mensch am Texteditor noch ein Sprachmodell. Der Löser
(Levenberg-Marquardt, numerische Jacobi-Matrix) rückt die `frei`-Werte zurecht,
bis die Kontakte stimmen, hält dabei die Gelenkgrenzen ein, bestraft jedes
Segment unter dem Boden und bleibt so nah wie möglich an den angegebenen
Winkeln. Zwischen zwei Schlüsselbildern legt er zwei **gelöste** Zwischenbilder
(`ZWISCHENBILDER`): Beim bloßen Überblenden der Winkel rutschte ein stehender
Fuß bis zu 9 cm über den Boden, mit ihnen bleibt er unter 3 cm.

**Das Körpermodell steht zweimal: in Python und in Swift.**
`animation/koerper.py` ist die Quelle, `ios/TriCoach/Animation/Figur.swift`
rechnet dieselbe Vorwärtskinematik nach. Beide prüfen gegen
`backend/tests/fixtures/animation_fk_referenz.json` (Python in
`test_animation.py`, die App im DEBUG-Build beim Start). Wer an Maßen,
Gelenkreihenfolge oder Achsen dreht, erzeugt die Referenz neu **und** zieht
Swift nach — sonst sieht die App eine andere Figur als die, für die der Löser
gerechnet hat, und die Hände schweben über dem Boden.

**Kugelgelenke sind Schwenkvektoren, keine Euler-Winkel** (`koerper._gelenk`).
Schulter und Hüfte drehen um eine Achse aus Beugen und Abspreizen
(Rodrigues), danach um die Längsachse. Die erste Fassung schachtelte drei
Drehungen hintereinander — bei 90° Beugung wirkte das Abspreizen dann um
dieselbe Achse wie das Drehen, und ein Schmetterlingssitz ließ sich schlicht
nicht ausdrücken (Gimbal Lock). Die Kehrseite steht als Faustregel im Prompt:
Beugen und Abspreizen **addieren sich** zur Anhebung.

**Die Bibliothek wird vorab gelöst, nicht beim Start**
(`animation/bibliothek/rezepte.json` → `bibliothek.json`,
`scripts/animationen_loesen.py`). Alle Rezepte zu lösen dauert in reinem
Python eine halbe Minute, auf dem Raspberry Pi ein Vielfaches — bei jedem
Neustart des Add-ons. Beim Start spielt `bibliothek.einspielen()` nur noch ein,
was neu ist oder eine andere `fassung` (Prüfsumme) hat. Wer ein Rezept ändert
und das Skript vergisst, fällt in `test_bibliothek_passt_zu_den_rezepten` auf.

**Der Schlüssel ist der englische Übungsname** (`animation/schluessel.py`,
`animation/einheit.py`). Der Prompt verlangt ohnehin hinter jeder deutschen
Bezeichnung den geläufigen englischen Namen in Klammern — „3x12 Beckenheben
(Glute Bridge)" —, und der ist über Pläne hinweg viel stabiler als der deutsche
(„Beckenheben", „Hüftbrücke", „Glute Bridge liegend"). Normalisiert wird auf
Kleinbuchstaben mit Bindestrichen, Apostrophe fallen weg („Child's Pose" →
`childs-pose`). Aliase fangen Varianten ab. Fehlt die Klammer, hilft der
Bauplan: Jeder Übungsschritt trägt `exercise_en`, und stehen gleich viele
Übungen im Text wie im Bauplan, gehören sie der Reihe nach zusammen. Garmins
Übungskatalog taugt dafür nicht — er ist zu grob („PLANK" für ein Dutzend
Varianten).

**Animationen gehören allen Konten** (`models.UebungsAnimation`). Ein Clamshell
sieht für jeden gleich aus, und was ein Konto hat erzeugen lassen, kostet das
nächste kein Kontingent. Freigeben und Verwerfen gilt deshalb ebenfalls für
alle — die Konten eines Add-ons sind ein Haushalt (siehe „Anmeldung ohne
Passwort" in [backend.md](backend.md)).

**Fehlt eine, erzeugt sie die KI — von selbst** (`animation/erzeugung.py`,
`ki/runner._animation_lauf`, Jobart `animation`). Der dritte Zweig der
Weckschleife prüft minütlich, ob der aktive Plan eines Kontos eine Übung ohne
Animation enthält, und startet dann einen Lauf: bis zu sechs Übungen je Lauf,
mit `effort high` statt der `max` der Planung. Frühestens alle **6 Stunden** je
Konto, nach einem gescheiterten Lauf erst nach **24** — eine Übung, die der
Löser nie annimmt, soll nicht viermal am Tag Kontingent kosten. Derselbe Lauf
lässt sich in der App anstoßen (`POST /api/ki/animationen`); ohne Lücke gibt es
dort eine 409 statt eines Laufs, der nichts zu tun hat. Gebraucht wird ein
Claude-Zugang wie für alles andere, aber **keiner** der Automatik-Schalter: Die
Animationen hängen an keinem Wochentag, und ohne sie fehlt der Einheit etwas.

**KI-Animationen stehen erst auf „ungeprüft"** (`zustand`). Die Antwort geht
durch dasselbe Format und denselben Löser wie die Bibliothek; was danach mehr
als **6 cm** im Boden steckt, wird gar nicht erst gespeichert (die Bibliothek
bleibt überall unter 3 cm). Alles andere erscheint in der App mit dem Hinweis
„ungeprüft" und zwei Knöpfen. *Freigeben* setzt sie auf „freigegeben".
*Verwerfen* nimmt eine Rückmeldung an („das Becken muss höher") — die geht
**wörtlich** in den Auftrag des nächsten Versuchs ein, und bis dahin zeigt die
App die Übung ohne Animation. Auch eine Bibliotheksanimation lässt sich
verwerfen; dann ersetzt sie die KI, und erst eine geänderte Bibliotheksfassung
holt die kuratierte zurück.

**Die Faustregeln im Prompt sind bezahlte Lektionen** (`animation/ki.py`,
„Worauf es ankommt"). Jede steht dort, weil die Bibliothek genau an dieser
Stelle einmal falsch war — siehe unten. Drei Beispiele aus der Bibliothek
(Glute Bridge, Bird Dog, Standing Quad Stretch) stehen als kompaktes JSON im
Prompt; zusammen gut 12.000 Zeichen.

**Die API** (`routers/animationen.py`):

- `GET /api/animationen/einheit/{plan_session_id}` — die Übungen einer
  Planeinheit in Reihenfolge, jede mit ihrer Animation samt Bewegung (eine
  Anfrage statt einer je Übung: hinter dem Ingress kostet jede spürbar Zeit),
  dazu `fehlend` und der jüngste Animationslauf des Kontos.
- `GET /api/animationen/{schluessel}` — eine Animation, auch über Name oder
  Alias; `GET /api/animationen?zustand=ungeprueft` — die Übersicht.
- `POST /api/animationen/{schluessel}/freigeben` und `…/verwerfen`
  (`{"rueckmeldung": "…"}`).
- `POST /api/ki/animationen` — Lauf anstoßen (202 mit Job).

**Ein unbekannter API-Pfad ist ein 404, keine Startseite** (`main.serve_frontend`).
Die Auffangroute für das Frontend lieferte auch für `/api/…` die `index.html`
mit Status 200 — ein Browser merkt davon nichts, die iOS-App scheiterte am
JSON und konnte ein zu altes Add-on nicht von einem Fehler unterscheiden. Für
Add-ons vor 4.6.0 wertet die App HTML auf einem API-Pfad selbst als 404.

**Was beim Schreiben der Bibliothek schiefging** — und wie es jetzt ist:

- *Füße im Boden.* Die Gelenkpunkte sind Mitten, keine Sohlen: Die
  Grundhaltung steht deshalb auf `y = 0,973`, und Ferse und Zehen liegen
  4,5 cm unter dem Knöchel.
- *Hände unter dem Boden im Stütz.* Ohne Handgelenk stach der Unterarm samt
  Fingern senkrecht in die Matte. Seitdem gibt es `handgelenk`; flach
  aufgesetzt ist ~85 mit `hand_*` **und** `finger_*` als Kontakt (Regel 3).
- *Ein Sitz mit 45° Hüfte.* Autoren denken den Oberschenkel „halb hoch";
  waagrecht im Sitz sind es ~90 (Regel 1). Zusammen mit dem Schwenkvektor
  (Regel 2) war das der Grund, warum der Schmetterlingssitz dreimal neu
  geschrieben wurde.
- *Nach vorn lehnen kippt die Beine mit.* `nicken` dreht den ganzen Körper um
  das Becken; im Sitz lehnt man über `rumpf_beugen` (Regel 4) — und gibt
  `nicken` dann gar nicht erst frei.
- *Ein steifer Rücken.* Mit einem Wirbelsegment sah Cat-Cow aus wie ein
  kippendes Brett. Die Wirbelsäule hat zwei Hälften, jede nimmt die halbe
  Beugung.
- *Ein vergessener Zwischenstand.* Ein zweites Schlüsselbild, das von
  ungelösten Winkeln ausging, zog die erste Lösung wieder heraus. Mit
  `aus_vorherigem` baut es auf der gelösten Pose auf und nennt nur, was sich
  ändert.
- *Rutschende Füße im Übergang* — siehe oben, die Zwischenbilder.
- *Zehen im Boden beim einbeinigen Kreuzheben und im Schmetterling.* Ein Fuß,
  der nur leicht aufsetzt, braucht trotzdem einen Kontakt, sonst streckt der
  Löser ihn in die Matte.

**Grenzen.** Der Fuß kennt nur Heben und Senken, kein Einwärtskanten — im
Schmetterling liegen die Sohlen deshalb nicht ganz aneinander. Hanteln, Bänder
und Bälle gibt es nicht; Requisiten sind Kasten und Wand. Die Taube, der
Schmetterling und die sitzende Oberschenkeldehnung verfehlen einen Kontakt um
3–7 cm, was man in der Animation nicht sieht. Eine Übung ohne englischen Namen
und ohne Bauplan findet keine Animation und löst auch keine Erzeugung aus.
