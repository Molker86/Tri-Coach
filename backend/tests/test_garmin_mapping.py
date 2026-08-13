"""Umrechnungen von Garmin-Daten — ohne Datenbank, ohne Netz.

Die Beispieldaten behalten absichtlich die krummen Formen des Originals
(Gewichte in Gramm, Geschwindigkeit in m/s, Sportart nur im verschachtelten
`activityType.typeKey`). Ein glattgebügeltes Beispiel würde genau die Fehler
verstecken, an denen das Mapping bricht.
"""

from datetime import date
from types import SimpleNamespace

import pytest

from app.garmin.mapping import (
    aktivitaet_zu_log,
    als_liste,
    erster_wert,
    gewicht_kg,
    hole,
    koppel_notiz,
    pace_aus_geschwindigkeit,
    schaetze_rpe,
    sport_aus_typkey,
    teile_multisport,
)


def test_hole_bricht_nicht_bei_fehlenden_feldern():
    assert hole({"a": {"b": 1}}, "a", "b") == 1
    assert hole({"a": {}}, "a", "b") is None
    assert hole({"a": None}, "a", "b", default=7) == 7
    assert hole(None, "a") is None
    # Listenindex — und ein zu kurzer Index darf nicht werfen
    assert hole({"xs": [{"v": 3}]}, "xs", 0, "v") == 3
    assert hole({"xs": []}, "xs", 0, "v") is None


def test_erster_wert_liest_beide_schlafformen():
    """`get_sleep_daily` und `get_sleep_data` verschachteln unterschiedlich."""
    aus_range = {"values": {"totalSleepSeconds": 27000}}
    aus_tag = {"dailySleepDTO": {"sleepTimeSeconds": 25200}}
    pfade = (
        ("values", "totalSleepSeconds"),
        ("dailySleepDTO", "sleepTimeSeconds"),
        ("sleepTimeSeconds",),
    )
    assert erster_wert(aus_range, *pfade) == 27000
    assert erster_wert(aus_tag, *pfade) == 25200
    assert erster_wert({}, *pfade, default=0) == 0


def test_als_liste_vertraegt_liste_und_umhuelltes_dict():
    """Die Bibliothek deklariert bei `get_activities` selbst `dict | list`."""
    assert als_liste([1, 2]) == [1, 2]
    assert als_liste({"activityList": [1]}, "activityList") == [1]
    assert als_liste({"anderes": [1]}, "activityList") == []
    assert als_liste(None) == []


@pytest.mark.parametrize(
    "typkey,erwartet",
    [
        ("running", "run"),
        ("trail_running", "run"),
        ("gravel_cycling", "bike"),
        ("lap_swimming", "swim"),
        ("strength_training", "strength"),
        ("yoga", "mobility"),
        ("multi_sport", "brick"),
        # Unbekannter Untertyp: über den Wortstamm erkannt statt verworfen
        ("virtual_trail_run", "run"),
        ("indoor_cycling_v2", "bike"),
        # Bewusst kein Training
        ("walking", None),
        ("golf", None),
        ("hiking", None),
        (None, None),
        ("voellig_unbekannt", None),
    ],
)
def test_sportart_aus_typkey(typkey, erwartet):
    assert sport_aus_typkey(typkey) == erwartet


@pytest.mark.parametrize(
    "sport,mps,erwartet",
    [
        # 3,333 m/s Laufen = 5:00 min/km
        ("run", 1000 / 300, "5:00"),
        # 2,78 m/s Rad = 10,0 km/h
        ("bike", 2.7778, "10.0"),
        # 1,25 m/s Schwimmen = 1:20 min/100 m
        ("swim", 1.25, "1:20"),
        ("run", 0, None),
        ("run", None, None),
        ("strength", 2.0, None),
    ],
)
def test_pace_aus_geschwindigkeit(sport, mps, erwartet):
    assert pace_aus_geschwindigkeit(sport, mps) == erwartet


def test_pace_rundung_erzeugt_keine_60_sekunden():
    """Ohne Übertrag käme bei knapper Rundung '4:60' heraus."""
    ergebnis = pace_aus_geschwindigkeit("run", 1000 / 299.6)
    assert ergebnis == "5:00"


def test_gewicht_kommt_in_gramm():
    assert gewicht_kg(78500.0) == 78.5
    assert gewicht_kg(None) is None


def test_rpe_aus_herzfrequenzzonen():
    """Zone-4-lastige Einheit muss über der Schwelle für 'intensiv' (7) landen."""
    aktivitaet = {
        "hrTimeInZone_1": 0.0,
        "hrTimeInZone_2": 300.0,
        "hrTimeInZone_3": 300.0,
        "hrTimeInZone_4": 1200.0,
        "hrTimeInZone_5": 0.0,
    }
    rpe, quelle = schaetze_rpe(aktivitaet)
    assert quelle == "hf_zonen"
    assert rpe >= 7


def test_rpe_faellt_auf_trainingseffekt_zurueck():
    rpe, quelle = schaetze_rpe(
        {"aerobicTrainingEffect": 3.4, "anaerobicTrainingEffect": 0.6}
    )
    assert quelle == "trainingseffekt"
    assert 1 <= rpe <= 10


