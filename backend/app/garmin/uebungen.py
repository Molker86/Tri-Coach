"""Übungen des Plans auf Garmins Übungskatalog abbilden.

Warum das nötig ist: Auf der Uhr zeigt Garmin zu einem Workout-Schritt eine
Bewegungsanimation — aber nur, wenn der Schritt eine Übung *benennt*. Dafür
trägt er zwei Felder, `category` (Bewegungsgruppe) und `exerciseName` (die
genaue Variante), beide aus Garmins eigenem Katalog. Ein Schritt mit bloßem
Beschreibungstext bleibt eine Textzeile: Der Athlet liest „Seitstütz 3x40 s“
und muss selbst wissen, wie das aussieht.

Der Katalog kommt aus Garmins eigenen JSON-Dateien, die `katalog.py` täglich
holt — und zwar in **zwei** Ausführungen: eine für Kraft (47 Kategorien), eine
für Mobility (15, darunter `POSE` und `MOVE` mit den Yogaposen und Dehnungen,
die der Kraftkatalog nicht führt). Gesucht wird im Katalog der jeweiligen
Sportart und nicht in beiden: Garmin lässt eine Yogapose nicht in ein
Krafttraining und lehnt eine dort unbekannte Kategorie mit 400 ab, und zwar das
ganze Workout. Eigene Zahlen kämen aus demselben Grund nicht in Frage.

Das Problem in der Mitte: Der Katalog ist englisch („Side Plank“), die KI
schreibt deutsche Pläne („Seitstütz“), und beide stehen in einer Zeile voller
Beiwerk („3x40 s Seitstütz je Seite, langsam absenken“). Deshalb zwei Schritte:
Der Text wird zu einer Folge von Wortstämmen normalisiert, und darin wird das
*längste* zusammenhängende Stück gesucht, das im Verzeichnis steht. Im
Verzeichnis stehen die Katalognamen und die deutschen Entsprechungen aus
`SYNONYME` nebeneinander — eine Übersetzung ist damit nichts anderes als ein
zweiter Schlüssel auf denselben Eintrag.

**Geraten wird nicht.** Wer nichts findet, gibt `None` zurück, und der Aufrufer
baut den Schritt wie bisher aus dem Beschreibungstext. Eine falsch zugeordnete
Übung wäre schlimmer als keine: Auf der Uhr liefe dann eine Animation, die eine
andere Bewegung zeigt als die, die im Plan steht — und die wird ungeprüft
nachgemacht.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from . import katalog

# --------------------------------------------------------------------------
# Normalisierung
# --------------------------------------------------------------------------

# Umlaute fallen auf ihren Grundbuchstaben, „ß“ auf „ss“ — die Schreibweise,
# die auch herauskommt, wenn jemand ohne ß-Taste tippt („Gesaessdehnung“ bleibt
# damit zwar außen vor, „Gesässdehnung“ und „Gesäßdehnung“ treffen sich aber).
# Beide Seiten laufen durch dieselbe Funktion; die Abbildung muss deshalb nur
# in sich stimmig sein, nicht sprachlich richtig.
_UMLAUTE = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss", "é": "e", "è": "e"})

# Alles, was kein Buchstabe und keine Ziffer ist, trennt zwei Wörter. Ziffern
# bleiben stehen: „90/90 Stretch“ ist ein Katalogname.
_WORT = re.compile(r"[a-z0-9]+")

# Füllwörter, die in Plänen ständig auftauchen. Sie fallen heraus, damit sie
# ein zusammenhängendes Stück nicht zerreißen: „Seitstütz je Seite langsam“
# soll „seitstutz“ hergeben.
#
# Das englische „side“ steht bewusst *nicht* hier: Es kommt in 103
# Katalognamen vor („Side Plank“, „Side-lying Leg Raise“), und es zu streichen
# machte die halbe Rumpfabteilung ununterscheidbar. „je Seite“ fängt die
# deutsche Wendung ohnehin ab. „with“, „and“, „in“ und „the“ stehen zwar
# ebenfalls in Katalognamen, sind dort aber Bindewörter — sie fallen auf beiden
# Seiten weg und stiften deshalb keinen Schaden.
_FUELLWOERTER = frozenset({
    "je", "jede", "jeder", "jeweils", "pro", "seite", "seiten", "links",
    "rechts", "beidseitig", "langsam", "zugig", "kontrolliert", "sauber",
    "mit", "und", "oder", "bis", "zum", "zur", "im", "in", "am", "auf",
    "der", "die", "das", "den", "dem", "ein", "eine", "einer", "einem",
    "each", "per", "slow", "with", "and", "the", "a", "an",
})


def _stamm(wort: str) -> str:
    """Grobe Einzahl. Muss nicht sprachlich richtig sein, nur eindeutig.

    Beide Seiten der Zuordnung laufen hier durch, entscheidend ist deshalb
    allein, dass „Jumping Jacks“ und „Jumping Jack“ auf demselben Ergebnis
    landen — ob das Ergebnis ein Wort der englischen Sprache ist, spielt keine
    Rolle („press“ wird zu „pre“, und das stört niemanden).
    """
    if len(wort) > 4 and wort.endswith("es") and wort[-3] in "sxzh":
        wort = wort[:-2]  # crunches -> crunch, stretches -> stretch
    while len(wort) > 3 and wort.endswith("s"):
        wort = wort[:-1]  # raises -> raise, jacks -> jack
    return wort


def _woerter(text: str) -> tuple[str, ...]:
    """Die bedeutungstragenden Wörter einer Zeile, ungekürzt."""
    kleingeschrieben = text.lower().translate(_UMLAUTE)
    return tuple(
        wort for wort in _WORT.findall(kleingeschrieben) if wort not in _FUELLWOERTER
    )


def _schluessel(woerter: tuple[str, ...]) -> str:
    """Wortfolge -> Suchschlüssel: erst verkleben, dann kürzen.

    Die Reihenfolge ist der Punkt. Wer zuerst kürzt, zerlegt Komposita an
    ihrer Fuge: „Quadrizeps-Dehnung“ verlöre das Fugen-s und fände
    „quadrizepsdehnung“ im Wörterbuch nicht mehr. Verklebt steht das s noch da,
    und gekürzt wird nur noch am Ende des ganzen Worts, wo die Mehrzahl sitzt.
    """
    return _stamm("".join(woerter))


# --------------------------------------------------------------------------
# Deutsche Entsprechungen
# --------------------------------------------------------------------------

# Deutscher Begriff -> Anzeigename im Katalog. Die rechte Seite muss dort
# wörtlich so stehen; ein Tippfehler fällt beim Aufbau des Verzeichnisses
# stillschweigend heraus, weshalb `test_garmin_uebungen.py` jeden Eintrag
# nachschlägt. Aufgenommen ist, was in Kraft- und Mobilityplänen für
# Ausdauersportler wirklich vorkommt — nicht der halbe Katalog.
SYNONYME: dict[str, str] = {
    # Rumpf
    "unterarmstutz": "Plank",
    "unterarmstutze": "Plank",
    "planke": "Plank",
    "bretthaltung": "Plank",
    # Garmin führt den Unterarmstütz schlicht als „Plank“; „Front Plank“ und
    # „Forearm Plank“ sind die geläufigen englischen Namen dafür und kommen
    # deshalb aus der Klammer des Plans.
    "front plank": "Plank",
    "forearm plank": "Plank",
    "seitstutz": "Side Plank",
    "seitlicher unterarmstutz": "Side Plank",
    "seitliche planke": "Side Plank",
    "unterarmstutz seitlich": "Side Plank",
    "knieplanke": "Kneeling Plank",
    "bergsteiger": "Mountain Climber",
    "kletterer": "Mountain Climber",
    "barengang": "Bear Crawl",
    "russischer twist": "Russian Twist",
    "russian twist": "Russian Twist",
    "rumpfheben": "Hyperextension",
    "ruckenstrecker": "Hyperextension",
    "kafer": "Dead Bug",
    "toter kafer": "Dead Bug",
    "deadbug": "Dead Bug",
    "beinheben": "Leg Raise",
    "beinheben seitlich": "Side-lying Leg Raise",
    "seitliches beinheben": "Side-lying Leg Raise",
    "crunches": "Crunch",
    "bauchpresse": "Crunch",
    "fahrradfahren im liegen": "Bicycle Crunch",
    "radfahrer": "Bicycle Crunch",
    "situps": "Sit-up",
    "aufsetzer": "Sit-up",
    "hohlkreuzschaukel": "Hollow Rock",
    "vierfusslerstand": "Quadruped with Leg Lift",
    "vierfussler": "Quadruped with Leg Lift",
    "vierfusslerstand diagonal": "Quadruped with Leg Lift",
    # „Bird Dog“ führt Garmin nicht unter diesem Namen, gemeint ist dieselbe
    # Bewegung — und in deutschen Plänen steht fast immer das englische Wort.
    "bird dog": "Quadruped with Leg Lift",
    "diagonalheben": "Opposite Arm and Leg Balance",
    "raupe": "Inchworm",
    "superman": "Superman from Floor",
    "schwimmer": "Superman from Floor",
    # Beine und Hüfte
    "kniebeuge": "Squat",
    "kniebeugen": "Squat",
    "hocke": "Squat",
    "wandsitz": "Body-weight Wall Squat",
    "wall sit": "Body-weight Wall Squat",
    "ausfallschritt": "Lunge",
    "ausfallschritte": "Lunge",
    "schrittstellung": "Lunge",
    "gehende ausfallschritte": "Walking Lunge",
    "ausfallschritt gehend": "Walking Lunge",
    # Einen nackten „Reverse Lunge“ führt der Katalog nicht — alle Einträge
    # tragen Hantel, Kasten oder Zusatzbewegung. „Core Control Rear Lunge“ ist
    # der einzige Rückwärtsausfallschritt ohne Gerät, und die Richtung ist der
    # Unterschied, auf den es hier ankommt: Vorwärts wäre eine andere Bewegung.
    "ruckwartiger ausfallschritt": "Core Control Rear Lunge",
    "ausfallschritt ruckwarts": "Core Control Rear Lunge",
    "ruckwartsausfallschritt": "Core Control Rear Lunge",
    "reverse lunge": "Core Control Rear Lunge",
    "rear lunge": "Core Control Rear Lunge",
    "seitlicher ausfallschritt": "Side Lunge",
    "seitliche ausfallschritte": "Side Lunge",
    "ausfallschritt seitlich": "Side Lunge",
    "hufthebung": "Hip Raise",
    "huftbrucke": "Hip Raise",
    "beckenheben": "Hip Raise",
    "glute bridge": "Hip Raise",
    "brucke": "Hip Raise",
    "einbeinige huftbrucke": "Single-leg Hip Raise",
    "einbeiniges beckenheben": "Single-leg Hip Raise",
    "einbeinige glute bridge": "Single-leg Hip Raise",
    "single leg glute bridge": "Single-leg Hip Raise",
    "muschel": "Clam Bridge",
    "muschelubung": "Clam Bridge",
    "clamshell": "Clam Bridge",
    "kreuzheben": "Deadlift",
    "rumanisches kreuzheben": "Romanian Deadlift",
    "gestrecktes kreuzheben": "Romanian Deadlift",
    # Einbeinig führt der Katalog nur mit Hantel oder Schlingen. Dieselbe
    # Hüftbeuge auf zwei Beinen ist die nächstliegende Animation — und der
    # Plan schreibt dieselbe Übung mal mit, mal ohne „rumänisch“.
    "einbeiniges kreuzheben": "Romanian Deadlift",
    "single leg deadlift": "Romanian Deadlift",
    "wadenheben": "Calf Raise",
    "wadenheber": "Calf Raise",
    # Einbeinig ist eine andere Übung als beidbeinig — ohne eigenen Eintrag
    # zeigte die Uhr das zweibeinige Wadenheben. „Standing“ ist Garmins
    # Vorgabevariante; die gebeugte („Bent-knee“) steht so nie im Plan.
    "einbeiniges wadenheben": "Single-leg Standing Calf Raise",
    "wadenheben einbeinig": "Single-leg Standing Calf Raise",
    "single leg calf raise": "Single-leg Standing Calf Raise",
    "stufensteigen": "Step-up",
    "aufstieg": "Step-up",
    "beinbeuger": "Leg Curl",
    "beinstrecker": "Leg Extensions",
    "guten morgen": "Good Morning",
    "kettlebell schwung": "Kettlebell Swing",
    "huftschwung": "Hip Swing",
    "monster walk": "Banded Lateral Band Walks",
    "monster walks": "Banded Lateral Band Walks",
    "seitliche bandgange": "Banded Lateral Band Walks",
    "lateral band walk": "Banded Lateral Band Walks",
    "seitschritte mit band": "Banded Lateral Band Walks",
    "seitschritte mit miniband": "Banded Lateral Band Walks",
    # „Hüftkreisen im Vierfüßler“ ist der Fire Hydrant und nicht das Hüftkreisen
    # im Stand, das „huftkreisen“ allein trifft.
    "fire hydrant": "Fire Hydrant Kicks",
    "huftkreisen im vierfussler": "Fire Hydrant Kicks",
    "sprungkniebeuge": "Jump Squat",
    "gobletkniebeuge": "Goblet Squat",
    "goblet kniebeuge": "Goblet Squat",
    "kastensprung": "Box Jump",
    "seilspringen": "Jump Rope",
    "hampelmann": "Jumping Jacks",
    # Oberkörper
    "liegestutz": "Push-up",
    "liegestutze": "Push-up",
    "klimmzug": "Pull-up",
    "klimmzuge": "Pull-up",
    "rudern": "Row",
    "ruderzug": "Row",
    "gesichtszug": "Face Pull",
    "bankdrucken": "Bench Press",
    "schulterdrucken": "Shoulder Press",
    "uberkopfdrucken": "Shoulder Press",
    "seitheben": "Lateral Raise",
    "frontheben": "Front Raise",
    "bizepscurl": "Curl",
    "armbeuger": "Curl",
    "trizepsstrecken": "Triceps Extension",
    "trizepsdrucken": "Triceps Extension",
    "schulterheben": "Shrug",
    "schulterblattzug": "Scapular Retraction",
    "pike liegestutz": "Pike Push-up",
    "hangendes knieheben": "Hanging Knee Raise",
    "koffertragen": "Farmer's Carry",
    "farmers walk": "Farmer's Carry",
    # Mobilität und Dehnung
    "dehnung waden": "Calf Stretch",
    "wadendehnung": "Calf Stretch",
    "quadrizepsdehnung": "Quad Stretch",
    "oberschenkeldehnung": "Quad Stretch",
    "huftbeugerdehnung": "Lunging Hip Flexor Stretch",
    "huftbeuger ausfallschritt": "Lunging Hip Flexor Stretch",
    "huftbeugerdehnung im ausfallschritt": "Lunging Hip Flexor Stretch",
    # Den bloßen Namen führt der Katalog nicht — er kennt die Dehnung nur im
    # Ausfallschritt und die Kombination mit dem Quadrizeps. Gemeint ist beide
    # Male dieselbe Bewegung, und der Plan schreibt sie so, wie sie hier steht:
    # aus einem echten Block, wo „Hip Flexor Stretch" in der Klammer stand und
    # deshalb ohne Animation blieb. Zugeordnet wird dieselbe Übung wie beim
    # deutschen Namen darüber — zwei Schreibweisen desselben Begriffs dürfen
    # nicht auf zwei Animationen zeigen.
    "hip flexor stretch": "Lunging Hip Flexor Stretch",
    "hueftbeugerdehnung": "Lunging Hip Flexor Stretch",
    "hamstringdehnung": "Hamstring Stretch",
    "beinruckseitendehnung": "Hamstring Stretch",
    "dehnung ruckseite oberschenkel": "Hamstring Stretch",
    "glutealdehnung": "Glutes Stretch",
    "gesassdehnung": "Glutes Stretch",
    "piriformisdehnung": "Piriformis Stretch",
    "piriformisdehnung im liegen": "Lying Piriformis Stretch",
    # Die Vierer- oder Figur-4-Dehnung *ist* die Piriformisdehnung — Knöchel
    # über dem Knie, das „4“ zeichnet das gebeugte Bein. Ohne diese Zeilen
    # blieb sie ohne Kennung, und auf der Uhr stand ein Schritt ohne Titel:
    # Garmin zeigt dort „--“, weil die Überschrift *nur* aus dem Katalog
    # kommt. Nennt der Plan die Lage („im Liegen“), gewinnt der längere
    # Schlüssel den eigenen Katalogeintrag; ohne Angabe bleibt es beim
    # allgemeinen.
    "figur 4 dehnung": "Piriformis Stretch",
    "figur 4 dehnung im liegen": "Lying Piriformis Stretch",
    "figure 4 stretch": "Piriformis Stretch",
    "figure four stretch": "Piriformis Stretch",
    "vierer dehnung": "Piriformis Stretch",
    "vierer dehnung im liegen": "Lying Piriformis Stretch",
    "tractusdehnung": "Standing IT Band Stretch",
    "tractus": "Standing IT Band Stretch",
    "it band": "Standing IT Band Stretch",
    # „Supine" ist die Rückenlage, die der Katalog „Lying" nennt. Ohne den
    # Eintrag blieb „Supine Spinal Twist" aus einem echten Mobility-Block ohne
    # Animation, während „Lying Spinal Twist" trifft.
    "supine spinal twist": "Lying Spinal Twist Stretch",
    "wirbelsaulendrehung im liegen": "Lying Spinal Twist Stretch",
    "liegende wirbelsaulendrehung": "Lying Spinal Twist Stretch",
    "schmetterling": "Butterfly Stretch",
    "schmetterlingsdehnung": "Butterfly Stretch",
    "huftoffner": "90/90 Stretch",
    "hufrotation": "90/90 Stretch",
    "huftrotation": "90/90 Stretch",
    "brustwirbelrotation": "Thoracic Rotation",
    "thoraxrotation": "Thoracic Rotation",
    "brustwirbelsaulenrotation": "Thoracic Rotation",
    "bws rotation": "Thoracic Rotation",
    "bwsrotation": "Thoracic Rotation",
    "rumpfrotation": "Thoracic Rotation",
    "katze kuh": "Cat Cow Stretch",
    "katzenbuckel": "Cat Camel",
    "kindshaltung": "Child's Pose Stretch",
    "kindeshaltung": "Child's Pose Stretch",
    "kindhaltung": "Child's Pose Stretch",
    "stellung des kindes": "Child's Pose Stretch",
    "kobra": "Cobra Stretch",
    "taube": "Pigeon Pose Stretch",
    "taubenhaltung": "Pigeon Pose Stretch",
    "skorpion": "Scorpion Stretch",
    "leistendehnung": "Groiners",
    "brustdehnung": "Pectoral Stretch",
    "brustoffner": "Pectoral Stretch",
    "brustoffnung": "Pectoral Stretch",
    # An der Wand hat Garmin einen eigenen Eintrag; drei Wörter schlagen das
    # einzelne „brustoffner“, wenn der Plan die Wand nennt. Im Türrahmen ist
    # dieselbe Bewegung gemeint — Garmin führt nur die Wandvariante.
    "brustoffner an der wand": "Wall Chest and Shoulder Stretch",
    "brustoffnung an der wand": "Wall Chest and Shoulder Stretch",
    "wall chest stretch": "Wall Chest and Shoulder Stretch",
    "brustoffnung im turrahmen": "Wall Chest and Shoulder Stretch",
    "doorway chest stretch": "Wall Chest and Shoulder Stretch",
    "hamstringdehnung im stand": "Standing Hamstring Stretch",
    "knie zur brust": "Lying Knee-to-Chest Stretch",
    "wirbelsaulendrehung im liegen": "Lying Spinal Twist Stretch",
    "liegende wirbelsaulendrehung": "Lying Spinal Twist Stretch",
    "latissimusdehnung": "Lat Stretch",
    "schulterdehnung": "Shoulder Stretch",
    "nackendehnung": "Neck Stretch",
    "trizepsdehnung": "Triceps Stretch",
    "seitneigung": "Side Stretch",
    "bauchdehnung": "Abs Stretch",
    "armkreisen": "Arm Circles",
    "schulterkreisen": "Shoulder Circles",
    "sprunggelenkkreisen": "Ankle Circles",
    "fussgelenkkreisen": "Ankle Circles",
    "huftkreisen": "Hip Circles",
    "kopfdrehen": "Neck Rotations",
    "beinschwingen": "Forward and Backward Leg Swings",
    "beinpendel": "Forward and Backward Leg Swings",
    "beinschwingen seitlich": "Side-to-Side Leg Swings",
    "kniehebelauf": "Walking High Knees",
    "knieheben gehend": "Walking High Knees",
    "knieumarmung": "Walking Knee Hugs",
    "vierfusslerschaukeln": "Quadruped Rocking",
    "ausfallschritt mit rotation": "Lunge with Spinal Twist Stretch",
}

# Katalognamen, die keine Bewegung benennen, sondern die Gruppe darüber. Ein
# Plan, in dem „Core-Stabilisation“ oder „Warm-up“ steht, meint keine bestimmte
# Übung — und eine Animation zu einer Gruppe gibt es nicht. Ohne diese Sperre
# schluckte das Verzeichnis solche Zeilen und der Schritt trüge eine Kennung,
# hinter der auf der Uhr nichts steht.
_ZU_ALLGEMEIN = frozenset({
    "Banded Exercises", "Battle Rope", "Bike Outdoor", "Cardio", "Chop",
    "Core", "Elliptical", "Floor Climb", "Hip Stability", "Indoor Bike",
    "Ladder", "Olympic Lift", "Plyo", "Run", "Run Indoor", "Sandbag",
    "Shoulder Stability", "Sled", "Sledge Hammer", "Stair Stepper",
    "Suspension", "Tire", "Total Body", "Warm-up",
})


# Zahlwörter und Einheiten. Sie stehen vor und hinter jeder Übung („3x15 …
# je Seite“, „… 2x45 s“) und sind deshalb *kein* Hinweis darauf, dass der
# Übungsname weitergeht — anders als ein unbekanntes Wort, siehe `_grundform_ok`.
_MENGENANGABE = frozenset({
    "s", "sek", "sec", "sekunde", "sekunden", "min", "minute", "minuten",
    "x", "mal", "wdh", "wiederholung", "wiederholungen", "satz", "satze",
    "runde", "runden", "schritt", "schritte", "atemzug", "atemzuge",
    "rep", "set", "round", "sec",
})


@dataclass(frozen=True)
class Uebung:
    """Ein Katalogeintrag, so wie ihn der Workout-Schritt trägt."""

    kategorie: str  # `category` — die Bewegungsgruppe
    name: str  # `exerciseName` — die genaue Variante
    anzeige: str  # Garmins Anzeigename, nur für Meldungen und Tests
    grundform: bool = False  # bloßer Name, der auch in längeren Namen steckt


def _ist_grundform(eintrag: dict[str, str]) -> bool:
    """Führt der Katalog diese Bewegung unter ihrem *bloßen* Namen?

    Zwei Merkmale, und beide zählen. Das eine ist die Grundübung ihrer eigenen
    Kategorie („Plank“ in PLANK, „Calf Raise“ in CALF_RAISE) — daran hing die
    Prüfung einmal allein. Das andere ist der einwortige Name, auch wenn er zu
    einer fremden Kategorie gehört: „Walk“ steht unter RUN, steckt aber in
    „Lateral Band Walk“, und ohne Sperre bekam eine Bandübung im Plan die
    Animation eines Spaziergangs. Zwanzig solcher Namen führt der Katalog
    („Jog“, „Sprint“, „Burpee“, „Step-up“, „Kicks“ …) — dieselbe Falle, nur
    ohne das erste Merkmal.
    """
    return eintrag["exercise"] == eintrag["category"] or len(eintrag["name"].split()) == 1


@lru_cache(maxsize=len(katalog.QUELLEN))
def _verzeichnis(welcher: str) -> dict[str, Uebung]:
    """Wortfolge -> Übung, aus Katalognamen und deutschen Entsprechungen.

    Der Schlüssel ist die **verklebte** Wortfolge ohne Trennzeichen. Denn im
    Deutschen ist die Wortgrenze eine Frage des Geschmacks: Der Plan schreibt
    „Hüftbeuger-Dehnung“, das Wörterbuch „huftbeugerdehnung“, und getrennt
    verglichen fänden die beiden nie zueinander. Verklebt schon.

    Kurze Namen kommen zuerst, damit sie einen Schlüssel behalten, den ein
    längerer Name durch die Normalisierung mitbesetzt: „Push-up“ und
    „Push-ups“ fallen beide auf „pushup“, gemeint ist die Grundübung.

    Je Katalog ein Verzeichnis: `welcher` ist „kraft“ oder „mobility“.
    """
    eintraege = katalog.eintraege(welcher)
    nach_namen = {e["name"]: e for e in eintraege}
    verzeichnis: dict[str, Uebung] = {}

    def merke(woerter: tuple[str, ...], eintrag: dict[str, str]) -> None:
        if woerter:
            verzeichnis.setdefault(
                _schluessel(woerter),
                Uebung(
                    eintrag["category"],
                    eintrag["exercise"],
                    eintrag["name"],
                    grundform=_ist_grundform(eintrag),
                ),
            )

    for eintrag in sorted(eintraege, key=lambda e: (len(e["name"]), e["name"])):
        if eintrag["name"] not in _ZU_ALLGEMEIN:
            merke(_woerter(eintrag["name"]), eintrag)

    for deutsch, anzeige in SYNONYME.items():
        eintrag = nach_namen.get(anzeige)
        if eintrag is None:
            # Der Katalog kann sich mit der Bibliothek ändern. Eine tote
            # Entsprechung darf den Start nicht verhindern — sie fällt heraus,
            # und der Test schlägt an.
            continue
        merke(_woerter(deutsch), eintrag)

    # Zuletzt die Dehnungsnamen ohne ihr angehängtes „Stretch“. Der Katalog
    # hängt es an fast jede Dehnung („Child's Pose Stretch“, „Pigeon Pose
    # Stretch“), die geläufige Bezeichnung kommt aber ohne aus — und genau die
    # schreibt die KI in die Klammer, weil Punkt 3 des Prompts nach dem
    # *geläufigen* englischen Namen fragt. Verlangt werden zwei verbleibende
    # Wörter: „Hamstring Stretch“ fiele sonst auf „hamstring“ zusammen und
    # zöge jede Zeile an sich, in der das Wort vorkommt.
    #
    # Zuletzt, weil `merke()` den ersten Eintrag behält: „Side Lunge Stretch“
    # ergibt gekürzt „side lunge“, und das ist bereits eine eigene Übung.
    for eintrag in eintraege:
        woerter = _woerter(eintrag["name"])
        if len(woerter) >= 3 and woerter[-1] == "stretch":
            merke(woerter[:-1], eintrag)

    # Und das Spiegelbild davon für die Yogaposen: Der Katalog führt sie unter
    # dem bloßen Namen („Lizard“, „Triangle“, „Chair“), der Plan schreibt sie
    # mit ihrer Gattung („Lizard Pose“). Ohne diesen zweiten Schlüssel fiele
    # genau die geläufige Schreibweise durch — und ein bloßes „Lizard“ wäre
    # obendrein eine Grundform, die `_grundform_ok` in einer Zeile mit Beiwerk
    # zurückweist.
    for eintrag in eintraege:
        woerter = _woerter(eintrag["name"])
        if eintrag["category"] == "POSE" and woerter and woerter[-1] != "pose":
            merke(woerter + ("pose",), eintrag)

    return verzeichnis


@lru_cache(maxsize=len(katalog.QUELLEN))
def _laengster_schluessel(welcher: str) -> int:
    """Aus wie vielen Wörtern der längste Eintrag besteht.

    Begrenzt die Fenstergröße der Suche. Die deutschen Entsprechungen zählen
    mit — sie können länger sein als jeder Katalogname.
    """
    namen = [e["name"] for e in katalog.eintraege(welcher)] + list(SYNONYME)
    # Ein Wort mehr, weil der POSE-Alias oben eines anhängt: „Downward Facing
    # Dog“ steht zusätzlich als „Downward Facing Dog Pose“ im Verzeichnis, und
    # ein zu enges Fenster fände genau diesen Schlüssel nie.
    return max((len(_woerter(name)) for name in namen), default=1) + 1


def _grundform_ok(woerter: tuple[str, ...], beginn: int, ende: int) -> bool:
    """Steht die Grundübung für sich allein — oder qualifiziert sie jemand?

    Der Katalog führt 47 Bewegungen unter ihrem bloßen Namen („Plank“,
    „Squat“, „Row“). Genau die stecken aber auch in Namen, die er *nicht*
    führt: „Copenhagen Plank“ ist eine Adduktorenübung und kein Unterarmstütz,
    „Squat Jumps“ sind keine Kniebeugen. Steht direkt davor oder dahinter ein
    Wort, das keine Mengenangabe ist, gehört es mit einiger Wahrscheinlichkeit
    zum Übungsnamen — und dann ist die Grundform die falsche Antwort. Lieber
    keine Animation als die einer anderen Bewegung.
    """
    davor = woerter[beginn - 1] if beginn > 0 else None
    danach = woerter[ende] if ende < len(woerter) else None
    return all(
        nachbar is None or nachbar in _MENGENANGABE or any(z.isdigit() for z in nachbar)
        for nachbar in (davor, danach)
    )


def _suche(woerter: tuple[str, ...], welcher: str) -> tuple[int, Uebung] | None:
    """Der längste Treffer in einer Wortfolge, mit seiner Länge.

    Gesucht wird das längste zusammenhängende Wortstück, das im Verzeichnis
    steht — „3x40 s Seitstütz je Seite“ ergibt „Side Plank“ und nicht „Plank“,
    weil zwei Wörter mehr wiegen als eins.
    """
    if not woerter:
        return None

    verzeichnis = _verzeichnis(welcher)
    for laenge in range(min(len(woerter), _laengster_schluessel(welcher)), 0, -1):
        for beginn in range(len(woerter) - laenge + 1):
            ende = beginn + laenge
            treffer = verzeichnis.get(_schluessel(woerter[beginn:ende]))
            if treffer is None:
                continue
            if treffer.grundform and not _grundform_ok(woerter, beginn, ende):
                # Weitersuchen statt zurückgeben: Vielleicht steht an anderer
                # Stelle der Zeile eine Übung, die für sich steht.
                continue
            return laenge, treffer
    return None


# Die Klammer trennt zwei Benennungen derselben Übung, keine zwei Wörter eines
# Namens.
_KLAMMER = re.compile(r"[()\[\]]")

# Faszienrollen und Massagebälle. Garmins Katalog kennt sie nicht als Bewegung
# — die einzigen Treffer mit „Foam Roller“ sind Übungen *auf* der Rolle
# („Foam Roller Reverse Crunch“). Ohne diese Sperre zog „Faszienrolle
# lateraler Oberschenkel (Foam Roll IT Band)“ die „Standing IT Band Stretch“ an
# sich, weil der Schlüssel „it band“ mitten im Text steht: Auf der Uhr lief die
# Animation einer Dehnung im Stand, während der Plan Ausrollen im Liegen meint.
# Zwei verschiedene Übungen, und die falsche wird ungeprüft nachgemacht.
_MIT_ROLLE = re.compile(
    r"faszienroll|faszienball|blackroll|black\s+roll|foam\s*roll"
    r"|massageroll|massageball|triggerpunktball",
    re.IGNORECASE,
)


def finde(text: str | None, welcher: str = "kraft") -> Uebung | None:
    """Die Übung aus einer Zeile des Aufbautexts, oder `None`.

    `welcher` wählt den Katalog — „kraft“ oder „mobility“. Er entscheidet mit,
    *was* gefunden werden darf: Eine Yogapose gehört nicht in ein Krafttraining,
    und Garmin lehnt eine dort unbekannte Kategorie mit 400 ab.

    Gesucht wird je Klammerabschnitt getrennt, und das ist nicht bloß Kosmetik:
    Punkt 3 des Prompts verlangt hinter der deutschen Bezeichnung den geläufigen
    englischen Namen in Klammern, und über die Klammergrenze hinweg gelesen
    stand der eine direkt neben dem anderen. Für `_grundform_ok` sah
    „Unterarmstütz (Front Plank)“ damit aus wie ein qualifizierter Unterarmstütz
    — der Zusatz, der die Trefferquote erhöhen sollte, verhinderte genau den
    Treffer. Getrennt gelesen steht „Unterarmstütz“ für sich, und der Plan
    bekommt seine Animation.

    Der längste Treffer über alle Abschnitte gewinnt; bei Gleichstand der erste,
    also die deutsche Bezeichnung vor der englischen Klammer. Steht nirgends
    etwas, ist das eine Antwort und kein Fehler: Der Schritt bleibt eine
    Textzeile.
    """
    if not text:
        return None

    bester: tuple[int, Uebung] | None = None
    for abschnitt in _KLAMMER.split(text):
        treffer = _suche(_woerter(abschnitt), welcher)
        if treffer is not None and (bester is None or treffer[0] > bester[0]):
            bester = treffer
    if bester is None:
        return None

    # Wer mit der Rolle arbeitet, dehnt nicht — es sei denn, der Katalogeintrag
    # nennt die Rolle selbst.
    if _MIT_ROLLE.search(text) and "foam roller" not in bester[1].anzeige.lower():
        return None
    return bester[1]


def leere_zwischenspeicher() -> None:
    """Beide Verzeichnisse neu aufbauen lassen.

    Gerufen von `katalog.py`, nachdem ein Download eine Datei ersetzt hat: Der
    Abgleich läuft im laufenden Prozess, und ohne das gälte der frische Katalog
    erst nach einem Neustart.
    """
    _verzeichnis.cache_clear()
    _laengster_schluessel.cache_clear()
