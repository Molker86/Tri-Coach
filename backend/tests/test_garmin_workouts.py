"""Trainings nach Garmin: bauen, übertragen, im Kalender verwalten.

Die Gegenrichtung zum Abgleich. Zwei Dinge werden getrennt geprüft: der Umbau
eines Fließtexts in Garmins Schrittliste (reine Rechnerei, ohne Netz) und der
Weg über die Endpunkte gegen die Nachbildung.
"""

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.garmin import kalender, workouts

HEUTE = date.today()
MORGEN = HEUTE + timedelta(days=1)

ZONEN = {"Z1": (100, 120), "Z2": (120, 140), "Z3": (140, 155), "Z4": (155, 170), "Z5": (170, 185)}


def einheit(**abweichend):
    """Eine Planeinheit, wie sie aus der KI-Antwort entsteht."""
    felder = dict(
        id=1,
        date=MORGEN,
        sport="run",
        session_type="intervals",
        title="Schwellenintervalle",
        description="Die harte Einheit der Woche",
        structure=None,
        purpose="Laktatschwelle anheben",
        duration_min=60,
        distance_km=None,
        intensity_zone=None,
        target_hr_low=None,
        target_hr_high=None,
        target_pace=None,
        target_power=None,
        rpe_target=8,
        order_in_day=0,
        swim_location=None,
        steps_json=None,
    )
    felder.update(abweichend)
    return SimpleNamespace(**felder)


def schritte(workout, segment=0):
    return workout["workoutSegments"][segment]["workoutSteps"]


def uebungsschritte(workout, segment=0):
    """Die ausführbaren Schritte, Wiederholungsgruppen aufgelöst.

    Bei Kraft und Mobility steckt die Übung im Kind einer Serie — „Wiederholen
    4ד über einem Schritt von 45 s —, und die Kennung sitzt dort und nicht an
    der Gruppe.
    """
    ausgepackt = []
    for eintrag in schritte(workout, segment):
        ausgepackt.extend(eintrag.get("workoutSteps") or [eintrag])
    return ausgepackt


# --------------------------------------------------------------------------
# Der Aufbautext wird zu Schritten
# --------------------------------------------------------------------------


