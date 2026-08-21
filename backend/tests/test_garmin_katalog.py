"""Garmins Übungskatalog: Abruf, Prüfung, Ablage.

Kein Netzzugriff — `_hole` wird ersetzt. Was hier geprüft wird, ist nicht der
Download selbst, sondern die Frage, wann eine gespeicherte Datei ersetzt werden
darf: Eine kaputte Antwort, die eine gute Datei überschreibt, nähme jeder
Kraft- und Mobility-Einheit ihre Bewegungsanimation — und zwar unbemerkt, bis
jemand auf die Uhr sieht.
"""

import json

import pytest

from app.garmin import katalog, uebungen


def _katalog_json(kategorien: int = 10, je_kategorie: int = 10) -> bytes:
    daten = {
        "categories": {
            f"KATEGORIE_{i}": {
                "primaryMuscles": ["ABS"],
                "secondaryMuscles": [],
                "exercises": {
                    f"UEBUNG_{i}_{j}": {"primaryMuscles": ["ABS"]}
                    for j in range(je_kategorie)
                },
            }
            for i in range(kategorien)
        }
    }
    return json.dumps(daten).encode()


@pytest.fixture
def katalogordner(tmp_path, monkeypatch, echter_katalogabruf):
    """Ein leerer Katalogordner — und hinterher ein leerer Zwischenspeicher.

    Das Aufräumen ist Pflicht und nicht Kosmetik: `uebungen` hält sein
    Verzeichnis in einem `lru_cache`, und ein hier eingespielter Ersatzkatalog
    überlebte den Test sonst und beantwortete jede spätere Übungssuche der
    ganzen Sitzung.
    """
    monkeypatch.setattr(katalog, "KATALOG_DIR", tmp_path)
    yield tmp_path
    uebungen.leere_zwischenspeicher()


@pytest.fixture
def antwort(monkeypatch):
    """Steuert, was `_hole` liefert — ein Bytes-Objekt oder eine Ausnahme."""
    kasten: dict[str, object] = {"wert": _katalog_json()}

    def _hole(adresse: str) -> bytes:
        wert = kasten["wert"]
        if isinstance(wert, Exception):
            raise wert
        return wert  # type: ignore[return-value]

    monkeypatch.setattr(katalog, "_hole", _hole)
    return kasten


# --------------------------------------------------------------------------
# Der gute Fall
# --------------------------------------------------------------------------


def test_ein_gueltiger_katalog_wird_gespeichert(katalogordner, antwort):
    hinweise = katalog.aktualisiere()

    assert hinweise == []
    for dateiname, _ in katalog.QUELLEN.values():
        assert (katalogordner / dateiname).exists()


def test_ein_zweiter_lauf_am_selben_tag_holt_nicht_erneut(katalogordner, antwort):
    katalog.aktualisiere()
    antwort["wert"] = OSError("dürfte gar nicht erst gefragt werden")

    assert katalog.aktualisiere() == []


def test_erzwungen_wird_trotz_frischer_datei_geholt(katalogordner, antwort):
    katalog.aktualisiere()
    antwort["wert"] = _katalog_json(kategorien=11)

    katalog.aktualisiere(erzwinge=True)

    dateiname = katalog.QUELLEN["kraft"][0]
    inhalt = json.loads((katalogordner / dateiname).read_bytes())
    assert len(inhalt["categories"]) == 11


# --------------------------------------------------------------------------
# Was eine gute Datei nicht ersetzen darf
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kaputt",
    [
        pytest.param(b"<html><body>503 Service Unavailable</body></html>", id="html"),
        pytest.param(b'{"categories": {"PLANK": {"exer', id="abgeschnitten"),
        pytest.param(b'{"categories": {}}', id="leer"),
        pytest.param(b'{"etwas": "anderes"}', id="fremde_form"),
        pytest.param(_katalog_json(kategorien=2), id="zu_wenig_kategorien"),
        pytest.param(_katalog_json(kategorien=6, je_kategorie=1), id="zu_wenig_uebungen"),
    ],
)
def test_eine_kaputte_antwort_laesst_den_bestand_stehen(
    katalogordner, antwort, kaputt
):
    katalog.aktualisiere()
    vorher = {
        dateiname: (katalogordner / dateiname).read_bytes()
        for dateiname, _ in katalog.QUELLEN.values()
    }

    antwort["wert"] = kaputt
    hinweise = katalog.aktualisiere(erzwinge=True)

    assert hinweise, "eine verworfene Antwort muss gemeldet werden"
    assert "zuletzt gespeicherte" in hinweise[-1]
    for dateiname, rohdaten in vorher.items():
        assert (katalogordner / dateiname).read_bytes() == rohdaten