def test_rpe_faellt_auf_durchschnittspuls_zurueck():
    profil = SimpleNamespace(resting_hr=45, max_hr=185)
    rpe, quelle = schaetze_rpe({"averageHR": 150}, profil)
    assert quelle == "hf_schnitt"
    # (150-45)/(185-45) = 0,75 → 8
    assert rpe == 8


def test_rpe_ohne_jede_grundlage_bleibt_leer():
    rpe, quelle = schaetze_rpe({})
    assert rpe is None
    assert quelle == "manual"


LAUF = {
    "activityId": 21482357291,
    "activityName": "Zürich Laufen",
    "activityType": {"typeId": 1, "typeKey": "running"},
    "startTimeLocal": "2026-08-12 07:14:23",
    "startTimeGMT": "2026-08-12 05:14:23",
    "duration": 3600.0,
    "distance": 12000.0,
    "elevationGain": 142.0,
    "averageSpeed": 1000 / 300,
    "averageRunningCadenceInStepsPerMinute": 178.0,
    "averageHR": 148.0,
    "maxHR": 172.0,
    "calories": 812.0,
    "avgPower": 280.0,
    "aerobicTrainingEffect": 3.4,
    "anaerobicTrainingEffect": 0.6,
    "activityTrainingLoad": 142.5,
    "hrTimeInZone_1": 210.0,
    "hrTimeInZone_2": 1420.0,
    "hrTimeInZone_3": 1502.0,
    "hrTimeInZone_4": 289.0,
    "hrTimeInZone_5": 0.0,
}


def test_aktivitaet_wird_zu_trainingseintrag():
    log = aktivitaet_zu_log(LAUF)
    assert log["date"] == date(2026, 8, 12)
    assert log["sport"] == "run"
    assert log["duration_min"] == 60
    assert log["distance_km"] == 12.0
    assert log["avg_pace"] == "5:00"
    assert log["avg_cadence"] == 178
    assert log["elevation_gain_m"] == 142
    assert log["source"] == "garmin"
    assert log["garmin_activity_id"] == "21482357291"
    assert log["garmin_training_load"] == 142.5
    assert log["rpe_source"] == "hf_zonen"


def test_laufleistung_landet_nicht_in_der_wattspalte():
    """`avg_power` ist die Radleistung — Laufleistung ist eine andere Größe."""
    assert aktivitaet_zu_log(LAUF)["avg_power"] is None
    rad = {**LAUF, "activityType": {"typeKey": "cycling"}}
    assert aktivitaet_zu_log(rad)["avg_power"] == 280


def test_trainingstag_ist_der_lokale_tag():
    """Kurz nach Mitternacht Ortszeit ist der UTC-Tag noch der Vortag."""
    spaet = {
        **LAUF,
        "startTimeLocal": "2026-08-13 00:30:00",
        "startTimeGMT": "2026-08-12 22:30:00",
    }
    assert aktivitaet_zu_log(spaet)["date"] == date(2026, 8, 13)


def test_spaziergang_wird_nicht_importiert():
    assert aktivitaet_zu_log({**LAUF, "activityType": {"typeKey": "walking"}}) is None


def test_aktivitaet_ohne_kennung_wird_uebersprungen():
    ohne = {k: v for k, v in LAUF.items() if k != "activityId"}
    assert aktivitaet_zu_log(ohne) is None


def test_multisport_wird_eine_koppeleinheit():
    eltern = {
        "activityId": 900,
        "activityType": {"typeKey": "multi_sport"},
        "isMultiSportParent": True,
        "startTimeLocal": "2026-07-05 09:00:00",
        "duration": 9000.0,
    }
    kinder = [
        {
            "activityId": 901,
            "parentId": 900,
            "activityType": {"typeKey": "lap_swimming"},
            "startTimeLocal": "2026-07-05 09:00:00",
            "distance": 1500.0,
        },
        {
            "activityId": 902,
            "parentId": 900,
            "activityType": {"typeKey": "cycling"},
            "startTimeLocal": "2026-07-05 09:30:00",
            "distance": 40000.0,
        },
        {
            "activityId": 903,
            "parentId": 900,
            "activityType": {"typeKey": "running"},
            "startTimeLocal": "2026-07-05 10:45:00",
            "distance": 10000.0,
        },
    ]

    zu_importieren, nach_eltern = teile_multisport([eltern, *kinder])

    assert [a["activityId"] for a in zu_importieren] == [900]
    assert len(nach_eltern["900"]) == 3
    assert aktivitaet_zu_log(eltern)["sport"] == "brick"

    notiz = koppel_notiz(nach_eltern["900"])
    assert "Schwimmen 1,5 km" in notiz
    assert "Radfahren 40,0 km" in notiz
    assert "Laufen 10,0 km" in notiz


def test_eigenstaendige_aktivitaet_mit_parentid_bleibt_erhalten():
    """Eine `parentId`, zu der kein Elternteil vorliegt, darf nichts verschlucken."""
    einzeln = {**LAUF, "parentId": 12345}
    zu_importieren, kinder = teile_multisport([einzeln])
    assert len(zu_importieren) == 1
    assert kinder == {}
