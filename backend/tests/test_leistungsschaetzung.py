"""Geschätzte Leistung für Radfahrten ohne Wattmessung.

Die Physik gegen Fälle, die sich von Hand nachrechnen lassen; der Weg durch die
FIT-Datei an Außenfahrten, die Garmins eigener Encoder schreibt. Eine echte
Außenfahrt gibt es als Fixture nicht — und sie trüge den Weg des Athleten.
"""

import io
import random
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from garmin_fit_sdk import Encoder, Profile
from sqlalchemy import text

from app import ai_export
from app.database import SessionLocal
from app.garmin.fitdaten import entpacke_fit, kennwerte_aus_fit
from app.garmin.leistungsschaetzung import (
    RADTYPEN,
    Probe,
    leistungsreihe,
    schaetze_leistung,
)

from fakes import baue_aktivitaet

HEUTE = date.today()
FIXTURES = Path(__file__).parent / "fixtures" / "fit"
RENNRAD = RADTYPEN["road_biking"]
# 75 kg Fahrer auf dem Rennrad.
MASSE = 75 + RENNRAD.rad_kg
KMH_30 = 30 / 3.6


def _fahrt(
    abschnitte: list[tuple[int, float, float]],
    *,
    rauschen_m: float = 0.0,
    pause: tuple[int, int] | None = None,
) -> list[Probe]:
    """Proben im Sekundentakt: je Abschnitt (Sekunden, m/s, Steigung).

    `pause` ist (nach wie vielen Sekunden, wie lange): Die Uhr steht, die
    Wanduhr läuft weiter.
    """
    zufall = random.Random(7)
    proben: list[Probe] = []
    zeit = strecke = 0.0
    hoehe = 100.0
    for sekunden, tempo, steigung in abschnitte:
        for _ in range(sekunden):
            proben.append(
                Probe(zeit, 1.0, strecke, hoehe + zufall.uniform(-rauschen_m, rauschen_m))
            )
            zeit += 1
            if pause and len(proben) == pause[0]:
                zeit += pause[1]
            strecke += tempo
            hoehe += tempo * steigung
    letzte = proben[-1]
    proben[-1] = Probe(letzte.zeit_s, 0.0, letzte.strecke_m, letzte.hoehe_m)
    return proben


# --------------------------------------------------------------------------
# Physik
# --------------------------------------------------------------------------


def test_in_der_ebene_zaehlen_roll_und_luftwiderstand():
    """(83,5·9,81·8,33·0,0045 + ½·1,213·0,32·8,33³) / 0,976 ≈ 147 W."""
    werte = schaetze_leistung(_fahrt([(600, KMH_30, 0.0)]), MASSE, RENNRAD)
    assert werte == {"schnitt_w": 147, "normalisiert_w": 147, "beste_minute_w": 147}


def test_am_anstieg_zaehlt_das_gewicht():
    """5 % bei 4 m/s: Hangabtrieb 163 W von 195 W — und 15 kg mehr kosten 33 W."""
    leicht = schaetze_leistung(_fahrt([(600, 4.0, 0.05)]), MASSE, RENNRAD)
    schwer = schaetze_leistung(_fahrt([(600, 4.0, 0.05)]), MASSE + 15, RENNRAD)
    assert leicht["schnitt_w"] == 195
    assert schwer["schnitt_w"] - leicht["schnitt_w"] == pytest.approx(33, abs=1)


def test_bergab_rollt_mit_null_watt():
    """Keine negative Leistung — und der Schnitt zählt das Rollen mit, wie Garmin."""
    proben = _fahrt([(600, KMH_30, 0.0), (600, 12.0, -0.06)])
    watt = leistungsreihe(proben, MASSE, RENNRAD)
    assert min(watt) == 0.0
    assert schaetze_leistung(proben, MASSE, RENNRAD)["schnitt_w"] == pytest.approx(
        147 / 2, abs=2
    )


def test_eine_timerpause_zaehlt_nicht():
    mit_pause = schaetze_leistung(
        _fahrt([(600, KMH_30, 0.0)], pause=(300, 240)), MASSE, RENNRAD
    )
    assert mit_pause["schnitt_w"] == 147
    assert mit_pause["normalisiert_w"] == 147


def test_die_beste_minute_springt_nicht_ueber_eine_pause():
    """Zwei harte halbe Minuten vor und nach der Ampel sind keine harte Minute."""
    proben = _fahrt(
        [(300, KMH_30, 0.0), (30, 4.0, 0.08), (30, 4.0, 0.08), (300, KMH_30, 0.0)],
        pause=(330, 120),
    )
    ohne_pause = _fahrt(
        [(300, KMH_30, 0.0), (30, 4.0, 0.08), (30, 4.0, 0.08), (300, KMH_30, 0.0)]
    )
    assert (
        schaetze_leistung(proben, MASSE, RENNRAD)["beste_minute_w"]
        < schaetze_leistung(ohne_pause, MASSE, RENNRAD)["beste_minute_w"]
    )


