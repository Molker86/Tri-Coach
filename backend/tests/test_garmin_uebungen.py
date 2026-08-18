"""Übungen des Plans in Garmins Katalog wiederfinden.

Reine Rechnerei ohne Netz. Geprüft wird beides: dass Erkanntes richtig
zugeordnet wird — und dass Nicht-Erkanntes leer bleibt, statt auf irgendetwas
zu zeigen. Eine falsche Animation auf der Uhr zeigt eine andere Bewegung als
die geplante, und sie wird ungeprüft nachgemacht.
"""

import pytest
from garminconnect import exercises as katalog

from app.garmin import uebungen


def test_jede_deutsche_entsprechung_zeigt_auf_einen_katalogeintrag():
    """Die rechte Seite von `SYNONYME` muss wörtlich im Katalog stehen.

    Zur Laufzeit fällt ein toter Eintrag stillschweigend heraus, damit ein
    Bibliotheksupdate den Start nicht verhindert. Gemerkt werden muss es
    trotzdem — hier.
    """
    tot = {d: a for d, a in uebungen.SYNONYME.items() if katalog.resolve(a) is None}
    assert tot == {}


def test_deutsche_uebung_wird_zur_katalogkennung():
    treffer = uebungen.finde("3x12 Liegestütze")
    assert (treffer.kategorie, treffer.name) == ("PUSH_UP", "PUSH_UP")


def test_englischer_name_wird_direkt_erkannt():
    treffer = uebungen.finde("3x40 s Side Plank je Seite")
    assert (treffer.kategorie, treffer.name) == ("PLANK", "SIDE_PLANK")


def test_laengster_treffer_gewinnt():
    """„Seitstütz“ ist Side Plank und nicht Plank — zwei Wörter wiegen mehr."""
    assert uebungen.finde("Unterarmstütz 3x45 s").name == "PLANK"
    assert uebungen.finde("Seitstütz 3x45 s").name == "SIDE_PLANK"
    assert uebungen.finde("Side-lying Leg Raise 3x15").name == "SIDE_LYING_LEG_RAISE"
    assert uebungen.finde("Leg Raise 3x15").name == "LEG_RAISE"


@pytest.mark.parametrize(
    ("zeile", "erwartet"),
    [
        ("3x15 Monster Walks mit Band", "LATERAL_BAND_WALKS"),
        ("Hüftbeuger-Ausfallschritt 2x45 s je Seite", "STRETCH_LUNGING_HIP_FLEXOR"),
        ("Thoraxrotation 2x8 je Seite", "THORACIC_ROTATION"),
        ("90/90-Hüftrotation 2x8 je Seite", "STRETCH_90_90"),
        ("Katze-Kuh 10 Wiederholungen", "STRETCH_CAT_COW"),
        ("Kindshaltung 60 s", "STRETCH_CHILDS_POSE"),
        ("Taubenhaltung 2x45 s je Seite", "STRETCH_PIGEON_POSE"),
        ("4x10 Kniebeugen langsam", "SQUAT"),
        ("3x15 Hüftbrücke", "HIP_RAISE"),
        ("Bird Dog 3x10 je Seite", "QUADRUPED_WITH_LEG_LIFT"),
    ],
)
def test_gaengige_planzeilen(zeile, erwartet):
    treffer = uebungen.finde(zeile)
    assert treffer is not None, zeile
    assert treffer.name == erwartet


def test_mehrzahl_und_einzahl_landen_gleich():
    assert uebungen.finde("Jumping Jacks 3x30 s") == uebungen.finde("Jumping Jack")
    assert uebungen.finde("3x12 Liegestütz") == uebungen.finde("3x12 Liegestütze")


def test_je_seite_zerreisst_die_uebung_nicht():
    """„je Seite“ steht mitten im Namen und darf ihn nicht trennen."""
    assert uebungen.finde("Side Plank je Seite 3x30 s").name == "SIDE_PLANK"


