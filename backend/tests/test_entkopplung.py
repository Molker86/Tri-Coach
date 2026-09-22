"""Die aerobe Entkopplung aus der Original-Aufzeichnung — bis in den Prompt.

Zwei Wege hierher: die echten Aufzeichnungen aus `fixtures/fit/` und
zusammengesetzte FIT-Dateien. Beide braucht es. Die echten sagen, was am
wirklichen Konto herauskommt — nämlich an den meisten Einheiten **nichts**, und
genau das ist die Aussage: Der bergige Dauerlauf und die Krafteinheit tragen
keinen Wert. Der Fall, auf den es ankommt (gleichmäßig, lang, mit sauberem
Pulsverlauf), liegt als Fixture nicht vor, und ihn aus einem Konto
nachzuladen hieße, den Weg des Athleten abzulegen. Deshalb daneben Dateien mit
von Hand gesetztem Puls: Nur so lässt sich eine Entkopplung prüfen, deren
Prozentzahl sich nachrechnen lässt.
"""

import io
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from garmin_fit_sdk import Encoder, Profile
from sqlalchemy import text

from app import ai_export
from app.database import SessionLocal
from app.garmin.fitdaten import entpacke_fit, kennwerte_aus_fit

from fakes import baue_aktivitaet

HEUTE = date.today()
FIXTURES = Path(__file__).parent / "fixtures" / "fit"

_MESG = Profile["mesg_num"]
_START = datetime(2026, 9, 12, 8, 0, tzinfo=timezone.utc)

# Die Aufzeichnung läuft eine Stunde: zehn Minuten Einfahren, danach zwei
# Hälften von je 25 Minuten. Die Grenze zwischen ihnen liegt damit auf Sekunde
# 2100 — an ihr wechseln die Tests den Puls, und die Prozentzahl ist von Hand
# nachzurechnen.
_DAUER_S = 3600
_MITTE_S = 2100


def _aufzeichnung(
    *,
    sport: str = "cycling",
    sub_sport: str = "generic",
    sekunden: int = _DAUER_S,
    puls=lambda s: 130,
    watt=lambda s: 150,
    tempo=lambda s: 3.0,
    anstieg_m: float | None = 40.0,
    mit_watt: bool = True,
) -> bytes:
    """Eine Einheit im Sekundentakt, Puls und Leistung als Funktion der Sekunde.

    `sekunden` Records ergeben `sekunden - 1` wirksame Sekunden: Der letzte
    Record hat keinen Nachfolger und damit keine Dauer (`_wirksame_dauern`).
    """
    encoder = Encoder()
    encoder.write_mesg(
        {"mesg_num": _MESG["FILE_ID"], "type": "activity", "manufacturer": "garmin",
         "time_created": _START}
    )
    encoder.write_mesg(
        {"mesg_num": _MESG["EVENT"], "timestamp": _START, "event": "timer",
         "event_type": "start"}
    )
    strecke = 0.0
    for s in range(sekunden):
        record = {
            "mesg_num": _MESG["RECORD"],
            "timestamp": _START + timedelta(seconds=s),
            "distance": strecke,
            "enhanced_altitude": 100.0,
            "enhanced_speed": tempo(s),
        }
        if (schlag := puls(s)) is not None:
            record["heart_rate"] = schlag
        if mit_watt:
            record["power"] = watt(s)
        encoder.write_mesg(record)
        strecke += tempo(s)

    ende = _START + timedelta(seconds=sekunden - 1)
    encoder.write_mesg(
        {"mesg_num": _MESG["EVENT"], "timestamp": ende, "event": "timer",
         "event_type": "stop_all"}
    )
    session = {
        "mesg_num": _MESG["SESSION"], "timestamp": ende, "start_time": _START,
        "sport": sport, "sub_sport": sub_sport,
        "total_elapsed_time": float(sekunden - 1),
        "total_timer_time": float(sekunden - 1),
        "total_distance": strecke,
    }
    if anstieg_m is not None:
        session["total_ascent"] = anstieg_m
    encoder.write_mesg(session)
    encoder.write_mesg({"mesg_num": _MESG["ACTIVITY"], "timestamp": ende, "num_sessions": 1})
    return encoder.close()


def _entkopplung(**bauteile) -> float | None:
    return kennwerte_aus_fit(_aufzeichnung(**bauteile)).entkopplung_pct


def _als_zip(fit: bytes) -> bytes:
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as archiv:
        archiv.writestr("1_ACTIVITY.fit", fit)
    return puffer.getvalue()


