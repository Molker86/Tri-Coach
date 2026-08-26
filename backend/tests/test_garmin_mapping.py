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
    abschnitte_aus_detail,
    aktivitaet_zu_log,
    als_liste,
    bestzeiten,
    bewertung_aus_detail,
    erster_wert,
    gewicht_kg,
    hole,
    koppel_notiz,
    pace_aus_geschwindigkeit,
    schaetze_rpe,
    schwellenpuls,
    sport_aus_typkey,
    uebungen_aus_saetzen,
    detail_zu_feldern,
    teile_multisport,
    zonensekunden,
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
        # Unter dieser Sportart überträgt die App ihre Mobility-Einheiten —
        # sie muss auch zurückfinden.
        ("mobility", "mobility"),
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


def test_bewertung_rechnet_auf_die_skala_des_athleten_zurueck():
    """Garmin speichert beides mal zehn — bewertet wird von 0/1 bis 10."""
    detail = {"summaryDTO": {"directWorkoutRpe": 60, "directWorkoutFeel": 75}}
    # Die 7,5 kommt von der Uhr: Sie bietet fünf Stufen statt der Skala an.
    assert bewertung_aus_detail(detail) == {"rpe": 6, "feel": 7.5}


def test_bewertung_fehlt_an_den_meisten_einheiten():
    assert bewertung_aus_detail({"summaryDTO": {"averageHR": 148}}) == {
        "rpe": None,
        "feel": None,
    }
    assert bewertung_aus_detail({}) == {"rpe": None, "feel": None}


def test_befinden_null_ist_ein_wert_rpe_null_dagegen_nicht():
    """"Sehr schwach" ist eine Aussage — ein RPE 0 wäre kein Training."""
    bewertung = bewertung_aus_detail(
        {"summaryDTO": {"directWorkoutFeel": 0, "directWorkoutRpe": 0}}
    )
    assert bewertung["feel"] == 0
    assert bewertung["rpe"] is None




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


def test_bewertung_des_athleten_schlaegt_die_schaetzung():
    log = aktivitaet_zu_log(LAUF, None, {"rpe": 4, "feel": 2.5})
    assert log["rpe"] == 4
    assert log["rpe_source"] == "athlet"
    assert log["garmin_feel"] == 2.5

    # Ohne eingetragenes RPE bleibt die Schätzung — das Befinden kommt trotzdem
    # mit, die beiden Felder hängen in Connect nicht aneinander.
    ohne_rpe = aktivitaet_zu_log(LAUF, None, {"rpe": None, "feel": 10.0})
    assert ohne_rpe["rpe_source"] == "hf_zonen"
    assert ohne_rpe["garmin_feel"] == 10.0


def test_ohne_detailabruf_fehlen_die_bewertungsfelder_ganz():
    """Sonst überschriebe ein Lauf ohne Detail eine früher geholte Bewertung."""
    assert "garmin_feel" not in aktivitaet_zu_log(LAUF)
    # Nachgesehen und nichts gefunden ist etwas anderes: Dann steht die Antwort
    # ausdrücklich da.
    assert (
        aktivitaet_zu_log(LAUF, None, {"rpe": None, "feel": None})["garmin_feel"] is None
    )


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


# --------------------------------------------------------------------------
# Schwellenpuls
# --------------------------------------------------------------------------


def test_schwellenpuls_aus_der_laktatschwelle():
    antwort = {
        "speed_and_heart_rate": {"speed": 3.7037, "heartRate": 168},
        "power": {},
    }
    assert schwellenpuls(antwort) == 168

    # Garmins historischer Tippfehler im Feldnamen
    assert schwellenpuls({"speed_and_heart_rate": {"hearRate": 171}}) == 171
    # Und die flache Form aus den Profileinstellungen
    assert schwellenpuls({"lactateThresholdHeartRate": 165}) == 165
    assert schwellenpuls(None) is None


def test_schwellenpuls_ausserhalb_der_profilspanne_wird_verworfen():
    """Ein Ausreißer würde die Profilseite mit einem Validierungsfehler lahmlegen."""
    assert schwellenpuls({"heartRate": 40}) is None
    assert schwellenpuls({"heartRate": 400}) is None