def test_hoehenrauschen_wird_keine_rampe():
    """±0,5 m Barometerzittern in der Ebene verschiebt den Schnitt kaum."""
    werte = schaetze_leistung(_fahrt([(600, KMH_30, 0.0)], rauschen_m=0.5), MASSE, RENNRAD)
    assert werte["schnitt_w"] == pytest.approx(147, rel=0.05)


def test_wechselndes_tempo_hebt_np_und_beste_minute():
    proben = _fahrt([(120, 10.0, 0.0), (120, 5.0, 0.0)] * 5)
    werte = schaetze_leistung(proben, MASSE, RENNRAD)
    assert werte["normalisiert_w"] > werte["schnitt_w"]
    assert werte["beste_minute_w"] > werte["normalisiert_w"]


def test_unter_einer_minute_gibt_es_nichts():
    assert schaetze_leistung(_fahrt([(45, KMH_30, 0.0)]), MASSE, RENNRAD) is None


# --------------------------------------------------------------------------
# Aus der FIT-Datei
# --------------------------------------------------------------------------

_MESG = Profile["mesg_num"]
_START = datetime(2026, 9, 12, 8, 0, tzinfo=timezone.utc)


def _fit(
    *,
    sekunden: int = 600,
    tempo: float = KMH_30,
    steigung: float = 0.0,
    gewicht: float | None = 75.0,
    watt: int | None = None,
) -> bytes:
    """Eine Außenfahrt, wie die Uhr sie schreibt: Records im Sekundentakt."""
    encoder = Encoder()
    encoder.write_mesg(
        {"mesg_num": _MESG["FILE_ID"], "type": "activity", "manufacturer": "garmin",
         "time_created": _START}
    )
    if gewicht is not None:
        encoder.write_mesg({"mesg_num": _MESG["USER_PROFILE"], "weight": gewicht})
    encoder.write_mesg(
        {"mesg_num": _MESG["EVENT"], "timestamp": _START, "event": "timer",
         "event_type": "start"}
    )
    for s in range(sekunden):
        record = {
            "mesg_num": _MESG["RECORD"],
            "timestamp": _START + timedelta(seconds=s),
            "distance": tempo * s,
            "enhanced_altitude": 100.0 + tempo * s * steigung,
            "enhanced_speed": tempo,
            "heart_rate": 140,
        }
        if watt is not None:
            record["power"] = watt
        encoder.write_mesg(record)
    ende = _START + timedelta(seconds=sekunden - 1)
    encoder.write_mesg(
        {"mesg_num": _MESG["EVENT"], "timestamp": ende, "event": "timer",
         "event_type": "stop_all"}
    )
    encoder.write_mesg(
        {"mesg_num": _MESG["SESSION"], "timestamp": ende, "start_time": _START,
         "sport": "cycling", "sub_sport": "road",
         "total_elapsed_time": float(sekunden - 1), "total_timer_time": float(sekunden - 1)}
    )
    encoder.write_mesg({"mesg_num": _MESG["ACTIVITY"], "timestamp": ende, "num_sessions": 1})
    return encoder.close()


def _als_zip(fit: bytes) -> bytes:
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as archiv:
        archiv.writestr("1_ACTIVITY.fit", fit)
    return puffer.getvalue()


def test_eine_aussenfahrt_bekommt_eine_schaetzung():
    kennwerte = kennwerte_aus_fit(_fit(), radtyp="road_biking")
    assert kennwerte.leistung_geschaetzt == {
        "schnitt_w": 147, "normalisiert_w": 147, "beste_minute_w": 147,
    }
    # Die Rad-Bestwerte rechnen nur mit Messung — sonst meldete eine
    # Schätzung ohne Wind eine veraltete FTP.
    assert kennwerte.bestwerte is None


def test_das_gewicht_der_uhr_geht_dem_profil_vor():
    """Die Uhr kennt das Gewicht vom Tag der Fahrt, das Profil nur das heutige."""
    anstieg = _fit(tempo=4.0, steigung=0.05)
    assert kennwerte_aus_fit(anstieg, radtyp="road_biking", gewicht_kg=95.0) == (
        kennwerte_aus_fit(anstieg, radtyp="road_biking")
    )