# --------------------------------------------------------------------------
# Die Rechnung
# --------------------------------------------------------------------------


def test_der_pulsanstieg_bei_gleicher_leistung_ist_die_entkopplung():
    """130 → 143 bpm bei festen 150 W: 1 − 130/143 = 9,1 %."""
    assert _entkopplung(puls=lambda s: 130 if s < _MITTE_S else 143) == 9.1


def test_ein_leistungseinbruch_zaehlt_genauso():
    """Der Puls hält, die Watt fallen um ein Zehntel — dieselbe Entkopplung."""
    assert _entkopplung(watt=lambda s: 150 if s < _MITTE_S else 135) == 10.0


def test_wer_durchhaelt_hat_keine_entkopplung():
    assert _entkopplung() == 0.0


def test_ein_frischerer_zweiter_teil_faellt_negativ_aus():
    """Kein Betrag: Ein sinkender Puls bei gleicher Leistung ist das Gegenteil."""
    assert _entkopplung(puls=lambda s: 143 if s < _MITTE_S else 130) == pytest.approx(
        -10.0, abs=0.1
    )


def test_das_einfahren_zaehlt_nicht_mit():
    """Die ersten zehn Minuten fehlen — sonst wäre jede Einheit entkoppelt.

    Der Puls hinkt dem Tempo am Anfang hinterher; hier steht er die ersten
    zehn Minuten bei 105 und danach durchgehend bei 130. Über die ganze Datei
    gerechnet ergäbe das eine satte Entkopplung, tatsächlich ist es das
    Einfahren.
    """
    assert _entkopplung(puls=lambda s: 105 if s < 600 else 130) == 0.0


# --------------------------------------------------------------------------
# Wo keine entsteht
# --------------------------------------------------------------------------


def test_unter_45_minuten_gibt_es_nichts():
    """40 min: Nach dem Einfahren bleiben keine 35 übrig."""
    assert _entkopplung(sekunden=40 * 60) is None