# --------------------------------------------------------------------------
# Bestzeiten
# --------------------------------------------------------------------------


def test_bestzeiten_werden_nach_strecke_sortiert_und_formatiert():
    antwort = [
        {"typeId": 6, "activityId": 4, "value": 11900.0},  # Marathon 3:18:20
        {"typeId": 3, "activityId": 1, "value": 1214.0,
         "activityStartDateTimeLocal": "2026-05-02T08:14:00.0"},
        {"typeId": 4, "activityId": 2, "value": 2550.0},  # 10 km 42:30
    ]
    gefunden = bestzeiten(antwort)

    assert [b["strecke"] for b in gefunden] == ["5 km", "10 km", "Marathon"]
    assert [b["zeit"] for b in gefunden] == ["20:14", "42:30", "3:18:20"]
    assert gefunden[0]["datum"] == "2026-05-02"
    assert gefunden[1]["datum"] is None
    assert all(b["sportart"] == "run" for b in gefunden)


def test_bestzeiten_ohne_deutbare_kennziffer_fallen_heraus():
    """Garmin führt in derselben Liste Rekorde, deren `value` keine Zeit ist."""
    # Schritte an einem Tag: hängt an keiner Aktivität.
    assert bestzeiten([{"typeId": 12, "activityId": None, "value": 28412.0}]) == []
    # Eine Kennziffer, die diese App nicht als Laufstrecke kennt.
    assert bestzeiten([{"typeId": 9, "activityId": 7, "value": 1800.0}]) == []
    assert bestzeiten(None) == []


def test_bestzeit_mit_unmoeglichem_tempo_wird_verworfen():
    """Der Test gegen ein menschenmögliches Tempo fängt eine fehlgedeutete Zahl."""
    # 16 Sekunden auf 1 km wären 0:16 min/km.
    assert bestzeiten([{"typeId": 1, "activityId": 1, "value": 16.0}]) == []
    # 25 000 als Halbmarathonzeit wären 19:45 min/km — in Wahrheit Meter.
    assert bestzeiten([{"typeId": 5, "activityId": 1, "value": 25000.0}]) == []


def test_bestzeit_nimmt_den_schnellsten_eintrag_je_strecke():
    antwort = [
        {"typeId": 3, "activityId": 1, "value": 1300.0},
        {"typeId": 3, "activityId": 2, "value": 1214.0},
    ]
    assert [b["zeit"] for b in bestzeiten(antwort)] == ["20:14"]


# --------------------------------------------------------------------------
# Wie die Einheit ausgeführt wurde
# --------------------------------------------------------------------------

# Wortlaut aus `scripts/garmin_aktivitaetsdetail_probe.py` gegen das echte
# Konto, Aktivität 24031745045 vom 19.08.2026 — die Schlüsseleinheit, für die
# 3x8 min Schwelle geplant waren. Bewusst mit den Nebenbefunden, die Garmin in
# dieselbe Liste legt: `SURFACE_TYPE_*` beschreibt den Untergrund und hat mit
# der Trainingsstruktur nichts zu tun.
DETAIL_SCHWELLENEINHEIT = {
    "splitSummaries": [
        {"splitType": "SURFACE_TYPE_PAVED", "noOfSplits": 4, "duration": 1270.749,
         "averageHR": 145.0},
        {"splitType": "SURFACE_TYPE_UNPAVED", "noOfSplits": 3, "duration": 930.999,
         "averageHR": 153.0},
        {"splitType": "INTERVAL_ACTIVE", "noOfSplits": 6, "duration": 995.874,
         "averageHR": 163.0},
        {"splitType": "INTERVAL_WARMUP", "noOfSplits": 1, "duration": 540.0,
         "averageHR": 129.0},
        {"splitType": "INTERVAL_COOLDOWN", "noOfSplits": 1, "duration": 108.083,
         "averageHR": 133.0},
        {"splitType": "INTERVAL_RECOVERY", "noOfSplits": 6, "duration": 560.571,
         "averageHR": 142.0},
    ],
    "summaryDTO": {"directWorkoutComplianceScore": 48, "averageHR": 148.0},
    "metadataDTO": {"associatedWorkoutId": 1668990922},
}

