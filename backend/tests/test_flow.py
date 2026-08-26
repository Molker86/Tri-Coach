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

    # Die Wochenübersicht muss das ganze Rückblickfenster abdecken. Wie viele
    # Kalenderwochen das sind, hängt vom Wochentag ab: Nur wenn heute Montag
    # ist, sind es genau vier — sonst ragt das Fenster in eine fünfte hinein.
    wochen = payload["trainingshistorie"]["wochenuebersicht"]
    assert date.fromisoformat(wochen[0]["week_start"]) <= date.today() - timedelta(weeks=4)
    assert date.fromisoformat(wochen[-1]["week_end"]) >= date.today()

    # Der Prompt muss Auftrag, Daten und Formatvorgabe enthalten
    assert "nächsten 7 Trainingstage" in data["prompt"]
    assert '"days"' in data["prompt"]
    assert "Olympische Distanz" in data["prompt"]


def test_der_prompt_verlangt_arbeit_an_der_beschwerde(client, auth):
    """`verletzungen_einschraenkungen` reiste mit, aber kein Prinzip zeigte darauf.

    Der Freitext stand im Payload, und die KI hat ihn beim Ausdauerteil auch von
    sich aus gelesen — die Ergänzungseinheiten dagegen wichen der betroffenen
    Region aus, weil Punkt 9 den Wechsel der Körperregion verlangt und nichts
    dagegenstand. Genau umgekehrt ist es richtig: Ein Läuferknie wird in Kraft
    und Mobility behandelt, nicht umgangen.
    """
    beschwerde = "leichtes Läuferknie rechts, dazu Beschwerden im rechten Gesäß"
    assert (
        client.put("/api/profile", headers=auth, json={"injuries": beschwerde}).status_code
        == 200
    )
    try:
        data = client.get("/api/plans/export", headers=auth).json()
        prompt = data["prompt"]

        assert data["payload"]["athlet"]["verletzungen_einschraenkungen"] == beschwerde

        # Das Feld wird namentlich aufgerufen. Ohne diesen Verweis war es die
        # Eigeninitiative des Modells, ob es überhaupt hineinsah.
        assert "`athlet.verletzungen_einschraenkungen`" in prompt
        # Und zwar in beide Richtungen: als Bremse und als Auftrag.
        assert "**Als Bremse**" in prompt
        assert "**Als Auftrag**" in prompt
        assert "**auszusparen, ist die falsche Antwort**" in prompt
        # Punkt 6 darf über die Beschwerde nicht hinwegplanen.
        assert "Die Punkte 1 bis 4 und 13 sind" in prompt
        # Und die Abwechslungsregel aus Punkt 9 gilt nur für gesunde Regionen.
        assert "Diese Abwechslungsregel gilt für gesunde" in prompt
        # Die Ausnahme deckt aber nur die Region, nicht die Einheit: Sonst kam
        # drei Tage hintereinander dieselbe Dehnübung, ausdrücklich gedeckt.
        assert "**Die Ausnahme gilt der Region, nicht der Einheit**" in prompt
        assert "Dieselbe Übungsliste am Folgetag ist keine Behandlung" in prompt
        # Und die Ursache entscheidet über die Form, nicht die Tageslänge.
        assert "auch über die **Form** der Arbeit" in prompt
    finally:
        client.put("/api/profile", headers=auth, json={"injuries": None})


def test_punkt_9_stellt_kraft_und_mobility_gleich(client, auth):
    """Kraft stand unter Vorbehalt, Mobility nicht — und das entschied den Block.

    „Falls gewünscht, Kraft (…) — nie unmittelbar vor einer Schlüsseleinheit.
    Mobility kurz und regelmäßig": eine Bedingung samt Sperre gegen die eine
    Form, ein unbedingter Wiederholungsauftrag für die andere. Bei täglicher
    Neuplanung las sich „regelmäßig" als „heute wieder", und die Krafteinheit
    rutschte auf einen späteren Blocktag, den es nie gab.
    """
    prompt = client.get("/api/plans/export", headers=auth).json()["prompt"]

    assert "Kraft und Mobility stehen gleichrangig" in prompt
    # Die Terminierungsregel bleibt — sie ist sachlich richtig —, taugt aber
    # nicht mehr als Grund, die Krafteinheit ganz wegzulassen.
    assert "eine Frage des Tages und kein Grund, sie wegzulassen" in prompt
    assert "statt durch eine Mobility-Einheit ersetzt zu werden" in prompt
    # „Regelmäßig" gilt jetzt für beide Formen, nicht nur für Mobility.
    assert "Beide Formen gehören regelmäßig" in prompt
    # Und „kurz" ist keine Vorgabe mehr: Die Länge leitet die KI selbst ab.
    assert "**Wie lang eine solche Einheit ist, entscheidest du**" in prompt
    assert "kurz und regelmäßig" not in prompt


