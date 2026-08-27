"""Die Einkaufsliste rechnen — ohne Netz, ohne Datenbank.

Der Schwerpunkt liegt auf dem, was Bring nicht kann: Mengen zusammenzählen. Ein
Eintrag dort hat nur einen Freitext neben dem Namen, und was daraus zu lesen ist,
entscheidet, ob eine zweite Übertragung die Menge verdoppelt oder ergänzt.
"""

import pytest

from app import einkaufsliste as el


class Zutat:
    """Was `sammle()` von einer Zutat braucht — mehr nicht."""

    def __init__(self, name, menge=None, einheit=None):
        self.name = name
        self.menge = menge
        self.einheit = einheit


class Mahlzeit:
    def __init__(self, *zutaten):
        self.zutaten = list(zutaten)


class Tag:
    def __init__(self, *mahlzeiten):
        self.mahlzeiten = list(mahlzeiten)


# --------------------------------------------------------------------------
# Einheiten
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("menge", "roh", "erwartet"),
    [
        (1.5, "kg", (1500.0, "g")),
        (2, "l", (2000.0, "ml")),
        (500, "G", (500.0, "g")),
        (3, "Stk", (3.0, "Stück")),
        (1, "esslöffel", (1.0, "EL")),
        (2, "  ", (2.0, None)),
        (2, None, (2.0, None)),
    ],
)
def test_einheiten_werden_auf_eine_schreibweise_gebracht(menge, roh, erwartet):
    assert el.normalisiere(menge, roh) == erwartet


def test_eine_unbekannte_einheit_bleibt_stehen():
    """Tolerant wie überall im Import: „Dose" ist eine Angabe, kein Fehler."""
    assert el.normalisiere(2, "Dose") == (2.0, "Dose")
    assert el.normalisiere(1, "Zweig") == (1.0, "Zweig")


def test_ohne_menge_bleibt_die_einheit_ohne_menge():
    assert el.normalisiere(None, "kg") == (None, "g")


# --------------------------------------------------------------------------
# Anzeige
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("menge", "einheit", "erwartet"),
    [
        (500, "g", "500 g"),
        (1200, "g", "1,2 kg"),
        (1000, "ml", "1 l"),
        (999, "ml", "999 ml"),
        (3, "Stück", "3 Stück"),
        (2.5, "EL", "2,5 EL"),
        (None, "Bund", "Bund"),
        (None, None, ""),
    ],
)
def test_mengen_werden_lesbar_geschrieben(menge, einheit, erwartet):
    assert el.formatiere_menge(menge, einheit) == erwartet


# --------------------------------------------------------------------------
# Eine vorhandene Bring-Angabe lesen
# --------------------------------------------------------------------------


def test_eine_vorhandene_angabe_wird_gelesen():
    gelesen = el.parse_menge("500 g")
    assert (gelesen.menge, gelesen.einheit, gelesen.rest) == (500.0, "g", "")


def test_der_rest_hinter_der_menge_bleibt_erhalten():
    gelesen = el.parse_menge("1,5 kg, bio")
    assert (gelesen.menge, gelesen.einheit) == (1500.0, "g")
    assert gelesen.rest == ", bio"


def test_eine_zahl_ohne_einheit_zaehlt_als_stueckzahl_ohne_einheit():
    gelesen = el.parse_menge("3")
    assert (gelesen.menge, gelesen.einheit) == (3.0, None)


@pytest.mark.parametrize("spez", ["fettarm", "", None, "bio, regional"])
def test_ohne_zahl_ist_nichts_zu_lesen(spez):
    assert el.parse_menge(spez) is None


# --------------------------------------------------------------------------
# Zusammenrechnen
# --------------------------------------------------------------------------


def test_gleiche_einheit_wird_addiert():
    assert el.verschmelze("500 g", 200, "g") == "700 g"


def test_ueber_tausend_gramm_wird_auf_kilo_umgestellt():
    assert el.verschmelze("800 g", 500, "g") == "1,3 kg"


def test_liter_und_milliliter_treffen_sich():
    assert el.verschmelze("1 l", 500, "ml") == "1,5 l"


def test_eine_leere_angabe_bekommt_einfach_die_neue():
    assert el.verschmelze("", 200, "g") == "200 g"
    assert el.verschmelze(None, 2, "Stück") == "2 Stück"


def test_was_sich_nicht_rechnen_laesst_wird_angehaengt():
    """Lieber sichtbar zweimal als still falsch summiert."""
    assert el.verschmelze("fettarm", 500, "ml") == "fettarm + 500 ml"


def test_verschiedene_einheiten_werden_nicht_verrechnet():
    assert el.verschmelze("2 Stück", 200, "g") == "2 Stück + 200 g"


def test_der_zusatz_bleibt_beim_addieren_stehen():
    assert el.verschmelze("500 g, bio", 300, "g") == "800 g, bio"


# --------------------------------------------------------------------------
# Summieren über die Tage
# --------------------------------------------------------------------------


def test_dieselbe_zutat_wird_ueber_die_tage_summiert():
    tage = [
        Tag(Mahlzeit(Zutat("Haferflocken", 80, "g"))),
        Tag(Mahlzeit(Zutat("Haferflocken", 120, "g"))),
    ]
    assert [(p.name, p.text) for p in el.sammle(tage)] == [("Haferflocken", "200 g")]


def test_gross_und_kleinschreibung_meinen_dasselbe_regal():
    tage = [Tag(Mahlzeit(Zutat("milch", 300, "ml"), Zutat("Milch", 200, "ml")))]
    posten = el.sammle(tage)
    assert len(posten) == 1
    # Angezeigt wird die erste gesehene Schreibweise.
    assert (posten[0].name, posten[0].text) == ("milch", "500 ml")


def test_verschiedene_einheiten_bleiben_getrennte_zeilen():
    """Niemand weiß, wie schwer diese Tomaten sind."""
    tage = [Tag(Mahlzeit(Zutat("Tomaten", 200, "g"), Zutat("Tomaten", 2, "Stück")))]
    assert [p.text for p in el.sammle(tage)] == ["200 g", "2 Stück"]


def test_eine_zutat_ohne_menge_behaelt_keine():
    tage = [Tag(Mahlzeit(Zutat("Salz")))]
    posten = el.sammle(tage)
    assert posten[0].menge is None
    assert posten[0].text == ""


def test_namenlose_zutaten_fallen_weg():
    assert el.sammle([Tag(Mahlzeit(Zutat("   ", 5, "g")))]) == []


def test_die_liste_ist_alphabetisch_sortiert():
    tage = [Tag(Mahlzeit(Zutat("Zwiebel", 1, "Stück"), Zutat("Apfel", 2, "Stück")))]
    assert [p.name for p in el.sammle(tage)] == ["Apfel", "Zwiebel"]


def test_ohne_zutaten_bleibt_die_liste_leer():
    assert el.sammle([Tag(Mahlzeit()), Tag()]) == []