def test_ohne_gewicht_in_der_datei_zaehlt_das_profil():
    ohne = _fit(tempo=4.0, steigung=0.05, gewicht=None)
    assert kennwerte_aus_fit(ohne, radtyp="road_biking").leistung_geschaetzt is None
    mit_profil = kennwerte_aus_fit(ohne, radtyp="road_biking", gewicht_kg=75.0)
    assert mit_profil.leistung_geschaetzt["schnitt_w"] == 195


@pytest.mark.parametrize(
    "radtyp", ["e_bike_fitness", "indoor_cycling", "virtual_ride", "recumbent_cycling", None]
)
def test_nur_die_bekannten_radtypen_werden_geschaetzt(radtyp):
    """Ein E-Bike schiebt ein Motor, drinnen misst ein Gerät."""
    assert kennwerte_aus_fit(_fit(), radtyp=radtyp).leistung_geschaetzt is None


def test_gemessene_leistung_gewinnt():
    kennwerte = kennwerte_aus_fit(_fit(watt=210), radtyp="road_biking")
    assert kennwerte.leistung_geschaetzt is None
    assert kennwerte.bestwerte == {"bike": {"300": 210}}


def test_die_zwift_fahrt_misst_selbst():
    """Auch falsch als Straßenfahrt eingeordnet: Wo Watt stehen, zählen sie."""
    fit = entpacke_fit((FIXTURES / "rad_indoor_watt.zip").read_bytes())
    assert kennwerte_aus_fit(fit, radtyp="road_biking").leistung_geschaetzt is None


def test_ein_lauf_bekommt_keine_radleistung():
    fit = entpacke_fit((FIXTURES / "lauf_lang.zip").read_bytes())
    assert kennwerte_aus_fit(fit, radtyp="road_biking").leistung_geschaetzt is None


# --------------------------------------------------------------------------
# Abgleich
# --------------------------------------------------------------------------


def _backfill(client, auth) -> dict:
    antwort = client.post(
        "/api/garmin/backfill",
        json={"von": (HEUTE - timedelta(days=10)).isoformat()},
        headers=auth,
    )
    assert antwort.status_code == 202, antwort.text
    return client.get(f"/api/garmin/jobs/{antwort.json()['id']}", headers=auth).json()


def _gespeichert(kennung: int) -> str | None:
    with SessionLocal() as db:
        return db.execute(
            text("SELECT leistung_geschaetzt FROM session_logs WHERE garmin_activity_id = :k"),
            {"k": str(kennung)},
        ).scalar_one()


def test_der_abgleich_speichert_die_schaetzung(client, verbunden, fake):
    fake._aktivitaeten = [
        baue_aktivitaet(4901, HEUTE - timedelta(days=1), typkey="gravel_cycling",
                        dauer_s=600, distanz_m=5000)
    ]
    fake.originale["4901"] = _als_zip(_fit())

    _backfill(client, verbunden)

    assert '"schnitt_w"' in _gespeichert(4901)
    einheit = next(
        log for log in client.get("/api/logs", headers=verbunden).json()
        if log["garmin_activity_id"] == "4901"
    )
    assert einheit["avg_power"] is None
    # Gravel rollt schwerer und sitzt aufrechter als das Rennrad.
    assert einheit["leistung_geschaetzt"]["schnitt_w"] > 147


def test_ein_e_bike_bleibt_ohne_schaetzung(client, verbunden, fake):
    fake._aktivitaeten = [
        baue_aktivitaet(4902, HEUTE - timedelta(days=1), typkey="e_bike_fitness",
                        dauer_s=600, distanz_m=5000)
    ]
    fake.originale["4902"] = _als_zip(_fit())

    _backfill(client, verbunden)

    assert _gespeichert(4902) is None


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mit_schaetzung(client, registriere, erfasse):
    kopf = registriere("schaetzung@example.com", "schaetzung")
    erfasse(
        kopf, date=HEUTE - timedelta(days=2), sport="bike", duration_min=90,
        distance_km=42.0, avg_hr=138, garmin_activity_type="gravel_cycling",
        leistung_geschaetzt={"schnitt_w": 152, "normalisiert_w": 171, "beste_minute_w": 318},
    )
    # Gemessen und geschätzt zugleich entsteht im Abgleich nicht; stünde es
    # doch da, gewinnt die Messung.
    erfasse(
        kopf, date=HEUTE - timedelta(days=4), sport="bike", duration_min=60,
        distance_km=30.0, avg_hr=140, avg_power=180,
        leistung_geschaetzt={"schnitt_w": 150},
    )
    return client.get("/api/plans/export", headers=kopf).json()


