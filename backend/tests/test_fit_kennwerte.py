"""Pulshistogramm und Bestwerte aus der Original-Aufzeichnung.

Gegen echte ORIGINAL-ZIPs (`fixtures/fit/`): neben Einstufungslauf und
Krafteinheit ein Beckenschwimmen (25 m, 15.09.2026), eine Zwift-Fahrt mit Watt
(16.02.2026) und ein langer Lauf (101 min, 05.07.2026). Die drei neuen sind über
die bestehende Verbindung geholt und vor dem Ablegen anonymisiert: Positionen,
Seriennummern und die Texte des Nutzerprofils stehen in den Rohbytes auf dem
FIT-Wert „ungültig", alles andere ist Byte für Byte das Original.

Der Prüfstein für das Histogramm ist Garmin selbst: Jede Uhr-Aufzeichnung
trägt ihre eigene Zonenzählung samt Grenzen (`time_in_zone_mesgs`). Wer das
Histogramm nach **diesen** Grenzen zählt, muss dieselben Zahlen bekommen —
erst dann ist die Zählung nach den Zonen der App etwas wert.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from garmin_fit_sdk import Decoder, Stream

from app.garmin.fitdaten import (
    _beste_bahnzeiten,
    _wirksame_dauern,
    entpacke_fit,
    kennwerte_aus_fit,
)
from app.sportscience import hr_zones, zonensekunden_aus_histogramm

FIXTURES = Path(__file__).parent / "fixtures" / "fit"
MIT_UHRZONEN = ["lauf_workout.zip", "kraft.zip", "schwimmen_becken.zip", "lauf_lang.zip"]


def _fit(name: str) -> bytes:
    return entpacke_fit((FIXTURES / name).read_bytes())


@pytest.fixture(scope="module")
def kennwerte():
    return {
        name: kennwerte_aus_fit(_fit(name))
        for name in (*MIT_UHRZONEN, "rad_indoor_watt.zip")
    }


def _uhrzonen(name: str) -> tuple[list[dict], dict[str, float]]:
    """Die Zonengrenzen der Uhr und ihre eigene Zählung, aus derselben Datei."""
    nachrichten, _ = Decoder(Stream.from_byte_array(_fit(name))).read()
    tiz = next(
        t for t in nachrichten["time_in_zone_mesgs"] if t["reference_mesg"] == "session"
    )
    grenzen = tiz["hr_zone_high_boundary"]
    # Zone k beginnt, wo Zone k-1 endet; Zone 0 ist „unter Z1".
    zonen = [{"zone": f"Z{k}", "low_bpm": grenzen[k - 1]} for k in range(1, 6)]
    garmin = {str(k): tiz["time_in_hr_zone"][k] for k in range(1, 6)}
    # Die App zählt die Zeit unter Z1 zu Z1 — Garmin führt sie als Zone 0.
    garmin["1"] += tiz["time_in_hr_zone"][0]
    return zonen, garmin


# --------------------------------------------------------------------------
# Pulshistogramm
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", MIT_UHRZONEN)
def test_die_nachzaehlung_trifft_garmins_eigene_zonenzeiten(kennwerte, name):
    zonen, garmin = _uhrzonen(name)
    eigene = zonensekunden_aus_histogramm(kennwerte[name].puls_histogramm, zonen)

    for zone, sekunden in garmin.items():
        assert eigene.get(zone, 0) == pytest.approx(sekunden, abs=max(5, 0.02 * sekunden))


def test_smart_recording_zaehlt_voll_mit(kennwerte):
    """Die Krafteinheit schreibt bis zu zwölf Sekunden lang keinen Record.

    Eine Lückenschwelle hätte diese Zeit verworfen; Pausen kommen deshalb aus
    den Timer-Ereignissen. Das Histogramm deckt die volle Timerzeit ab.
    """
    assert sum(kennwerte["kraft.zip"].puls_histogramm.values()) == 1445


def test_nach_den_zonen_der_app_ist_der_lange_lauf_keine_schwelleneinheit(kennwerte):
    """Der Grund für das Ganze, am echten Lauf vom 05.07.2026.

    Die Uhr zählt nach Prozent der HFmax und meldet 84 min Z4 und knapp vier
    Minuten Z5. Nach den Karvonen-Zonen des Profils (189/58), mit denen die KI
    plant, ist es gut die Hälfte davon — und keine Minute Z5.
    """
    histogramm = kennwerte["lauf_lang.zip"].puls_histogramm
    _, uhr = _uhrzonen("lauf_lang.zip")
    app = zonensekunden_aus_histogramm(histogramm, hr_zones(189, 58))

    assert uhr["4"] / 60 == pytest.approx(84, abs=1)
    assert app["4"] / 60 == pytest.approx(44, abs=1)
    assert "5" not in app


def test_ein_puls_auf_der_grenze_zaehlt_zur_hoeheren_zone():
    """So zählt die Uhr — mit der anderen Lesart träfe die Nachzählung sie nicht."""
    zonen = [{"zone": f"Z{k}", "low_bpm": unten} for k, unten in
             enumerate((100, 120, 140, 160, 180), 1)]

    assert zonensekunden_aus_histogramm({"120": 20, "200": 30}, zonen) == {
        "2": 20,
        "5": 30,
    }


def test_zeit_unter_z1_zaehlt_als_z1():
    """Sonst fiele an einem echten Konto ein Viertel jeder lockeren Einheit heraus.

    Die Karvonen-Z1 beginnt bei der halben Herzfrequenzreserve (dort 124 bpm).
    Die Zeit darunter ist leichte Zeit — ohne sie las sich die
    Intensitätsverteilung härter, als trainiert wurde.
    """
    zonen = [{"zone": f"Z{k}", "low_bpm": unten} for k, unten in
             enumerate((100, 120, 140, 160, 180), 1)]

    assert zonensekunden_aus_histogramm({"80": 40, "99": 10, "100": 5}, zonen) == {
        "1": 55
    }


def test_die_krafteinheit_liegt_ganz_in_z1(kennwerte):
    """Ihr Puls liegt komplett unter der Karvonen-Z1 von 189/58.

    Früher kam dabei `None` heraus — und der Export griff still auf Garmins
    Zählung zurück, also auf ein anderes Zonenmodell.
    """
    app = zonensekunden_aus_histogramm(
        kennwerte["kraft.zip"].puls_histogramm, hr_zones(189, 58)
    )
    assert app == {"1": 1445}


def test_timerpausen_zaehlen_nicht():
    """Ohne sie stünde eine Kaffeepause mit dem letzten Puls davor im Histogramm."""
    start = datetime(2026, 9, 1, 8, tzinfo=timezone.utc)
    records = [{"timestamp": start + timedelta(seconds=s)} for s in (0, 5, 65, 70)]
    pause = (start + timedelta(seconds=10), start + timedelta(seconds=60))

    assert _wirksame_dauern(records, [pause]) == [5.0, 10.0, 5.0, 0.0]


# --------------------------------------------------------------------------
# Bestwerte
# --------------------------------------------------------------------------


def test_der_fuenfminutenwert_ist_die_aktive_runde(kennwerte):
    """Das Workout hatte genau einen Arbeitsschritt über 300 s: 843,79 m."""
    assert kennwerte["lauf_workout.zip"].bestwerte == {
        "run": {"300": pytest.approx(843.79 / 300, abs=0.002)}
    }


def test_der_lange_lauf_traegt_alle_drei_dauern(kennwerte):
    lauf = kennwerte["lauf_lang.zip"].bestwerte["run"]

    assert set(lauf) == {"300", "1200", "3600"}
    assert lauf["300"] > lauf["1200"] > lauf["3600"]


def test_die_radleistung_kommt_aus_watt_mal_zeit(kennwerte):
    """Die Zwift-Datei führt kein `accumulated_power` — die Rechnung geht trotzdem."""
    rad = kennwerte["rad_indoor_watt.zip"].bestwerte["bike"]

    assert rad == {"300": 130, "1200": 125, "3600": 119}
    # Die beste Stunde einer 91-min-Fahrt liegt nicht unter ihrem Schnitt.
    assert rad["3600"] >= 110


def test_im_becken_zaehlt_nur_freistil_am_stueck(kennwerte):
    """Am 15.09. stand Freistil höchstens vier Bahnen am Stück.

    Dazwischen Brust, Rücken und Pausen — zwei 50er mit Pause sind kein 100er,
    und ein 200er oder 400er kam in der ganzen Einheit nicht vor.
    """
    assert kennwerte["schwimmen_becken.zip"].bestwerte == {
        "swim": {"50": 60.7, "100": 152.2}
    }


def test_eine_falsch_erkannte_wende_unterbricht_die_folge():
    """Eine Bahn in fünf Sekunden ist kein Rekord, sondern ein Messfehler."""

    def bahn(zeit, art="active", stil="freestyle"):
        return {"length_type": art, "swim_stroke": stil, "total_timer_time": zeit}

    bahnen = [bahn(30), bahn(31), bahn(5), bahn(29), bahn(28), bahn(40, "idle", None),
              bahn(27), bahn(26, stil="breaststroke")]

    assert _beste_bahnzeiten(bahnen, 25.0) == {"50": 57.0}


def test_krafteinheit_hat_keine_bestwerte(kennwerte):
    assert kennwerte["kraft.zip"].bestwerte is None
