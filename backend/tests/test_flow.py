"""End-to-End-Test des kompletten Ablaufs.

Registrierung → Profil → Fragebogen → KI-Export → Plan-Import → Training
erfassen → Auswertung.
"""

import json
from datetime import date, timedelta

import pytest

# `client` und `auth` kommen aus `tests/conftest.py` — dort steht auch die
# Vorbereitung der Umgebung, die vor dem Import von `app.main` laufen muss.

ROTATION = [
    ("swim", "technique", "Techniktraining", 45),
    ("bike", "endurance", "Grundlagenfahrt", 90),
    ("run", "intervals", "Intervalle 5x1000m", 60),
    ("strength", "strength", "Rumpfkraft", 30),
    ("bike", "threshold", "Schwellenintervalle", 75),
    ("run", "long", "Langer Lauf", 100),
    ("rest", "rest", "Ruhetag", 0),
]


def make_ai_days(start: date, days: int) -> list[dict]:
    result = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        sport, stype, title, duration = ROTATION[offset % len(ROTATION)]
        result.append({
            "date": day.isoformat(),
            "sessions": [{
                "sport": sport,
                "type": stype,
                "title": title,
                "description": f"{title} am Tag {offset + 1}",
                "structure": "15 min ein / Hauptteil / 10 min aus",
                "purpose": "Grundlagenausdauer",
                "duration_min": duration,
                "distance_km": 12.0 if sport == "run" else None,
                "intensity_zone": "Z2",
                "target_hr_low": 130,
                "target_hr_high": 148,
                "target_pace": "5:30-5:50 min/km" if sport == "run" else None,
                "rpe_target": 4,
            }],
        })
    return result


def make_ai_plan(start: date, days: int = 4) -> dict:
    """Baut eine realistische KI-Antwort über einen kurzen Block."""
    return {
        "schema_version": "2.0",
        "plan": {
            "title": "Triathlon Grundlagenblock",
            "summary": "Kurzer Block mit Fokus auf aerober Basis.",
            "coaching_notes": "Bei Morgenpuls +8 bpm die Einheit tauschen.",
            "start_date": start.isoformat(),
            "days": make_ai_days(start, days),
        },
    }


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_login_and_duplicate_registration(client, auth):
    duplicate = client.post(
        "/api/auth/register",
        json={"email": "athlet@example.com", "username": "anderer"},
    )
    assert duplicate.status_code == 409

    # Die Kontoauswahl ist ohne Token erreichbar und gibt nur den Namen preis.
    users = client.get("/api/auth/users")
    assert users.status_code == 200, users.text
    athlet = next(u for u in users.json() if u["username"] == "athlet")
    assert set(athlet) == {"id", "username"}

    login = client.post("/api/auth/login", json={"user_id": athlet["id"]})
    assert login.status_code == 200, login.text

    unknown = client.post("/api/auth/login", json={"user_id": 999_999})
    assert unknown.status_code == 404


def test_requires_auth(client):
    assert client.get("/api/profile").status_code == 401