@pytest.mark.parametrize(
    ("zeile", "erwartet"),
    [
        # Die KI schreibt Komposita mit Bindestrich, das Wörterbuch führt sie
        # zusammengeschrieben. Wer vor dem Verkleben kürzt, verliert das
        # Fugen-s und findet „quadrizepsdehnung“ nie wieder.
        ("Hüftbeuger-Dehnung 2x45 s je Seite", "STRETCH_LUNGING_HIP_FLEXOR"),
        ("Quadrizeps-Dehnung 2x30 s je Seite", "STRETCH_QUAD"),
        ("BWS-Rotation im Vierfüßler 2x8 je Seite", "THORACIC_ROTATION"),
        # „ß“ muss auf „ss“ fallen, sonst trifft „Gesäßdehnung“ das Wörterbuch
        # um genau einen Buchstaben nicht.
        ("Gesäßdehnung im Sitzen 2x45 s je Seite", "GLUTES_STRETCH"),
        ("Piriformis- und Gesäßdehnung 2x45 s je Seite", "GLUTES_STRETCH"),
    ],
)
def test_deutsche_komposita_werden_erkannt(zeile, erwartet):
    treffer = uebungen.finde(zeile)
    assert treffer is not None, zeile
    assert treffer.name == erwartet


def test_qualifizierte_grundform_wird_nicht_zur_grundform():
    """„Copenhagen Plank“ ist eine Adduktorenübung, kein Unterarmstütz.

    Der Katalog kennt sie nicht. Ohne Sperre liefe auf der Uhr die Animation
    eines gewöhnlichen Planks — eine andere Bewegung als die geplante.
    """
    assert uebungen.finde("Copenhagen Plank in der Knievariante 20 s je Seite") is None
    assert uebungen.finde("Copenhagen Plank") is None
    # Mengenangaben ringsum sind kein Qualifizierer.
    assert uebungen.finde("3x45 s Plank").name == "PLANK"
    assert uebungen.finde("Plank 3x45 s").name == "PLANK"


def test_einbeinige_variante_bleibt_einbeinig():
    """Sonst zeigte die Uhr zur einbeinigen Brücke die zweibeinige."""
    assert uebungen.finde("einbeinige Glute Bridge 10 je Seite").name == (
        "SINGLE_LEG_HIP_RAISE"
    )


def test_ohne_erkennbare_uebung_bleibt_es_leer():
    assert uebungen.finde("Ganzkörperkraft nach Tagesform, 3 Runden") is None
    assert uebungen.finde("10 min lockeres Ausrollen auf der Faszienrolle") is None
    assert uebungen.finde("") is None
    assert uebungen.finde(None) is None


def test_gruppennamen_zaehlen_nicht_als_uebung():
    """Zu „Core“ oder „Warm-up“ gibt es keine Animation, nur eine Schublade."""
    assert uebungen.finde("Core-Stabilisation 10 min") is None
    assert uebungen.finde("Warm-up 10 min") is None
    assert uebungen.finde("Cardio 20 min") is None


def test_der_englische_name_in_klammern_blockiert_den_deutschen_nicht():
    """Punkt 9 des Prompts verlangt die Klammer — sie darf nicht schaden.

    Über die Klammergrenze hinweg gelesen stand „Unterarmstütz“ direkt neben
    „Front“, und für `_grundform_ok` sah das aus wie ein qualifizierter
    Unterarmstütz. Der Zusatz, der die Trefferquote erhöhen sollte, verhinderte
    damit genau den Treffer.
    """
    assert uebungen.finde("3x45 s Unterarmstütz (Front Plank)").name == "PLANK"
    assert uebungen.finde("3x12 Kniebeugen (Squat)").name == "SQUAT"
    # Und die Klammer verklebt auch nichts, was nicht zusammengehört.
    assert uebungen.finde("Copenhagen Plank (Adduktoren) 20 s je Seite") is None


@pytest.mark.parametrize(
    ("zeile", "erwartet"),
    [
        # Der Katalog hängt „Stretch“ an, die geläufige Bezeichnung nicht — und
        # die schreibt die KI in die Klammer.
        ("2x60 s Kindhaltung (Child's Pose)", "STRETCH_CHILDS_POSE"),
        ("2x60 s je Seite Taube (Pigeon Pose)", "STRETCH_PIGEON_POSE"),
        ("2x10 Katze-Kuh (Cat-Cow)", "STRETCH_CAT_COW"),
        ("2x45 s Iliotibialband-Dehnung (Standing IT Band)", "STRETCH_STANDING_IT_BAND"),
    ],
)
def test_dehnungsname_ohne_angehaengtes_stretch(zeile, erwartet):
    treffer = uebungen.finde(zeile)
    assert treffer is not None, zeile
    assert treffer.name == erwartet