def test_intervalltext_wird_eine_wiederholungsgruppe():
    """Fünf Wiederholungen sind ein Block, den die Uhr fünfmal abarbeitet.

    Genau die Form, in der Garmin selbst eine Serie führt: eine Zeile
    „Wiederholen 5×" mit Belastung und Pause darunter, statt zehn Zeilen
    hintereinander.
    """
    plan = workouts.baue_workout(
        einheit(structure="15 min Einlaufen Z1-Z2, 5 x 3 min Z4 mit je 2 min Trabpause, 10 min Auslaufen"),
        zonen=ZONEN,
    )
    folge = schritte(plan)

    assert [s["stepType"]["stepTypeKey"] for s in folge] == ["warmup", "repeat", "cooldown"]
    gruppe = folge[1]
    assert gruppe["type"] == "RepeatGroupDTO"
    assert gruppe["numberOfIterations"] == 5
    assert gruppe["endConditionValue"] == 5.0
    assert [s["stepType"]["stepTypeKey"] for s in gruppe["workoutSteps"]] == [
        "interval",
        "recovery",
    ]

    belastung, pause = gruppe["workoutSteps"]
    assert belastung["endConditionValue"] == 180.0
    assert belastung["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert (belastung["targetValueOne"], belastung["targetValueTwo"]) == (155.0, 170.0)

    # Die Pause bleibt ohne Zielkorridor: Ein Alarm in der Erholung triebe
    # genau die Herzfrequenz hoch, die gerade sinken soll.
    assert pause["targetType"]["workoutTargetTypeKey"] == "no.target"

    # Die Nummerierung läuft durch die Gruppe hindurch, und die Kinder tragen
    # deren `childStepId` — daran erkennt Garmin, wozu sie gehören.
    assert [s["stepOrder"] for s in folge] == [1, 2, 5]
    assert [s["stepOrder"] for s in gruppe["workoutSteps"]] == [3, 4]
    assert gruppe["childStepId"] == 1
    assert all(s["childStepId"] == 1 for s in gruppe["workoutSteps"])
    assert folge[0]["childStepId"] is None and folge[2]["childStepId"] is None


def test_streckenintervalle_enden_nach_distanz():
    plan = workouts.baue_workout(
        einheit(structure="20 min einlaufen, 6x800m (3:45/km) mit 400m Trabpause, 15 min auslaufen"),
        zonen=ZONEN,
    )
    gruppe = schritte(plan)[1]
    assert gruppe["numberOfIterations"] == 6
    belastung, pause = gruppe["workoutSteps"]
    assert belastung["endCondition"]["conditionTypeKey"] == "distance"
    assert belastung["endConditionValue"] == 800.0
    # Die Tempoangabe in der Klammer darf nicht als Dauer von 3:45 durchgehen.
    assert belastung["endConditionValue"] != 225.0
    assert pause["endConditionValue"] == 400.0


def test_unverstandener_text_wird_ein_einziger_schritt():
    """Lieber grob und richtig als fein und geraten."""
    plan = workouts.baue_workout(
        einheit(structure="Ganzkörperkraft nach Tagesform, 3 Runden", duration_min=45),
        zonen=ZONEN,
    )
    folge = schritte(plan)
    assert len(folge) == 1
    assert folge[0]["endConditionValue"] == 45 * 60


def test_uebungsliste_wird_zu_serien_mit_timer():
    """Was in der Notiz als Aufbau steht, muss auf der Uhr als Serie stehen.

    „2x45 s je Seite“ sind vier Haltephasen zu 45 s. Vorher stand dort *ein*
    Schritt bis zur Rundentaste, und die Uhr zählte weder Sätze noch Sekunden;
    der Athlet las die Zahlen in der Beschreibung und stoppte selbst.
    """
    plan = workouts.baue_workout(
        einheit(
            sport="mobility",
            duration_min=12,
            target_hr_low=90,
            target_hr_high=115,
            structure=(
                "90/90-Hüftrotation 2x8 je Seite"
                " / Hüftbeuger-Ausfallschritt 2x45 s je Seite"
                " / Kindhaltung 2x60 s"
                " / Zwerchfellatmung 3 min"
                " / Thoraxrotation nach Gefühl"
            ),
        ),
        zonen=ZONEN,
    )
    folge = schritte(plan)

    # Vier Serien und ein Einzelschritt — die Zeile ohne Umfangsangabe bleibt,
    # was sie war: ein Abschnitt bis zur Rundentaste.
    assert [s["type"] for s in folge] == [
        "RepeatGroupDTO",
        "RepeatGroupDTO",
        "RepeatGroupDTO",
        "ExecutableStepDTO",
        "ExecutableStepDTO",
    ]
    assert [s.get("numberOfIterations") for s in folge[:3]] == [4, 4, 2]

    umfang = [
        (s["endCondition"]["conditionTypeKey"], s["endConditionValue"])
        for s in uebungsschritte(plan)
    ]
    assert umfang == [
        ("reps", 8.0),  # „2x8 je Seite“ wird gezählt, nicht gestoppt
        ("time", 45.0),
        ("time", 60.0),
        ("time", 180.0),
        ("lap.button", 10.0),
    ]

    # Der Aufbautext bleibt am Schritt stehen; nur wo verdoppelt wurde, sagt
    # ein Zusatz, dass ein Durchgang eine Seite ist.
    beschreibungen = [s["description"] for s in uebungsschritte(plan)]
    assert beschreibungen[0] == "90/90-Hüftrotation 2x8 je Seite — je Durchgang eine Seite"
    assert beschreibungen[2] == "Kindhaltung 2x60 s"

    # Kein Herzfrequenzalarm über einer Dehnung.
    assert all(
        s["targetType"]["workoutTargetTypeKey"] == "no.target"
        for s in uebungsschritte(plan)
    )
    assert plan["estimatedDurationInSecs"] == 12 * 60


def test_krafttext_zaehlt_wiederholungen_und_stoppt_keine_sekunden():
    """„3x15 Leg Raise“ sind fünfzehn Wiederholungen, keine fünfzehn Sekunden."""
    plan = workouts.baue_workout(
        einheit(
            sport="strength",
            duration_min=20,
            structure=(
                "3x15 Side-Lying Leg Raise je Seite"
                " / 3x40 s Side Plank je Seite"
                " / 3x15 Monster Walks mit Band"
                " / 3x8 Step-Downs je Seite, 4 s exzentrisch abgesenkt"
            ),
        ),
        zonen=ZONEN,
    )
    folge = schritte(plan)

    # „je Seite“ verdoppelt die Durchgänge: drei Sätze je Seite sind sechs.
    assert [s["numberOfIterations"] for s in folge] == [6, 6, 3, 6]
    assert [
        (s["endCondition"]["conditionTypeKey"], s["endConditionValue"])
        for s in uebungsschritte(plan)
    ] == [
        ("reps", 15.0),
        ("time", 40.0),
        ("reps", 15.0),
        # Die „4 s“ beschreiben die Ausführung, den Umfang nennt „3x8“.
        ("reps", 8.0),
    ]

    # „mit Band“ gehört zur Übung, das Komma trennt einen Zusatz und keine Übung.
    assert [s["description"] for s in uebungsschritte(plan)] == [
        "3x15 Side-Lying Leg Raise je Seite — je Durchgang eine Seite",
        "3x40 s Side Plank je Seite — je Durchgang eine Seite",
        "3x15 Monster Walks mit Band",
        "3x8 Step-Downs je Seite, 4 s exzentrisch abgesenkt — je Durchgang eine Seite",
    ]


def test_erkannte_uebungen_tragen_die_katalogkennung():
    """Erst `category` und `exerciseName` bringen die Animation auf die Uhr."""
    plan = workouts.baue_workout(
        einheit(
            sport="strength",
            duration_min=20,
            structure=(
                "3x15 Side-Lying Leg Raise je Seite"
                " / 3x40 s Side Plank je Seite"
                " / 3x12 Liegestütze"
                " / 3x8 Step-Downs je Seite, 4 s exzentrisch abgesenkt"
            ),
        ),
        zonen=ZONEN,
    )
    folge = uebungsschritte(plan)

    assert [(s.get("category"), s.get("exerciseName")) for s in folge] == [
        ("HIP_STABILITY", "SIDE_LYING_LEG_RAISE"),
        ("PLANK", "SIDE_PLANK"),
        ("PUSH_UP", "PUSH_UP"),
        # „Step-Downs“ kennt Garmin nicht. Lieber keine Kennung als eine
        # falsche — der Schritt bleibt die Textzeile, die er vorher war.
        (None, None),
    ]
    # Die Kennung ersetzt den Aufbautext nicht, sie tritt daneben.
    assert folge[2]["description"] == "3x12 Liegestütze"


def test_uebungsschritt_hat_die_form_von_garmins_eigenen_workouts():
    """Die Kennung allein genügt nicht — die Uhr braucht die ganze Form.

    Abgelesen an Garmins „Ganzkörper-Mobilitäts-Warm-up“ (Workout 1336531040):
    Dessen Schritte tragen die Gewichts-, Zug- und Materialfelder, und wo sie
    per Rundentaste enden, steht dort trotzdem ein Zahlenwert. Mit leerem
    `endConditionValue` erkannte die Uhr den Schritt nicht als Übung.
    """
    plan = workouts.baue_workout(
        einheit(
            sport="mobility",
            duration_min=12,
            structure=(
                "Katze-Kuh 10 Wiederholungen"
                " / Wadendehnung 2x30 s je Seite"
                " / Ausrollen nach Gefühl"
            ),
        ),
        zonen=ZONEN,
    )
    for schritt in uebungsschritte(plan):
        assert schritt["endConditionValue"] is not None
        assert schritt["weightValue"] == -1.0
        assert schritt["weightUnit"]["unitKey"] == "kilogram"
        assert schritt["strokeType"]["strokeTypeId"] == 0
        assert schritt["equipmentType"]["equipmentTypeId"] == 0

    # Ohne Umfangsangabe bleibt es bei der Rundentaste — dann trägt der Schritt
    # Garmins Platzhalter, weil `None` ihn nicht als Übung durchgehen ließ.
    ohne_umfang = uebungsschritte(plan)[-1]
    assert ohne_umfang["endCondition"]["conditionTypeKey"] == "lap.button"
    assert ohne_umfang["endConditionValue"] == 10.0


def test_ausdauerschritt_bleibt_ohne_uebungsfelder():
    """Ein Laufintervall ist keine Übung — die Felder haben dort nichts zu suchen."""
    plan = workouts.baue_workout(
        einheit(structure="60 min Dauerlauf Z2"), zonen=ZONEN
    )
    schritt = schritte(plan)[0]
    assert "weightValue" not in schritt
    assert "category" not in schritt


def test_mobility_geht_als_mobility_und_nicht_als_yoga():
    """Der Übungskatalog hängt an der Sportart; Yoga hat einen eigenen."""
    plan = workouts.baue_workout(
        einheit(
            sport="mobility",
            duration_min=12,
            structure="Katze-Kuh 10 Wiederholungen / Taubenhaltung 2x45 s je Seite",
        ),
        zonen=ZONEN,
    )
    assert plan["sportType"]["sportTypeKey"] == "mobility"
    assert [s.get("exerciseName") for s in uebungsschritte(plan)] == [
        "STRETCH_CAT_COW",
        "STRETCH_PIGEON_POSE",
    ]


def test_ausdauerschritte_bekommen_keine_uebungskennung():
    """„5 x 3 min Z4“ ist kein Katalogeintrag und darf keiner werden."""
    plan = workouts.baue_workout(
        einheit(structure="15 min Einlaufen Z2, 5 x 3 min Z4 mit 2 min Trabpause"),
        zonen=ZONEN,
    )
    for segment in plan["workoutSegments"]:
        for schritt in segment["workoutSteps"]:
            kinder = schritt.get("workoutSteps", [schritt])
            assert all("category" not in k for k in kinder)


def test_kraft_ohne_uebungsliste_bleibt_ein_einziger_schritt():
    plan = workouts.baue_workout(
        einheit(
            sport="strength",
            structure="Ganzkörperkraft nach Tagesform, 3 Runden",
            duration_min=45,
        ),
        zonen=ZONEN,
    )
    folge = schritte(plan)
    assert len(folge) == 1
    assert folge[0]["endConditionValue"] == 45 * 60


def test_ohne_dauer_und_strecke_zaehlt_die_rundentaste():
    plan = workouts.baue_workout(
        einheit(structure=None, duration_min=None, distance_km=None), zonen=ZONEN
    )
    assert schritte(plan)[0]["endCondition"]["conditionTypeKey"] == "lap.button"


def test_herzfrequenzvorgabe_der_einheit_greift_ohne_zone_im_text():
    plan = workouts.baue_workout(
        einheit(structure="60 min Dauerlauf", target_hr_low=128, target_hr_high=142),
        zonen=ZONEN,
    )
    schritt = schritte(plan)[0]
    assert (schritt["targetValueOne"], schritt["targetValueTwo"]) == (128.0, 142.0)


def test_wattvorgabe_wird_zum_leistungsziel():
    plan = workouts.baue_workout(
        einheit(sport="bike", structure="90 min Grundlage", target_power="210-240 W"),
        zonen={},
    )
    schritt = schritte(plan)[0]
    assert schritt["targetType"]["workoutTargetTypeKey"] == "power.zone"
    assert (schritt["targetValueOne"], schritt["targetValueTwo"]) == (210.0, 240.0)


def test_laufpace_wird_zu_geschwindigkeit_in_meter_pro_sekunde():
    plan = workouts.baue_workout(
        einheit(structure="40 min Tempolauf", target_pace="4:30"), zonen={}
    )
    schritt = schritte(plan)[0]
    assert schritt["targetType"]["workoutTargetTypeKey"] == "pace.zone"
    # 4:30/km sind 3,70 m/s; der Korridor liegt um fünf Sekunden herum.
    assert 3.6 < schritt["targetValueOne"] < schritt["targetValueTwo"] < 3.8


def test_zwei_serien_bleiben_zwei_gruppen():
    """„3x 3 min Z4" und danach „3x 2 min Z4" sind zwei Blöcke, nicht einer.

    Beide Gruppen brauchen eine eigene `childStepId`: Daran hängt Garmin die
    Kinder an ihre Gruppe, und zwei Blöcke unter derselben Nummer liefen
    ineinander.
    """
    plan = workouts.baue_workout(
        einheit(
            structure="10 min Einlaufen Z2, 3x 3 min Z4, 3x 2 min Z4, 10 min Auslaufen"
        ),
        zonen=ZONEN,
    )
    folge = schritte(plan)

    assert [s["stepType"]["stepTypeKey"] for s in folge] == [
        "warmup",
        "repeat",
        "repeat",
        "cooldown",
    ]
    erste, zweite = folge[1], folge[2]
    assert (erste["numberOfIterations"], zweite["numberOfIterations"]) == (3, 3)
    assert erste["workoutSteps"][0]["endConditionValue"] == 180.0
    assert zweite["workoutSteps"][0]["endConditionValue"] == 120.0
    assert erste["childStepId"] != zweite["childStepId"]
    assert zweite["workoutSteps"][0]["childStepId"] == zweite["childStepId"]

    # Die Schrittnummern laufen quer durch beide Gruppen weiter.
    assert [s["stepOrder"] for s in folge] == [1, 2, 4, 6]


def test_block_mit_innerer_struktur_behaelt_belastung_und_pause():
    """„4 × (3 min hart / 2 min locker)" — der zweite Teil ist die Erholung."""
    plan = workouts.baue_workout(
        einheit(structure="15 min Einlaufen Z1-Z2, 4x (3 min Z4 mit 2 min Z2), 10 min Auslaufen"),
        zonen=ZONEN,
    )
    gruppe = schritte(plan)[1]

    assert gruppe["numberOfIterations"] == 4
    assert [s["stepType"]["stepTypeKey"] for s in gruppe["workoutSteps"]] == [
        "interval",
        "recovery",
    ]
    assert [s["endConditionValue"] for s in gruppe["workoutSteps"]] == [180.0, 120.0]


def test_einfache_wiederholung_bleibt_ein_schritt():
    """„1 ד ist keine Serie, sondern eine Schreibweise."""
    plan = workouts.baue_workout(
        einheit(structure="1x 20 min Z3"), zonen=ZONEN
    )
    folge = schritte(plan)
    assert len(folge) == 1
    assert folge[0]["type"] == "ExecutableStepDTO"
    assert folge[0]["endConditionValue"] == 1200.0


def test_smarttrainer_einheit_kommt_vollstaendig_auf_die_uhr():
    """Der Fall, an dem drei Fehler zugleich sichtbar wurden.

    Auf dem Gerät stand: 15 min Einrollen, *ein* Intervall über 6 min, 3 min
    Kurbeln, Ausrollen — alles vier mit Herzfrequenzkorridor. Gemeint waren vier
    Runden, und auf dem Smarttrainer steuert die Leistung, nicht der Puls.

    Drei Ursachen: Die Zahl der Wiederholungen stand hinter einem Schrägstrich
    und wurde nur am Abschnittsanfang gesucht; die Serienpause stand hinter dem
    Komma und damit im nächsten Abschnitt; und Watt las der Bauplan nur aus dem
    Feld `target_power`, nie aus dem Aufbautext.
    """
    plan = workouts.baue_workout(
        einheit(
            sport="bike",
            duration_min=60,
            target_hr_low=162,
            target_hr_high=175,
            structure=(
                "15 min Einrollen Z1-Z2 inkl. 3x30 s Trittfrequenz 105"
                " / 4x6 min bei 195-210 W (HF 162-172),"
                " dazwischen 3 min lockeres Kurbeln bei 110-130 W"
                " / 10 min Ausrollen Z1"
            ),
        ),
        zonen=ZONEN,
    )
    folge = schritte(plan)

    assert [s["stepType"]["stepTypeKey"] for s in folge] == ["warmup", "repeat", "cooldown"]

    gruppe = folge[1]
    assert gruppe["numberOfIterations"] == 4
    belastung, pause = gruppe["workoutSteps"]
    assert (belastung["endConditionValue"], pause["endConditionValue"]) == (360.0, 180.0)
    assert pause["stepType"]["stepTypeKey"] == "recovery"

    # Beide Schritte werden über Watt gesteuert, jeder mit seinem eigenen
    # Korridor — auch die Erholung, denn dort ist die Zahl eine Anweisung an
    # die Rolle und kein Alarm.
    assert belastung["targetType"]["workoutTargetTypeKey"] == "power.zone"
    assert (belastung["targetValueOne"], belastung["targetValueTwo"]) == (195.0, 210.0)
    assert pause["targetType"]["workoutTargetTypeKey"] == "power.zone"
    assert (pause["targetValueOne"], pause["targetValueTwo"]) == (110.0, 130.0)

    # Ein- und Ausrollen nennen keine Watt, und ohne FTP lässt sich aus ihrer
    # Zone keine berechnen — deshalb bleibt es hier beim Puls.
    assert folge[0]["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert folge[2]["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"


def test_die_serienpause_im_wasser_gehoert_in_die_gruppe():
    """Am echten Plan aufgefallen: „6 Mal" mit nur einem Schritt darin.

    Die Pause stand wie vorgesehen hinter dem Komma, hieß aber „je 30 s
    lockeres Treiben" — die Pausenwörter kannten Rad und Lauf, nicht das
    Wasser. Als Belastung gelesen fiel sie aus der Serie heraus und stand als
    eigener Abschnitt dahinter: sechs Technikminuten am Stück und eine
    einzelne halbe Minute Treiben.
    """
    plan = workouts.baue_workout(
        einheit(
            sport="swim",
            duration_min=45,
            structure=(
                "8 min locker einschwimmen ufernah"
                " / 6x1 min Technik: 2x Abschlagschwimmen (Catch-up),"
                " 2x einarmig (Single-Arm), je 30 s lockeres Treiben"
                " / 5 min locker ausschwimmen Z1"
            ),
        ),
        zonen=ZONEN,
    )
    folge = schritte(plan)

    assert [s["stepType"]["stepTypeKey"] for s in folge] == ["warmup", "repeat", "cooldown"]

    gruppe = folge[1]
    assert gruppe["numberOfIterations"] == 6
    belastung, pause = gruppe["workoutSteps"]
    assert (belastung["endConditionValue"], pause["endConditionValue"]) == (60.0, 30.0)
    assert pause["stepType"]["stepTypeKey"] == "recovery"


def test_die_technikuebungen_verteilen_sich_auf_die_runden():
    """„6x1 min Technik: 2x A, 2x B, 2x C" — die Zahlen zählen keine Schritte.

    Ohne Zeitangabe baute `_baue_schritt()` aus den beiden hinteren Übungen
    nichts und ließ sie fallen: Auf der Uhr stand sechsmal die erste. Die
    Rundenzahlen ergeben aber genau die Serie, also ist die Verteilung
    eindeutig — drei Serien zu zwei Runden, jede mit ihrer Übung und mit der
    Pause, die zu jeder Runde gehört.
    """
    elemente = workouts.zerlege_struktur(
        "6x1 min Technik: 2x Abschlagschwimmen (Catch-up),"
        " 2x Fingerspitzen ziehen (Fingertip Drag), 2x einarmig (Single-Arm),"
        " je 30 s lockeres Treiben"
    )

    assert [e.anzahl for e in elemente] == [2, 2, 2]
    assert [e.schritte[0].text for e in elemente] == [
        "1 min Technik: Abschlagschwimmen (Catch-up)",
        "1 min Technik: Fingerspitzen ziehen (Fingertip Drag)",
        "1 min Technik: einarmig (Single-Arm)",
    ]
    for block in elemente:
        assert [s.art for s in block.schritte] == ["interval", "recovery"]
        assert [s.dauer_s for s in block.schritte] == [60.0, 30.0]


def test_die_uebung_darf_auch_ganz_ohne_eigene_zeile_kommen():
    """Die erste Übung steckt nicht immer im Schritt der Serie."""
    elemente = workouts.zerlege_struktur(
        "6x100 m Kraul, 2x mit Pull-Buoy, 2x mit Paddles, 2x ohne Hilfsmittel, 20 s Pause"
    )
    assert [e.anzahl for e in elemente] == [2, 2, 2]
    assert elemente[2].schritte[0].text == "100 m Kraul: ohne Hilfsmittel"
    assert elemente[2].schritte[0].distanz_m == 100


def test_ohne_aufgehende_rechnung_wird_nichts_verteilt_und_nichts_verschluckt():
    """2 + 2 sind nicht 6 — welche Übung in welcher Runde läuft, ist unklar.

    Geraten wird dann nicht. Verlorengehen dürfen die Übungen trotzdem nicht:
    Sie stehen im Wortlaut im Schritttext, so wie der Plan sie schreibt.
    """
    elemente = workouts.zerlege_struktur(
        "6x1 min Technik: 2x Abschlag, 2x einarmig, je 30 s Treiben"
    )
    assert [e.anzahl for e in elemente] == [6]
    assert elemente[0].schritte[0].text == "1 min Technik: 2x Abschlag, 2x einarmig"


def test_eine_serie_mit_maß_bleibt_eine_serie():
    """Trägt die Zeile ein Maß, zählt die Zahl Schritte und keine Runden."""
    elemente = workouts.zerlege_struktur("4x6 min bei 195-210 W, 3x30 s Trittfrequenz 105")
    assert [type(e) for e in elemente] == [workouts.Block, workouts.Block]
    assert [e.anzahl for e in elemente] == [4, 3]


def test_antreiben_ist_keine_pause():
    """„treiben" zählt nur als eigenes Wort — sonst zöge „antreiben" mit."""
    assert workouts._art("2 min Beine antreiben") == "interval"
    assert workouts._art("30 s lockeres Treiben") == "recovery"


def test_auf_dem_rad_bekommt_jeder_schritt_eine_leistungsvorgabe():
    """Auch Ein- und Ausrollen — sonst fällt die Rolle mittendrin aus der Regelung.

    Der Puls verschwindet dabei nicht, er wechselt die Rolle: Statt Zielkorridor
    steht er als Hinweis in der Beschreibung, die die Uhr unter dem Abschnitt
    anzeigt.
    """
    plan = workouts.baue_workout(
        einheit(
            sport="bike",
            duration_min=55,
            target_power="135-160 W",
            structure=(
                "10 min locker einrollen Z1"
                " / 40 min gleichmäßig Z2, Trittfrequenz 85-95"
                " / 5 min ausrollen Z1"
            ),
        ),
        zonen=ZONEN,
        ftp=260,
    )
    folge = schritte(plan)

    assert [s["stepType"]["stepTypeKey"] for s in folge] == [
        "warmup",
        "interval",
        "cooldown",
    ]
    assert {s["targetType"]["workoutTargetTypeKey"] for s in folge} == {"power.zone"}

    # Ein- und Ausrollen: aus Z1 gerechnet (45–55 % FTP). Die Hauptbelastung
    # behält die Wattvorgabe der Einheit — sie ist die genauere Angabe.
    assert (folge[0]["targetValueOne"], folge[0]["targetValueTwo"]) == (117.0, 143.0)
    assert (folge[2]["targetValueOne"], folge[2]["targetValueTwo"]) == (117.0, 143.0)
    assert (folge[1]["targetValueOne"], folge[1]["targetValueTwo"]) == (135.0, 160.0)

    assert folge[0]["description"] == "10 min locker einrollen Z1 (Zielpuls 100-120 bpm)"
    assert folge[1]["description"].endswith("(Zielpuls 120-140 bpm)")
    assert folge[2]["description"] == "5 min ausrollen Z1 (Zielpuls 100-120 bpm)"


def test_puls_im_aufbautext_wird_nicht_verdoppelt():
    """Die KI schreibt den Korridor oft selbst dazu — zweimal liest sich falsch."""
    plan = workouts.baue_workout(
        einheit(sport="bike", structure="10 min locker einrollen Z1 (120-134 bpm)"),
        zonen=ZONEN,
        ftp=260,
    )
    schritt = schritte(plan)[0]
    assert schritt["targetType"]["workoutTargetTypeKey"] == "power.zone"
    assert schritt["description"] == "10 min locker einrollen Z1 (120-134 bpm)"


def test_ohne_ftp_bleibt_der_puls_das_ziel():
    """Eine Leistung, die niemand ausrechnen kann, ist keine."""
    plan = workouts.baue_workout(
        einheit(sport="bike", structure="10 min locker einrollen Z1"), zonen=ZONEN
    )
    schritt = schritte(plan)[0]
    assert schritt["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert (schritt["targetValueOne"], schritt["targetValueTwo"]) == (100.0, 120.0)
    assert "Zielpuls" not in schritt["description"]


def test_ausrollen_nach_einer_serie_bleibt_draussen():
    """Nur eine Pause wandert in die Gruppe, nicht der nächstbeste Schritt."""
    plan = workouts.baue_workout(
        einheit(sport="bike", structure="4x6 min Z4 / 10 min Ausrollen Z1"),
        zonen=ZONEN,
    )
    folge = schritte(plan)
    assert [s["stepType"]["stepTypeKey"] for s in folge] == ["repeat", "cooldown"]
    assert len(folge[0]["workoutSteps"]) == 1


def test_zweite_pause_wandert_nicht_auch_noch_in_die_serie():
    """Hat die Gruppe ihre Pause, ist sie zu."""
    plan = workouts.baue_workout(
        einheit(structure="5x 3 min Z4 mit 2 min Trabpause, danach 5 min Gehpause"),
        zonen=ZONEN,
    )
    folge = schritte(plan)
    assert [s["stepType"]["stepTypeKey"] for s in folge] == ["repeat", "recovery"]
    assert len(folge[0]["workoutSteps"]) == 2


def test_wattangabe_im_schritt_schlaegt_die_herzfrequenzvorgabe():
    """Auf dem Rad steuert die Leistung — die Herzfrequenz zieht nur nach."""
    plan = workouts.baue_workout(
        einheit(
            sport="bike",
            structure="40 min bei 200-220 W",
            target_hr_low=150,
            target_hr_high=165,
        ),
        zonen=ZONEN,
    )
    schritt = schritte(plan)[0]
    assert schritt["targetType"]["workoutTargetTypeKey"] == "power.zone"
    assert (schritt["targetValueOne"], schritt["targetValueTwo"]) == (200.0, 220.0)


def test_beim_laufen_bleibt_watt_im_text_unbeachtet():
    """`_leistung_im_schritt` gilt nur dem Rad — beim Laufen führt die Pace."""
    plan = workouts.baue_workout(
        einheit(structure="30 min Dauerlauf", target_hr_low=140, target_hr_high=155),
        zonen=ZONEN,
    )
    schritt = schritte(plan)[0]
    assert schritt["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"


def test_prozentangabe_im_schritt_zaehlt_nur_mit_ftp_daneben():
    """Ein Prozentwert im Fließtext kann auch „% HFmax" meinen.

    Im Feld `target_power` steht nichts als die Vorgabe, dort genügt das
    Prozentzeichen. Im Aufbautext muss „FTP" danebenstehen.
    """
    mit_ftp = workouts.baue_workout(
        einheit(sport="bike", structure="20 min bei 95-100% FTP"), zonen={}, ftp=250
    )
    schritt = schritte(mit_ftp)[0]
    assert schritt["targetType"]["workoutTargetTypeKey"] == "power.zone"
    assert (schritt["targetValueOne"], schritt["targetValueTwo"]) == (237.5, 250.0)

    ohne_ftp = workouts.baue_workout(
        einheit(sport="bike", structure="20 min bei 85-90% der maximalen Herzfrequenz"),
        zonen={},
        ftp=250,
    )
    assert schritte(ohne_ftp)[0]["targetType"]["workoutTargetTypeKey"] == "no.target"


def test_schwimmeinheit_bekommt_bahnlaenge_und_zugart():
    plan = workouts.baue_workout(
        einheit(sport="swim", structure="400m Einschwimmen, 8x100m Kraul P30s, 200m Ausschwimmen"),
        zonen=ZONEN,
    )
    assert plan["poolLength"] == workouts.POOL_LAENGE_M
    assert plan["sportType"]["sportTypeKey"] == "swimming"
    assert schritte(plan)[0]["strokeType"]["strokeTypeId"] == 0


def test_freiwasser_bekommt_keine_bahnlaenge():
    """Die Bahnlänge machte aus jeder Freiwasserrunde ein Beckentraining.

    Im See gibt es keine Bahn: Die Uhr zählt dann Längen statt Strecke zu
    messen, und das Workout misst etwas anderes, als der Plan meint.
    """
    plan = workouts.baue_workout(
        einheit(
            sport="swim",
            swim_location="open_water",
            title="Freiwasser: Orientierung",
            structure="400 m locker / 4x200 m zügig, 30 s Pause / 200 m ausschwimmen",
        ),
        zonen=ZONEN,
    )
    assert "poolLength" not in plan
    assert "poolLengthUnit" not in plan
    assert plan["sportType"]["sportTypeKey"] == "swimming"
    # Die Uhr wählt den Modus nicht selbst — der Athlet muss ihn kennen.
    assert plan["description"].startswith("Freiwasser")


def test_schwimmort_faellt_auf_den_wortlaut_zurueck():
    """Für Blöcke, die vor dem Feld entstanden sind, und für fremde KIs.

    Anders als beim Zerlegen des Aufbautexts ist die Entscheidung binär und
    das Wort eindeutig; ohne Hinweis bleibt es beim Becken.
    """
    ohne_feld = einheit(
        sport="swim", swim_location=None, title="Freiwasser: Technik und Orientierung"
    )
    assert workouts.schwimmort(ohne_feld) == "open_water"
    assert "poolLength" not in workouts.baue_workout(ohne_feld, zonen=ZONEN)

    # Das Feld schlägt den Wortlaut: Wer „open_water" sagt, meint es auch.
    assert workouts.schwimmort(einheit(sport="swim", swim_location="pool")) == "pool"
    assert workouts.schwimmort(einheit(sport="swim", title="Lockeres Schwimmen")) == "pool"


def test_freiwasser_im_zweck_macht_noch_keine_seerunde():
    """Aus einem echten Plan: Die Beckeneinheit, die Freiwasser *übt*.

    „Orientierungsblick fürs Freiwasser" stand in der Beschreibung einer
    Einheit über 4x50 m und 4x150 m mit 20 s Pause — also im Becken. Über
    Beschreibung und Zweck gelesen kippte der Rückfall sie ins Freiwasser und
    nahm ihr die Bahnlänge.
    """
    beckeneinheit = einheit(
        sport="swim",
        swim_location=None,
        title="Ruhiges Schwimmen mit Orientierungsblick",
        description="… mit kurzen Technikanteilen und Orientierungsblick fürs Freiwasser.",
        purpose="Freiwasser-Orientierung",
        structure="200 m locker / 4x150 m gleichmäßig Z2, 25 s Pause / 100 m locker",
    )
    assert workouts.schwimmort(beckeneinheit) == "pool"
    assert workouts.baue_workout(beckeneinheit, zonen=ZONEN)["poolLength"] == 25.0


def test_koppeleinheit_wird_zu_zwei_abschnitten():
    plan = workouts.baue_workout(
        einheit(sport="brick", structure="60 min Rad Z3, direkt danach 20 min Laufen Z2"),
        zonen=ZONEN,
    )
    abschnitte = plan["workoutSegments"]
    assert [a["sportType"]["sportTypeKey"] for a in abschnitte] == ["cycling", "running"]
    assert plan["sportType"]["sportTypeKey"] == "multi_sport"


def test_koppeleinheit_ohne_erkennbare_teilung_weist_die_schaetzung_aus():
    plan = workouts.baue_workout(
        einheit(sport="brick", structure=None, duration_min=90), zonen=ZONEN
    )
    assert len(plan["workoutSegments"]) == 2
    assert "geschätzt" in plan["description"]


def test_ruhetag_laesst_sich_nicht_bauen():
    with pytest.raises(ValueError):
        workouts.baue_workout(einheit(sport="rest"), zonen=ZONEN)


def test_name_traegt_kein_datum():
    """Den Tag trägt der Kalendereintrag, an dem die Einheit hängt.

    Das Datum stand einmal voran, um die Workout-Bibliothek sortierbar zu
    halten. Ziel ist aber der Kalender, und dort steht der Tag schon in der
    Spalte — „16.08. Lockerer Dauerlauf“ am 16.08. las sich wie ein Fehler.
    """
    plan = workouts.baue_workout(einheit(title="Lockerer Dauerlauf"), zonen=ZONEN)
    assert plan["workoutName"] == "Lockerer Dauerlauf"


def test_name_faellt_nie_leer_aus():
    """Garmin lehnt ein Workout ohne Namen ab.

    Bis zum Wegfall des Datums war der Name zwangsläufig nicht leer; ohne den
    Rückfall hinge das jetzt am Titel aus der KI-Antwort.
    """
    plan = workouts.baue_workout(einheit(title="   "), zonen=ZONEN)
    assert plan["workoutName"] == "Training"


def test_gleicher_inhalt_gleicher_fingerabdruck():
    """Trägt die Ersparnis: Unverändertes wird gar nicht erst gesendet."""
    eine = workouts.baue_workout(einheit(structure="60 min locker"), zonen=ZONEN)
    andere = workouts.baue_workout(einheit(structure="60 min locker"), zonen=ZONEN)
    geaendert = workouts.baue_workout(einheit(structure="75 min locker"), zonen=ZONEN)

    assert workouts.fingerabdruck(eine) == workouts.fingerabdruck(andere)
    assert workouts.fingerabdruck(eine) != workouts.fingerabdruck(geaendert)


# --------------------------------------------------------------------------
# Der Weg über die Endpunkte
# --------------------------------------------------------------------------


def _autopush(client, auth, an: bool) -> None:
    """Schaltet die Automatik beim Übernehmen eines Blocks ein oder aus.

    Die meisten Tests hier prüfen den Knopf und zählen dabei Anfragen an Garmin.
    Liefe die Automatik mit, wäre der Block schon übertragen, bevor der Knopf
    gedrückt wird — jede Zählung läge um genau diesen Lauf daneben. Die
    Automatik selbst hat weiter unten eigene Tests.
    """
    antwort = client.put(
        "/api/garmin/settings", json={"auto_push_enabled": an}, headers=auth
    )
    assert antwort.status_code == 200, antwort.text


def _importiere_plan(client, auth, tage=3, *, autopush=False, ab=None):
    return _importiere(client, auth, tage, autopush=autopush, ab=ab)["plan"]


def _importiere(client, auth, tage=3, *, autopush=False, ab=None):
    """Wie `_importiere_plan`, gibt aber die ganze Antwort samt Job zurück."""
    _autopush(client, auth, autopush)
    beginn = ab or HEUTE
    plan = {
        "schema_version": "2.0",
        "plan": {
            "title": "Übertragungsblock",
            "summary": "kurz",
            "coaching_notes": "keine",
            "start_date": beginn.isoformat(),
            "days": [
                {
                    "date": (beginn + timedelta(days=i)).isoformat(),
                    "sessions": [
                        {
                            "sport": ["run", "bike", "rest"][i % 3],
                            "type": "endurance",
                            "title": f"Einheit {i + 1}",
                            "duration_min": 60,
                            "structure": "15 min einlaufen, 4 x 4 min Z4 mit 3 min Pause, 10 min auslaufen",
                        }
                    ],
                }
                for i in range(tage)
            ],
        },
    }
    antwort = client.post(
        "/api/plans/import",
        json={"raw": json.dumps(plan), "days": tage},
        headers=auth,
    )
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _uebertrage(client, auth):
    antwort = client.post("/api/garmin/workouts/uebertragen", json={}, headers=auth)
    assert antwort.status_code == 202, antwort.text
    job_id = antwort.json()["id"]
    return client.get(f"/api/garmin/jobs/{job_id}", headers=auth).json()


def _entsperre(client, auth) -> None:
    """Hebt die nach einem 429 gesetzte Anfragesperre wieder auf.

    Sie gilt eine Stunde und blockierte sonst jeden folgenden Lauf im selben
    Test — gewollt im Betrieb, im Test nur die Uhr, auf die niemand warten will.
    """
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import GarminAccount, User

    email = client.get("/api/auth/me", headers=auth).json()["email"]
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        konto = db.scalar(
            select(GarminAccount).where(GarminAccount.user_id == user.id)
        )
        konto.rate_limited_until = None
        konto.status = "connected"
        konto.status_message = None
        db.commit()


def test_uebertragung_legt_workouts_an_und_terminiert_sie(client, verbunden, fake):
    _importiere_plan(client, verbunden)
    fertig = _uebertrage(client, verbunden)

    assert fertig["state"] == "done", fertig["message"]
    assert fertig["workouts_pushed"] == 2  # der Ruhetag bleibt außen vor
    assert len(fake._workouts) == 15
    assert len(fake._termine) == 2

    # Jede Vorlage hat genau einen Termin, und der liegt auf dem geplanten Tag.
    for _, (workout_id, tag) in fake._termine.items():
        assert workout_id in fake._workouts
        assert date.fromisoformat(tag) >= HEUTE


def test_zweite_uebertragung_kostet_keine_anfrage(client, verbunden, fake):
    _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)
    fake.aufrufe.clear()

    fertig = _uebertrage(client, verbunden)

    assert fertig["state"] == "done"
    assert fertig["workouts_pushed"] == 0
    assert "bereits aktuell" in fertig["message"]
    assert "upload_workout" not in fake.aufrufe
    assert "schedule_workout" not in fake.aufrufe
    assert len(fake._workouts) == 15


def test_neuer_block_verwendet_dieselben_workout_ids(client, verbunden, fake):
    _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)
    pool_ids = set(fake._workouts)
    assert len(pool_ids) == 15

    _importiere_plan(client, verbunden)
    fake.aufrufe.clear()
    fertig = _uebertrage(client, verbunden)

    assert fertig["state"] == "done", fertig["message"]
    assert set(fake._workouts) == pool_ids
    assert "upload_workout" not in fake.aufrufe
    assert "update_workout" in fake.aufrufe


def test_bestehende_workout_ids_werden_in_den_pool_uebernommen(
    client, verbunden, fake
):
    from app.database import SessionLocal
    from app.models import GarminWorkoutLink, GarminWorkoutPoolSlot, PlanSession

    plan = _importiere_plan(client, verbunden)
    alte_ids = set()
    user_id = None
    with SessionLocal() as db:
        for daten in (s for s in plan["sessions"] if s["sport"] != "rest"):
            session = db.get(PlanSession, daten["id"])
            user_id = session.plan.user_id
            workout = workouts.baue_workout(session)
            workout_id = fake.upload_workout(workout)["workoutId"]
            schedule_id = fake.schedule_workout(workout_id, session.date.isoformat())[
                "workoutScheduleId"
            ]
            alte_ids.add(workout_id)
            db.add(
                GarminWorkoutLink(
                    user_id=session.plan.user_id,
                    plan_session_id=session.id,
                    garmin_workout_id=str(workout_id),
                    garmin_schedule_id=str(schedule_id),
                    scheduled_date=session.date,
                    title=workout["workoutName"],
                    fingerabdruck=workouts.fingerabdruck(workout),
                )
            )
        db.commit()

    fake.aufrufe.clear()
    fertig = _uebertrage(client, verbunden)

    assert fertig["state"] == "done", fertig["message"]
    assert fake.aufrufe.count("upload_workout") == 13
    assert alte_ids <= set(fake._workouts)
    assert len(fake._workouts) == 15
    with SessionLocal() as db:
        slots = db.query(GarminWorkoutPoolSlot).filter_by(user_id=user_id).all()
        links = db.query(GarminWorkoutLink).filter_by(user_id=user_id).all()
        assert len(slots) == 15
        assert all(link.pool_slot_id for link in links)


def test_mehr_als_15_alt_ids_werden_nach_prioritaet_bereinigt(
    client, verbunden, fake
):
    from app.database import SessionLocal
    from app.garmin import workout_pool
    from app.models import GarminWorkoutLink, PlanSession

    plan = {
        "schema_version": "2.0",
        "plan": {
            "title": "Legacy-Block",
            "start_date": HEUTE.isoformat(),
            "days": [
                {
                    "date": (HEUTE + timedelta(days=index)).isoformat(),
                    "sessions": [
                        {
                            "sport": "run",
                            "type": "easy",
                            "title": f"Alt {index + 1}",
                            "duration_min": 30,
                        }
                    ],
                }
                for index in range(16)
            ],
        },
    }
    _autopush(client, verbunden, False)
    antwort = client.post(
        "/api/plans/import", json={"raw": json.dumps(plan), "days": 16}, headers=verbunden
    )
    assert antwort.status_code == 201, antwort.text
    sessions = antwort.json()["plan"]["sessions"]
    bevorzugt = {session["id"] for session in sessions[:15]}

    with SessionLocal() as db:
        user_id = None
        for daten in sessions:
            session = db.get(PlanSession, daten["id"])
            user_id = session.plan.user_id
            workout = workouts.baue_workout(session)
            workout_id = fake.upload_workout(workout)["workoutId"]
            schedule_id = fake.schedule_workout(workout_id, session.date.isoformat())[
                "workoutScheduleId"
            ]
            db.add(
                GarminWorkoutLink(
                    user_id=user_id,
                    plan_session_id=session.id,
                    garmin_workout_id=str(workout_id),
                    garmin_schedule_id=str(schedule_id),
                    scheduled_date=session.date,
                    title=workout["workoutName"],
                    fingerabdruck=workouts.fingerabdruck(workout),
                )
            )
        db.commit()

        workout_pool.stelle_pool_sicher(
            db, fake, user_id, bevorzugte_session_ids=bevorzugt
        )

        links = db.query(GarminWorkoutLink).filter_by(user_id=user_id).all()
        assert len(links) == 15
        assert {link.plan_session_id for link in links} == bevorzugt

    assert len(fake._workouts) == 15
    assert len(fake._termine) == 15


def test_voller_pool_bricht_vor_der_ersten_terminierung_ab(
    client, verbunden, fake
):
    plan = {
        "schema_version": "2.0",
        "plan": {
            "title": "Zu großer Block",
            "start_date": HEUTE.isoformat(),
            "days": [
                {
                    "date": (HEUTE + timedelta(days=index)).isoformat(),
                    "sessions": [
                        {
                            "sport": "run",
                            "type": "easy",
                            "title": f"Lauf {index + 1}",
                            "duration_min": 30,
                        }
                    ],
                }
                for index in range(16)
            ],
        },
    }
    _autopush(client, verbunden, False)
    antwort = client.post(
        "/api/plans/import",
        json={"raw": json.dumps(plan), "days": 16},
        headers=verbunden,
    )
    assert antwort.status_code == 201, antwort.text

    fertig = _uebertrage(client, verbunden)

    assert fertig["state"] == "failed"
    assert "15" in fertig["message"]
    assert fertig["workouts_pushed"] == 0
    assert len(fake._workouts) == 15
    assert fake._termine == {}


def test_geaenderte_einheit_wird_ersetzt_statt_verdoppelt(client, verbunden, fake):
    plan = _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)

    # Der Nutzer plant um: dieselbe Einheit, andere Dauer.
    from app.database import SessionLocal
    from app.models import PlanSession

    einheit_id = next(
        s["id"] for s in plan["sessions"] if s["sport"] != "rest"
    )
    with SessionLocal() as db:
        session = db.get(PlanSession, einheit_id)
        session.duration_min = 95
        db.commit()

    zustand = client.get("/api/garmin/workouts/status", headers=verbunden).json()
    assert zustand["geaendert"] == 1
    assert zustand["aktuell"] == 1

    fake.aufrufe.clear()
    fertig = _uebertrage(client, verbunden)

    assert fertig["state"] == "done"
    assert "update_workout" in fake.aufrufe
    assert "upload_workout" not in fake.aufrufe
    # Die Vorlage behält ihre Kennung — der Termin bleibt damit gültig.
    assert len(fake._workouts) == 15
    assert len(fake._termine) == 2


def test_status_kennt_offene_einheiten_vor_der_uebertragung(client, verbunden):
    _importiere_plan(client, verbunden)
    zustand = client.get("/api/garmin/workouts/status", headers=verbunden).json()

    assert zustand["offen"] == 2
    assert zustand["aktuell"] == 0
    assert {e["sport"] for e in zustand["einheiten"]} == {"run", "bike"}


def test_vergangene_tage_bleiben_liegen(client, verbunden, fake):
    """Ein Workout von vorgestern im Kalender wäre Altpapier."""
    plan = {
        "schema_version": "2.0",
        "plan": {
            "title": "Alter Block",
            "start_date": (HEUTE - timedelta(days=3)).isoformat(),
            "days": [
                {
                    "date": (HEUTE - timedelta(days=3)).isoformat(),
                    "sessions": [{"sport": "run", "type": "easy", "title": "Gestern",
                                  "duration_min": 40}],
                },
                {
                    "date": MORGEN.isoformat(),
                    "sessions": [{"sport": "run", "type": "easy", "title": "Morgen",
                                  "duration_min": 40}],
                },
            ],
        },
    }
    _autopush(client, verbunden, False)
    client.post(
        "/api/plans/import", json={"raw": json.dumps(plan)}, headers=verbunden
    )

    zustand = client.get("/api/garmin/workouts/status", headers=verbunden).json()
    assert zustand["vergangen"] == 1
    assert len(zustand["einheiten"]) == 1

    _uebertrage(client, verbunden)
    assert len(fake._workouts) == 15
    assert len(fake._termine) == 1


def _mache_vergangen(plan_session_id: int, tage: int = 1) -> None:
    """Schiebt eine übertragene Einheit in die Vergangenheit.

    Billiger als die Uhr zu stellen: Das Aufräumen entscheidet allein am Datum
    der Einheit, ob ihr Tag vorbei ist.
    """
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import GarminWorkoutLink, PlanSession

    with SessionLocal() as db:
        session = db.get(PlanSession, plan_session_id)
        session.date = HEUTE - timedelta(days=tage)
        link = db.scalar(
            select(GarminWorkoutLink).where(
                GarminWorkoutLink.plan_session_id == plan_session_id
            )
        )
        link.scheduled_date = session.date
        db.commit()


def test_abgleich_raeumt_vergangene_einheiten_auf(client, verbunden, fake):
    """Vergangene Termine geben ihren Slot frei, die Pool-ID bleibt bestehen."""
    plan = _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)
    assert len(fake._workouts) == 15

    _mache_vergangen(next(s["id"] for s in plan["sessions"] if s["sport"] == "run"))
    fake.aufrufe.clear()

    antwort = client.post("/api/garmin/sync", headers=verbunden)
    assert antwort.status_code == 202, antwort.text
    fertig = client.get(
        f"/api/garmin/jobs/{antwort.json()['id']}", headers=verbunden
    ).json()

    assert fertig["state"] == "done", fertig["message"]
    assert fertig["workouts_removed"] == 1
    assert "aufgeräumt" in fertig["message"]
    assert "unschedule_workout" in fake.aufrufe
    assert "delete_workout" not in fake.aufrufe
    assert len(fake._workouts) == 15
    assert len(fake._termine) == 1