# Ein freier Dauerlauf, ebenfalls abgelesen (Aktivität 23876437487). Garmin
# meldet dort *einen* Arbeitsabschnitt über die ganze Einheit, dazu seine
# Geh-Lauf-Erkennung.
DETAIL_DAUERLAUF = {
    "splitSummaries": [
        {"splitType": "RWD_STAND", "noOfSplits": 2, "duration": 7.0, "averageHR": 148.0},
        {"splitType": "INTERVAL_ACTIVE", "noOfSplits": 1, "duration": 1821.578,
         "averageHR": 145.0},
        {"splitType": "RWD_RUN", "noOfSplits": 10, "duration": 1694.277,
         "averageHR": 145.0},
        {"splitType": "RWD_WALK", "noOfSplits": 10, "duration": 120.244,
         "averageHR": 145.0},
    ],
    "summaryDTO": {"normalizedPower": 359.0},
    "metadataDTO": {"associatedWorkoutId": None},
}


def test_zonensekunden_liest_nur_belegte_zonen():
    werte = zonensekunden({
        "hrTimeInZone_1": 210.0,
        "hrTimeInZone_2": 1420.0,
        "hrTimeInZone_3": 1502.0,
        "hrTimeInZone_4": 289.0,
        "hrTimeInZone_5": 0.0,
    })
    assert werte == {"1": 210, "2": 1420, "3": 1502, "4": 289}


def test_ohne_zonenzeiten_gibt_es_kein_objekt_aus_nullen():
    """`None` heißt "nicht aufgezeichnet" — ein Objekt aus Nullen wäre eine Messung."""
    assert zonensekunden({}) is None
    assert zonensekunden({f"hrTimeInZone_{i}": 0.0 for i in range(1, 6)}) is None


def test_abschnitte_zeigen_die_absolvierte_struktur():
    """Sechs Arbeitsabschnitte über 17 min — geplant waren 3x8 min."""
    abschnitte = abschnitte_aus_detail(DETAIL_SCHWELLENEINHEIT)

    assert [a["art"] for a in abschnitte] == [
        "aufwaermen", "belastung", "pause", "abwaermen"
    ]
    belastung = abschnitte[1]
    assert belastung == {"art": "belastung", "anzahl": 6, "dauer_min": 17, "hf_schnitt": 163}
    # Das Ausrollen brach nach 1:48 ab; geplant waren 9 min.
    assert abschnitte[3]["dauer_min"] == 2


def test_untergrund_und_gehpausen_zaehlen_nicht_als_struktur():
    """Garmin mischt `SURFACE_TYPE_*` und `RWD_*` in dieselbe Liste."""
    arten = {a["art"] for a in abschnitte_aus_detail(DETAIL_SCHWELLENEINHEIT)}
    assert arten == {"aufwaermen", "belastung", "pause", "abwaermen"}


def test_ein_einziger_arbeitsabschnitt_ist_keine_gliederung():
    """Sonst stünde an jedem freien Dauerlauf die Gesamtdauer ein zweites Mal."""
    assert abschnitte_aus_detail(DETAIL_DAUERLAUF) is None
    assert abschnitte_aus_detail({}) is None
    assert abschnitte_aus_detail(None) is None


def test_detail_liefert_einhaltung_und_workout_kennung():
    felder = detail_zu_feldern(DETAIL_SCHWELLENEINHEIT)

    assert felder["garmin_compliance"] == 48
    # Als Text, wie die Spalte am `SessionLog` — die Zuordnung vergleicht ihn
    # mit `GarminWorkoutLink.garmin_workout_id`.
    assert felder["garmin_workout_id"] == "1668990922"
    assert felder["garmin_abschnitte"][1]["anzahl"] == 6