def _einheit(paket: dict, tag: date) -> dict:
    return next(
        e for e in paket["payload"]["trainingshistorie"]["einheiten"]
        if e["datum"] == tag.isoformat()
    )


def test_die_schaetzung_steht_unter_eigenem_namen(mit_schaetzung):
    einheit = _einheit(mit_schaetzung, HEUTE - timedelta(days=2))
    assert einheit["leistung_watt"] is None
    assert einheit["leistung_watt_geschaetzt"] == 152
    assert einheit["normalisierte_leistung_geschaetzt"] == 171
    assert einheit["beste_minute_watt_geschaetzt"] == 318
    # Watt je Herzschlag nur aus Messung: Die Effizienz je Monat zeigte sonst
    # den Anteil der Schätzungen statt der Form.
    assert "effizienz" not in einheit


def test_neben_einer_messung_steht_keine_schaetzung(mit_schaetzung):
    einheit = _einheit(mit_schaetzung, HEUTE - timedelta(days=4))
    assert einheit["leistung_watt"] == 180
    assert "leistung_watt_geschaetzt" not in einheit


def test_der_prompt_nennt_die_schaetzung(mit_schaetzung):
    prompt = mit_schaetzung["prompt"]
    assert "ohne Wind und Windschatten" in prompt
    assert "leistung_watt_geschaetzt" in prompt.split("## Datenpaket")[-1]
    # Dieselbe Grenze wie `test_der_anweisungstext_bleibt_kurz` — dort ohne
    # Schätzung, also ohne diesen Satz.
    assert len(prompt.split("## Ausgabeformat")[0]) < 9500


def test_ohne_schaetzung_kein_hinweis(client, registriere, erfasse):
    kopf = registriere("ohne-schaetzung@example.com", "ohneschaetzung")
    erfasse(kopf, date=HEUTE - timedelta(days=1), sport="run", duration_min=40,
            distance_km=8.0)
    prompt = client.get("/api/plans/export", headers=kopf).json()["prompt"]
    assert "leistung_watt_geschaetzt" not in prompt


def test_auch_die_analyse_nennt_die_schaetzung():
    mit = ai_export.build_analyse_prompt(
        {"analyse": {"sportart": "bike"}, "training": {"leistung_watt_geschaetzt": 152}}
    )
    ohne = ai_export.build_analyse_prompt(
        {"analyse": {"sportart": "bike"}, "training": {"leistung_watt": 180}}
    )
    assert "ohne Wind und Windschatten" in mit
    assert "ohne Wind und Windschatten" not in ohne


# --------------------------------------------------------------------------
# Nachholen
# --------------------------------------------------------------------------


def test_ausgewertete_fahrten_stehen_einmal_wieder_offen(tmp_path):
    """Nur Radfahrten ohne Messung — und nur im Lauf, der die Spalte anlegt."""
    import sqlalchemy as sa

    from app.database import _ergaenze_spalten, _setze_altwerte_zurueck

    alt = sa.create_engine(f"sqlite:///{tmp_path / 'vor_schaetzung.db'}")
    with alt.begin() as verbindung:
        verbindung.exec_driver_sql(
            "CREATE TABLE session_logs (id INTEGER PRIMARY KEY, sport VARCHAR(32),"
            " avg_power INTEGER, duration_min INTEGER, fit_ausgewertet_am DATETIME)"
        )
        # Alle drei unter 45 min: Die Entkopplung rüstet im selben Lauf nach
        # und öffnet die langen Lauf- und Radeinheiten (siehe
        # `test_entkopplung.py`) — hier soll nur die Schätzung greifen.
        verbindung.exec_driver_sql(
            "INSERT INTO session_logs VALUES (1, 'bike', NULL, 40, '2026-09-01'),"
            " (2, 'bike', 190, 40, '2026-09-01'), (3, 'run', NULL, 40, '2026-09-01')"
        )

    with alt.begin() as verbindung:
        ergaenzt = _ergaenze_spalten(verbindung)
        assert "session_logs.leistung_geschaetzt" in ergaenzt
        assert _setze_altwerte_zurueck(verbindung, ergaenzt) == ["session_logs (1)"]
        offen = verbindung.exec_driver_sql(
            "SELECT id FROM session_logs WHERE fit_ausgewertet_am IS NULL"
        ).scalars().all()
        assert offen == [1]

    with alt.begin() as verbindung:
        verbindung.exec_driver_sql(
            "UPDATE session_logs SET fit_ausgewertet_am = '2026-09-02' WHERE id = 1"
        )
        assert _setze_altwerte_zurueck(verbindung, _ergaenze_spalten(verbindung)) == []