def test_aufraeumen_laesst_fremde_workouts_stehen(client, verbunden, fake):
    """Angefasst wird nur, was diese App selbst angelegt hat."""
    plan = _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)

    # Ein Training, das der Athlet selbst in Connect gebaut hat.
    eigenes = fake.upload_workout({"workoutName": "Mein eigenes"})["workoutId"]
    for eintrag in plan["sessions"]:
        if eintrag["sport"] != "rest":
            _mache_vergangen(eintrag["id"])

    client.post("/api/garmin/sync", headers=verbunden)

    assert eigenes in fake._workouts
    assert len(fake._workouts) == 16


def test_uebertragen_raeumt_den_vorigen_termin_auf(client, verbunden, fake):
    """Auch ohne täglichen Abgleich bleibt der Kalender sauber."""
    plan = _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)

    _mache_vergangen(next(s["id"] for s in plan["sessions"] if s["sport"] == "run"))
    fertig = _uebertrage(client, verbunden)

    assert fertig["state"] == "done", fertig["message"]
    assert fertig["workouts_removed"] == 1
    assert "aufgeräumt" in fertig["message"]
    assert len(fake._workouts) == 15
    assert len(fake._termine) == 1


def test_neuplanung_raeumt_den_kalender_auch_ohne_uebertragung(
    client, verbunden, fake
):
    """Wer die Automatik abgeschaltet hat, behält trotzdem keinen alten Block.

    Ohne diesen Lauf stünde nach dem Neuplanen der *überholte* Block allein im
    Kalender — die neue Vorgabe geht nicht hin, die alte bleibt liegen und gilt
    auf der Uhr weiter. Dass ein Block nicht von selbst auf die Uhr geht, ist
    eine Entscheidung über das Hinlegen; das Wegräumen dessen, was diese App
    selbst einmal hingelegt hat, hängt nicht daran.
    """
    _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)
    assert len(fake._workouts) == 15

    antwort = _importiere(client, verbunden)  # autopush aus
    neu = antwort["plan"]

    fertig = _job(client, verbunden, antwort["garmin_job_id"])
    assert fertig["kind"] == "workout_cleanup"
    assert fertig["state"] == "done", fertig["message"]
    assert fertig["workouts_pushed"] == 0, "es sollte nichts hineingehen"
    assert fertig["workouts_removed"] == 2
    assert "abgelösten Block" in fertig["message"]

    # Der Kalender ist leer, nicht doppelt belegt — und der leere Vorgänger
    # fällt weg, sobald nichts mehr von ihm in Garmin steht.
    assert len(fake._workouts) == 15
    assert fake._termine == {}
    assert [p["id"] for p in client.get("/api/plans", headers=verbunden).json()] == [
        neu["id"]
    ]