def test_ein_frei_gestartetes_training_hat_keine_workout_kennung():
    """`associatedWorkoutId: None` darf keinen leeren Schlüssel hinterlassen."""
    felder = detail_zu_feldern(DETAIL_DAUERLAUF)
    assert felder == {}


def test_zonenzeiten_gehen_mit_in_die_einheit():
    """Sie stehen in derselben Antwort — sie zu holen kostet keine Anfrage."""
    aktivitaet = {
        "activityId": 42,
        "activityType": {"typeKey": "running"},
        "startTimeLocal": "2026-08-19 07:00:00",
        "duration": 3600.0,
        "distance": 12000.0,
        "hrTimeInZone_2": 1200.0,
        "hrTimeInZone_4": 600.0,
    }
    felder = aktivitaet_zu_log(aktivitaet)
    assert felder["hr_zone_seconds"] == {"2": 1200, "4": 600}


# --------------------------------------------------------------------------
# Die gezählten Übungen (`get_activity_exercise_sets`)
#
# Beide Beispiele stammen aus `scripts/garmin_aktivitaetsdetail_probe.py` am
# echten Konto — die Krafteinheit vom 17.08.2026 und die Mobility-Einheit vom
# 20.08.2026 —, nicht aus einer nach dem Parser geformten Nachbildung.
# --------------------------------------------------------------------------


def _satz(kategorie, name=None, dauer=45.0, wiederholungen=None, art="ACTIVE"):
    """Garmin nennt dieselbe Übung dreimal; eine Pause hat gar keine."""
    uebungen = (
        []
        if kategorie is None
        else [{"category": kategorie, "name": name, "probability": 99.609375}] * 3
    )
    return {
        "exercises": uebungen,
        "duration": dauer,
        "repetitionCount": wiederholungen,
        "weight": None,
        "setType": art,
        "startTime": "2026-08-17T16:45:56.0",
        "wktStepIndex": 0,
        "messageIndex": 0,
    }


SAETZE_MOBILITY = {
    "exerciseSets": [
        satz
        for kategorie, name, dauer, pause, runden in (
            ("WARM_UP", "STRETCH_PIGEON_POSE", 60.0, 15.0, 4),
            ("WARM_UP", "STRETCH_LUNGING_HIP_FLEXOR", 45.0, 15.0, 4),
            ("WARM_UP", "STRETCH_PIRIFORMIS", 45.0, 15.0, 4),
            ("WARM_UP", "STRETCH_LYING_SPINAL_TWIST", 45.0, 10.0, 2),
        )
        for _ in range(runden)
        for satz in (
            _satz(kategorie, name, dauer),
            _satz(None, dauer=pause, art="REST"),
        )
    ]
}

SAETZE_KRAFT = {
    "exerciseSets": [
        _satz("HIP_RAISE", "SINGLE_LEG_HIP_RAISE", 194.487, 10),
        _satz("HIP_RAISE", "CLAM_BRIDGE", 232.436, 3),
        _satz("PLANK", "SIDE_PLANK", 92.616, None),
        # `repetitionCount: 0` heißt bei Garmin „nicht gezählt", nicht „null
        # Wiederholungen" — an dieser Einheit stand es an drei von sechs Übungen.
        _satz("HIP_STABILITY", "QUADRUPED_WITH_LEG_LIFT", 172.421, 0),
        _satz("SQUAT", "BODY_WEIGHT_WALL_SQUAT", 10.165, 0),
        _satz("CALF_RAISE", "SINGLE_LEG_STANDING_CALF_RAISE", 8.677, 0),
        _satz(None, dauer=35.928, art="REST"),
    ]
}


