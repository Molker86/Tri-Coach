"""Die FIT-Pipeline: Entpacken, Verdichten, Parsen, Paketabschnitt, Abruf.

Die Parser-Tests laufen gegen eine **echte, vom Nutzer exportierte** ORIGINAL-
ZIP (`fixtures/fit/lauf_workout.zip`, Aktivität 24040558837, „Einstufungslauf"
vom 19.08.2026, aus einem strukturierten Workout gestartet). Synthetische
FIT-Dateien gibt es bewusst nicht: `garmin-fit-sdk` kann nur dekodieren, und
eine selbstgebaute Datei prüfte den eigenen Baumeister statt Garmins Format.

Dazu inzwischen Kraft (`kraft.zip`), ein Beckenschwimmen und eine Zwift-Fahrt
(`schwimmen_becken.zip`, `rad_indoor_watt.zip`, anonymisiert — siehe
`test_fit_kennwerte.py`). Multisport hat weiterhin kein Fixture; getestet ist
dort nur das Leerverhalten. Die Lücke steht in `docs/analyse.md` unter
„Grenzen".
"""

import io
import zipfile
from pathlib import Path

import pytest

from app.garmin import fitdaten
from app.garmin.fitdaten import (
    AktivitaetsDaten,
    FitDatenFehler,
    entpacke_fit,
    hole_aktivitaet,
    parse_fit,
    verdichte_stuetzpunkte,
)

FIXTURE = Path(__file__).parent / "fixtures" / "fit" / "lauf_workout.zip"


def _zip_mit(dateien: dict[str, bytes]) -> bytes:
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as archiv:
        for name, inhalt in dateien.items():
            archiv.writestr(name, inhalt)
    return puffer.getvalue()


# --------------------------------------------------------------------------
# Entpacken
# --------------------------------------------------------------------------


def test_entpacken_liefert_die_fit_datei():
    zip_bytes = _zip_mit({"12345_ACTIVITY.fit": b"fit-inhalt"})
    assert entpacke_fit(zip_bytes) == b"fit-inhalt"


def test_entpacken_nimmt_die_erste_fit_datei_gross_oder_klein():
    zip_bytes = _zip_mit({"lesmich.txt": b"nein", "A.FIT": b"ja"})
    assert entpacke_fit(zip_bytes) == b"ja"


def test_zip_ohne_fit_ist_ein_definierter_fehler():
    zip_bytes = _zip_mit({"nur_text.txt": b"kein fit"})
    with pytest.raises(FitDatenFehler):
        entpacke_fit(zip_bytes)


def test_kaputtes_archiv_ist_ein_definierter_fehler():
    with pytest.raises(FitDatenFehler):
        entpacke_fit(b"das ist kein zip")


# --------------------------------------------------------------------------
# Verdichten — reine Mathematik, synthetische Eingaben
# --------------------------------------------------------------------------


def test_wenige_punkte_bleiben_unveraendert():
    punkte = [{"zeit_s": i, "puls": 100 + i} for i in range(10)]
    assert verdichte_stuetzpunkte(punkte, max_punkte=150) == punkte


def test_viele_punkte_werden_auf_hoechstens_max_punkte_verdichtet():
    punkte = [{"zeit_s": i, "puls": 100} for i in range(540)]
    verdichtet = verdichte_stuetzpunkte(punkte, max_punkte=150)
    assert 100 < len(verdichtet) <= 150


def test_das_mittel_stimmt_fuer_ein_handbeispiel():
    punkte = [
        {"zeit_s": 0, "puls": 100, "watt": 200},
        {"zeit_s": 1, "puls": 110, "watt": 210},
        {"zeit_s": 2, "puls": 120, "watt": 220},
        {"zeit_s": 3, "puls": 130, "watt": 230},
    ]
    verdichtet = verdichte_stuetzpunkte(punkte, max_punkte=2)
    assert len(verdichtet) == 2
    assert verdichtet[0]["puls"] == 105
    assert verdichtet[0]["watt"] == 205
    assert verdichtet[1]["puls"] == 125
    assert verdichtet[1]["watt"] == 225


def test_fehlende_kanaele_werden_nicht_zu_null_gemittelt():
    punkte = [
        {"zeit_s": 0, "puls": 100, "watt": None},
        {"zeit_s": 1, "puls": None, "watt": None},
        {"zeit_s": 2, "puls": 120, "watt": None},
        {"zeit_s": 3, "puls": 140, "watt": None},
    ]
    verdichtet = verdichte_stuetzpunkte(punkte, max_punkte=2)
    # None zählt nicht als 0: (100)/1, nicht (100+0)/2.
    assert verdichtet[0]["puls"] == 100
    assert verdichtet[1]["puls"] == 130
    # Ein durchgehend leerer Kanal bleibt leer statt zu 0 zu werden.
    assert verdichtet[0]["watt"] is None