def test_abgeloester_block_verschwindet_erst_nach_dem_aufraeumen(
    client, verbunden, fake
):
    """Der stillgelegte Plan hält seine Garmin-Einheiten fest, bis sie weg sind.

    Mit dem Plan verschwände die Zuordnung — und ohne sie fasst die App in
    Garmin nichts mehr an. Ein sofort gelöschter Block ließe seine Einheiten
    also für immer im fremden Kalender stehen, neben denen des neuen. Deshalb
    hier der Fall, in dem das Aufräumen scheitert: Der Block muss stehen
    bleiben, damit ein späterer Lauf ihn noch erreicht.
    """
    alt = _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)

    fake.unschedule_workout = _wirft_429
    antwort = _importiere(client, verbunden)
    neu = antwort["plan"]

    # Der Aufräumlauf hat sein einziges Ziel verfehlt und sagt das auch — als
    # „done" durchgewunken stünde eine Erfolgsmeldung über einem vollen Kalender.
    fertig = _job(client, verbunden, antwort["garmin_job_id"])
    assert fertig["state"] == "failed"
    assert "steht dort weiter" in fertig["message"]

    # Nichts ging weg, also bleiben beide Pläne — samt ihrer Zuordnungen.
    assert len(fake._workouts) == 15
    assert {p["id"] for p in client.get("/api/plans", headers=verbunden).json()} == {
        alt["id"],
        neu["id"],
    }

    del fake.unschedule_workout
    _entsperre(client, verbunden)
    fertig = _uebertrage(client, verbunden)
    assert fertig["state"] == "done", fertig["message"]

    # Erst räumt der Lauf die abgelösten Einheiten aus Garmin, dann fällt der
    # leere Block von selbst weg.
    assert [p["id"] for p in client.get("/api/plans", headers=verbunden).json()] == [
        neu["id"]
    ]
    assert len(fake._workouts) == 15