def test_gleiche_uebungen_werden_zu_saetzen_zusammengefasst():
    """Vier Runden Taubenstellung sind eine Zeile mit `saetze: 4`, nicht vier."""
    uebungen = uebungen_aus_saetzen(SAETZE_MOBILITY)

    assert [u["uebung"] for u in uebungen] == [
        "STRETCH_PIGEON_POSE",
        "STRETCH_LUNGING_HIP_FLEXOR",
        "STRETCH_PIRIFORMIS",
        "STRETCH_LYING_SPINAL_TWIST",
    ]
    assert uebungen[0] == {
        "uebung": "STRETCH_PIGEON_POSE",
        "saetze": 4,
        "kategorie": "WARM_UP",
        "dauer_s": 60,
    }
    # Die letzte Übung lief nur zwei Runden — der Athlet hat abgebrochen.
    assert uebungen[3]["saetze"] == 2


def test_pausen_sind_keine_uebung():
    """Sonst stünden in der Mobility-Einheit vierzehn Sätze statt vierzehn Runden."""
    assert sum(u["saetze"] for u in uebungen_aus_saetzen(SAETZE_MOBILITY)) == 14


def test_nicht_gezaehlte_wiederholungen_stehen_nicht_da():
    """`null` und `0` heißen beide „nicht gezählt" — eine 0 wäre eine Behauptung."""
    uebungen = {u["uebung"]: u for u in uebungen_aus_saetzen(SAETZE_KRAFT)}

    assert uebungen["SINGLE_LEG_HIP_RAISE"]["wiederholungen"] == 10
    assert "wiederholungen" not in uebungen["SIDE_PLANK"]
    assert "wiederholungen" not in uebungen["QUADRUPED_WITH_LEG_LIFT"]
    assert "wiederholungen" not in uebungen["BODY_WEIGHT_WALL_SQUAT"]
    # Die Bewegungsgruppe trägt die Abwechslungsregel aus Punkt 9 des Prompts.
    assert uebungen["SIDE_PLANK"]["kategorie"] == "PLANK"


def test_ungleiche_saetze_bleiben_die_liste():
    """Dass der letzte Satz nicht mehr aufging, ist die Aussage."""
    saetze = {
        "exerciseSets": [
            _satz("SQUAT", "AIR_SQUAT", 40.0, 12),
            _satz("SQUAT", "AIR_SQUAT", 40.0, 12),
            _satz("SQUAT", "AIR_SQUAT", 38.0, 9),
        ]
    }
    eintrag = uebungen_aus_saetzen(saetze)[0]

    assert eintrag["wiederholungen"] == [12, 12, 9]
    # Beim Halten dagegen ist der Mittelwert richtig: 40/40/38 s ist Rauschen.
    assert eintrag["dauer_s"] == 39


def test_teilweise_gezaehlte_saetze_melden_gar_nichts():
    """Eine Liste über zwei von drei Sätzen läse sich wie zwei Sätze."""
    saetze = {
        "exerciseSets": [
            _satz("SQUAT", "AIR_SQUAT", 40.0, 12),
            _satz("SQUAT", "AIR_SQUAT", 40.0, None),
            _satz("SQUAT", "AIR_SQUAT", 40.0, 11),
        ]
    }
    eintrag = uebungen_aus_saetzen(saetze)[0]

    assert eintrag["saetze"] == 3
    assert "wiederholungen" not in eintrag


def test_unerkannte_bewegungen_fallen_heraus():
    """`UNKNOWN` ist keine Übung, sondern Garmins Achselzucken."""
    saetze = {
        "exerciseSets": [
            _satz("UNKNOWN", "UNKNOWN", 30.0),
            _satz("PLANK", "SIDE_PLANK", 40.0),
        ]
    }
    uebungen = uebungen_aus_saetzen(saetze)

    assert [u["uebung"] for u in uebungen] == ["SIDE_PLANK"]
    assert uebungen_aus_saetzen({"exerciseSets": [_satz("UNKNOWN", "UNKNOWN")]}) is None


def test_ohne_saetze_gibt_es_keine_leere_liste():
    """Dieselbe Regel wie überall: kein Feld, das wie eine Aussage aussieht."""
    assert uebungen_aus_saetzen({"exerciseSets": []}) is None
    assert uebungen_aus_saetzen({}) is None
    assert uebungen_aus_saetzen(None) is None
    assert uebungen_aus_saetzen({"exerciseSets": ["Unfug", 7]}) is None