def test_profile_and_zones(client, auth):
    response = client.put(
        "/api/profile",
        headers=auth,
        json={
            "birth_date": "1990-05-14",
            "sex": "male",
            "height_cm": 182,
            "weight_kg": 78.5,
            "resting_hr": 48,
            "max_hr": 192,
            "vo2max": 54.2,
            "hrv_rmssd": 68,
            "ftp_watts": 265,
            "current_weekly_hours": 7,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["age"] is not None
    assert data["bmi"] == pytest.approx(23.7, abs=0.1)
    assert len(data["hr_zones"]) == 5

    # Karvonen: Z2-Untergrenze = 48 + (192-48) * 0.60
    z2 = next(z for z in data["hr_zones"] if z["zone"] == "Z2")
    assert z2["low_bpm"] == round(48 + (192 - 48) * 0.60)
    assert z2["basis"] == "HFR (Karvonen)"

    # Teil-Update darf bestehende Werte nicht löschen
    partial = client.put("/api/profile", headers=auth, json={"weight_kg": 77.0})
    assert partial.status_code == 200
    assert partial.json()["max_hr"] == 192
    assert partial.json()["weight_kg"] == 77.0

    history = client.get("/api/profile/history", headers=auth)
    assert history.status_code == 200
    assert len(history.json()) >= 2  # Gewichtsänderung wurde mitgeschrieben


def test_questionnaire(client, auth):
    response = client.post(
        "/api/requests",
        headers=auth,
        json={
            "discipline": "triathlon",
            "goal_type": "Wettkampfvorbereitung",
            "goal_text": "Erste Olympische Distanz unter 2:30",
            "race_date": (date.today() + timedelta(days=90)).isoformat(),
            "race_distance": "Olympische Distanz",
            "available_days": ["Montag", "mittwoch", "FR", "samstag", "sunday"],
            "day_sport_map": {"Montag": ["Schwimmen"], "mittwoch": ["Radfahren", "laufen"]},
            "day_time_budget": {"monday": 60, "wednesday": 120},
            "long_session_day": "saturday",
            "weekly_hours_target": 8,
            "supplemental": ["strength", "mobility"],
            "equipment": ["pool", "smart_trainer", "powermeter"],
            "free_text": {"goal": "Radfahren ist meine Schwäche."},
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()

    # Deutsche und abgekürzte Wochentage werden normalisiert
    assert data["available_days"] == [
        "monday", "wednesday", "friday", "saturday", "sunday",
    ]
    assert data["day_sport_map"]["monday"] == ["swim"]
    assert data["day_sport_map"]["wednesday"] == ["bike", "run"]


def test_ai_export_contains_context(client, auth):
    response = client.get("/api/plans/export", headers=auth)
    assert response.status_code == 200, response.text
    data = response.json()

    payload = data["payload"]
    assert payload["athlet"]["maximalpuls"] == 192
    assert payload["athlet"]["maximalpuls_geschaetzt"] is False
    assert payload["trainingswunsch"]["disziplin"] == "Triathlon"
    assert len(payload["herzfrequenzzonen"]) == 5

    # Geplant wird ein kurzer Block, zurückgeblickt wird über vier Wochen.
    period = payload["planungszeitraum"]
    assert period["tage"] == 7
    assert period["startdatum"] == date.today().isoformat()
    assert period["enddatum"] == (date.today() + timedelta(days=6)).isoformat()
    assert len(period["wochentage"]) == 7
    assert len(payload["trainingshistorie"]["wochenuebersicht"]) == 4

    # Der Prompt muss Auftrag, Daten und Formatvorgabe enthalten
    assert "nächsten 7 Trainingstage" in data["prompt"]
    assert '"days"' in data["prompt"]
    assert "Olympische Distanz" in data["prompt"]


def test_ai_export_honours_block_length(client, auth):
    start = date.today() + timedelta(days=2)
    response = client.get(
        "/api/plans/export",
        headers=auth,
        params={"start_date": start.isoformat(), "days": 3},
    )
    assert response.status_code == 200, response.text
    period = response.json()["payload"]["planungszeitraum"]

    assert period["tage"] == 3
    assert period["startdatum"] == start.isoformat()
    assert period["enddatum"] == (start + timedelta(days=2)).isoformat()

    # Ein Vier-Wochen-Block ist über die API nicht mehr anforderbar.
    assert client.get(
        "/api/plans/export", headers=auth, params={"days": 28}
    ).status_code == 422


def test_plan_import_and_retrieval(client, auth):
    # Startet morgen, damit noch keine Einheit fällig ist — das prüfen
    # test_export_includes_history_after_logging und die Umsetzungsquote.
    start = date.today() + timedelta(days=1)
    ai_response = make_ai_plan(start, days=4)

    # So, wie eine KI es typischerweise ausgibt: mit Fließtext und Codefence
    messy = (
        "Klar, hier ist dein Plan:\n\n```json\n"
        + json.dumps(ai_response, ensure_ascii=False)
        + "\n```\n\nViel Erfolg!"
    )

    response = client.post(
        "/api/plans/import", headers=auth, json={"raw": messy, "days": 4}
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["warnings"] == []
    plan = body["plan"]
    assert plan["title"] == "Triathlon Grundlagenblock"
    assert len(plan["sessions"]) == 4
    assert plan["sessions"][0]["date"] == start.isoformat()
    assert plan["end_date"] == (start + timedelta(days=3)).isoformat()
    # Ein kurzer Block liegt komplett in Woche 1.
    assert {s["week_number"] for s in plan["sessions"]} == {1}

    active = client.get("/api/plans/active", headers=auth)
    assert active.status_code == 200
    assert active.json()["id"] == plan["id"]


def test_import_rejects_garbage(client, auth):
    assert client.post(
        "/api/plans/import", headers=auth, json={"raw": "Ich habe keine Lust."}
    ).status_code == 422

    truncated = client.post(
        "/api/plans/import", headers=auth, json={"raw": '{"plan": {"title": "x"'}
    )
    assert truncated.status_code == 422
    assert "abgeschnitten" in truncated.json()["detail"]

    wrong_shape = client.post(
        "/api/plans/import",
        headers=auth,
        json={"raw": json.dumps({"plan": {"title": "Ohne Startdatum", "weeks": []}})},
    )
    assert wrong_shape.status_code == 422


def test_import_warns_about_gaps(client, auth):
    start = date.today() + timedelta(days=40)
    incomplete = make_ai_plan(start, days=4)
    incomplete["plan"]["days"] = incomplete["plan"]["days"][:2]

    response = client.post(
        "/api/plans/validate",
        headers=auth,
        json={"raw": json.dumps(incomplete), "days": 4},
    )
    assert response.status_code == 200
    warnings = response.json()["warnings"]
    assert any("2 statt 4 Tage" in w for w in warnings)
    assert any("Ohne Eintrag geblieben" in w for w in warnings)


def test_import_accepts_old_week_format(client, auth):
    """KI-Antworten mit Wochenebene werden auf Tage heruntergezogen."""
    start = date.today() + timedelta(days=60)
    legacy = {
        "plan": {
            "title": "Antwort im Wochenformat",
            "start_date": start.isoformat(),
            "weeks": [
                {"week_number": 1, "focus": "Basis", "days": make_ai_days(start, 7)},
                {
                    "week_number": 2,
                    "focus": "Basis",
                    "days": make_ai_days(start + timedelta(days=7), 7),
                },
            ],
        }
    }

    response = client.post(
        "/api/plans/validate", headers=auth, json={"raw": json.dumps(legacy)}
    )
    assert response.status_code == 200, response.text
    body = response.json()

    plan = body["plan"]
    assert len(plan["sessions"]) == 14
    assert plan["end_date"] == (start + timedelta(days=13)).isoformat()
    # Ohne angeforderte Blocklänge wird nur der gelieferte Zeitraum geprüft.
    assert body["warnings"] == []
    # Die Wochenzuordnung wird aus den Daten neu abgeleitet.
    assert {s["week_number"] for s in plan["sessions"]} == {1, 2}


def test_trainings_lassen_sich_nicht_von_hand_eintragen(client, auth):
    """Die einzige Quelle für absolvierte Trainings ist Garmin.

    Ein Formular gäbe es zwei — und jede Einheit zählte in Umsetzungsquote,
    sRPE-Last und Belastungsverhältnis doppelt, sobald sie auch aus der Uhr
    käme. Anlegen und Bearbeiten sind deshalb weg, Lesen und Löschen bleiben.
    """
    heute = date.today().isoformat()
    angelegt = client.post(
        "/api/logs", headers=auth, json={"date": heute, "sport": "run"}
    )
    assert angelegt.status_code == 405

    assert client.get("/api/logs", headers=auth).status_code == 200


def test_log_session_and_stats(client, auth, erfasse):
    plan = client.get("/api/plans/active", headers=auth).json()
    target = next(s for s in plan["sessions"] if s["sport"] == "run")

    erfasse(
        auth,
        plan_session_id=target["id"],
        date=date.today(),
        sport="run",
        duration_min=62,
        distance_km=11.4,
        avg_hr=152,
        max_hr=178,
        avg_pace="5:26",
        rpe=6,
        notes="Lief rund.",
    )

    logs = client.get("/api/logs", headers=auth).json()
    assert len(logs) == 1
    assert logs[0]["trimp"] is not None and logs[0]["trimp"] > 0

    stats = client.get("/api/logs/stats", headers=auth).json()
    assert stats["total_sessions"] == 1
    assert stats["total_minutes"] == 62
    assert len(stats["weekly"]) == 4

    # Die erfasste Einheit ist im Plan als erledigt markiert
    refreshed = client.get("/api/plans/active", headers=auth).json()
    assert any(s["logged"] for s in refreshed["sessions"])


def test_export_includes_history_after_logging(client, auth):
    payload = client.get("/api/plans/export", headers=auth).json()["payload"]
    history = payload["trainingshistorie"]

    assert len(history["einheiten"]) == 1
    assert history["einheiten"][0]["rpe_1_10"] == 6
    assert history["einheiten"][0]["trimp"] is not None

    # Für den kurzen Block sind die Abstände seit der letzten Einheit die
    # wichtigste Steuergröße — heute gelaufen, also 0 Tage.
    assert history["tage_seit_letzter_einheit_je_sportart"]["run"] == 0
    assert history["tage_seit_letzter_intensiver_einheit"] is None  # RPE 6 < 7

    # Der aktive Plan startet erst morgen — es ist noch keine Einheit fällig
    # gewesen, also gibt es auch keine Umsetzungsquote.
    assert history["umsetzung_aktueller_plan"]["planned_past"] == 0
    assert history["umsetzung_aktueller_plan"]["rate_pct"] is None

    weekly = history["wochenuebersicht"]
    assert len(weekly) == 4
    assert weekly[-1]["total_minutes"] == 62  # laufende Woche


def test_compliance_for_running_plan(client, auth, erfasse):
    """Plan, der vor zwei Wochen begonnen hat: Umsetzungsquote muss zählen."""
    start = date.today() - timedelta(days=14)
    response = client.post(
        "/api/plans/import", headers=auth, json={"raw": json.dumps(make_ai_plan(start))}
    )
    assert response.status_code == 201, response.text
    plan = response.json()["plan"]

    # Zwei bereits fällige Einheiten sind absolviert (Ruhetage zählen nicht mit)
    due = [
        s for s in plan["sessions"]
        if date.fromisoformat(s["date"]) <= date.today() and s["sport"] != "rest"
    ]
    assert len(due) >= 2
    for session in due[:2]:
        erfasse(
            auth,
            plan_session_id=session["id"],
            date=date.fromisoformat(session["date"]),
            sport=session["sport"],
            duration_min=session["duration_min"] or 45,
            avg_hr=148,
            rpe=5,
        )

    stats = client.get("/api/logs/stats", headers=auth).json()
    assert stats["compliance"]["planned_past"] == len(due)
    assert stats["compliance"]["logged"] == 2
    assert stats["compliance"]["rate_pct"] == round(100 * 2 / len(due))


def test_session_ohne_planbezug_zaehlt_im_vierwochenfenster(client, auth, erfasse):
    """Eine Einheit ohne Planbezug muss die Auswertung mitsteuern.

    Der Abgleich holt auch Tage, für die nie etwas geplant war — ein spontanes
    Schwimmen zählt in Umfang, Abständen und Export genauso mit.
    """
    before = client.get("/api/logs/stats", headers=auth).json()

    day = date.today() - timedelta(days=10)
    erfasse(
        auth,
        date=day,
        sport="swim",
        duration_min=50,
        distance_km=2.0,
        avg_hr=141,
        rpe=8,
        notes="Aus Garmin.",
    )

    after = client.get("/api/logs/stats", headers=auth).json()
    assert after["total_sessions"] == before["total_sessions"] + 1
    assert after["total_minutes"] == before["total_minutes"] + 50

    # Nicht in der laufenden, sondern in der Woche des Trainings verbucht
    week = next(
        w for w in after["weekly"]
        if w["week_start"] <= day.isoformat() <= w["week_end"]
    )
    assert week["by_sport"]["swim"]["minutes"] >= 50

    # Und im Export: als Einheit, in den Abständen und in der Umsetzungsquote
    history = client.get("/api/plans/export", headers=auth).json()["payload"][
        "trainingshistorie"
    ]
    assert any(e["notiz"] == "Aus Garmin." for e in history["einheiten"])
    assert history["tage_seit_letzter_einheit_je_sportart"]["swim"] == 10
    assert history["tage_seit_letzter_intensiver_einheit"] == 10  # RPE 8

    # Älter als vier Wochen: bleibt im Verlauf, zählt aber nicht mehr mit
    erfasse(auth, date=date.today() - timedelta(days=40), sport="run", duration_min=70)
    assert client.get("/api/logs/stats", headers=auth).json()["total_minutes"] == (
        after["total_minutes"]
    )
    assert len(client.get("/api/logs?weeks=4", headers=auth).json()) == len(
        client.get("/api/logs?weeks=12", headers=auth).json()
    ) - 1


def test_logs_of_other_user_are_invisible(client):
    other = client.post(
        "/api/auth/register",
        json={"email": "fremd@example.com", "username": "fremd"},
    ).json()
    headers = {"Authorization": f"Bearer {other['access_token']}"}

    assert client.get("/api/logs", headers=headers).json() == []
    assert client.get("/api/plans/active", headers=headers).json() is None
    assert client.get("/api/plans", headers=headers).json() == []