def test_entfernen_nimmt_termine_zurueck_und_behaelt_den_pool(
    client, verbunden, fake
):
    _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)

    antwort = client.post("/api/garmin/workouts/entfernen", json={}, headers=verbunden)
    assert antwort.status_code == 202, antwort.text
    fertig = client.get(
        f"/api/garmin/jobs/{antwort.json()['id']}", headers=verbunden
    ).json()

    assert fertig["state"] == "done"
    assert fertig["workouts_removed"] == 2
    assert len(fake._workouts) == 15
    assert fake._termine == {}

    zustand = client.get("/api/garmin/workouts/status", headers=verbunden).json()
    assert zustand["offen"] == 2


def test_cleanup_vor_poolmigration_entfernt_legacy_vorlage(
    client, verbunden, fake
):
    from app.database import SessionLocal
    from app.models import GarminWorkoutLink, PlanSession

    plan = _importiere_plan(client, verbunden)
    einheit_id = next(s["id"] for s in plan["sessions"] if s["sport"] != "rest")
    with SessionLocal() as db:
        session = db.get(PlanSession, einheit_id)
        workout = workouts.baue_workout(session)
        workout_id = fake.upload_workout(workout)["workoutId"]
        schedule_id = fake.schedule_workout(workout_id, session.date.isoformat())[
            "workoutScheduleId"
        ]
        db.add(
            GarminWorkoutLink(
                user_id=session.plan.user_id,
                plan_session_id=session.id,
                garmin_workout_id=str(workout_id),
                garmin_schedule_id=str(schedule_id),
                scheduled_date=session.date,
                title=workout["workoutName"],
                fingerabdruck=workouts.fingerabdruck(workout),
            )
        )
        db.commit()

    fake.aufrufe.clear()
    antwort = client.post("/api/garmin/workouts/entfernen", json={}, headers=verbunden)
    assert antwort.status_code == 202, antwort.text
    fertig = _job(client, verbunden, antwort.json()["id"])

    assert fertig["state"] == "done"
    assert "delete_workout" in fake.aufrufe
    assert fake._workouts == {}
    assert fake._termine == {}


def test_plan_loeschen_nimmt_seine_einheiten_aus_garmin(client, verbunden, fake):
    """Ein gelöschter Plan darf nichts auf der Uhr zurücklassen.

    Vorher verschwand nur die Zuordnung — und damit der einzige Weg, die
    Einheiten je wieder zu entfernen. Im Kalender stand dann eine Vorgabe, die
    es in der App gar nicht mehr gibt.
    """
    plan = _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)
    assert len(fake._workouts) == 15

    antwort = client.delete(f"/api/plans/{plan['id']}", headers=verbunden)
    assert antwort.status_code == 200, antwort.text
    assert antwort.json() == {"garmin_entfernt": 2, "garmin_fehler": []}

    assert len(fake._workouts) == 15
    assert fake._termine == {}
    assert client.get("/api/plans", headers=verbunden).json() == []