def test_der_prompt_sagt_wenn_morgen_neu_geplant_wird(client, auth):
    """Bei aktiver Automatik sind die Tage ab dem zweiten schon vergeben.

    Die KI verteilte Kraft und Mobility über sieben Tage, von denen der nächste
    Lauf sechs verwirft — was Punkt 9 vom ersten Tag wegdrängt, landete auf
    Tag 3 und fand nie statt. Bewusst **nicht** die Behauptung, Tag 1 finde
    sicher statt: Ob trainiert wird, entscheidet der Athlet.
    """
    ohne = client.get("/api/plans/export", headers=auth).json()["prompt"]
    assert "automatisch neu geplant" not in ohne

    client.put("/api/ki/settings", headers=auth, json={"auto_plan_enabled": True})
    try:
        mit = client.get("/api/plans/export", headers=auth).json()["prompt"]
        assert "**Dieser Block wird morgen früh automatisch neu geplant.**" in mit
        assert "Ob der erste Tag stattfindet, entscheidet der Athlet" in mit
        # Der Platzhalter für die Blocklänge muss gefüllt sein — `.format()`
        # formatiert eingesetzte Werte nicht erneut.
        assert "{tage}" not in mit
        assert "über alle 7 Tage stimmig" in mit
    finally:
        client.put(
            "/api/ki/settings", headers=auth, json={"auto_plan_enabled": False}
        )


def test_der_prompt_gibt_die_trainingslehre_nicht_vor(client, auth):
    """Punkt 3 und 4 schrieben Quote und Stundenzahl vor — das tun sie nicht mehr.

    Die Rolle im Prompt ist ein Ausdauer-Trainingswissenschaftler; die
    Verteilung und den Abstand zwischen zwei Reizen bringt er mit. Was ihm
    fehlt, sind die Daten dieses Athleten — die nennen beide Punkte weiterhin
    namentlich, und daran hängt mehr als der Prompt: `_days_since_hard_session`
    rechnet ausdrücklich über die ganze Historie statt über vier Wochen, weil
    Punkt 4 diese Zahl liest.
    """
    prompt = client.get("/api/plans/export", headers=auth).json()["prompt"]

    # Keine festen Vorgaben mehr.
    assert "48 h" not in prompt
    assert "je drei Tage" not in prompt
    assert "Polarisiert" not in prompt

    # Aber weiterhin die Felder, an denen die Entscheidung hängt.
    assert "`tage_seit_letzter_intensiver_einheit`" in prompt
    assert "`zeit_in_hf_zonen_min`" in prompt

    # Punkt 6 zählt beide weiterhin zu den Bremsen — sonst läse sich "greift
    # keine davon, also wird aufgebaut" über sie hinweg.
    assert "Die Punkte 1 bis 4 und 13 sind" in prompt


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

    # Der Zeitraum ist vollständig. Der Hinweis auf die fehlende Schrittliste
    # bleibt erwartet: Diese Antwort kommt ohne — genau der Fall, für den der
    # Zerleger als Rückfall stehen bleibt.
    assert not [w for w in body["warnings"] if "Schrittliste" not in w]
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