# --------------------------------------------------------------------------
# Parsen — gegen die echte Fixture
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lauf() -> AktivitaetsDaten:
    fit = entpacke_fit(FIXTURE.read_bytes())
    aktivitaeten = parse_fit(fit)
    # Eine Session in der Datei → genau ein Element.
    assert len(aktivitaeten) == 1
    return aktivitaeten[0]


def test_kopffelder_des_laufs(lauf):
    kopf = lauf.kopf
    assert kopf["sportart"] == "running"
    assert kopf["workout_name"] == "Einstufungslauf"
    # Ortszeit, nicht UTC: Die FIT trägt 18:53:41Z, gelaufen wurde 20:53:41.
    assert kopf["start_lokal"] == "2026-08-19T20:53:41"
    assert kopf["dauer_min"] == 9.0
    assert kopf["distanz_km"] == 1.43
    assert kopf["kalorien"] == 143
    assert kopf["trainingslast"] == 34.1
    assert kopf["te_aerob"] == 2.6
    assert kopf["te_anaerob"] == 0.0


def test_soll_schritte_aus_dem_workout(lauf):
    schritte = lauf.soll_schritte
    assert [s["nr"] for s in schritte] == [1, 2, 3]
    assert [s["intensitaet"] for s in schritte] == ["warmup", "active", "cooldown"]
    assert [s["dauer_s"] for s in schritte] == [120.0, 300.0, 120.0]
    assert schritte[0]["ziel_typ"] == "open"
    # Die Notiz kommt beim SDK als Liste mit Datenmüll dahinter — es zählt nur
    # der erste Eintrag.
    assert schritte[0]["beschreibung"] == "Gehen oder joggen Sie locker."


def test_runden_mit_bezug_auf_den_soll_schritt(lauf):
    runden = lauf.runden
    assert len(runden) == 3
    erste = runden[0]
    assert erste["nr"] == 1
    assert erste["zeit_s"] == 120.0
    assert erste["distanz_m"] == 293.02
    assert erste["avg_puls"] == 122
    assert erste["max_puls"] == 135
    assert erste["avg_watt"] == 384
    assert erste["kadenz"] == 76
    # Der Rückbezug auf den geplanten Schritt — der Kern des Soll-Ist-Vergleichs.
    assert erste["soll_schritt"] == 1
    assert runden[1]["soll_schritt"] == 2


def test_stuetzpunkte_sind_verdichtet(lauf):
    # 540 Records in der Datei, verdichtet auf höchstens 150.
    assert 100 < len(lauf.stuetzpunkte) <= 150
    erster = lauf.stuetzpunkte[0]
    assert set(erster) >= {"zeit_s", "puls", "geschw_m_s", "watt", "kadenz"}
    assert 90 <= erster["puls"] <= 120


def test_pausen_ereignisse(lauf):
    assert {"zeit_s": 0.0, "typ": "start"} in lauf.pausen
    assert any(p["typ"] == "stop_all" for p in lauf.pausen)


def test_lauf_ohne_schwimm_und_kraftdaten_hat_leere_listen(lauf):
    assert lauf.bahnen == []
    assert lauf.saetze == []


def test_unlesbare_fit_ist_ein_definierter_fehler():
    with pytest.raises(FitDatenFehler):
        parse_fit(b"das ist keine fit-datei")


# --------------------------------------------------------------------------
# Paketabschnitt
# --------------------------------------------------------------------------


def test_paketabschnitt_traegt_kopf_und_tabellen(lauf):
    from app.paketformat import paket_als_text

    text = paket_als_text({"aktivitaeten": [lauf.als_dict()]})
    assert '"sportart":"running"' in text
    assert '"workout_name":"Einstufungslauf"' in text
    assert "### aktivitaeten.1.soll_schritte" in text
    assert "### aktivitaeten.1.runden" in text
    assert "### aktivitaeten.1.stuetzpunkte" in text
    # Erwartete Spaltennamen in den Kopfzeilen der Tabellen. Konstante Spalten
    # wandern in die Klammer der Überschrift — gesucht wird in beiden Zeilen.
    def kopfzeilen(pfad: str) -> str:
        zeilen = text.split(f"### {pfad}")[1].splitlines()
        return zeilen[0] + "\n" + zeilen[1]

    soll = kopfzeilen("aktivitaeten.1.soll_schritte")
    assert "intensitaet" in soll and "dauer_s" in soll
    runden = kopfzeilen("aktivitaeten.1.runden")
    assert "soll_schritt" in runden and "avg_puls" in runden
    punkte = kopfzeilen("aktivitaeten.1.stuetzpunkte")
    assert "puls" in punkte and "geschw_m_s" in punkte