def test_plan_loeschen_wartet_auf_garmin_statt_karteileichen_zu_hinterlassen(
    client, verbunden, fake
):
    """Scheitert der Zugang, bleibt der Plan stehen — sonst wäre er unerreichbar.

    Ein Plan ist schnell noch einmal gelöscht; ein Workout in einem fremden
    Kalender, zu dem keine Zuordnung mehr führt, nie mehr. Wer trotzdem
    darauf besteht, sagt es ausdrücklich.
    """
    plan = _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)
    fake.unschedule_workout = _wirft_429

    antwort = client.delete(f"/api/plans/{plan['id']}", headers=verbunden)
    assert antwort.status_code == 429, antwort.text
    assert "nicht gelöscht" in antwort.json()["detail"]
    assert [p["id"] for p in client.get("/api/plans", headers=verbunden).json()] == [
        plan["id"]
    ]
    assert len(fake._workouts) == 15

    # Der ausdrückliche Weg daran vorbei — die Einheiten bleiben dann in Garmin
    # stehen und lassen sich nur noch im Kalender der App entfernen.
    antwort = client.delete(
        f"/api/plans/{plan['id']}?garmin_uebergehen=true", headers=verbunden
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["garmin_entfernt"] == 0
    assert client.get("/api/plans", headers=verbunden).json() == []
    assert len(fake._workouts) == 15


def test_einzelne_einheit_geht_ohne_job(client, verbunden, fake):
    plan = _importiere_plan(client, verbunden)
    einheit_id = next(s["id"] for s in plan["sessions"] if s["sport"] != "rest")

    antwort = client.post(
        f"/api/garmin/workouts/einheit/{einheit_id}", headers=verbunden
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["zustand"] == "aktuell"
    assert len(fake._workouts) == 15

    assert client.delete(
        f"/api/garmin/workouts/einheit/{einheit_id}", headers=verbunden
    ).status_code == 204
    assert len(fake._workouts) == 15
    assert fake._termine == {}


def test_einzeluebertragung_wartet_nicht_neben_einem_garmin_lauf(
    client, verbunden, fake
):
    from app.garmin.runner import runner

    plan = _importiere_plan(client, verbunden)
    einheit_id = next(s["id"] for s in plan["sessions"] if s["sport"] != "rest")

    with runner.exklusiver_direktaufruf():
        antwort = client.post(
            f"/api/garmin/workouts/einheit/{einheit_id}", headers=verbunden
        )

    assert antwort.status_code == 409
    assert "Garmin-Vorgang" in antwort.json()["detail"]
    assert fake._workouts == {}
    assert fake._termine == {}


def test_ruhetag_wird_abgelehnt(client, verbunden):
    plan = _importiere_plan(client, verbunden)
    ruhetag = next(s["id"] for s in plan["sessions"] if s["sport"] == "rest")

    antwort = client.post(
        f"/api/garmin/workouts/einheit/{ruhetag}", headers=verbunden
    )
    assert antwort.status_code == 422
    assert "Ruhetag" in antwort.json()["detail"]


# --------------------------------------------------------------------------
# Kalender
# --------------------------------------------------------------------------


def test_kalender_zeigt_eigene_und_fremde_eintraege(client, verbunden, fake):
    _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)

    antwort = client.get(
        f"/api/garmin/kalender?jahr={HEUTE.year}&monat={HEUTE.month}", headers=verbunden
    )
    assert antwort.status_code == 200, antwort.text
    eintraege = antwort.json()["eintraege"]

    eigene = [e for e in eintraege if e["aus_tri_coach"]]
    assert eigene, "Die übertragenen Einheiten fehlen im Kalender"
    assert all(e["art"] == "workout" for e in eigene)
    assert all(e["plan_session_id"] is not None for e in eigene)

    # Absolvierte Aktivitäten stehen daneben — sie gehören nicht dieser App.
    fremde = [e for e in eintraege if e["art"] == "aktivitaet"]
    assert fremde
    assert all(not e["aus_tri_coach"] for e in fremde)

    # Millisekunden und Zentimeter, nicht Sekunden und Meter: Die Aktivitäten
    # der Nachbildung laufen 3600 s über 12000 m.
    assert all(e["dauer_min"] == 60 for e in fremde)
    assert all(e["distanz_km"] == 12.0 for e in fremde)


def test_kalender_deutet_garmins_einheiten_richtig():
    """Der Fall aus der Praxis: 32:25 über 9,34 km, nicht 32417 min über 933 km."""
    aktivitaet = kalender.eintrag_aus_garmin({
        "itemType": "activity",
        "date": "2026-08-14",
        "title": "Sonthofen Radfahren",
        "activityId": 4711,
        "activityType": {"typeKey": "cycling"},
        "duration": 1945020,  # ms
        "distance": 933660,  # cm
    })
    assert aktivitaet["dauer_min"] == 32
    assert aktivitaet["distanz_km"] == 9.34

    # Beim geplanten Workout sagt der Feldname die Einheit — nur dieses Feld
    # wird gelesen, geraten wird nicht.
    workout = kalender.eintrag_aus_garmin({
        "itemType": "workout",
        "date": "2026-08-14",
        "title": "Schwellenintervalle",
        "workoutId": 99,
        "estimatedDurationInSecs": 3600,
        "estimatedDistanceInMeters": 12000,
    })
    assert workout["dauer_min"] == 60
    assert workout["distanz_km"] == 12.0


def test_kalender_erfindet_keine_dauer_aus_einem_deutungsfreien_feld():
    """Ein nacktes `duration` an einem Workout bleibt ungelesen.

    Ob Garmin dort Sekunden oder Millisekunden führt, ist nicht belegt. Eine
    fehlende Zeile ist besser als eine um Faktor 1000 falsche Dauer.
    """
    workout = kalender.eintrag_aus_garmin({
        "itemType": "workout",
        "date": "2026-08-14",
        "title": "Schwellenintervalle",
        "workoutId": 99,
        "duration": 3600,
        "distance": 12000,
    })
    assert workout["dauer_min"] is None
    assert workout["distanz_km"] is None


def test_kalender_benennt_garmins_namenlose_tageseintraege():
    """Eine Wiegung ist kein Termin, gehört aber trotzdem in den Kalender.

    Am echten Konto kamen für August 2026 53 Einträge, darunter 16 mit
    `itemType: "weight"` und einer mit `"nap"` — alle ohne `title`, ohne
    `workoutId`, ohne `activityId`. Sie standen deshalb als „Ohne Titel" da.
    Die Felder stammen aus der abgelesenen Antwort, nicht aus einer Vermutung:
    Das Gewicht kommt in Gramm, die Differenz zur Vormessung daneben.
    """
    wiegung = kalender.eintrag_aus_garmin({
        "id": 1787028093924,
        "itemType": "weight",
        "date": "2026-08-18",
        "title": None,
        "weight": 89680.0,
        "difference": -1299.0,
        "workoutId": None,
        "activityTypeId": None,
    })
    assert wiegung is not None
    # Zwei Nachkommastellen, deutsches Komma — genau das steht auf der Waage.
    assert wiegung["titel"] == "89,68 kg"
    assert wiegung["art"] == "sonstiges"

    # Glatte Kilogramm ohne angehängte Nullen.
    glatt = kalender.eintrag_aus_garmin({
        "itemType": "weight", "date": "2026-08-16", "title": None, "weight": 91000.0,
    })
    assert glatt["titel"] == "91 kg"

    nickerchen = kalender.eintrag_aus_garmin({
        "itemType": "nap",
        "date": "2026-07-29",
        "title": None,
        "duration": 2940,
        "napStartTimeLocal": "2026-07-29T07:59:46",
    })
    assert nickerchen["titel"] == "Nickerchen"
    # `duration` trägt hier keine Einheit im Namen — dieselbe Regel wie beim
    # Workout: lieber keine Zahl als eine um Faktor 1000 falsche.
    assert nickerchen["dauer_min"] is None


def test_kalender_zeigt_auch_was_er_nicht_benennen_kann():
    """Nichts wird verworfen — der Kalender soll den echten Stand zeigen.

    Was diese App nicht kennt, trägt Garmins eigene Gattungsbezeichnung. Ein
    stillschweigend weggelassener Eintrag wäre hier der schlimmere Fehler:
    Niemand bemerkt eine Lücke in einer Ansicht, die den fremden Kalender
    wiedergeben soll.
    """
    abzeichen = kalender.eintrag_aus_garmin({
        "itemType": "badge", "date": "2026-08-18", "title": None,
    })
    assert abzeichen is not None
    assert abzeichen["titel"] == "badge"

    # Eine Wiegung ohne Messwert fällt auf ihre Gattung zurück statt zu
    # verschwinden.
    ohne_wert = kalender.eintrag_aus_garmin({
        "itemType": "weight", "date": "2026-08-18", "title": None, "weight": None,
    })
    assert ohne_wert["titel"] == "weight"

    # Erst ohne jede Angabe bleibt der alte Rückfall.
    nichts = kalender.eintrag_aus_garmin({"date": "2026-08-18"})
    assert nichts["titel"] == "Ohne Titel"

    notiz = kalender.eintrag_aus_garmin({
        "itemType": "note", "date": "2026-08-18", "title": "Radservice",
    })
    assert notiz["art"] == "sonstiges"
    assert notiz["titel"] == "Radservice"


def test_kalendereintrag_loescht_keine_pool_vorlage(client, verbunden, fake):
    _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)

    eintraege = client.get(
        f"/api/garmin/kalender?jahr={HEUTE.year}&monat={HEUTE.month}", headers=verbunden
    ).json()["eintraege"]
    eigener = next(e for e in eintraege if e["aus_tri_coach"])
    fake.aufrufe.clear()

    antwort = client.delete(
        f"/api/garmin/kalender/{eigener['schedule_id']}"
        f"?workout_id={eigener['workout_id']}",
        headers=verbunden,
    )
    assert antwort.status_code == 204, antwort.text
    assert int(eigener["workout_id"]) in fake._workouts
    assert len(fake._workouts) == 15
    assert int(eigener["schedule_id"]) not in fake._termine
    assert "delete_workout" not in fake.aufrufe

    # Und die Einheit gilt wieder als offen.
    zustand = client.get("/api/garmin/workouts/status", headers=verbunden).json()
    assert zustand["offen"] == 1


def test_nur_termin_loeschen_laesst_die_vorlage_stehen(client, verbunden, fake):
    _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)

    eintraege = client.get(
        f"/api/garmin/kalender?jahr={HEUTE.year}&monat={HEUTE.month}", headers=verbunden
    ).json()["eintraege"]
    eigener = next(e for e in eintraege if e["aus_tri_coach"])

    client.delete(f"/api/garmin/kalender/{eigener['schedule_id']}", headers=verbunden)

    assert int(eigener["workout_id"]) in fake._workouts
    assert int(eigener["schedule_id"]) not in fake._termine


def test_monat_leeren_nimmt_alle_eigenen_termine_und_laesst_die_vorlagen(
    client, verbunden, fake
):
    """Der Knopf im Kalender: alles weg aus dem Zeitplan, nichts weg aus der Bibliothek."""
    _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)
    assert fake._termine
    fake.aufrufe.clear()

    antwort = client.post(
        "/api/garmin/kalender/leeren",
        json={"jahr": HEUTE.year, "monat": HEUTE.month},
        headers=verbunden,
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["entfernt"] == 2
    assert antwort.json()["fehler"] == []

    assert fake._termine == {}
    # Die fünfzehn Pool-Vorlagen sind der Kern der ganzen Übertragung — an sie
    # darf dieser Knopf nicht rühren.
    assert len(fake._workouts) == 15
    assert "delete_workout" not in fake.aufrufe

    # Und die Einheiten warten wieder auf ihre Übertragung.
    zustand = client.get("/api/garmin/workouts/status", headers=verbunden).json()
    assert zustand["aktuell"] == 0
    assert zustand["offen"] + zustand["geaendert"] == 2


def test_monat_leeren_laesst_fremde_termine_stehen(client, verbunden, fake):
    """Was der Athlet in Connect selbst eingeplant hat, gehört dieser App nicht."""
    _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)

    fremd = fake.upload_workout({"workoutName": "Eigener Longrun"})["workoutId"]
    fremder_termin = fake.schedule_workout(fremd, HEUTE.isoformat())[
        "workoutScheduleId"
    ]

    antwort = client.post(
        "/api/garmin/kalender/leeren",
        json={"jahr": HEUTE.year, "monat": HEUTE.month},
        headers=verbunden,
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["entfernt"] == 2

    assert list(fake._termine) == [fremder_termin]
    assert fremd in fake._workouts


def test_monat_leeren_wartet_nicht_neben_einem_garmin_lauf(client, verbunden, fake):
    """Eine Reihe von Schreibaufrufen neben einem Übertragungslauf: 409 statt Rennen."""
    from app.garmin.runner import runner

    _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)
    vorher = dict(fake._termine)

    with runner.exklusiver_direktaufruf():
        antwort = client.post(
            "/api/garmin/kalender/leeren",
            json={"jahr": HEUTE.year, "monat": HEUTE.month},
            headers=verbunden,
        )

    assert antwort.status_code == 409
    assert "Garmin-Vorgang" in antwort.json()["detail"]
    assert fake._termine == vorher


def test_verschieben_legt_den_termin_auf_einen_anderen_tag(client, verbunden, fake):
    _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)

    eintraege = client.get(
        f"/api/garmin/kalender?jahr={HEUTE.year}&monat={HEUTE.month}", headers=verbunden
    ).json()["eintraege"]
    eigener = next(e for e in eintraege if e["aus_tri_coach"])
    ziel = HEUTE + timedelta(days=5)

    antwort = client.post(
        f"/api/garmin/kalender/{eigener['schedule_id']}/verschieben",
        json={"workout_id": eigener["workout_id"], "datum": ziel.isoformat()},
        headers=verbunden,
    )
    assert antwort.status_code == 204, antwort.text

    termine = {tag for _, tag in fake._termine.values()}
    assert ziel.isoformat() in termine
    # Die Vorlage blieb dieselbe — sonst hinge die Zuordnung in der Luft.
    assert int(eigener["workout_id"]) in fake._workouts


def test_in_garmin_geloeschtes_workout_wird_neu_angelegt(client, verbunden, fake):
    """Wer die Vorlage in Connect löscht, darf hier nicht dauerhaft hängen bleiben."""
    plan = _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)
    vorher = set(fake._workouts)

    # Eine Vorlage von Hand in Garmin Connect gelöscht — die App weiß davon nichts.
    geloescht = next(iter(fake._termine.values()))[0]
    fake._workouts.pop(geloescht)
    for schedule_id, (workout_id, _) in list(fake._termine.items()):
        if workout_id == geloescht:
            fake._termine.pop(schedule_id)

    # Der Plan ändert sich, damit die Übertragung die Vorlage anfassen muss.
    from app.database import SessionLocal
    from app.models import PlanSession

    einheit_id = next(s["id"] for s in plan["sessions"] if s["sport"] != "rest")
    with SessionLocal() as db:
        session = db.get(PlanSession, einheit_id)
        session.duration_min = 75
        db.commit()

    fake.aufrufe.clear()
    fertig = _uebertrage(client, verbunden)

    assert fertig["state"] == "done", fertig["message"]
    assert len(fake._workouts) == 15
    assert len(vorher & set(fake._workouts)) == 14
    assert fake.aufrufe.count("upload_workout") == 1
    zustand = client.get("/api/garmin/workouts/status", headers=verbunden).json()
    assert zustand["fehler"] == 0


