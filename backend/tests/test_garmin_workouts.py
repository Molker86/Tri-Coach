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
    )
    felder.update(abweichend)
    return SimpleNamespace(**felder)


def schritte(workout, segment=0):
    return workout["workoutSegments"][segment]["workoutSteps"]


# --------------------------------------------------------------------------
# Der Aufbautext wird zu Schritten
# --------------------------------------------------------------------------


def test_intervalltext_wird_zu_wiederholungsgruppe():
    plan = workouts.baue_workout(
        einheit(structure="15 min Einlaufen Z1-Z2, 5 x 3 min Z4 mit je 2 min Trabpause, 10 min Auslaufen"),
        zonen=ZONEN,
    )
    folge = schritte(plan)

    assert [s["stepType"]["stepTypeKey"] for s in folge] == ["warmup", "repeat", "cooldown"]
    gruppe = folge[1]
    assert gruppe["numberOfIterations"] == 5
    belastung, pause = gruppe["workoutSteps"]

    assert belastung["endConditionValue"] == 180.0
    assert belastung["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert (belastung["targetValueOne"], belastung["targetValueTwo"]) == (155.0, 170.0)

    # Die Pause bleibt ohne Zielkorridor: Ein Alarm in der Erholung triebe
    # genau die Herzfrequenz hoch, die gerade sinken soll.
    assert pause["stepType"]["stepTypeKey"] == "recovery"
    assert pause["targetType"]["workoutTargetTypeKey"] == "no.target"

    # Die Schrittnummern laufen über die Verschachtelung hinweg durch.
    assert [s["stepOrder"] for s in folge] == [1, 2, 5]
    assert [s["stepOrder"] for s in gruppe["workoutSteps"]] == [3, 4]


def test_streckenintervalle_enden_nach_distanz():
    plan = workouts.baue_workout(
        einheit(structure="20 min einlaufen, 6x800m (3:45/km) mit 400m Trabpause, 15 min auslaufen"),
        zonen=ZONEN,
    )
    belastung = schritte(plan)[1]["workoutSteps"][0]
    assert belastung["endCondition"]["conditionTypeKey"] == "distance"
    assert belastung["endConditionValue"] == 800.0
    # Die Tempoangabe in der Klammer darf nicht als Dauer von 3:45 durchgehen.
    assert belastung["endConditionValue"] != 225.0


def test_unverstandener_text_wird_ein_einziger_schritt():
    """Lieber grob und richtig als fein und geraten."""
    plan = workouts.baue_workout(
        einheit(structure="Ganzkörperkraft nach Tagesform, 3 Runden", duration_min=45),
        zonen=ZONEN,
    )
    folge = schritte(plan)
    assert len(folge) == 1
    assert folge[0]["endConditionValue"] == 45 * 60


def test_uebungsliste_wird_abschnitt_fuer_abschnitt_uebernommen():
    """Was in der Notiz als Aufbau steht, muss auf der Uhr als Abschnitt stehen."""
    plan = workouts.baue_workout(
        einheit(
            sport="mobility",
            duration_min=12,
            target_hr_low=90,
            target_hr_high=115,
            structure=(
                "90/90-Hüftrotation 2x8 je Seite"
                " / Hüftbeuger-Ausfallschritt 2x45 s je Seite"
                " / Tractus- und Glutealdehnung 2x45 s je Seite"
                " / Thoraxrotation 2x8 je Seite"
            ),
        ),
        zonen=ZONEN,
    )
    folge = schritte(plan)

    # Vorher blieben zwei Schritte übrig: Übungen ohne Zeitangabe fielen weg,
    # und aus „2x45 s je Seite“ wurde ein einziger Schritt über 45 Sekunden.
    assert [s["description"] for s in folge] == [
        "90/90-Hüftrotation 2x8 je Seite",
        "Hüftbeuger-Ausfallschritt 2x45 s je Seite",
        "Tractus- und Glutealdehnung 2x45 s je Seite",
        "Thoraxrotation 2x8 je Seite",
    ]
    assert all(s["endCondition"]["conditionTypeKey"] == "lap.button" for s in folge)
    # Kein Herzfrequenzalarm über einer Dehnung.
    assert all(s["targetType"]["workoutTargetTypeKey"] == "no.target" for s in folge)
    assert plan["estimatedDurationInSecs"] == 12 * 60


def test_krafttext_wird_keine_wiederholungsgruppe():
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

    assert all(s["type"] == "ExecutableStepDTO" for s in folge)
    # „mit Band“ gehört zur Übung, das Komma trennt einen Zusatz und keine Übung.
    assert [s["description"] for s in folge] == [
        "3x15 Side-Lying Leg Raise je Seite",
        "3x40 s Side Plank je Seite",
        "3x15 Monster Walks mit Band",
        "3x8 Step-Downs je Seite, 4 s exzentrisch abgesenkt",
    ]
    # Und keine Übung wird zur Pause umgedeutet, bloß weil sie an zweiter
    # Stelle steht.
    assert {s["stepType"]["stepTypeKey"] for s in folge} == {"interval"}


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
    folge = schritte(plan)

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
    Dessen Schritte enden ebenfalls per Rundentaste, tragen dabei aber einen
    Zahlenwert und die Gewichts-, Zug- und Materialfelder. Mit leerem
    `endConditionValue` erkannte die Uhr den Schritt nicht als Übung.
    """
    plan = workouts.baue_workout(
        einheit(
            sport="mobility",
            duration_min=12,
            structure="Katze-Kuh 10 Wiederholungen / Wadendehnung 2x30 s je Seite",
        ),
        zonen=ZONEN,
    )
    for schritt in schritte(plan):
        assert schritt["endCondition"]["conditionTypeKey"] == "lap.button"
        assert schritt["endConditionValue"] is not None
        assert schritt["weightValue"] == -1.0
        assert schritt["weightUnit"]["unitKey"] == "kilogram"
        assert schritt["strokeType"]["strokeTypeId"] == 0
        assert schritt["equipmentType"]["equipmentTypeId"] == 0


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
    assert [s.get("exerciseName") for s in schritte(plan)] == [
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


def test_schwimmeinheit_bekommt_bahnlaenge_und_zugart():
    plan = workouts.baue_workout(
        einheit(sport="swim", structure="400m Einschwimmen, 8x100m Kraul P30s, 200m Ausschwimmen"),
        zonen=ZONEN,
    )
    assert plan["poolLength"] == workouts.POOL_LAENGE_M
    assert plan["sportType"]["sportTypeKey"] == "swimming"
    assert schritte(plan)[0]["strokeType"]["strokeTypeId"] == 0


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


def test_uebertragung_legt_workouts_an_und_terminiert_sie(client, verbunden, fake):
    _importiere_plan(client, verbunden)
    fertig = _uebertrage(client, verbunden)

    assert fertig["state"] == "done", fertig["message"]
    assert fertig["workouts_pushed"] == 2  # der Ruhetag bleibt außen vor
    assert len(fake._workouts) == 2
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
    assert len(fake._workouts) == 2


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
    assert len(fake._workouts) == 2
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
    assert len(fake._workouts) == 1


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
    """Sonst wüchse Garmins Bibliothek mit jedem Block weiter."""
    plan = _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)
    assert len(fake._workouts) == 2

    _mache_vergangen(next(s["id"] for s in plan["sessions"] if s["sport"] == "run"))

    antwort = client.post("/api/garmin/sync", headers=verbunden)
    assert antwort.status_code == 202, antwort.text
    fertig = client.get(
        f"/api/garmin/jobs/{antwort.json()['id']}", headers=verbunden
    ).json()

    assert fertig["state"] == "done", fertig["message"]
    assert fertig["workouts_removed"] == 1
    assert "aufgeräumt" in fertig["message"]
    # Vorlage *und* Termin sind weg, die künftige Einheit bleibt stehen.
    assert len(fake._workouts) == 1
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

    assert list(fake._workouts) == [eigenes]


def test_uebertragen_raeumt_den_vorigen_block_auf(client, verbunden, fake):
    """Auch ohne täglichen Abgleich bleibt die Bibliothek sauber."""
    plan = _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)

    _mache_vergangen(next(s["id"] for s in plan["sessions"] if s["sport"] == "run"))
    fertig = _uebertrage(client, verbunden)

    assert fertig["state"] == "done", fertig["message"]
    assert fertig["workouts_removed"] == 1
    assert "aufgeräumt" in fertig["message"]
    assert len(fake._workouts) == 1


def test_abgeloester_block_verschwindet_erst_nach_dem_aufraeumen(
    client, verbunden, fake
):
    """Der stillgelegte Plan hält seine Garmin-Einheiten fest, bis sie weg sind.

    Mit dem Plan verschwände die Zuordnung — und ohne sie fasst die App in
    Garmin nichts mehr an. Ein sofort gelöschter Block ließe seine Einheiten
    also für immer im fremden Kalender stehen, neben denen des neuen.
    """
    _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)

    neu = _importiere_plan(client, verbunden)
    assert len(client.get("/api/plans", headers=verbunden).json()) == 2

    fertig = _uebertrage(client, verbunden)
    assert fertig["state"] == "done", fertig["message"]

    # Erst räumt der Lauf die abgelösten Einheiten aus Garmin, dann fällt der
    # leere Block von selbst weg.
    assert [p["id"] for p in client.get("/api/plans", headers=verbunden).json()] == [
        neu["id"]
    ]
    assert len(fake._workouts) == 2


def test_entfernen_nimmt_vorlage_und_termin_zurueck(client, verbunden, fake):
    _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)

    antwort = client.post("/api/garmin/workouts/entfernen", json={}, headers=verbunden)
    assert antwort.status_code == 202, antwort.text
    fertig = client.get(
        f"/api/garmin/jobs/{antwort.json()['id']}", headers=verbunden
    ).json()

    assert fertig["state"] == "done"
    assert fertig["workouts_removed"] == 2
    assert fake._workouts == {}
    assert fake._termine == {}

    zustand = client.get("/api/garmin/workouts/status", headers=verbunden).json()
    assert zustand["offen"] == 2


def test_einzelne_einheit_geht_ohne_job(client, verbunden, fake):
    plan = _importiere_plan(client, verbunden)
    einheit_id = next(s["id"] for s in plan["sessions"] if s["sport"] != "rest")

    antwort = client.post(
        f"/api/garmin/workouts/einheit/{einheit_id}", headers=verbunden
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["zustand"] == "aktuell"
    assert len(fake._workouts) == 1

    assert client.delete(
        f"/api/garmin/workouts/einheit/{einheit_id}", headers=verbunden
    ).status_code == 204
    assert fake._workouts == {}


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


def test_kalendereintrag_laesst_sich_loeschen(client, verbunden, fake):
    _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)

    eintraege = client.get(
        f"/api/garmin/kalender?jahr={HEUTE.year}&monat={HEUTE.month}", headers=verbunden
    ).json()["eintraege"]
    eigener = next(e for e in eintraege if e["aus_tri_coach"])

    antwort = client.delete(
        f"/api/garmin/kalender/{eigener['schedule_id']}"
        f"?workout_id={eigener['workout_id']}",
        headers=verbunden,
    )
    assert antwort.status_code == 204, antwort.text
    assert int(eigener["workout_id"]) not in fake._workouts
    assert int(eigener["schedule_id"]) not in fake._termine

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

    # Von Hand in Garmin Connect gelöscht — die App weiß davon nichts.
    fake._workouts.clear()
    fake._termine.clear()

    # Der Plan ändert sich, damit die Übertragung die Vorlage anfassen muss.
    from app.database import SessionLocal
    from app.models import PlanSession

    einheit_id = next(s["id"] for s in plan["sessions"] if s["sport"] != "rest")
    with SessionLocal() as db:
        session = db.get(PlanSession, einheit_id)
        session.duration_min = 75
        db.commit()

    fertig = _uebertrage(client, verbunden)

    assert fertig["state"] == "done", fertig["message"]
    assert len(fake._workouts) >= 1
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

    fertig = _uebertrage(client, verbunden)

    assert fertig["state"] == "done", fertig["message"]
    assert fertig["workouts_pushed"] == 2
    assert len(fake._workouts) == 2
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
    alte_vorlagen = set(fake._workouts)

    # Der nächste Block: ein neuer Plan, der alte wird nur stillgelegt.
    _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)

    assert not (alte_vorlagen & set(fake._workouts)), "Der alte Block steht noch in Garmin"
    assert len(fake._workouts) == 2
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
    original = fake.upload_workout
    versuche = {"n": 0}

    def mal_so_mal_so(workout_json):
        versuche["n"] += 1
        if versuche["n"] == 1:
            raise RuntimeError("400 Bad Request: unsupported step")
        return original(workout_json)

    fake.upload_workout = mal_so_mal_so
    fertig = _uebertrage(client, verbunden)

    assert fertig["state"] == "done"
    assert fertig["workouts_pushed"] == 1
    assert "Nicht geklappt hat es bei" in fertig["message"]
    assert len(fake._workouts) == 1

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


def _wirft_429(workout_json):
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
    assert len(fake._workouts) == 2
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
    assert len(zuerst) == 2

    # Derselbe Zeitraum, neu geplant.
    _importiere(client, verbunden, autopush=True)

    assert len(fake._workouts) == 2
    assert not zuerst & set(fake._workouts), "der abgelöste Block steht noch"
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
    laufend = set(fake._workouts)
    assert len(laufend) == 2

    # Der nächste Block hängt hinten an, statt die laufenden Tage zu ersetzen.
    _importiere(client, verbunden, autopush=True, ab=HEUTE + timedelta(days=3))

    assert laufend < set(fake._workouts), "die laufenden Tage wurden mit geräumt"
    assert len(fake._workouts) == 4
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
    assert len(fake._workouts) == 2

    fake.upload_workout = _wirft_429
    antwort = _importiere(client, verbunden, autopush=True)

    fertig = _job(client, verbunden, antwort["garmin_job_id"])
    assert fertig["state"] == "rate_limited"
    assert fake._workouts == {}
    assert fake._termine == {}


def test_gesperrte_verbindung_erklaert_den_leeren_kalender(client, verbunden, fake):
    """Wer nichts auf der Uhr findet, soll den Grund beim Übernehmen lesen."""
    _importiere_plan(client, verbunden)
    fake.upload_workout = _wirft_429
    assert _uebertrage(client, verbunden)["state"] == "rate_limited"

    antwort = _importiere(client, verbunden, autopush=True)

    assert antwort["garmin_job_id"] is None
    assert "gesperrt" in antwort["garmin_hinweis"]


def test_frueherer_block_von_hand_uebertragen_bleibt_stehen(client, verbunden, fake):
    """Ein stillgelegter Plan lässt sich gezielt übertragen — und überlebt es.

    Ohne die Ausnahme in `raeume_ersetzte_auf` löschte derselbe Lauf am Ende
    wieder, was er gerade hochgeladen hat: Der Block ist ja nicht mehr aktiv.
    """
    alt = _importiere_plan(client, verbunden)
    _uebertrage(client, verbunden)
    _importiere_plan(client, verbunden)  # legt ihn still

    antwort = client.post(
        "/api/garmin/workouts/uebertragen",
        json={"plan_id": alt["id"]},
        headers=verbunden,
    )
    assert antwort.status_code == 202, antwort.text
    fertig = _job(client, verbunden, antwort.json()["id"])

    assert fertig["state"] == "done", fertig["message"]
    assert fertig["workouts_removed"] == 0
    assert len(fake._workouts) == 2