def test_ein_netzfehler_wirft_nicht_und_meldet_deutsch(katalogordner, antwort):
    antwort["wert"] = OSError("Name or service not known")

    hinweise = katalog.aktualisiere()

    assert any("konnte nicht geladen werden" in h for h in hinweise)
    assert not list(katalogordner.glob("*.json"))


def test_nach_einem_fehlschlag_bleibt_keine_halbe_datei_liegen(
    katalogordner, antwort
):
    antwort["wert"] = b"<html>nein</html>"

    katalog.aktualisiere()

    assert list(katalogordner.iterdir()) == []


def test_die_anfrage_traegt_eine_eigene_kennung(monkeypatch, echter_katalogabruf):
    """Ohne sie antwortet Garmin mit 403.

    Am echten Dienst nachgemessen: Auf Pythons Vorgabe „Python-urllib/3.12“
    kommt **403 Forbidden**, auf so ziemlich jede andere Kennung 200. Ohne
    diesen Kopf schlüge der Abruf also jedes Mal fehl — und weil er sauber
    degradiert, fiele es nur an einem Hinweis auf, den niemand liest.
    """
    gesehen: dict[str, str] = {}

    class Attrappe:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return _katalog_json()

    def _urlopen(anfrage, **_):
        gesehen.update(anfrage.headers)
        return Attrappe()

    monkeypatch.setattr(katalog.urllib.request, "urlopen", _urlopen)
    katalog._hole("https://example.invalid/Exercises.json")

    # urllib normalisiert Kopfnamen auf Kleinschreibung mit großem Anfang.
    assert gesehen.get("User-agent") == "tri-coach"
    assert "python" not in gesehen.get("User-agent", "").lower()


# --------------------------------------------------------------------------
# Erstausstattung und Einträge
# --------------------------------------------------------------------------


def test_ohne_heruntergeladene_datei_gilt_die_erstausstattung(katalogordner):
    # `katalogordner` ist leer — gelesen wird, was im Abbild mitliegt.
    assert len(katalog.eintraege("kraft")) > 1000
    assert len(katalog.eintraege("mobility")) > 200


def test_die_grundform_traegt_ihre_kategorie_als_namen():
    """Nicht den Leerstring: Der Wert geht als `exerciseName` auf die Uhr."""
    plank = [
        e
        for e in katalog.eintraege("kraft")
        if e["category"] == "PLANK" and e["name"] == "Plank"
    ]
    assert plank == [{"name": "Plank", "category": "PLANK", "exercise": "PLANK"}]


def test_jedes_paar_kommt_nur_einmal_vor():
    for welcher in katalog.QUELLEN:
        eintraege = katalog.eintraege(welcher)
        paare = {(e["category"], e["exercise"]) for e in eintraege}
        assert len(paare) == len(eintraege)


def test_bekannte_namen_kommen_aus_der_bibliothek():
    """Der Qualifizierer steckt im Anzeigenamen, nicht im Schlüssel.

    `AB_TWIST` unter `BANDED_EXERCISES` heißt bei Garmin „Banded Ab Twist“ —
    aus dem Schlüssel allein käme „Ab Twist“ heraus, und die Zeile „Ab Twist
    mit Band“ fände ihren Eintrag schlechter.
    """
    namen = {
        (e["category"], e["exercise"]): e["name"] for e in katalog.eintraege("kraft")
    }
    assert namen[("BANDED_EXERCISES", "AB_TWIST")] == "Banded Ab Twist"
    assert namen[("PLANK", "SIDE_PLANK")] == "Side Plank"


def test_unbekannte_namen_werden_aus_dem_schluessel_gebildet():
    """Die Yogaposen kennt die Bibliothek nicht — die JSON schon."""
    namen = {
        (e["category"], e["exercise"]): e["name"]
        for e in katalog.eintraege("mobility")
    }
    assert namen[("POSE", "DOWNWARD_FACING_DOG")] == "Downward Facing Dog"
    assert namen[("MOVE", "PSOAS_LUNGE_STRETCH")] == "Psoas Lunge Stretch"


def test_ein_frischer_katalog_gilt_ohne_neustart(katalogordner, antwort):
    """Sonst hinge das Verzeichnis bis zum Neustart am alten Stand."""
    assert uebungen.finde("Side Plank", "kraft") is not None

    katalog.aktualisiere()

    # Der Ersatzkatalog kennt „Side Plank“ nicht mehr.
    assert uebungen.finde("Side Plank", "kraft") is None