# --------------------------------------------------------------------------
# Der Zustand der App gegen den Zustand in Garmin
#
# `GarminWorkoutLink` allein ist eine Behauptung: „liegt in Garmin", weil die
# App es einmal hingelegt hat. Wird sie nicht nachgeprüft, zeigt die Oberfläche
# einen leeren Kalender neben dem Satz „6 von 8 Einheiten liegen in Garmin" —
# und der Knopf zum Übertragen überspringt genau die Einheiten, die fehlen.
# --------------------------------------------------------------------------


def test_kalender_deckt_auf_dass_workouts_in_garmin_fehlen(client, verbunden, fake):
    _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)
    assert client.get("/api/garmin/workouts/status", headers=verbunden).json()["aktuell"] == 2

    # Der Athlet räumt in Connect auf.
    fake._workouts.clear()
    fake._termine.clear()

    kalender = client.get(
        f"/api/garmin/kalender?jahr={HEUTE.year}&monat={HEUTE.month}", headers=verbunden
    ).json()
    assert not [e for e in kalender["eintraege"] if e["aus_tri_coach"]]

    # Der Monat lag ohnehin vor — die Zuordnungen sind damit berichtigt.
    zustand = client.get("/api/garmin/workouts/status", headers=verbunden).json()
    assert (zustand["aktuell"], zustand["offen"]) == (0, 2)


def test_uebertragen_legt_in_garmin_geloeschte_einheiten_neu_an(client, verbunden, fake):
    """Ohne den Abstecher zu Garmin übersprünge der Lauf genau das Fehlende."""
    _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)
    fake._workouts.clear()
    fake._termine.clear()
    fake.aufrufe.clear()

    fertig = _uebertrage(client, verbunden)

    assert fertig["state"] == "done", fertig["message"]
    assert fertig["workouts_pushed"] == 2
    assert len(fake._workouts) == 15
    assert fake.aufrufe.count("upload_workout") == 15
    assert len(fake._termine) == 2


def test_termin_ohne_kennung_gilt_nicht_als_erfolg(client, verbunden, fake):
    """Sonst meldete der Lauf Erfolg und jeder weitere Druck legte einen Termin daneben."""
    echtes_planen = fake.schedule_workout
    fake.schedule_workout = lambda workout_id, date_str: (
        echtes_planen(workout_id, date_str) and {}
    )

    _importiere_plan(client, verbunden)
    fertig = _uebertrage(client, verbunden)

    assert fertig["state"] == "failed"
    assert "keine Kennung" in fertig["message"]
    zustand = client.get("/api/garmin/workouts/status", headers=verbunden).json()
    assert zustand["fehler"] == 2

    # Der zweite Lauf findet den Termin im Kalender und trägt seine Kennung
    # nach, statt einen zweiten anzulegen.
    fake.schedule_workout = echtes_planen
    assert len(fake._termine) == 2
    _uebertrage(client, verbunden)
    assert len(fake._termine) == 2
    assert client.get("/api/garmin/workouts/status", headers=verbunden).json()["fehler"] == 0


def test_abgeloester_block_wird_aus_garmin_geraeumt(client, verbunden, fake):
    """Zwei Blöcke auf denselben Tagen hießen zwei Trainings je Tag auf der Uhr."""
    _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)
    pool_ids = set(fake._workouts)

    # Der nächste Block: ein neuer Plan, der alte wird nur stillgelegt.
    _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)

    assert set(fake._workouts) == pool_ids
    assert len(fake._termine) == 2


def test_unbekannte_kalenderform_wird_gemeldet_statt_verschwiegen(client, verbunden, fake):
    """Ein leerer Monat und eine unverstandene Antwort dürfen nicht gleich aussehen."""
    fake.get_scheduled_workouts = lambda jahr, monat: {"unbekannt": []}

    antwort = client.get(
        f"/api/garmin/kalender?jahr={HEUTE.year}&monat={HEUTE.month}", headers=verbunden
    )
    assert antwort.status_code == 502
    assert "unerwarteten Form" in antwort.json()["detail"]


def test_verschieben_nimmt_die_planeinheit_mit(client, verbunden, fake):
    """Sonst schöbe die nächste Übertragung den Termin wortlos zurück."""
    _importiere_plan(client, verbunden, tage=2)
    _uebertrage(client, verbunden)

    eintraege = client.get(
        f"/api/garmin/kalender?jahr={HEUTE.year}&monat={HEUTE.month}", headers=verbunden
    ).json()["eintraege"]
    eigener = next(e for e in eintraege if e["aus_tri_coach"])
    ziel = HEUTE + timedelta(days=4)

    client.post(
        f"/api/garmin/kalender/{eigener['schedule_id']}/verschieben",
        json={"workout_id": eigener["workout_id"], "datum": ziel.isoformat()},
        headers=verbunden,
    )
    _uebertrage(client, verbunden)

    assert ziel.isoformat() in {tag for _, tag in fake._termine.values()}
    plan = client.get("/api/plans/active", headers=verbunden).json()
    assert ziel.isoformat() in {s["date"] for s in plan["sessions"]}


def test_eine_abgelehnte_einheit_stoppt_die_anderen_nicht(client, verbunden, fake):
    """Garmin lehnt gelegentlich einzelne Workouts ab — das darf kein Alles-oder-Nichts sein."""
    _importiere_plan(client, verbunden)
    original = fake.update_workout
    versuche = {"n": 0}

    def mal_so_mal_so(workout_id, workout_json):
        versuche["n"] += 1
        if versuche["n"] == 1:
            raise RuntimeError("400 Bad Request: unsupported step")
        return original(workout_id, workout_json)

    fake.update_workout = mal_so_mal_so
    fertig = _uebertrage(client, verbunden)

    assert fertig["state"] == "done"
    assert fertig["workouts_pushed"] == 1
    assert "Nicht geklappt hat es bei" in fertig["message"]
    assert len(fake._workouts) == 15

    zustand = client.get("/api/garmin/workouts/status", headers=verbunden).json()
    assert zustand["aktuell"] == 1
    assert zustand["offen"] == 1


def test_anfragesperre_beendet_die_uebertragung_sofort(client, verbunden, fake):
    """Weitermachen verlängerte die Sperre nur — deshalb hält der ganze Lauf an."""
    from garminconnect import GarminConnectTooManyRequestsError

    _importiere_plan(client, verbunden)

    def gesperrt(workout_json):
        raise GarminConnectTooManyRequestsError("429 Too Many Requests")

    fake.upload_workout = gesperrt
    fertig = _uebertrage(client, verbunden)

    assert fertig["state"] == "rate_limited"
    assert "48 Stunden" in fertig["message"]

    # Ein sofortiger zweiter Versuch wird abgelehnt, statt es erneut zu wagen.
    antwort = client.post("/api/garmin/workouts/uebertragen", json={}, headers=verbunden)
    assert antwort.status_code == 429


def test_uebertragen_ohne_plan_meldet_409(client, verbunden):
    antwort = client.post(
        "/api/garmin/workouts/uebertragen", json={"plan_id": 999999}, headers=verbunden
    )
    assert antwort.status_code == 404


def test_uebertragen_ohne_garmin_konto_meldet_409(client, garmin_auth):
    antwort = client.post("/api/garmin/workouts/uebertragen", json={}, headers=garmin_auth)
    assert antwort.status_code == 409
    assert "kein Garmin-Konto" in antwort.json()["detail"]


# --------------------------------------------------------------------------
# Die Automatik: Ein übernommener Block geht von selbst auf die Uhr
# --------------------------------------------------------------------------


def _wirft_429(*_args):
    from garminconnect import GarminConnectTooManyRequestsError

    raise GarminConnectTooManyRequestsError("429 Too Many Requests")


def _job(client, auth, job_id):
    return client.get(f"/api/garmin/jobs/{job_id}", headers=auth).json()


def test_uebernommener_block_geht_von_selbst_auf_die_uhr(client, verbunden, fake):
    """Der Knopf bleibt, ist aber nicht mehr der Weg."""
    antwort = _importiere(client, verbunden, autopush=True)

    assert antwort["garmin_job_id"] is not None
    assert antwort["garmin_hinweis"] is None

    fertig = _job(client, verbunden, antwort["garmin_job_id"])
    assert fertig["state"] == "done", fertig["message"]
    assert fertig["workouts_pushed"] == 2  # der Ruhetag bleibt außen vor
    assert len(fake._workouts) == 15
    assert len(fake._termine) == 2


def test_abgeschaltete_automatik_laesst_den_kalender_unberuehrt(client, verbunden, fake):
    antwort = _importiere(client, verbunden, autopush=False)

    assert antwort["garmin_job_id"] is None
    assert fake._workouts == {}
    assert "upload_workout" not in fake.aufrufe


def test_neuer_block_verdraengt_den_alten_aus_dem_kalender(client, verbunden, fake):
    """Sonst stünden auf jedem Tag zwei Trainings, von denen eines überholt ist."""
    _importiere(client, verbunden, autopush=True)
    zuerst = set(fake._workouts)
    assert len(zuerst) == 15

    # Derselbe Zeitraum, neu geplant.
    _importiere(client, verbunden, autopush=True)

    assert set(fake._workouts) == zuerst
    assert len(fake._termine) == 2

    # Und der leere Vorgänger fällt weg, sobald nichts mehr von ihm in Garmin steht.
    assert len(client.get("/api/plans", headers=verbunden).json()) == 1


def test_folgeblock_laesst_die_restlichen_tage_stehen(client, verbunden, fake):
    """Wer die nächste Woche plant, verliert nicht den Rest dieser Woche.

    Abgelöst ist ein Tag erst, wenn der neue Block ihn beansprucht. Sonst stünde
    der Athlet zwischen heute und dem Blockbeginn ohne Vorgabe auf der Uhr da —
    obwohl er nichts weggeplant hat.
    """
    _importiere(client, verbunden, autopush=True)
    pool_ids = set(fake._workouts)
    laufende_termine = dict(fake._termine)
    assert len(pool_ids) == 15

    # Der nächste Block hängt hinten an, statt die laufenden Tage zu ersetzen.
    _importiere(client, verbunden, autopush=True, ab=HEUTE + timedelta(days=3))

    assert set(fake._workouts) == pool_ids
    assert laufende_termine.items() <= fake._termine.items()
    assert len(fake._termine) == 4


def test_abgeloester_block_geht_auch_bei_gescheiterter_uebertragung(
    client, verbunden, fake
):
    """Erst räumen, dann legen.

    Andersherum bliebe nach einem Abbruch mitten im Lauf der alte Block neben
    dem halben neuen stehen — zwei Vorgaben am selben Tag, und welche gilt,
    sieht der Athlet auf der Uhr nicht. Ein Tag ohne Vorgabe ist das kleinere
    Übel.
    """
    _importiere(client, verbunden, autopush=True)
    assert len(fake._workouts) == 15

    fake.update_workout = _wirft_429
    antwort = _importiere(client, verbunden, autopush=True)

    fertig = _job(client, verbunden, antwort["garmin_job_id"])
    assert fertig["state"] == "rate_limited"
    assert len(fake._workouts) == 15
    assert fake._termine == {}


def test_gesperrte_verbindung_erklaert_den_leeren_kalender(client, verbunden, fake):
    """Wer nichts auf der Uhr findet, soll den Grund beim Übernehmen lesen."""
    _importiere_plan(client, verbunden)
    fake.upload_workout = _wirft_429
    assert _uebertrage(client, verbunden)["state"] == "rate_limited"

    antwort = _importiere(client, verbunden, autopush=True)

    assert antwort["garmin_job_id"] is None
    assert "gesperrt" in antwort["garmin_hinweis"]


