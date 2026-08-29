"""Das Antwortformat in seinen zwei Fassungen.

`SESSION_SCHEMA` ist die Lehrfassung im Prompt-Text, `strukturschema()` dieselbe
Aussage als JSON Schema für `--json-schema`. Zwei Darstellungen desselben
Formats laufen auseinander, sobald jemand ein Feld nur an einer Stelle ergänzt —
diese Tests sind die Bremse dagegen.
"""

import pytest

from app import ai_export
from app.schemas import (
    HF_MAX,
    HF_MIN,
    RPE_MAX,
    RPE_MIN,
    AISessionIn,
    AIStepIn,
    STEP_KIND_ALIASES,
)


def einheit(disziplin: str) -> dict:
    schema = ai_export.strukturschema(disziplin)
    tage = schema["properties"]["plan"]["properties"]["days"]
    return tage["items"]["properties"]["sessions"]["items"]


@pytest.mark.parametrize("disziplin", ["run", "swim", "bike", "triathlon"])
def test_beide_fassungen_kennen_dieselben_felder(disziplin):
    """Die Feldliste wird abgeleitet, nicht abgeschrieben — hier steht es fest."""
    lehrfassung = set(ai_export._session_schema(disziplin))
    struktur = set(einheit(disziplin)["properties"])
    assert lehrfassung == struktur


@pytest.mark.parametrize("disziplin", ["run", "swim", "bike", "triathlon"])
def test_jedes_feld_landet_auch_im_datenmodell(disziplin):
    """Ein Feld, das Pydantic nicht kennt, wird beim Import stillschweigend verworfen."""
    unbekannt = set(einheit(disziplin)["properties"]) - set(AISessionIn.model_fields)
    assert unbekannt == set()


def test_die_disziplin_schneidet_die_sportarten_zu():
    """Ein Laufblock, dessen Schema `swim` anbietet, lädt genau das ein."""
    assert einheit("run")["properties"]["sport"]["enum"] == [
        "run", "strength", "mobility", "rest",
    ]
    assert "brick" not in einheit("run")["properties"]["type"]["enum"]

    triathlon = einheit("triathlon")["properties"]["sport"]["enum"]
    assert {"swim", "bike", "run", "brick"} <= set(triathlon)


def test_der_ort_gehoert_zur_sportart():
    """Ohne Schwimmen kein Becken, ohne Rad keine Rolle."""
    assert "swim_location" not in einheit("run")["properties"]
    assert "bike_location" not in einheit("run")["properties"]
    assert einheit("swim")["properties"]["swim_location"]["enum"] == [
        "pool", "open_water",
    ]
    assert einheit("bike")["properties"]["bike_location"]["enum"] == [
        "indoor", "outdoor",
    ]


def test_die_pflichtfelder_sind_die_der_app():
    """Genau das, woraus `garmin/workouts.py` ein Workout baut — und `summary`.

    Jedes weitere Pflichtfeld wäre eine Stelle, an der ein inhaltlich guter
    Block an einer Formalie scheitert.
    """
    plan = ai_export.strukturschema("triathlon")["properties"]["plan"]
    assert plan["required"] == [
        "title", "summary", "coaching_notes", "start_date", "days",
    ]
    assert set(einheit("triathlon")["required"]) == {
        "sport", "type", "title", "structure", "duration_min", "steps",
    }


def test_kein_zusatzfeldverbot_und_keine_bedingungen():
    """Beides wäre die Fessel, vor der `docs/ki-und-prompt.md` warnt.

    Und beides ist unnötig: Pydantic ignoriert Zusatzfelder, und welches Feld zu
    welcher Sportart gehört, entscheidet seit `_raeume_fremde_felder` der Code.
    """
    text = str(ai_export.strukturschema("triathlon"))
    assert "additionalProperties" not in text
    assert "'if'" not in text and "allOf" not in text


def test_der_bauplan_verweist_rekursiv_auf_sich_selbst():
    """Eine Serie ist eine Gruppe aus `repeat` und `steps` — beliebig tief im Schema.

    Am echten Programm geprüft: `$defs`/`$ref` werden von der CLI unterstützt.
    Ohne die Rekursion ließe sich eine Wiederholungsgruppe nicht ausdrücken.
    """
    schema = ai_export.strukturschema("run")
    schritt = schema["$defs"]["schritt"]
    assert schritt["properties"]["steps"]["items"] == {"$ref": "#/$defs/schritt"}
    assert einheit("run")["properties"]["steps"]["items"] == {
        "$ref": "#/$defs/schritt"
    }


def test_die_schrittarten_sind_garmins_eigene():
    """Dieselben fünf, die `STEP_KIND_ALIASES` als Ziel hat."""
    erlaubt = ai_export.strukturschema("run")["$defs"]["schritt"]["properties"]
    assert set(erlaubt["kind"]["enum"]) == set(STEP_KIND_ALIASES.values())


def test_die_grenzen_stimmen_mit_dem_datenmodell_ueberein():
    """Zwei Tabellen mit denselben Zahlen — hier laufen sie nicht auseinander.

    Eine Grenze, die das Schema erlaubt und Pydantic ablehnt, wäre die
    schlimmste Sorte: Sie ginge durch die Erzwingung und stürbe erst im Import.
    """
    schritt = ai_export.strukturschema("run")["$defs"]["schritt"]["properties"]
    felder = AIStepIn.model_fields

    def grenzen(feld):
        unten = next(m.ge for m in felder[feld].metadata if hasattr(m, "ge"))
        oben = next(m.le for m in felder[feld].metadata if hasattr(m, "le"))
        return unten, oben

    for feld in ("duration_s", "distance_m", "reps", "repeat"):
        assert (schritt[feld]["minimum"], schritt[feld]["maximum"]) == grenzen(feld)

    props = einheit("run")["properties"]
    assert (props["target_hr_low"]["minimum"], props["target_hr_low"]["maximum"]) == (
        HF_MIN, HF_MAX,
    )
    assert (props["rpe_target"]["minimum"], props["rpe_target"]["maximum"]) == (
        RPE_MIN, RPE_MAX,
    )


def test_die_einzelanpassung_verlangt_die_begruendung():
    """Sie ist die einzige Stelle, an der der Athlet erfährt, was passiert ist."""
    schema = ai_export.einheit_strukturschema("run")
    assert set(schema["required"]) == {"einheit", "begruendung"}
    assert schema["$defs"]["schritt"]["properties"]["steps"]["items"] == {
        "$ref": "#/$defs/schritt"
    }


def test_das_schema_reist_mit_dem_export():
    """Prompt und Schema kommen aus derselben Disziplin, nicht aus zwei Rechnungen."""
    payload = {
        "planungszeitraum": {"tage": 7},
        "trainingswunsch": {"disziplin_key": "run"},
    }
    schema = ai_export.strukturschema(ai_export._disziplin(payload))
    tage = schema["properties"]["plan"]["properties"]["days"]
    sport = tage["items"]["properties"]["sessions"]["items"]["properties"]["sport"]
    assert "swim" not in sport["enum"]