def test_paketabschnitt_vermerkt_fehlende_fit():
    """Ohne ladbare Aufzeichnung steht nur der Vermerk im Abschnitt.

    Den Block baut nicht `fitdaten`, sondern `ai_export` — hier zählt, dass
    `paket_als_text` ihn ohne Tabellen durchlässt.
    """
    from app.ai_export import HINWEIS_OHNE_FIT
    from app.paketformat import paket_als_text

    text = paket_als_text({"aktivitaeten": [{"hinweis": HINWEIS_OHNE_FIT}]})
    assert "nur Listendaten" in text
    assert "### aktivitaeten.1." not in text  # keine Tabellen ohne Daten


def test_zwei_aktivitaeten_werden_durchnummeriert(lauf):
    from app.paketformat import paket_als_text

    text = paket_als_text({"aktivitaeten": [lauf.als_dict(), lauf.als_dict()]})
    assert "### aktivitaeten.1.runden" in text
    assert "### aktivitaeten.2.runden" in text


# --------------------------------------------------------------------------
# Abruf über die Garmin-API
# --------------------------------------------------------------------------


from datetime import date  # noqa: E402

from fakes import FakeGarmin, baue_aktivitaet  # noqa: E402

HEUTE = date.today()


def test_abruf_laedt_und_parst_das_original():
    stand = FakeGarmin(aktivitaeten=[baue_aktivitaet(24040558837, HEUTE)])
    stand.originale["24040558837"] = FIXTURE.read_bytes()

    aktivitaeten = hole_aktivitaet(stand, "24040558837")
    assert len(aktivitaeten) == 1
    assert aktivitaeten[0].kopf["sportart"] == "running"
    assert len(aktivitaeten[0].soll_schritte) == 3
    # ORIGINAL und nichts anderes — TCX trüge die Soll-Schritte nicht.
    assert stand.aufrufe == ["download_activity"]


def test_gescheiterter_download_fliegt():
    """Anders als beim alten Zeitraumabruf wird hier nichts übersprungen.

    Es gibt nur diese eine Datei; wer sie nicht bekommt, hat nichts. Ob
    trotzdem aus den Listendaten bewertet wird, entscheidet der Aufrufer
    (`runner._aufzeichnung`), nicht der Abruf.
    """
    stand = FakeGarmin(aktivitaeten=[baue_aktivitaet(1002, HEUTE)])
    stand.download_fehler.add("1002")

    with pytest.raises(RuntimeError):
        hole_aktivitaet(stand, "1002")


def test_unlesbare_zip_ist_ein_fitdatenfehler():
    stand = FakeGarmin(aktivitaeten=[baue_aktivitaet(1001, HEUTE)])
    stand.originale["1001"] = b"kein zip"

    with pytest.raises(FitDatenFehler):
        hole_aktivitaet(stand, "1001")


# --------------------------------------------------------------------------
# Kraft — zweites echtes Fixture (Krafttraining vom 18.09.2026)
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def kraft() -> AktivitaetsDaten:
    fit = entpacke_fit((FIXTURE.parent / "kraft.zip").read_bytes())
    aktivitaeten = parse_fit(fit)
    assert len(aktivitaeten) == 1
    return aktivitaeten[0]


def test_kraft_saetze_aus_der_fixture(kraft):
    assert kraft.kopf["sportart"] == "training"
    saetze = kraft.saetze
    assert len(saetze) == 6
    # Aktive Sätze und Pausen wechseln sich ab; die Pause hat keine Übung.
    assert [s["typ"] for s in saetze] == ["active", "rest"] * 3
    assert saetze[0]["wiederholungen"] == 11
    # `category` kommt als Liste von Kandidaten — es zählt der erste belegte.
    assert saetze[0]["uebung"] == "bench_press"
    assert saetze[1]["uebung"] is None
    assert kraft.bahnen == []


# --------------------------------------------------------------------------
# Schwimmen und Zwift — echte Fixtures, seit die Planung sie braucht
# --------------------------------------------------------------------------


def test_schwimmbahnen_aus_der_fixture():
    """Bis hierher war Schwimmen nur im Leerverhalten getestet."""
    schwimmen = parse_fit(
        entpacke_fit((FIXTURE.parent / "schwimmen_becken.zip").read_bytes())
    )[0]

    assert schwimmen.kopf["sub_sportart"] == "lap_swimming"
    assert len(schwimmen.bahnen) == 71
    assert schwimmen.bahnen[0] == {
        "nr": 1, "zeit_s": 19.0, "zuege": 6, "stil": "breaststroke", "kadenz": 19,
        "art": "active",
    }


def test_zwift_ohne_ortszeit_startet_nicht_1989():
    """Zwift schreibt `local_timestamp = 0` — das ist keine Zeitzone.

    Ohne Grenze stand die Fahrt vom 16.02.2026 mit Start am 30.12.1989 im
    Paket; jetzt steht sie in UTC da, wie jede Datei ohne Ortszeit.
    """
    rad = parse_fit(entpacke_fit((FIXTURE.parent / "rad_indoor_watt.zip").read_bytes()))[0]

    assert rad.kopf["start_lokal"] == "2026-02-16T18:04:27"
    assert any(punkt["watt"] for punkt in rad.stuetzpunkte)