def test_frueherer_block_von_hand_uebertragen_bleibt_stehen(
    client, verbunden, fake, erfasse
):
    """Ein stillgelegter Plan lässt sich gezielt übertragen — und überlebt es.

    Ohne die Ausnahme in `raeume_ersetzte_auf` löschte derselbe Lauf am Ende
    wieder, was er gerade hochgeladen hat: Der Block ist ja nicht mehr aktiv.

    Das erfasste Training hält den alten Block am Leben: Ohne eine absolvierte
    Einheit räumt ihn die Neuplanung weg, sobald nichts mehr von ihm in Garmin
    steht — dann gäbe es nichts mehr, was sich von Hand übertragen ließe.
    """
    alt = _importiere_plan(client, verbunden)
    erfasse(
        verbunden,
        plan_session_id=alt["sessions"][0]["id"],
        date=date.fromisoformat(alt["sessions"][0]["date"]),
        sport=alt["sessions"][0]["sport"],
        duration_min=60,
    )
    _uebertrage(client, verbunden)
    _importiere_plan(client, verbunden)  # legt ihn still und räumt ihn aus Garmin

    antwort = client.post(
        "/api/garmin/workouts/uebertragen",
        json={"plan_id": alt["id"]},
        headers=verbunden,
    )
    assert antwort.status_code == 202, antwort.text
    fertig = _job(client, verbunden, antwort.json()["id"])

    assert fertig["state"] == "done", fertig["message"]
    assert fertig["workouts_removed"] == 0
    assert len(fake._workouts) == 15


def test_bei_katalogtreffer_traegt_die_beschreibung_den_englischen_namen():
    """Oben Garmins deutsche Bezeichnung, unten der englische Name.

    Die Überschrift eines Übungsschritts kommt allein aus `category` und
    `exerciseName`; Garmin übersetzt sie in die Sprache seiner App. Der
    deutsche Name aus dem Plan steht damit schon oben und wird in der
    Beschreibung durch den englischen aus der Klammer ersetzt — jede Zeile
    nennt ihre Übung genau einmal je Sprache.
    """
    plan = workouts.baue_workout(
        einheit(
            sport="mobility",
            duration_min=20,
            structure=(
                "Hüftbeuger-Dehnung (Hip Flexor Stretch) 2x45 s je Seite"
                " / Taubenstellung (Pigeon Pose) 2x45 s je Seite"
                " / Katze-Kuh (Cat-Cow) 10 Wdh."
            ),
        ),
        zonen=ZONEN,
    )

    assert [s["description"] for s in uebungsschritte(plan)] == [
        "Hip Flexor Stretch 2x45 s je Seite — je Durchgang eine Seite",
        "Pigeon Pose 2x45 s je Seite — je Durchgang eine Seite",
        "Cat-Cow 10 Wdh",
    ]


def test_ohne_katalogtreffer_bleibt_der_deutsche_name_stehen():
    """Was Garmin nicht kennt, behält seine Bezeichnung in der Beschreibung.

    Faszienrollen führt Garmins Katalog nicht, der Titel bleibt dort leer
    („--“). Den deutschen Namen gegen den englischen zu tauschen nähme dem
    Schritt die einzige Bezeichnung, die der Athlet dann noch sieht.
    """
    plan = workouts.baue_workout(
        einheit(
            sport="mobility",
            duration_min=15,
            structure=(
                "Faszienrolle Gesäß (Foam Roll Glutes) 90 s je Seite"
                " / Taubenstellung (Pigeon Pose) 2x45 s je Seite"
            ),
        ),
        zonen=ZONEN,
    )
    folge = uebungsschritte(plan)

    assert folge[0].get("exerciseName") is None
    assert folge[0]["description"] == (
        "Faszienrolle Gesäß (Foam Roll Glutes) 90 s je Seite"
        " — je Durchgang eine Seite"
    )
    assert folge[1]["description"].startswith("Pigeon Pose")


def test_der_tausch_laesst_umfang_und_ausfuehrungshinweis_unangetastet():
    """Zwei Proben halten ihn davon ab, mehr wegzunehmen als den Namen.

    Steht der Umfang *vor* der Klammer, nähme der Tausch ihn mit; und ein
    deutscher Ausführungshinweis in der Klammer ist kein englischer Name.
    Beides erkennt die Zeile an sich selbst, ohne zu raten.
    """
    plan = workouts.baue_workout(
        einheit(
            sport="strength",
            duration_min=20,
            structure=(
                "3x12 Liegestütze (Push-Up)"
                " / Wandsitz (Rücken flach an der Wand) 3x30 s"
            ),
        ),
        zonen=ZONEN,
    )
    folge = uebungsschritte(plan)

    # Der Umfang steht vor der Klammer — die Zeile bleibt, wie sie ist.
    assert folge[0]["exerciseName"] == "PUSH_UP"
    assert folge[0]["description"] == "3x12 Liegestütze (Push-Up)"
    # Ein Umlaut verrät den deutschen Nachsatz.
    assert folge[1]["exerciseName"] == "BODY_WEIGHT_WALL_SQUAT"
    assert folge[1]["description"] == "Wandsitz (Rücken flach an der Wand) 3x30 s"


# --------------------------------------------------------------------------
# Der Bauplan der KI (`steps`) — der zweite Weg neben dem Fließtext
# --------------------------------------------------------------------------


def test_bauplan_schlaegt_den_fliesstext():
    """Beide Kanäle vorhanden: Was die KI ausdrücklich sagt, gewinnt.

    Der Fließtext ist hier absichtlich ein Fall, an dem der Zerleger einmal
    gescheitert ist — die Serie hinter dem Schrägstrich. Der Bauplan sagt
    dieselbe Einheit ohne Grammatik dazwischen.
    """
    plan = workouts.baue_workout(
        einheit(
            sport="run",
            structure="15 min Einlaufen Z2 / 5x1000 m Z4, dazwischen 2 min traben / 10 min Auslaufen Z1",
            steps_json=[
                {"kind": "warmup", "duration_s": 900, "zone": "Z2", "text": "Einlaufen"},
                {
                    "repeat": 5,
                    "steps": [
                        {"kind": "interval", "distance_m": 1000, "zone": "Z4", "text": "zügig"},
                        {"kind": "recovery", "duration_s": 120, "text": "Trabpause"},
                    ],
                },
                {"kind": "cooldown", "duration_s": 600, "zone": "Z1", "text": "Auslaufen"},
            ],
        ),
        zonen=ZONEN,
    )
    abschnitte = schritte(plan)
    assert [a.get("type") for a in abschnitte] == [
        "ExecutableStepDTO",
        "RepeatGroupDTO",
        "ExecutableStepDTO",
    ]
    gruppe = abschnitte[1]
    assert gruppe["numberOfIterations"] == 5
    assert len(gruppe["workoutSteps"]) == 2
    # Die Pause sagt sich selbst als Pause — nicht abgeleitet aus ihrer Position.
    assert gruppe["workoutSteps"][1]["stepType"]["stepTypeKey"] == "recovery"
    assert abschnitte[0]["stepType"]["stepTypeKey"] == "warmup"
    assert abschnitte[2]["stepType"]["stepTypeKey"] == "cooldown"


def test_ohne_bauplan_bleibt_es_beim_zerleger():
    """Der Rückfall trägt die Blöcke, die vor dem Feld entstanden sind."""
    mit_text = einheit(
        sport="run",
        steps_json=None,
        structure="15 min Einlaufen Z2 / 5x1000 m Z4, dazwischen 2 min traben / 10 min Auslaufen Z1",
    )
    assert len(schritte(workouts.baue_workout(mit_text, zonen=ZONEN))) == 3


def test_unbrauchbare_schritte_fallen_weg_statt_das_workout_zu_kippen():
    """Dieselbe Linie wie beim Import: Warnung statt Ablehnung.

    Ein Abschnitt ohne jedes Maß steuert die Uhr nicht — er fällt heraus, die
    übrigen gehen durch. Bleibt gar nichts übrig, greift der Fließtext.
    """
    plan = workouts.baue_workout(
        einheit(
            sport="run",
            structure="40 min locker",
            steps_json=[
                {"kind": "warmup", "duration_s": 600, "text": "Einlaufen"},
                {"kind": "interval", "text": "irgendwas ohne Maß"},
                {"kind": "cooldown", "duration_s": 300, "text": "Auslaufen"},
            ],
        ),
        zonen=ZONEN,
    )
    assert len(schritte(plan)) == 2

    # Nichts Brauchbares im Bauplan -> der Fließtext übernimmt.
    leer = einheit(
        sport="run", structure="40 min locker Z2", steps_json=[{"kind": "interval"}]
    )
    assert len(schritte(workouts.baue_workout(leer, zonen=ZONEN))) == 1


def test_bauplan_nennt_die_uebung_beim_namen():
    """`exercise_en` ersetzt das Herausfischen aus der Zeile.

    Genau hier lagen die Fehlgriffe des Textwegs: „Lateral Band Walk" zog die
    Animation eines Spaziergangs an sich, „Copenhagen Plank" die des
    Unterarmstützes.
    """
    plan = workouts.baue_workout(
        einheit(
            sport="strength",
            structure="Seitstütz (Side Plank) 3x40 s je Seite",
            steps_json=[
                {
                    "repeat": 3,
                    "steps": [
                        {
                            "kind": "interval",
                            "duration_s": 40,
                            "text": "Side Plank",
                            "exercise_en": "Side Plank",
                        }
                    ],
                }
            ],
        ),
        zonen=ZONEN,
    )
    schritt = schritte(plan)[0]["workoutSteps"][0]
    assert schritt["category"] == "PLANK"
    assert "SIDE_PLANK" in schritt["exerciseName"]


def test_bauplan_ueberlebt_den_weg_durch_den_import():
    """Von der KI-Antwort bis zur Garmin-JSON, ohne Abkürzung.

    Der Bauplan wandert durch drei Stationen — Pydantic, `steps_json` an der
    Einheit, `baue_workout` —, und jede könnte ihn stillschweigend verlieren.
    Genau das wäre der teuerste Fehler: Das Workout entstünde weiter aus dem
    Fließtext, und niemandem fiele auf, dass der zweite Kanal gar nicht trägt.
    """
    from app.plan_import import _schritte_json, parse_ai_response

    antwort = json.dumps({
        "plan": {
            "title": "Testblock",
            "start_date": "2026-08-20",
            "days": [{
                "date": "2026-08-20",
                "sessions": [{
                    "sport": "Laufen",
                    "type": "intervals",
                    "title": "Schwellenintervalle",
                    "structure": "15 min Einlaufen / 4x2000 m Z4, 3 min Pause / 10 min Auslaufen",
                    "steps": [
                        {"kind": "Einlaufen", "duration_s": 900, "zone": "Z2", "text": "Einlaufen"},
                        {"repeat": 4, "steps": [
                            {"kind": "work", "distance_m": 2000, "zone": "Z4", "text": "zügig"},
                            {"kind": "Pause", "duration_s": 180, "text": "Trabpause"},
                        ]},
                        {"kind": "cooldown", "duration_s": 600, "zone": "Z1", "text": "Auslaufen"},
                    ],
                }],
            }],
        }
    })

    body = parse_ai_response(antwort)
    ki_einheit = body.days[0].sessions[0]
    # Die Sprachvarianten sind unterwegs normalisiert worden.
    assert [s.kind for s in ki_einheit.steps] == ["warmup", "interval", "cooldown"]
    assert [s.kind for s in ki_einheit.steps[1].steps] == ["interval", "recovery"]

    gespeichert = _schritte_json(ki_einheit)
    plan = workouts.baue_workout(
        einheit(sport="run", structure=ki_einheit.structure, steps_json=gespeichert),
        zonen=ZONEN,
    )
    abschnitte = schritte(plan)
    assert abschnitte[1]["numberOfIterations"] == 4
    assert abschnitte[1]["workoutSteps"][0]["endConditionValue"] == 2000
    assert abschnitte[1]["workoutSteps"][1]["stepType"]["stepTypeKey"] == "recovery"


def test_koppeleinheit_wird_im_bauplan_benannt_statt_geschaetzt():
    """Der eine Fall, an dem der Textweg ausdrücklich schätzt.

    Ohne erkennbare Teilung im Aufbautext fällt `_koppel_segmente` auf 2:1 für
    Rad und Lauf zurück und weist das in der Beschreibung aus. Sagt der Bauplan
    die Disziplin, wird nicht geschätzt.
    """
    plan = workouts.baue_workout(
        einheit(
            sport="brick",
            duration_min=90,
            structure="Koppeleinheit",
            steps_json=[
                {"kind": "interval", "duration_s": 3600, "sport": "bike", "text": "Rad Z3"},
                {"kind": "interval", "duration_s": 1200, "sport": "run", "text": "Antritt Z2"},
            ],
        ),
        zonen=ZONEN,
    )
    segmente = plan["workoutSegments"]
    assert [s["sportType"]["sportTypeKey"] for s in segmente] == ["cycling", "running"]
    assert "geschätzt" not in plan["description"]