def test_intervalle_ergeben_keinen_wert():
    """Vier Minuten hart, vier Minuten Pause — dazwischen bedeutet der Quotient nichts."""
    hart = _entkopplung(
        watt=lambda s: 260 if (s // 240) % 2 == 0 else 90,
        puls=lambda s: 165 if (s // 240) % 2 == 0 else 120,
    )
    assert hart is None


def test_ohne_wattmessung_bleibt_die_fahrt_ohne_wert():
    """Tempo gegen Puls ist auf dem Rad Wind und Windschatten."""
    assert _entkopplung(mit_watt=False, puls=lambda s: 130 if s < _MITTE_S else 143) is None


def test_ein_flacher_lauf_zaehlt_ueber_das_tempo():
    assert _entkopplung(
        sport="running", mit_watt=False, anstieg_m=40.0,
        puls=lambda s: 130 if s < _MITTE_S else 143,
    ) == 9.1


def test_ein_welliger_lauf_bleibt_ohne_wert():
    """410 Höhenmeter auf 10,8 km: Gemessen würde das Profil, nicht der Athlet."""
    assert _entkopplung(
        sport="running", mit_watt=False, anstieg_m=410.0,
        puls=lambda s: 130 if s < _MITTE_S else 143,
    ) is None


def test_ohne_hoehenangabe_gilt_ein_lauf_nicht_als_flach():
    """Eine fehlende Messung ist kein Beleg für flaches Gelände."""
    assert _entkopplung(
        sport="running", mit_watt=False, anstieg_m=None,
        puls=lambda s: 130 if s < _MITTE_S else 143,
    ) is None


def test_auf_dem_laufband_gibt_es_keine_entkopplung():
    """Dort schätzt die Uhr die Strecke aus dem Armschwung — wie beim Bestwert."""
    assert _entkopplung(
        sport="running", sub_sport="treadmill", mit_watt=False,
        puls=lambda s: 130 if s < _MITTE_S else 143,
    ) is None


def test_eine_pulsluecke_verwirft_die_einheit():
    """Ein Gurt, der die letzte Viertelstunde aussetzt, ergäbe sonst eine Entkopplung."""
    assert _entkopplung(puls=lambda s: None if s > _DAUER_S - 900 else 130) is None


def test_eine_kurze_pulsluecke_traegt_den_wert_weiter():
    """Zwei Minuten Aussetzer sind kein Grund, die Einheit wegzuwerfen."""
    assert _entkopplung(
        puls=lambda s: None if 1800 < s < 1920 else (130 if s < _MITTE_S else 143)
    ) == pytest.approx(9.1, abs=0.3)


# --------------------------------------------------------------------------
# Gegen die echten Aufzeichnungen
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def kennwerte():
    return {
        name: kennwerte_aus_fit(entpacke_fit((FIXTURES / name).read_bytes()))
        for name in (
            "rad_indoor_watt.zip", "lauf_lang.zip", "lauf_workout.zip",
            "kraft.zip", "schwimmen_becken.zip",
        )
    }


def test_die_zwift_fahrt_traegt_einen_wert(kennwerte):
    """91 min mit Powermeter, gleichmäßig gefahren — 123 W auf 95 W bei fallendem Puls."""
    assert kennwerte["rad_indoor_watt.zip"].entkopplung_pct == pytest.approx(13.5, abs=0.1)


@pytest.mark.parametrize(
    "name, grund",
    [
        ("lauf_lang.zip", "410 Höhenmeter auf 11,3 km"),
        ("lauf_workout.zip", "neun Minuten"),
        ("kraft.zip", "keine Dauerbelastung"),
        ("schwimmen_becken.zip", "Schwimmen hat keine"),
    ],
)
def test_die_uebrigen_aufzeichnungen_tragen_keinen(kennwerte, name, grund):
    assert kennwerte[name].entkopplung_pct is None, grund


# --------------------------------------------------------------------------
# Abgleich
# --------------------------------------------------------------------------


def test_der_abgleich_schreibt_die_entkopplung(client, verbunden, fake):
    fake._aktivitaeten = [
        baue_aktivitaet(5201, HEUTE - timedelta(days=1), typkey="indoor_cycling")
    ]
    fake.originale["5201"] = (FIXTURES / "rad_indoor_watt.zip").read_bytes()

    antwort = client.post(
        "/api/garmin/backfill",
        json={"von": (HEUTE - timedelta(days=3)).isoformat()},
        headers=verbunden,
    )
    assert antwort.status_code == 202, antwort.text
    client.get(f"/api/garmin/jobs/{antwort.json()['id']}", headers=verbunden)

    with SessionLocal() as db:
        # Per SQL, weil die Spalte bewusst nicht in `SessionLogOut` steht.
        wert = db.execute(
            text(
                "SELECT entkopplung_pct FROM session_logs "
                "WHERE garmin_activity_id = '5201'"
            )
        ).scalar_one()
    assert wert == pytest.approx(13.5, abs=0.1)


def test_lange_einheiten_stehen_einmal_wieder_offen(tmp_path):
    """Die Historie trägt die Entkopplung — dafür wird sie einmal nachgeholt."""
    import sqlalchemy as sa

    from app.database import _ergaenze_spalten, _setze_altwerte_zurueck

    alt = sa.create_engine(f"sqlite:///{tmp_path / 'vor_entkopplung.db'}")
    with alt.begin() as verbindung:
        verbindung.exec_driver_sql(
            "CREATE TABLE session_logs (id INTEGER PRIMARY KEY, sport VARCHAR(32),"
            " avg_power INTEGER, duration_min INTEGER, fit_ausgewertet_am DATETIME)"
        )
        verbindung.exec_driver_sql(
            "INSERT INTO session_logs VALUES"
            " (1, 'bike', 190, 120, '2026-09-01'),"   # lang genug
            " (2, 'run', NULL, 90, '2026-09-01'),"    # lang genug
            " (3, 'run', NULL, 30, '2026-09-01'),"    # zu kurz
            " (4, 'swim', NULL, 75, '2026-09-01')"    # falsche Sportart
        )

    with alt.begin() as verbindung:
        ergaenzt = _ergaenze_spalten(verbindung)
        assert "session_logs.entkopplung_pct" in ergaenzt
        _setze_altwerte_zurueck(verbindung, ergaenzt)
        offen = verbindung.exec_driver_sql(
            "SELECT id FROM session_logs WHERE fit_ausgewertet_am IS NULL"
        ).scalars().all()
    assert offen == [1, 2]

    # Nur im Lauf der Ergänzung: Danach bliebe jeder Neustart bei den Dateien
    # hängen, die er gerade erst geholt hat.
    with alt.begin() as verbindung:
        verbindung.exec_driver_sql("UPDATE session_logs SET fit_ausgewertet_am = '2026-09-02'")
        assert _setze_altwerte_zurueck(verbindung, _ergaenze_spalten(verbindung)) == []


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def athlet(client, registriere, erfasse):
    kopf = registriere("entkopplung@example.com", "entkopplung")
    assert client.put(
        "/api/profile", headers=kopf, json={"max_hr": 189, "resting_hr": 58}
    ).status_code == 200

    erfasse(kopf, date=HEUTE - timedelta(days=3), sport="bike", duration_min=120,
            distance_km=70.0, avg_hr=131, avg_power=178, entkopplung_pct=3.4)
    # Ohne Wert: Die Einheit war zu kurz, um eine zu tragen.
    erfasse(kopf, date=HEUTE - timedelta(days=2), sport="run", duration_min=35,
            distance_km=7.0, avg_hr=144)
    # Im Saisonfenster, aber außerhalb der sechs Wochen — nur die Tabelle
    # reicht so weit zurück.
    erfasse(kopf, date=HEUTE - timedelta(weeks=10), sport="run", duration_min=95,
            distance_km=17.0, avg_hr=138, entkopplung_pct=8.2)
    # Älter als das Saisonfenster: zählt nirgends mehr.
    erfasse(kopf, date=HEUTE - timedelta(days=220), sport="run", duration_min=100,
            distance_km=18.0, avg_hr=140, entkopplung_pct=12.5)
    return kopf


@pytest.fixture(scope="module")
def paket(client, athlet):
    return client.get("/api/plans/export", headers=athlet).json()


def test_die_einheit_traegt_ihre_entkopplung(paket):
    einheiten = paket["payload"]["trainingshistorie"]["einheiten"]
    lang = next(e for e in einheiten if e["dauer_min"] == 120)
    kurz = next(e for e in einheiten if e["dauer_min"] == 35)
    assert lang["entkopplung_pct"] == 3.4
    # Kein `null`: Das wäre eine Aussage über eine Einheit, die keine trägt.
    assert "entkopplung_pct" not in kurz


def test_die_tabelle_reicht_weiter_zurueck_als_die_einheiten(paket):
    tabelle = paket["payload"]["athlet"]["entkopplung"]
    assert [zeile["datum"] for zeile in tabelle] == [
        (HEUTE - timedelta(weeks=10)).isoformat(),
        (HEUTE - timedelta(days=3)).isoformat(),
    ]
    assert tabelle[0] == {
        "datum": (HEUTE - timedelta(weeks=10)).isoformat(),
        "sportart": "run",
        "dauer_min": 95,
        "hf_schnitt": 138,
        "entkopplung_pct": 8.2,
    }


def test_die_tabelle_steht_im_prompt(paket):
    assert "### athlet.entkopplung" in paket["prompt"]


def test_der_prompt_erklaert_die_zahl(paket):
    anweisung = paket["prompt"].split("## Datenpaket")[0]
    assert "aerobe Entkopplung" in anweisung
    # Der wichtigste Teil des Satzes: woran ein **fehlender** Wert liegt. Ohne
    # ihn läse die KI die Lücken als Aussage über die Einheiten.
    assert "ab 45 min" in anweisung
    assert "keine Aussage über sie" in anweisung


def test_der_satz_nennt_keine_schwelle():
    """Ab wann eine Entkopplung zu hoch ist, ist Trainingslehre.

    Dieselbe Bremse wie `test_der_prompt_gibt_die_trainingslehre_nicht_vor`,
    nur für diesen einen Absatz: Eine Prozentzahl darin wäre eine Vorgabe, und
    die App hat keine. Die Längengrenze hält ihn daneben davon ab, zum Aufsatz
    zu werden — der Anweisungsteil ist schon ohne ihn an seiner Grenze.
    """
    import re

    satz = ai_export._entkopplungshinweis(
        {"trainingshistorie": {"einheiten": [{"entkopplung_pct": 5.0}]}}
    )
    assert not re.search(r"\d\s*%", satz)
    assert len(satz) < 700


def test_ohne_entkopplung_kein_hinweis(client, registriere, erfasse):
    kopf = registriere("ohne-entkopplung@example.com", "ohneentkopplung")
    erfasse(kopf, date=HEUTE - timedelta(days=1), sport="run", duration_min=40,
            distance_km=8.0, avg_hr=140)
    prompt = client.get("/api/plans/export", headers=kopf).json()["prompt"]
    assert "entkopplung_pct" not in prompt


def test_auch_die_analyse_erklaert_die_zahl():
    mit = ai_export.build_analyse_prompt(
        {"analyse": {"sportart": "bike"}, "training": {"entkopplung_pct": 4.1}}
    )
    ohne = ai_export.build_analyse_prompt(
        {"analyse": {"sportart": "bike"}, "training": {"leistung_watt": 180}}
    )
    assert "aerobe Entkopplung" in mit
    assert "aerobe Entkopplung" not in ohne