def test_unlesbares_json_nennt_die_fundstelle(client, auth):
    """Zeile und Spalte allein helfen bei einer einzeiligen Antwort nicht.

    Ein nicht maskiertes Anführungszeichen mitten im Aufbautext ist der
    häufigste Grund für „Expecting ',' delimiter" — die Meldung nannte dafür
    einmal nur „Zeile 1, Spalte 2318", und die zählt niemand ab. Jetzt steht
    der Wortlaut der Fundstelle daneben.
    """
    start = date.today() + timedelta(days=1)
    plan = make_ai_plan(start)
    plan["plan"]["days"][0]["sessions"][0]["structure"] = "4x400 m PLATZHALTER"
    kaputt = json.dumps(plan, ensure_ascii=False).replace(
        "PLATZHALTER", 'zügig ("Renntempo")'
    )

    response = client.post(
        "/api/plans/import", headers=auth, json={"raw": kaputt}
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "nicht lesbar" in detail
    assert '4x400 m zügig ("Renntempo")' in detail


def test_import_nimmt_den_plan_und_nicht_das_erste_objekt(client, auth):
    """Ein Notizobjekt vor dem Block darf den Import nicht kosten.

    Der Parser nahm einmal die erste Codefence und darin das erste
    JSON-Objekt. Schrieb die KI vorweg eine kurze Notiz als JSON — oder hängte
    sie eine hinterher —, scheiterte der Import mit „plan → days: Field
    required" über einem Text, in dem der Block vollständig dastand.
    """
    start = date.today() + timedelta(days=1)
    antwort = (
        "Kurz vorweg:\n```json\n{\"hinweis\": \"Fokus auf die aerobe Basis\"}\n```\n\n"
        "```json\n"
        + json.dumps(make_ai_plan(start), ensure_ascii=False)
        + "\n```\n{\"nachtrag\": \"viel Erfolg\"}"
    )

    response = client.post(
        "/api/plans/import", headers=auth, json={"raw": antwort, "days": 4}
    )
    assert response.status_code == 201, response.text
    assert len(response.json()["plan"]["sessions"]) == 4


def test_import_akzeptiert_eine_fremd_benannte_huelle(client, auth):
    """`{"trainingsplan": {...}}` ist derselbe Block, nur anders verpackt."""
    start = date.today() + timedelta(days=1)
    plan = make_ai_plan(start)["plan"]

    response = client.post(
        "/api/plans/import",
        headers=auth,
        json={"raw": json.dumps({"trainingsplan": plan}), "days": 4},
    )
    assert response.status_code == 201, response.text
    assert response.json()["plan"]["start_date"] == start.isoformat()


def test_import_leitet_das_startdatum_aus_den_tagen_ab(client, auth):
    """Ohne `start_date` gilt der früheste Tag — das Feld ist ablesbar.

    Einen vollständigen Block an einer Zahl scheitern zu lassen, die daneben
    steht, wäre dieselbe teuerste Antwort wie beim verworfenen Zielpuls.
    """
    start = date.today() + timedelta(days=1)
    ohne = make_ai_plan(start)
    del ohne["plan"]["start_date"]

    response = client.post(
        "/api/plans/import", headers=auth, json={"raw": json.dumps(ohne), "days": 4}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    plan = body["plan"]
    assert plan["start_date"] == start.isoformat()
    assert plan["end_date"] == (start + timedelta(days=3)).isoformat()
    # Gemeldet wird es trotzdem: Ausbessern ist kein Grund zu schweigen.
    assert any("start_date" in w for w in body["warnings"])


def test_import_benennt_das_verwechselte_datenpaket(client, auth):
    """Das Datenpaket eingefügt statt der Antwort: Das ist die Auskunft.

    „plan → start_date: Field required" beschreibt, was fehlt — der Athlet
    muss aber wissen, was dasteht, und der nächste Handgriff ist ein anderer
    als bei einer misslungenen Antwort.
    """
    payload = client.get("/api/plans/export", headers=auth).json()["payload"]

    response = client.post(
        "/api/plans/import", headers=auth, json={"raw": json.dumps(payload)}
    )
    assert response.status_code == 422
    assert "Datenpaket" in response.json()["detail"]


def test_import_benennt_den_zurueckkopierten_prompt(client, auth):
    """Der ganze Prompt eingefügt: Auch dann ist es das Datenpaket.

    Der Prompt trägt am Ende das Antwortformat als Beispiel — mit einer
    Tagesliste darin. Nach der Form gesucht ist das ein Planobjekt, und der
    Athlet läse „days → 0 → date: YYYY-MM-DD ist kein Datum". Scheitert der
    Kandidat, gilt deshalb der Fund daneben.
    """
    prompt = client.get("/api/plans/export", headers=auth).json()["prompt"]

    response = client.post("/api/plans/import", headers=auth, json={"raw": prompt})
    assert response.status_code == 422
    assert "Datenpaket" in response.json()["detail"]


def test_import_benennt_die_antwort_auf_eine_einzelanpassung(client, auth):
    """Die eine Einheit gehört in den Dialog im Trainingsplan, nicht hierher."""
    einzeln = {
        "schema_version": "1.0",
        "einheit": {"sport": "run", "type": "endurance", "title": "Lockerer Lauf"},
        "begruendung": "Kürzer, weil nur 40 Minuten Zeit sind.",
    }

    response = client.post(
        "/api/plans/import", headers=auth, json={"raw": json.dumps(einzeln)}
    )
    assert response.status_code == 422
    assert "Einzelanpassung" in response.json()["detail"]


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


def test_import_verwirft_unbrauchbaren_zielpuls_statt_abzulehnen(client, auth):
    """Eine 0 im Zielpuls darf den Block nicht kippen.

    Der Prompt verlangt zu jeder Einheit Steuerungsgrößen; bei Kraft und
    Mobility gibt es keinen sinnvollen Korridor, und Modelle setzen dann eine 0.
    Das kostete einen kompletten Planungslauf, obwohl der Wert nirgends gelesen
    wird.
    """
    start = date.today() + timedelta(days=30)
    plan = make_ai_plan(start, days=4)
    # Zweite Einheit am ersten Tag — genau die Stelle, an der es in echt auffiel.
    plan["plan"]["days"][0]["sessions"].append({
        "sport": "strength",
        "type": "strength",
        "title": "Rumpfkraft",
        "structure": "3x12 Liegestütze (Push-up)",
        "duration_min": 30,
        "target_hr_low": 0,
        "target_hr_high": 130,
    })
    # Auch ein Wert, der gar keine Zahl ist, fällt nur heraus.
    plan["plan"]["days"][2]["sessions"][0]["target_hr_high"] = "Z2"

    response = client.post(
        "/api/plans/import", headers=auth, json={"raw": json.dumps(plan), "days": 4}
    )
    assert response.status_code == 201, response.text
    body = response.json()

    einheiten = {(s["date"], s["title"]): s for s in body["plan"]["sessions"]}
    kraft = einheiten[(start.isoformat(), "Rumpfkraft")]
    assert kraft["target_hr_low"] is None
    # Nur der unbrauchbare Wert fällt weg, der brauchbare bleibt stehen.
    assert kraft["target_hr_high"] == 130

    warnungen = " ".join(body["warnings"])
    assert "Unbrauchbare Steuerungsgröße verworfen" in warnungen
    assert "target_hr_low=0" in warnungen
    assert "target_hr_high=Z2" in warnungen


def test_import_verwirft_unbrauchbares_rpe_statt_abzulehnen(client, auth):
    """Dieselbe Regel für `rpe_target`: 0 an einer Ruheeinheit kippt nichts.

    Der Prompt verlangt Steuerungsgrößen zu *jeder* Einheit; wer dort einen
    Zielpuls auf 0 setzt, setzt aus demselben Grund auch die geplante
    Anstrengung auf 0. Als Feldgrenze (`ge=1`) wäre das derselbe harte Fehler.
    """
    start = date.today() + timedelta(days=30)
    plan = make_ai_plan(start, days=4)
    plan["plan"]["days"][1]["sessions"] = [{
        "sport": "rest",
        "type": "rest",
        "title": "Ruhetag",
        "duration_min": 0,
        "rpe_target": 0,
    }]
    # Auch oberhalb der Spanne fällt der Wert nur heraus.
    plan["plan"]["days"][3]["sessions"][0]["rpe_target"] = 15

    response = client.post(
        "/api/plans/import", headers=auth, json={"raw": json.dumps(plan), "days": 4}
    )
    assert response.status_code == 201, response.text
    body = response.json()

    einheiten = {(s["date"], s["title"]): s for s in body["plan"]["sessions"]}
    ruhe = einheiten[((start + timedelta(days=1)).isoformat(), "Ruhetag")]
    assert ruhe["rpe_target"] is None

    warnungen = " ".join(body["warnings"])
    assert "rpe_target=0" in warnungen
    assert "rpe_target=15" in warnungen


def test_import_laesst_je_schritt_ein_mass_stehen(client, auth):
    """Zwei Maße an einem Schritt sind eine Angabe zu viel, kein Fehler.

    `workouts._schritt_json()` nimmt in fester Reihenfolge Distanz, Zeit,
    Wiederholungen. Bei Kraft ist das die falsche Wahl: „3x12 in 30 s“ ist
    eine Wiederholungszahl, und die Uhr zählte stattdessen dreißig Sekunden
    herunter — still, ohne dass es irgendwo aufgefallen wäre.
    """
    start = date.today() + timedelta(days=90)
    plan = make_ai_plan(start, days=4)
    plan["plan"]["days"][0]["sessions"] = [{
        "sport": "strength",
        "type": "strength",
        "title": "Rumpfkraft",
        "structure": "3x12 Liegestütze (Push-up)",
        "duration_min": 10,
        "steps": [{
            "repeat": 3,
            "steps": [
                {"kind": "interval", "reps": 12, "duration_s": 30, "text": "Push-up"},
                {"kind": "rest", "duration_s": 60, "text": "Pause"},
            ],
        }],
    }]

    response = client.post(
        "/api/plans/import", headers=auth, json={"raw": json.dumps(plan), "days": 4}
    )
    assert response.status_code == 201, response.text
    body = response.json()

    warnungen = " ".join(body["warnings"])
    assert "Mehrfach bemaßte Schritte bereinigt" in warnungen
    assert "duration_s=30" in warnungen

    # Und geblieben ist bei Kraft die Wiederholungszahl, nicht der Timer:
    # `steps` steht nicht in der Ausgabe, also am Schema nachgesehen.
    from app.schemas import AISessionIn

    gelesen = AISessionIn.model_validate(plan["plan"]["days"][0]["sessions"][0])
    satz = gelesen.steps[0].steps[0]
    assert (satz.reps, satz.duration_s) == (12, None)


def test_import_meldet_wenn_dauer_und_bauplan_auseinanderlaufen(client, auth):
    """Fehlt im Bauplan die Zeit, fehlen meist die Pausen zwischen den Sätzen.

    Der Prompt verlangt, dass `duration_min` die Summe der Schritte ist. Läuft
    beides auseinander, beschreiben Aufbautext und Bauplan zwei verschiedene
    Einheiten — und auf der Uhr gilt der Bauplan.
    """
    start = date.today() + timedelta(days=120)
    plan = make_ai_plan(start, days=4)
    plan["plan"]["days"][0]["sessions"] = [{
        "sport": "mobility",
        "type": "mobility",
        "title": "Mobility kurz",
        "structure": "Taubenstellung (Pigeon Pose) 2x45 s je Seite",
        "duration_min": 20,
        "steps": [{
            "repeat": 4,
            "steps": [{"kind": "interval", "duration_s": 45, "text": "halten"}],
        }],
    }]
    # Eine Streckeneinheit hat keine Summe und darf deshalb nichts melden.
    plan["plan"]["days"][1]["sessions"][0]["steps"] = [
        {"kind": "interval", "distance_m": 10000, "text": "Dauerlauf"}
    ]

    response = client.post(
        "/api/plans/import", headers=auth, json={"raw": json.dumps(plan), "days": 4}
    )
    assert response.status_code == 201, response.text

    warnungen = [w for w in response.json()["warnings"] if "Bauplan" in w]
    passend = [w for w in warnungen if "Dauer und Bauplan" in w]
    assert len(passend) == 1
    assert "Mobility kurz" in passend[0]
    assert "20 min geplant, 3 min im Bauplan" in passend[0]


def test_import_meldet_die_serie_in_der_serie(client, auth):
    """Garmin kennt keine Gruppe in einer Gruppe — die innere wird ausgeschrieben."""
    start = date.today() + timedelta(days=150)
    plan = make_ai_plan(start, days=4)
    plan["plan"]["days"][0]["sessions"][0]["steps"] = [{
        "repeat": 2,
        "steps": [{
            "repeat": 3,
            "steps": [{"kind": "interval", "duration_s": 30, "text": "schnell"}],
        }],
    }]

    response = client.post(
        "/api/plans/import", headers=auth, json={"raw": json.dumps(plan), "days": 4}
    )
    assert response.status_code == 201, response.text

    warnungen = " ".join(response.json()["warnings"])
    assert "Serie in einer Serie geliefert" in warnungen


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
    # Der Hinweis auf die fehlende Schrittliste gehört zum alten Format dazu.
    assert not [w for w in body["warnings"] if "Schrittliste" not in w]
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
    # Anzahl der Kalenderwochen hängt am Wochentag (siehe
    # `test_ai_export_contains_context`); entscheidend ist die Abdeckung.
    assert date.fromisoformat(stats["weekly"][0]["week_start"]) <= date.today() - timedelta(weeks=4)

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
    assert weekly[-1]["total_minutes"] == 62  # laufende Woche
    # Die laufende Woche ist angebrochen und taugt deshalb nicht als Maßstab
    # für die Aufbauregel — genau dafür gibt es das Kennzeichen.
    assert weekly[-1]["ist_vollstaendig"] is False
    assert all(not w["ist_vollstaendig"] or w["week_end"] < date.today().isoformat()
               for w in weekly)


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