def test_einwortiger_katalogname_aus_fremder_kategorie_ist_gesperrt():
    """„Lateral Band Walk“ ist keine Runde um den Block.

    Garmin führt „Walk“ unter RUN — die Kennung `exercise == category` greift
    dort nicht, und ohne die zweite Bedingung bekam eine Bandübung im Plan die
    Animation eines Spaziergangs.
    """
    treffer = uebungen.finde("3x12 Seitschritte mit Miniband (Lateral Band Walk)")
    assert treffer.name == "LATERAL_BAND_WALKS"
    assert uebungen.finde("3x15 Lateral Band Walk").name == "LATERAL_BAND_WALKS"
    # Für sich allein bleibt die Grundform erreichbar.
    assert uebungen.finde("20 min Walk").name == "WALK"


@pytest.mark.parametrize(
    ("zeile", "erwartet"),
    [
        # Die Richtung ist der Unterschied: vorwärts wäre eine andere Bewegung.
        ("3x10 Rückwärtiger Ausfallschritt (Reverse Lunge)", "CORE_CONTROL_REAR_LUNGE"),
        # Einbeinig darf nicht als zweibeinig auf der Uhr landen.
        (
            "3x15 Wadenheben einbeinig (Single-Leg Calf Raise) je Seite",
            "SINGLE_LEG_STANDING_CALF_RAISE",
        ),
        (
            "2x30 s je Seite Brustöffner an der Wand (Wall Chest Stretch)",
            "STRETCH_WALL_CHEST_AND_SHOULDER",
        ),
        ("2x12 Hüftkreisen im Vierfüßler (Fire Hydrant)", "FIRE_HYDRANT_KICKS"),
        ("3x10 Rumänisches Kreuzheben", "ROMANIAN_DEADLIFT"),
        # Die Vierer- oder Figur-4-Dehnung ist die Piriformisdehnung; ohne
        # Eintrag blieb der Schritt namenlos, und die Uhr zeigte darüber „--“.
        (
            "Figur-4-Dehnung im Liegen (Figure-4 Stretch) 2x45 s je Seite",
            "STRETCH_LYING_PIRIFORMIS",
        ),
        (
            "Vierer-Dehnung im Sitzen (Figure-Four Stretch) 2x45 s je Seite",
            "STRETCH_PIRIFORMIS",
        ),
        (
            "Brustöffnung an der Wand (Doorway Chest Stretch) 2x30 s",
            "STRETCH_WALL_CHEST_AND_SHOULDER",
        ),
        (
            "Einbeiniges Kreuzheben (Single-Leg Deadlift) 3x10 je Seite",
            "ROMANIAN_DEADLIFT",
        ),
    ],
)
def test_zeilen_aus_echten_ki_plaenen(zeile, erwartet):
    """Wortlaut wie aus der Datenbank — hier fielen die Lücken auf."""
    treffer = uebungen.finde(zeile)
    assert treffer is not None, zeile
    assert treffer.name == erwartet


def test_arbeit_mit_der_rolle_bekommt_keine_dehnung():
    """Ausrollen ist keine Dehnung — Garmin kennt dafür keine Bewegung.

    „Faszienrolle lateraler Oberschenkel (Foam Roll IT Band)“ zog die
    „Standing IT Band Stretch“ an sich, weil deren Schlüssel „it band“ mitten
    im Text steht: Auf der Uhr lief die Animation einer Dehnung im Stand,
    während der Plan Ausrollen im Liegen meint.
    """
    assert uebungen.finde("Faszienrolle lateraler Oberschenkel (Foam Roll IT Band) 2x60 s") is None
    assert uebungen.finde("Faszienrolle Gesäß (Foam Roll Glutes) 90 s je Seite") is None
    assert uebungen.finde("2x60 s Oberschenkelvorderseite mit der Blackroll") is None

    # Die Dehnung derselben Struktur bleibt erreichbar, solange keine Rolle
    # im Spiel ist.
    assert uebungen.finde("2x45 s IT-Band-Dehnung im Stehen (Standing IT Band Stretch)").name == (
        "STRETCH_STANDING_IT_BAND"
    )
