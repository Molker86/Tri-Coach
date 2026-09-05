"""Robuster Parser für die von der KI zurückgegebene Plan-JSON.

KI-Antworten kommen in der Praxis selten sauber: mal in ```json-Fences, mal mit
einem einleitenden Satz davor, mal als flaches Objekt ohne "plan"-Wurzel, mal
mit der Wochenebene aus dem früheren Vier-Wochen-Format, mal mit einem zweiten
JSON-Objekt als Notiz davor oder dahinter. Der Parser fängt diese Fälle ab,
bevor die Pydantic-Validierung greift: Er liest *alle* Objekte des Textes und
sucht darin nach der Form des Plans, statt sich auf das erste zu verlassen.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from . import plan_aufraeumen
from .models import TRAININGSWUNSCH_AKTUALITAET, Plan, PlanSession, TrainingRequest
from .paketformat import ist_datenpaket
from .schemas import (
    DISCIPLINE_LABEL,
    DISZIPLINFREIE_SPORTARTEN,
    DISZIPLIN_SPORTARTEN,
    ERGAENZUNGSSPORTARTEN,
    AIEinheitBody,
    AIEinheitImport,
    AIPlanBody,
    AIPlanImport,
    AISessionIn,
    AIStepIn,
    AITagesformBody,
    AITagesformImport,
)
from .zeit import jetzt_utc


class PlanImportError(ValueError):
    """Fehler mit für den Nutzer lesbarer Meldung."""


def _json_objekte(text: str) -> tuple[list[str], bool]:
    """Alle vollständigen JSON-Objekte des Textes, in ihrer Reihenfolge.

    Gezählt wird klammernd; geschweifte Klammern innerhalb von Strings zählen
    nicht mit, damit Beschreibungstexte den Parser nicht aus dem Tritt bringen.
    Innerhalb eines Objekts wird nicht weitergesucht — gemeint sind die
    äußersten.

    Warum *alle* statt nur das erste: Eine KI-Antwort trägt oft mehr als ein
    Objekt — ein Beispiel im Vortext, eine erste Codefence mit einer Notiz,
    ein Nachtrag hinter dem Plan. Wer das erste nimmt, nimmt dann das falsche
    und meldet „Field required" über einem Text, in dem der Block sauber
    dasteht. Welches der Plan ist, entscheidet danach die Form und nicht die
    Reihenfolge; dafür ist auch das Herausschneiden der Codefences entfallen,
    denn die Zäune selbst tragen keine Klammern.

    Der zweite Rückgabewert sagt, ob am Ende ein Objekt offen geblieben ist —
    das ist die abgeschnittene Antwort, der häufigste Fehlerfall überhaupt.
    """
    objekte: list[str] = []
    start = 0
    tiefe = 0
    im_string = False
    maskiert = False

    for i, zeichen in enumerate(text):
        if im_string:
            if maskiert:
                maskiert = False
            elif zeichen == "\\":
                maskiert = True
            elif zeichen == '"':
                im_string = False
            continue

        if zeichen == '"':
            # Nur innerhalb eines Objekts: Ein Anführungszeichen im Fließtext
            # davor darf die Klammerzählung nicht abschalten.
            im_string = tiefe > 0
        elif zeichen == "{":
            if not tiefe:
                start = i
            tiefe += 1
        elif zeichen == "}" and tiefe:
            tiefe -= 1
            if not tiefe:
                objekte.append(text[start : i + 1])

    return objekte, tiefe > 0


def _fehlerstelle(fehler: json.JSONDecodeError, umfeld: int = 45) -> str:
    """Die Zeichen um die Fundstelle herum, im Wortlaut.

    Zeile und Spalte allein sind bei einer KI-Antwort wertlos: Sie steht oft
    in einer einzigen Zeile, und „Spalte 2318" zählt niemand ab. Der
    Ausschnitt dagegen lässt sich im Text suchen — und meist sieht man ihm die
    Ursache sofort an, denn „Expecting ',' delimiter" heißt fast immer, dass
    ein Anführungszeichen mitten in einem Text steht, das die KI nicht
    maskiert hat.
    """
    text = fehler.doc
    von = max(0, fehler.pos - umfeld)
    bis = min(len(text), fehler.pos + umfeld)
    ausschnitt = " ".join(text[von:bis].split())
    return f"{'…' if von else ''}{ausschnitt}{'…' if bis < len(text) else ''}"


def _gelesene_objekte(raw: str) -> list[dict[str, Any]]:
    """Die lesbaren JSON-Objekte des eingefügten Textes.

    Wirft die Meldungen, die der Athlet zu sehen bekommt. Die abgeschnittene
    Antwort steht dabei vor der unlesbaren: Sie ist der häufigste Fall, und
    „unvollständig" sagt ihm, was zu tun ist.
    """
    if not raw or not raw.strip():
        raise PlanImportError("Es wurde kein Text eingefügt.")

    objekte, offen = _json_objekte(raw)
    gelesen: list[dict[str, Any]] = []
    fehler: json.JSONDecodeError | None = None
    for kandidat in objekte:
        try:
            daten = json.loads(kandidat)
        except json.JSONDecodeError as exc:
            fehler = fehler or exc
            continue
        if isinstance(daten, dict):
            gelesen.append(daten)

    if gelesen:
        return gelesen
    if offen:
        raise PlanImportError(
            "Das JSON ist unvollständig — vermutlich wurde die KI-Antwort "
            "abgeschnitten. Bitte die Antwort vollständig kopieren."
        )
    if fehler:
        raise PlanImportError(
            f"Das eingefügte JSON ist nicht lesbar (Zeile {fehler.lineno}, "
            f"Spalte {fehler.colno}): {fehler.msg}. Dort steht: "
            f"„{_fehlerstelle(fehler)}\""
        )
    raise PlanImportError("Im eingefügten Text wurde kein JSON-Objekt gefunden.")


def _flatten_weeks(plan: Any) -> Any:
    """Zieht eine Antwort im Wochenformat auf die flache Tagesliste herunter.

    Modelle greifen gern auf die vertraute `weeks`-Struktur zurück, auch wenn nur
    wenige Tage angefordert waren. Inhaltlich ist das derselbe Plan — nur eine
    Ebene tiefer, und die Ebene interessiert uns nicht mehr.
    """
    if not isinstance(plan, dict) or plan.get("days"):
        return plan
    weeks = plan.get("weeks")
    if not isinstance(weeks, list):
        return plan

    days = [
        day
        for week in weeks
        if isinstance(week, dict)
        for day in (week.get("days") or [])
    ]
    return {**plan, "days": days}


# Woran ein Planobjekt zu erkennen ist: an seiner Tagesliste. Der Titel ist
# beliebig, `start_date` lässt sich aus den Tagen ablesen — die Tage selbst
# sind das Einzige, was ein Block zwingend mitbringt.
_TAGESLISTEN = ("days", "weeks")

_DATENPAKET_EINGEFUEGT = (
    "Das ist das Datenpaket für die KI, nicht ihre Antwort. Kopiere "
    "den Text oben, gib ihn der KI und füge hier ein, was sie "
    "zurückschreibt."
)


def _ist_planform(wert: Any) -> bool:
    return isinstance(wert, dict) and any(
        isinstance(wert.get(schluessel), list) and wert.get(schluessel)
        for schluessel in _TAGESLISTEN
    )


def _plan_darin(daten: Any, tiefe: int = 2) -> dict[str, Any] | None:
    """Sucht das Planobjekt — flach, unter `plan` oder unter fremdem Namen.

    Verlangt ist `{"plan": {...}}`; in der Praxis kommt der Block auch nackt,
    als `{"trainingsplan": …}` oder eine Hülle tiefer. Gesucht wird deshalb
    nach der Form statt nach dem Schlüsselnamen: Eine Tagesliste hat in dieser
    Antwort sonst nichts zu suchen, und ein umbenannter Wrapper ist keine
    inhaltliche Abweichung — dieselbe Linie wie bei den Sprachvarianten der
    Sportarten.
    """
    if _ist_planform(daten):
        return daten
    if tiefe <= 0 or not isinstance(daten, dict):
        return None
    for wert in daten.values():
        if (gefunden := _plan_darin(wert, tiefe - 1)) is not None:
            return gefunden
    return None


def _falsche_antwort(objekte: list[dict[str, Any]], roh: str = "") -> str | None:
    """Benennt das Verwechseln, statt Feldnamen aufzuzählen.

    Wer das Datenpaket oder die Antwort auf eine Einzelanpassung einfügt,
    bekam „plan → start_date: Field required" zu lesen — eine Auskunft
    darüber, was fehlt, während er wissen muss, was dasteht. Beide Fälle sehen
    in der Feldliste zudem gleich aus, obwohl der nächste Handgriff ein ganz
    anderer ist.

    Das Datenpaket wird am **Rohtext** erkannt und nicht mehr an obersten
    JSON-Schlüsseln: Sein Datenteil ist seit der Umstellung auf Tabellen kein
    JSON-Objekt mehr, und ein eingefügter Prompt trüge dann nur noch das
    Antwortformat als lesbares Objekt — also ausgerechnet eine Tagesliste.
    """
    if roh and ist_datenpaket(roh):
        return _DATENPAKET_EINGEFUEGT

    for daten in objekte:
        if any(
            schluessel in daten
            for schluessel in ("athlet", "trainingswunsch", "trainingshistorie")
        ):
            return _DATENPAKET_EINGEFUEGT
        if any(
            isinstance(daten.get(schluessel), dict)
            for schluessel in _EINHEIT_SCHLUESSEL
        ) or ("sport" in daten and "date" not in daten):
            return (
                "Das ist die Antwort auf eine Einzelanpassung — eine einzelne "
                "Einheit statt eines Blocks. Sie wird im Trainingsplan an der "
                "Einheit selbst übernommen, nicht hier."
            )
    return None


def _ohne_tagesliste(objekte: list[dict[str, Any]]) -> str:
    """Sagt, was stattdessen dastand — sonst rät der Athlet, was er hat."""
    felder = ", ".join(sorted(objekte[0])[:8]) or "gar keine"
    return (
        "In der Antwort war kein Trainingsblock zu finden: Auf oberster Ebene "
        f"stehen die Felder {felder}. Erwartet wird ein Objekt mit \"plan\" und "
        'darin einer Tagesliste "days" — so, wie es das Antwortformat am Ende '
        "des kopierten Textes vorgibt."
    )


def parse_ai_response(raw: str) -> AIPlanBody:
    """Der Texteinstieg: Aus einer Antwort im Klartext den Block lesen.

    Der Weg über die Zwischenablage hat nur diesen, und er bleibt der Rückfall,
    wenn ein Lauf ohne `--json-schema` gelaufen ist.
    """
    return plan_aus_objekten(_gelesene_objekte(raw), roh=raw)


def plan_aus_objekt(daten: dict[str, Any]) -> AIPlanBody:
    """Der Objekteinstieg: Die Antwort liegt schon geparst vor.

    Gibt es, seit `ki/client.py` ein `--json-schema` mitgibt — die CLI legt das
    Ergebnis dann als `structured_output` daneben, und den Text noch einmal nach
    Klammern abzusuchen wäre ein Umweg über eine Fehlerquelle, die hier gerade
    beseitigt wurde. Geprüft wird trotzdem dasselbe: Ein erzwungenes Schema
    sichert die Struktur, nicht die Datumsfolge oder die Disziplin.
    """
    return plan_aus_objekten([daten])


def plan_aus_objekten(
    objekte: list[dict[str, Any]], roh: str = ""
) -> AIPlanBody:
    plan = next(
        (gefunden for daten in objekte if (gefunden := _plan_darin(daten))), None
    )
    if plan is None:
        # Kein Objekt trägt eine Tagesliste. Steht wenigstens ein `plan` da,
        # bekommt Pydantic das Wort — seine Feldliste sagt dann genauer, was
        # daran fehlt. Sonst wurde etwas anderes eingefügt, und *das* ist der
        # Hinweis, den der Athlet braucht.
        plan = next(
            (d["plan"] for d in objekte if isinstance(d.get("plan"), dict)), None
        )
        if plan is None:
            raise PlanImportError(
                _falsche_antwort(objekte, roh) or _ohne_tagesliste(objekte)
            )

    try:
        return AIPlanImport.model_validate({"plan": _flatten_weeks(plan)}).plan
    except ValidationError as exc:
        # Der gewählte Kandidat trägt zwar eine Tagesliste, taugt aber nicht.
        # Steht daneben das Datenpaket im Text, wurde der ganze Prompt
        # zurückkopiert — dann stammt die Tagesliste aus dem Antwortformat am
        # Ende des Prompts, und „days → 0 → date: YYYY-MM-DD ist kein Datum"
        # wäre die Antwort auf eine Frage, die niemand gestellt hat. Geprüft
        # wird erst hier und nicht davor: Ein gültiger Block soll nie an einem
        # Objekt scheitern, das zufällig danebensteht.
        raise PlanImportError(
            _falsche_antwort(objekte, roh) or _readable_validation_error(exc)
        ) from exc


def _readable_validation_error(exc: ValidationError) -> str:
    lines = ["Der Plan entspricht nicht dem erwarteten Format:"]
    for err in exc.errors()[:6]:
        location = " → ".join(str(p) for p in err["loc"]) or "Wurzel"
        lines.append(f"  • {location}: {err['msg']}")
    if len(exc.errors()) > 6:
        lines.append(f"  • … und {len(exc.errors()) - 6} weitere Probleme")
    return "\n".join(lines)


def _week_number(day: date, start: date) -> int:
    """Fortlaufende Woche innerhalb des Blocks.

    Ein Block über wenige Tage liegt komplett in Woche 1. Das Feld bleibt am
    Modell, damit ältere Vier-Wochen-Pläne in der Ansicht weiter gruppiert
    dargestellt werden können.
    """
    return max(1, (day - start).days // 7 + 1)


def _schritte_json(session: Any) -> list[dict[str, Any]] | None:
    """Der Bauplan als schlichtes JSON — oder `None`, wenn keiner kam.

    `None` statt einer leeren Liste, weil beides Verschiedenes heißt: Kein
    Bauplan bedeutet „zerlege den Fließtext wie bisher", eine leere Liste
    bedeutete „diese Einheit hat keine Schritte".
    """
    schritte = getattr(session, "steps", None)
    if not schritte:
        return None
    return [schritt.model_dump(mode="json") for schritt in schritte]


def build_plan(
    body: AIPlanBody, user_id: int, request_id: int | None = None
) -> Plan:
    """Überführt die validierte KI-Antwort in Plan + Einheiten."""
    all_dates = [d.date for d in body.days]
    if not all_dates:
        raise PlanImportError("Der Plan enthält keinen einzigen Tag.")

    start = body.start_date
    end = max(max(all_dates), start)

    plan = Plan(
        user_id=user_id,
        request_id=request_id,
        title=body.title,
        summary=body.summary,
        coaching_notes=body.coaching_notes,
        start_date=start,
        end_date=end,
        # Einmal gesetzt und nie wieder angefasst: `start_date` wandert
        # zurück, sobald dieser Block die Vergangenheit seines Vorgängers
        # übernimmt (siehe `plan_aufraeumen`), `geplant_ab` nicht.
        geplant_ab=start,
        raw_json=body.model_dump(mode="json"),
    )

    for day in body.days:
        for order, session in enumerate(day.sessions):
            plan.sessions.append(
                PlanSession(
                    date=day.date,
                    week_number=_week_number(day.date, start),
                    order_in_day=order,
                    sport=session.sport,
                    session_type=session.type,
                    title=session.title,
                    description=session.description,
                    structure=session.structure,
                    purpose=session.purpose,
                    # Gerechnet statt übernommen, wo es exakt geht — siehe
                    # `_gerechnete_dauer`. Nicht im Pydantic-Modell: In
                    # `Plan.raw_json` gehört die KI-Antwort im Original, nicht
                    # unsere Korrektur daran.
                    duration_min=(
                        _gerechnete_dauer(session) or session.duration_min
                    ),
                    distance_km=session.distance_km,
                    intensity_zone=session.intensity_zone,
                    target_hr_low=session.target_hr_low,
                    target_hr_high=session.target_hr_high,
                    target_pace=session.target_pace,
                    target_power=session.target_power,
                    rpe_target=session.rpe_target,
                    swim_location=session.swim_location,
                    bike_location=session.bike_location,
                    steps_json=_schritte_json(session),
                )
            )

    return plan


# Wie weit die Summe der Schritte von der geplanten Dauer abweichen darf, bevor
# es einen Hinweis wert ist. Ein Bauplan rechnet nie auf die Minute auf: Ein
# Streckenschritt hängt an der Pace, und ein paar Sekunden Übergang zählt
# niemand mit.
_DAUER_TOLERANZ = 0.2


def _schrittzeit(schritte: list[AIStepIn]) -> float | None:
    """Die Gesamtzeit des Bauplans — oder `None`, wenn sie niemand kennt.

    Nur wenn *jeder* Schritt eine Dauer trägt, ist die Summe eine Aussage.
    Sobald eine Strecke oder eine Wiederholungszahl darunter liegt, hängt die
    Zeit an Pace und Ausführung, und eine Abweichung von `duration_min` wäre
    kein Fehler, sondern der Normalfall.
    """
    gesamt = 0.0
    for schritt in schritte:
        if schritt.repeat and schritt.steps:
            innen = _schrittzeit(schritt.steps)
            if innen is None:
                return None
            gesamt += schritt.repeat * innen
        elif schritt.duration_s:
            gesamt += schritt.duration_s
        else:
            return None
    return gesamt


def _gerechnete_dauer(einheit: AISessionIn) -> int | None:
    """Die Dauer aus dem Bauplan — oder `None`, wenn sie sich nicht rechnen lässt.

    Addieren ist eine Rechenoperation über `steps`, keine Trainingsentscheidung,
    und Sprachmodelle addieren vierzig Schritte mit Pausen und Durchgängen
    unzuverlässig. Gerechnet wird deshalb hier — aber **nur, wo es exakt geht**:
    `_schrittzeit` gibt auf, sobald ein Streckenschritt oder eine
    Wiederholungszahl darunterliegt. Deren Dauer hinge an Pace und Ausführung,
    und eine geschätzte Zahl wäre keine Korrektur, sondern eine Erfindung der
    App an einer Stelle, an der bisher wenigstens ein Fachmann geraten hat.

    `distance_km` bekommt bewusst **kein** Gegenstück: Ein Lauf mit
    zeitbasiertem Ein- und Auslaufen und Streckenintervallen ergäbe als Summe
    der `distance_m` systematisch zu wenig. Wer das hier ergänzt, macht die
    Angabe schlechter, nicht besser.
    """
    if not einheit.steps:
        return None
    summe = _schrittzeit(einheit.steps)
    if not summe:
        return None
    return round(summe / 60)


def _dauer_korrigiert(einheit: AISessionIn) -> str | None:
    """„Krafteinheit" (20 min angegeben, gerechnet wurden 14) — oder nichts.

    Gemeldet wird nur, was mehr als die Toleranz auseinanderliegt: Ein Bauplan
    trifft die runde Minute selten, und ein Hinweis bei jeder Einheit wäre
    keiner mehr. Übernommen wird der gerechnete Wert in jedem Fall.
    """
    gerechnet = _gerechnete_dauer(einheit)
    if gerechnet is None or not einheit.duration_min:
        return None
    geplant = einheit.duration_min * 60
    if abs(gerechnet * 60 - geplant) <= _DAUER_TOLERANZ * geplant:
        return None
    return (
        f"„{einheit.title}“ ({einheit.duration_min} min angegeben, "
        f"gerechnet wurden {gerechnet} min)"
    )


def _zeitteil(schritte: list[AIStepIn]) -> float:
    """Die Sekunden der zeittragenden Schritte, Strecke und Reps als 0.

    Anders als `_schrittzeit` gibt das nie auf: Was herauskommt, ist eine
    **untere Schranke** für die Dauer der Einheit — die Strecken- und
    Übungsschritte kommen ja noch obendrauf. Damit lässt sich auch dort etwas
    prüfen, wo sich nichts exakt rechnen lässt.
    """
    gesamt = 0.0
    for schritt in schritte:
        if schritt.repeat and schritt.steps:
            gesamt += schritt.repeat * _zeitteil(schritt.steps)
        elif schritt.duration_s:
            gesamt += schritt.duration_s
    return gesamt


def _dauer_zu_knapp(einheit: AISessionIn) -> str | None:
    """Wenn schon die Pausen allein länger dauern als die ganze Einheit.

    Der Fall, für den sich nichts exakt rechnen lässt — Kraft mit gezählten
    Wiederholungen, Intervalle nach Strecke —, ist nicht ganz unprüfbar:
    Übersteigt die Zeit der zeittragenden Schritte bereits `duration_min`, ist
    die Angabe sicher falsch, egal wie lange die übrigen Schritte dauern.
    """
    if not einheit.duration_min or not einheit.steps:
        return None
    # Wo exakt gerechnet wurde, ist die Zahl schon berichtigt.
    if _gerechnete_dauer(einheit) is not None:
        return None
    # Mit derselben Toleranz wie die Korrektur: Ein Bauplan trifft die runde
    # Minute selten, und ein paar Sekunden über der Angabe sind der Normalfall,
    # nicht der Fehler. Gemeint ist der Fall, in dem die Pausen allein die
    # Einheit sprengen — der liegt deutlich darüber.
    untergrenze = _zeitteil(einheit.steps)
    geplant = einheit.duration_min * 60
    if untergrenze <= geplant * (1 + _DAUER_TOLERANZ):
        return None
    return (
        f"„{einheit.title}“ ({einheit.duration_min} min angegeben, allein die "
        f"Zeitschritte dauern {round(untergrenze / 60)} min)"
    )


def _gekuerzt(eintraege: list[str], trenner: str = ", ") -> str:
    """Die ersten drei, der Rest gezählt — die Form der übrigen Hinweise."""
    gezeigt = trenner.join(eintraege[:3])
    if len(eintraege) > 3:
        return f"{gezeigt} (und {len(eintraege) - 3} weitere)"
    return gezeigt


# Die drei Ausdauersportarten heißen wie ihre Disziplinen. Koppeleinheit, Kraft
# und Mobility haben keine, kommen in den Meldungen aber vor — ohne Eintrag
# stünde ihre englische Kennung in einem deutschen Satz.
_SPORT_TEXT = {
    **DISCIPLINE_LABEL,
    "brick": "Koppeltraining",
    "strength": "Kraft",
    "mobility": "Mobility",
}


def _fremde_sportarten(body: AIPlanBody, disziplin: str | None) -> list[str]:
    """Ausdauereinheiten, die nicht zur gewählten Disziplin gehören.

    Punkt 1 des Prompts sagt der KI, dass ein Laufblock nur Laufeinheiten
    enthält — nachprüfen kann das nur der Import, und auch der meldet es bloß:
    Ein abgelehnter Block wäre die teuerste denkbare Antwort auf eine Einheit,
    die der Athlet notfalls selbst anpassen kann (dieselbe Linie wie überall
    hier). Kraft, Mobility und Ruhe gehören in jede Disziplin.
    """
    erlaubt = DISZIPLIN_SPORTARTEN.get(disziplin or "", [])
    if len(erlaubt) != 1:
        return []

    fremde: dict[str, int] = {}
    for tag in body.days:
        for einheit in tag.sessions:
            if einheit.sport in erlaubt or einheit.sport in DISZIPLINFREIE_SPORTARTEN:
                continue
            fremde[einheit.sport] = fremde.get(einheit.sport, 0) + 1

    if not fremde:
        return []

    benannt = ", ".join(
        f"{anzahl}x {_SPORT_TEXT.get(sport, sport)}"
        for sport, anzahl in sorted(fremde.items())
    )
    return [
        f"Der Block enthält Einheiten außerhalb der gewählten Disziplin "
        f"({DISCIPLINE_LABEL.get(disziplin, disziplin)}): {benannt}. Sie sind "
        "übernommen; wer sie nicht will, plant den Block neu oder passt die "
        "Einheiten einzeln an."
    ]


def _ungewolltes_ergaenzungstraining(
    body: AIPlanBody, zusatztraining: list[str] | None
) -> list[str]:
    """Kraft und Mobility, die im Fragebogen nicht angekreuzt sind.

    `_fremde_sportarten()` lässt beide bewusst durch — sie gehören in jede
    Disziplin. Ob sie überhaupt in den Block gehören, sagt aber nicht die
    Disziplin, sondern `supplemental`, und genau das ging verloren: Bei leerer
    Auswahl fiel das Feld aus dem Paket (`ai_export.KEIN_ZUSATZTRAINING`), und
    die KI plante Kraft- und Mobilityeinheiten, die niemand wollte. Der Prompt
    verbietet sie jetzt ausdrücklich; nachprüfen kann das nur der Import.

    Gemeldet, nicht gelöscht: Eine Einheit zu entfernen risse ein Loch in den
    Tag — dieselbe Linie wie bei den fremden Sportarten.
    """
    if zusatztraining is None:
        return []

    ungewollt: dict[str, int] = {}
    for tag in body.days:
        for einheit in tag.sessions:
            if einheit.sport not in ERGAENZUNGSSPORTARTEN:
                continue
            if einheit.sport in zusatztraining:
                continue
            ungewollt[einheit.sport] = ungewollt.get(einheit.sport, 0) + 1

    if not ungewollt:
        return []

    benannt = ", ".join(
        f"{anzahl}x {_SPORT_TEXT.get(sport, sport)}"
        for sport, anzahl in sorted(ungewollt.items())
    )
    gewaehlt = (
        ", ".join(_SPORT_TEXT.get(s, s) for s in zusatztraining)
        if zusatztraining
        else "nichts davon"
    )
    return [
        f"Der Block enthält Ergänzungstraining, das im Fragebogen nicht "
        f"gewählt ist ({benannt}; gewählt: {gewaehlt}). Es ist übernommen; wer "
        "es nicht will, passt die Einheiten einzeln an oder ergänzt den "
        "Fragebogen."
    ]


def validate_coverage(
    body: AIPlanBody,
    expected_days: int | None = None,
    disziplin: str | None = None,
    zusatztraining: list[str] | None = None,
) -> list[str]:
    """Nicht-blockierende Plausibilitätsprüfungen für die Nutzer-Rückmeldung.

    `expected_days` ist die beim Export angeforderte Blocklänge. Fehlt sie,
    wird der Zeitraum aus dem Plan selbst abgeleitet — dann fällt nur auf, was
    innerhalb des gelieferten Zeitraums fehlt.

    `disziplin` ist die Wahl aus dem Fragebogen. Ohne sie wird die Sportart
    nicht geprüft — dieselbe Zurückhaltung wie beim Prompt, der ohne
    Fragebogen alle Disziplinen offen lässt.

    `zusatztraining` ist dieselbe Wahl für Kraft und Mobility. `None` heißt
    „kein Fragebogen, also keine Prüfung"; die leere Liste heißt „ausdrücklich
    nichts davon" und ist damit die schärfste Vorgabe, nicht die schwächste.
    """
    warnings: list[str] = []

    all_dates = sorted({d.date for d in body.days})
    start = body.start_date

    if body.startdatum_abgeleitet:
        warnings.append(
            f"Ohne „start_date“ geliefert; als Beginn gilt der früheste Tag "
            f"({start.isoformat()}). Fehlen zugleich die ersten Tage des "
            "Blocks, fällt das nur über die Zahl der Tage auf."
        )

    # Beide Felder sind im Schema optional, weil ein Block ohne sie noch
    # brauchbar ist — anders als ein fehlender Tag lässt sich das aber nicht
    # aus der Tagesliste ablesen. Ohne diese Meldung fiele ein leer
    # gebliebenes Feld erst auf, wenn „Zur Ausrichtung des Blocks“ oder
    # „Hinweise zur Steuerung“ in der Ansicht fehlen — und dann ohne jeden
    # Hinweis darauf, dass die KI-Antwort daran schuld war.
    if not body.summary:
        warnings.append(
            "Ohne „summary“ geliefert — der Abschnitt „Zur Ausrichtung des "
            "Blocks“ bleibt leer."
        )
    if not body.coaching_notes:
        warnings.append(
            "Ohne „coaching_notes“ geliefert — der Abschnitt „Hinweise zur "
            "Steuerung“ bleibt leer."
        )

    if expected_days and len(all_dates) != expected_days:
        warnings.append(
            f"Der Plan enthält {len(all_dates)} statt {expected_days} Tage."
        )

    span = expected_days or ((max(all_dates) - start).days + 1)
    expected = {start + timedelta(days=i) for i in range(max(span, 0))}

    missing = sorted(expected - set(all_dates))
    if missing:
        shown = ", ".join(d.isoformat() for d in missing[:5])
        suffix = f" (und {len(missing) - 5} weitere)" if len(missing) > 5 else ""
        warnings.append(f"Ohne Eintrag geblieben: {shown}{suffix}.")

    outside = [d for d in all_dates if d not in expected]
    if outside:
        warnings.append(
            f"{len(outside)} Tag(e) liegen außerhalb des Zeitraums ab "
            f"{start.isoformat()}."
        )

    empty = [d.date.isoformat() for d in body.days if not d.sessions]
    if empty:
        warnings.append(f"{len(empty)} Tag(e) enthalten keine Einheit.")

    warnings.extend(_fremde_sportarten(body, disziplin))
    warnings.extend(_ungewolltes_ergaenzungstraining(body, zusatztraining))

    # Unbrauchbare Steuerungsgrößen (Zielpuls, RPE) hat `AISessionIn` bereits
    # weggeworfen, statt den Block abzulehnen. Stillschweigend darf das nicht
    # passieren: Die Einheit geht dann ohne Herzfrequenzkorridor auf die Uhr,
    # und wer den Plan liest, soll wissen warum.
    verworfen = [
        f"{tag.date.isoformat()} „{einheit.title}“ "
        f"({', '.join(einheit.verworfene_zielwerte)})"
        for tag in body.days
        for einheit in tag.sessions
        if einheit.verworfene_zielwerte
    ]
    if verworfen:
        warnings.append(
            "Unbrauchbare Steuerungsgröße verworfen: "
            f"{_gekuerzt(verworfen, '; ')}. Der Wert "
            "fehlt an diesen Einheiten; ein verworfener Zielpuls heißt außerdem, "
            "dass sie ohne Herzfrequenzkorridor auf die Uhr gehen."
        )

    # Fehlt der Bauplan, ist der Block trotzdem gut — er geht dann über den
    # Fließtext auf die Uhr, so wie vor der Einführung des Feldes. Gemeldet
    # wird es aber: Sonst fiele nie auf, dass der zweite Kanal nicht trägt,
    # und die Zerlegung bliebe stillschweigend der einzige Weg.
    ohne_bauplan = [
        f"„{einheit.title}“"
        for tag in body.days
        for einheit in tag.sessions
        if einheit.sport != "rest" and not einheit.steps
    ]
    if ohne_bauplan:
        warnings.append(
            f"Ohne Schrittliste geliefert: {_gekuerzt(ohne_bauplan)}. Diese Einheiten "
            "werden für die Uhr aus ihrem Aufbautext zerlegt — das ist der "
            "bisherige Weg und funktioniert, trifft den Aufbau aber nicht so "
            "sicher wie eine Schrittliste."
        )

    # Mehrere Maße an einem Schritt hat `AISessionIn._raeume_masse` bereits
    # bereinigt. Auch das darf nicht stillschweigend passieren: Auf der Uhr
    # steht dann ein Timer, wo Wiederholungen gemeint waren — oder umgekehrt.
    doppelt = [
        f"„{einheit.title}“ ({', '.join(einheit.verworfene_masse)})"
        for tag in body.days
        for einheit in tag.sessions
        if einheit.verworfene_masse
    ]
    if doppelt:
        warnings.append(
            f"Mehrfach bemaßte Schritte bereinigt: {_gekuerzt(doppelt, '; ')}. "
            "Die Uhr schaltet nach genau einem Maß weiter; der überzählige "
            "Wert ist weggefallen."
        )

    verschachtelt = [
        f"„{einheit.title}“"
        for tag in body.days
        for einheit in tag.sessions
        if einheit.verschachtelte_gruppen
    ]
    if verschachtelt:
        warnings.append(
            f"Serie in einer Serie geliefert: {_gekuerzt(verschachtelt)}. "
            "Garmin kennt keine Gruppe in einer Gruppe — die innere wird auf "
            "der Uhr ausgeschrieben."
        )

    einheiten = [einheit for tag in body.days for einheit in tag.sessions]

    korrigiert = [h for e in einheiten if (h := _dauer_korrigiert(e))]
    if korrigiert:
        warnings.append(
            f"Dauer aus dem Bauplan neu gerechnet: {_gekuerzt(korrigiert, '; ')}. "
            "Übernommen wurde der gerechnete Wert — auf der Uhr gilt ohnehin "
            "der Bauplan."
        )

    knapp = [h for e in einheiten if (h := _dauer_zu_knapp(e))]
    if knapp:
        warnings.append(
            f"Dauer und Bauplan passen nicht zusammen: {_gekuerzt(knapp, '; ')}. "
            "Hier ließ sich nichts nachrechnen, die Angabe der KI bleibt stehen."
        )

    return warnings


# --------------------------------------------------------------------------
# Übernahme — ein Weg für Einfügen von Hand und Lauf im Server
# --------------------------------------------------------------------------


@dataclass(slots=True)
class Uebernahme:
    plan: Plan
    warnings: list[str] = field(default_factory=list)
    garmin_job_id: int | None = None
    garmin_hinweis: str | None = None


def _letzter_fragebogen(db: Session, user_id: int) -> int | None:
    """Der zuletzt gespeicherte Fragebogen — dieselbe Wahl, die der Export trifft.

    Ohne ausdrückliche `request_id` nimmt `ai_export._lade_kontext()` den
    jüngsten Fragebogen; der Plan behielt trotzdem `request_id = NULL` und war
    damit von dem Fragebogen getrennt, aus dem er tatsächlich entstanden ist.
    Das fiel erst auf, als die Ausrüstung anfing, über den Inhalt des Workouts
    zu entscheiden: Ohne den Verweis wusste die Übertragung nicht, ob ein
    Powermeter am Rad sitzt, und legte vorsichtshalber Watt auf jede Einheit.
    """
    zeile = (
        db.query(TrainingRequest.id)
        .filter(TrainingRequest.user_id == user_id)
        .order_by(TRAININGSWUNSCH_AKTUALITAET.desc())
        .first()
    )
    return zeile[0] if zeile else None


def gepruefter_fragebogen(
    db: Session, user_id: int, request_id: int | None
) -> int | None:
    """Die Kennung, an der dieser Block hängen wird — nur wenn sie dem Nutzer gehört.

    Ohne Angabe der letzte eigene. Mit Angabe kam sie bisher ungeprüft aus dem
    Anfragekörper und landete über `build_plan()` in `Plan.request_id`: Ein Plan
    konnte an einem fremden Fragebogen hängen, und jeder spätere Export darauf
    scheiterte in `ai_export._lade_kontext()` an „Fragebogen nicht gefunden." —
    dann aber ohne Hinweis darauf, woher die falsche Kennung stammte. Der Weg
    über die KI prüft an derselben Stelle (`routers/ki.py`).
    """
    if request_id is None:
        return _letzter_fragebogen(db, user_id)
    treffer = (
        db.query(TrainingRequest.id)
        .filter(
            TrainingRequest.id == request_id,
            TrainingRequest.user_id == user_id,
        )
        .first()
    )
    if treffer is None:
        raise PlanImportError("Fragebogen nicht gefunden.")
    return treffer[0]


def vorgaben_des_fragebogens(
    db: Session, user_id: int, request_id: int | None
) -> tuple[str | None, list[str] | None]:
    """Disziplin und Ergänzungstraining — die beiden Vorgaben, die der Import prüft.

    In einer Abfrage, weil beide aus derselben Zeile kommen und aus derselben
    Zeile kommen **müssen**: Zwei Abfragen mit je eigenem Rückfall könnten die
    Disziplin des einen und das Ergänzungstraining eines anderen Fragebogens
    liefern.

    Ohne ausdrückliche `request_id` gilt derselbe Rückfall wie überall sonst:
    der zuletzt geänderte Fragebogen (`_letzter_fragebogen()`). Ohne Fragebogen
    gibt es keine Vorgabe — dann wird nichts geprüft, und beides ist `None`.
    """
    gesucht = request_id or _letzter_fragebogen(db, user_id)
    if gesucht is None:
        return None, None
    zeile = (
        db.query(TrainingRequest.discipline, TrainingRequest.supplemental)
        .filter(
            TrainingRequest.id == gesucht,
            TrainingRequest.user_id == user_id,
        )
        .first()
    )
    if zeile is None:
        return None, None
    # Die leere Liste ist eine Aussage („nichts davon“) und darf nicht zu `None`
    # („nicht bekannt“) werden — `list(...)` hält beides auseinander.
    return zeile[0], list(zeile[1] or [])


def disziplin_des_fragebogens(
    db: Session, user_id: int, request_id: int | None
) -> str | None:
    """Nur die Disziplin — für Aufrufer, die das Ergänzungstraining nicht brauchen."""
    return vorgaben_des_fragebogens(db, user_id, request_id)[0]


def uebernimm_plan(
    db: Session,
    user_id: int,
    raw: str,
    *,
    request_id: int | None = None,
    days: int | None = None,
    struktur: dict[str, Any] | None = None,
) -> Uebernahme:
    """Macht aus einer KI-Antwort den aktiven Block — samt allem, was daran hängt.

    Eine Funktion für beide Auslöser: den eingefügten Text und die Antwort, die
    der Server selbst geholt hat. Damit erbt der automatische Weg ohne
    Wiederholung, was am Übernehmen hängt — der abgelöste Block wird
    weggeräumt, und der neue geht von selbst auf die Uhr.

    `struktur` ist dieselbe Antwort, schon geparst — die CLI legt sie neben den
    Text, wenn ein `--json-schema` mitging. Liegt sie vor, gilt sie: `raw` ist
    dann nur noch das, was im Fehlerfall gespeichert wird.

    Wirft `PlanImportError`, wenn die Antwort nicht zu lesen ist; dann bleibt
    die Datenbank unberührt.
    """
    body = plan_aus_objekt(struktur) if struktur is not None else parse_ai_response(raw)
    # Einmal auflösen: Plan und Prüfung müssen denselben Fragebogen sehen,
    # sonst prüfte die Warnung gegen eine andere Disziplin als die, an der
    # der Plan später hängt. Und geprüft, weil `request_id` bis hierher aus dem
    # Anfragekörper kommt.
    fragebogen = gepruefter_fragebogen(db, user_id, request_id)
    plan = build_plan(body, user_id, fragebogen)
    disziplin, zusatztraining = vorgaben_des_fragebogens(db, user_id, fragebogen)
    warnings = validate_coverage(body, days, disziplin, zusatztraining)

    # Nur ein Plan ist gleichzeitig aktiv.
    db.query(Plan).filter(Plan.user_id == user_id, Plan.is_active.is_(True)).update(
        {"is_active": False}
    )

    db.add(plan)
    db.commit()
    db.refresh(plan)

    # Wer mitten im Block neu plant, lässt einen stillgelegten zurück. Trug er
    # nichts, verschwindet er hier; hängt Garmin daran, erst nach dem Aufräumen
    # dort (siehe plan_aufraeumen).
    # Nur was ganz in der Zukunft liegt: Das Training von heute steht
    # womöglich schon auf der Uhr, aber noch nicht in dieser Datenbank. Den
    # Rest räumt der nächste Garmin-Lauf, nach dem Import der Aktivitäten.
    plan_aufraeumen.raeume_abgeloeste_plaene(db, user_id, nur_zukunft=True)

    # Und ab auf die Uhr — als Job, der auch den abgelösten Block aus dem
    # Kalender nimmt. Die Antwort wartet nicht darauf: Ein halbes Dutzend
    # Einheiten kostet eine halbe Minute gegen eine fremde Gegenstelle, und der
    # Plan steht ja bereits.
    #
    # Erst hier importiert: `garmin.automatik` zieht den Runner und damit die
    # halbe Garmin-Anbindung nach, die beim bloßen Parsen einer Antwort nichts
    # zu suchen hat.
    from .garmin import automatik

    job_id, hinweis = automatik.starte_uebertragung_fuer_neuen_plan(db, user_id, plan)

    return Uebernahme(
        plan=plan,
        warnings=warnings,
        garmin_job_id=job_id,
        garmin_hinweis=hinweis,
    )


# --------------------------------------------------------------------------
# Eine einzelne Einheit anpassen
#
# Derselbe Zuschnitt wie beim Block: ein toleranter Parser, der Codefences und
# Begleittext abfängt, und eine Übernahme, die beide Auslöser bedienen —
# eingefügter Text und die Antwort, die der Server selbst geholt hat.
# --------------------------------------------------------------------------

# Schlüssel, unter denen Modelle die eine Einheit ablegen. Die App verlangt
# `einheit`; „session" kostet nichts und fängt den naheliegenden englischen
# Rückfall ab.
_EINHEIT_SCHLUESSEL = ("einheit", "session")


def parse_einheit_antwort(raw: str) -> AIEinheitBody:
    """Liest die Antwort auf eine Einzelanpassung.

    Toleriert dieselben drei Formen wie der Blockparser: die verlangte Hülle,
    ein anders benanntes Feld darum herum und das nackte Einheitenobjekt. Ein
    Plan im Blockformat wird dagegen **abgelehnt** statt aufgefaltet — er wäre
    die Antwort auf eine andere Frage, und die erste Einheit daraus zu nehmen
    hieße raten, welche gemeint ist.
    """
    return _einheit_aus_objekten(_gelesene_objekte(raw))


def einheit_aus_objekt(daten: dict[str, Any]) -> AIEinheitBody:
    """Der Objekteinstieg für die Einzelanpassung — siehe `plan_aus_objekt`."""
    return _einheit_aus_objekten([daten])


def _einheit_aus_objekten(objekte: list[dict[str, Any]]) -> AIEinheitBody:
    # Dieselbe Wahl nach der Form wie beim Block: Trägt der Text mehrere
    # Objekte, gilt das mit der Einheit darin und nicht das erste.
    data: Any = next(
        (
            d
            for d in objekte
            if any(isinstance(d.get(s), dict) for s in _EINHEIT_SCHLUESSEL)
            or "sport" in d
        ),
        objekte[0],
    )

    if "plan" in data or "days" in data or "weeks" in data:
        raise PlanImportError(
            "Die Antwort enthält einen ganzen Trainingsblock, erwartet war eine "
            "einzelne Einheit. Bitte den Text für die Anpassung kopieren — er "
            "verlangt ausdrücklich nur die eine Einheit."
        )

    for schluessel in _EINHEIT_SCHLUESSEL:
        if isinstance(data.get(schluessel), dict):
            data = {**data, "einheit": data[schluessel]}
            break
    else:
        # Das flache Objekt: Die Einheit steht ohne Hülle da. Erkennbar an
        # `sport` — ohne das Feld wäre es ohnehin keine Einheit.
        if "sport" not in data:
            raise PlanImportError(
                "In der Antwort war keine Einheit zu finden. Erwartet wird ein "
                'Objekt mit dem Schlüssel "einheit".'
            )
        data = {"einheit": data}

    try:
        gelesen = AIEinheitImport.model_validate(data)
    except ValidationError as exc:
        raise PlanImportError(_readable_validation_error(exc)) from exc

    return AIEinheitBody(einheit=gelesen.einheit, begruendung=gelesen.begruendung)


def pruefe_einheit(body: AIEinheitBody) -> list[str]:
    """Nicht-blockierende Hinweise zur angepassten Einheit.

    Dieselbe Linie wie bei `validate_coverage()`: Was sich melden lässt, wird
    gemeldet; abgelehnt wird nichts. Eine Einheit ohne Dauer ist brauchbar, ein
    abgelehnter Lauf gegen die KI dagegen teuer — die Antwort wird nirgends
    gespeichert, er wäre also ganz verloren.
    """
    warnings: list[str] = []
    einheit = body.einheit

    if einheit.verworfene_zielwerte:
        warnings.append(
            "Unbrauchbare Steuerungsgröße verworfen "
            f"({', '.join(einheit.verworfene_zielwerte)}). Der Wert fehlt an "
            "dieser Einheit; ein verworfener Zielpuls heißt außerdem, dass sie "
            "ohne Herzfrequenzkorridor auf die Uhr geht."
        )

    if einheit.sport != "rest" and not einheit.steps:
        warnings.append(
            "Die angepasste Einheit kam ohne Schrittliste. Sie wird für die "
            "Uhr aus ihrem Aufbautext zerlegt."
        )

    if einheit.verworfene_masse:
        warnings.append(
            "Mehrfach bemaßte Schritte bereinigt "
            f"({', '.join(einheit.verworfene_masse)}). Die Uhr schaltet nach "
            "genau einem Maß weiter; der überzählige Wert ist weggefallen."
        )

    if einheit.verschachtelte_gruppen:
        warnings.append(
            "Die Einheit kam mit einer Serie in einer Serie. Garmin kennt "
            "keine Gruppe in einer Gruppe — die innere wird auf der Uhr "
            "ausgeschrieben."
        )

    if (korrektur := _dauer_korrigiert(einheit)) is not None:
        warnings.append(
            f"Dauer aus dem Bauplan neu gerechnet: {korrektur}. Übernommen "
            "wurde der gerechnete Wert — auf der Uhr gilt ohnehin der Bauplan."
        )

    if (knapp := _dauer_zu_knapp(einheit)) is not None:
        warnings.append(
            f"Dauer und Bauplan passen nicht zusammen: {knapp}. Hier ließ sich "
            "nichts nachrechnen, die Angabe der KI bleibt stehen."
        )

    # Ohne Dauer hat das Workout auf der Uhr keinen Anhaltspunkt für seine
    # Länge — `garmin/workouts.py` baut den Ersatzschritt über `duration_min`.
    if einheit.sport != "rest" and not einheit.duration_min:
        warnings.append(
            "Die angepasste Einheit nennt keine Dauer. Auf der Uhr steht sie "
            "dann ohne Zeitvorgabe."
        )

    return warnings


def _schreibe_einheit(
    session: PlanSession,
    neu: AISessionIn,
    wunsch: str | None,
    begruendung: str | None,
) -> None:
    """Die neue Fassung in eine bestehende Planeinheit — für beide Anpassungen.

    Steht für sich, weil zwei Aufgaben dieselbe Zeile überschreiben: die
    Einzelanpassung auf Wunsch und die Tagesanpassung nach dem Abgleich. Zwei
    Kopien liefen mit dem ersten neuen Feld auseinander, und dann trüge dieselbe
    Einheit je nach Weg einen anderen Aufbau.

    Nicht angetastet werden Datum, Reihenfolge und Zugehörigkeit: Der Tag steht
    fest, und die Einheit bleibt an ihrem Platz im Block.
    """
    session.sport = neu.sport
    session.session_type = neu.type
    session.title = neu.title
    session.description = neu.description
    session.structure = neu.structure
    session.purpose = neu.purpose
    # Dieselbe Rechnung wie beim Block (siehe `_gerechnete_dauer`).
    session.duration_min = _gerechnete_dauer(neu) or neu.duration_min
    session.distance_km = neu.distance_km
    session.intensity_zone = neu.intensity_zone
    session.target_hr_low = neu.target_hr_low
    session.target_hr_high = neu.target_hr_high
    session.target_pace = neu.target_pace
    session.target_power = neu.target_power
    session.rpe_target = neu.rpe_target
    session.swim_location = neu.swim_location
    session.bike_location = neu.bike_location
    session.steps_json = _schritte_json(neu)
    session.angepasst_am = jetzt_utc()
    # `None` bei der Tagesanpassung, und das ist der Unterschied, an dem die
    # Ansicht die beiden Fälle auseinanderhält: Dort gab es keinen Wunsch,
    # sondern Messwerte. „Auf den Wunsch ‚automatisch angepasst'" wäre ein Satz,
    # der sich selbst widerspricht.
    session.anpassungswunsch = wunsch
    # Der Grund bleibt an der Einheit stehen. Bei der Anpassung von Hand steht
    # er auch in der Meldung des Laufs, und das reichte, solange der Athlet
    # daneben stand; die Tagesanpassung läuft dagegen morgens ab, und ihre
    # Meldung liest niemand.
    session.anpassungsbegruendung = begruendung


@dataclass(slots=True)
class EinheitUebernahme:
    session: PlanSession
    begruendung: str | None = None
    warnings: list[str] = field(default_factory=list)
    # Ob die Einheit danach überhaupt noch auf die Uhr gehört. Ein „rest" als
    # Antwort heißt: Sie fällt aus, und was von ihr in Garmin steht, muss weg.
    war_uebertragbar: bool = False


def uebernimm_einheit(
    db: Session,
    session: PlanSession,
    raw: str,
    wunsch: str,
    struktur: dict[str, Any] | None = None,
) -> EinheitUebernahme:
    """Schreibt die angepasste Fassung in die bestehende Planeinheit.

    **Dieselbe Zeile, nicht eine neue.** Daran hängt der ganze Weg zurück auf
    die Uhr: `GarminWorkoutLink` zeigt auf `plan_session_id`, und eine neue
    Einheit ließe die alte samt ihrem Termin im fremden Kalender zurück. So
    findet die Übertragung danach ihre Zuordnung wieder, ersetzt den Inhalt der
    Pool-Vorlage und behält den Termin.

    Nicht angetastet werden Datum, Reihenfolge und Zugehörigkeit: Der Tag steht
    fest (das sagt auch der Prompt), und die Einheit bleibt an ihrem Platz im
    Block.

    Wirft `PlanImportError`, wenn die Antwort nicht zu lesen ist; dann bleibt
    die Datenbank unberührt.
    """
    body = (
        einheit_aus_objekt(struktur)
        if struktur is not None
        else parse_einheit_antwort(raw)
    )
    warnings = pruefe_einheit(body)
    neu = body.einheit

    _schreibe_einheit(session, neu, wunsch, body.begruendung)

    # `Plan.raw_json` bleibt bewusst, wie es war: Dort steht die KI-Antwort im
    # Original, also der Block, wie er einmal geplant wurde. Die Anpassung
    # dorthin zu schreiben machte aus dem Original ein Gemisch aus zwei
    # Antworten — was gilt, steht ohnehin in den Einheiten.
    db.commit()
    db.refresh(session)

    return EinheitUebernahme(
        session=session,
        begruendung=body.begruendung,
        warnings=warnings,
        war_uebertragbar=neu.sport != "rest",
    )


# --------------------------------------------------------------------------
# Den heutigen Tag anpassen
#
# Derselbe Zuschnitt wie bei der Einzelanpassung, nur über mehrere Zeilen. Der
# Unterschied, der alles trägt: Zugeordnet wird über die `nr` aus dem Payload
# und **nicht** über die Position in der Liste. Über die Position zuzuordnen
# wäre still falsch, sobald das Modell eine Einheit auslässt — dann landete die
# Anpassung der einen auf der anderen, ohne dass irgendwo etwas fehlschlüge.
# --------------------------------------------------------------------------


@dataclass(slots=True)
class TagesformUebernahme:
    geaendert: list[PlanSession] = field(default_factory=list)
    unveraendert: list[PlanSession] = field(default_factory=list)
    begruendung: str | None = None
    warnings: list[str] = field(default_factory=list)
    # Einheiten, zu denen eine Änderung angekündigt war, aber keine Fassung
    # dabei. Sie bleiben stehen — aber der Aufrufer muss es sagen können: Bis
    # hierher verschwand genau dieser Fall in einer Warnung, die niemand las,
    # und der Athlet sah einen Tag, der „bleibt, wie er geplant war", obwohl
    # die KI ihn ändern wollte.
    unvollstaendig: list[int] = field(default_factory=list)


def parse_tagesform_antwort(raw: str) -> AITagesformBody:
    """Liest die Antwort auf eine Tagesanpassung."""
    return _tagesform_aus_objekten(_gelesene_objekte(raw))


def tagesform_aus_objekt(daten: dict[str, Any]) -> AITagesformBody:
    """Der Objekteinstieg für die Tagesanpassung — siehe `plan_aus_objekt`."""
    return _tagesform_aus_objekten([daten])


def _tagesform_aus_objekten(objekte: list[dict[str, Any]]) -> AITagesformBody:
    # Wie beim Block und bei der Einheit: Trägt der Text mehrere Objekte, gilt
    # das mit der Liste darin und nicht das erste.
    data: Any = next(
        (d for d in objekte if isinstance(d.get("einheiten"), list)),
        objekte[0],
    )

    if "plan" in data or "days" in data or "weeks" in data:
        raise PlanImportError(
            "Die Antwort enthält einen ganzen Trainingsblock, erwartet war die "
            "Anpassung der heutigen Einheiten."
        )

    if not isinstance(data.get("einheiten"), list):
        raise PlanImportError(
            "In der Antwort war keine Einheitenliste zu finden. Erwartet wird "
            'ein Objekt mit dem Schlüssel "einheiten".'
        )

    try:
        gelesen = AITagesformImport.model_validate(data)
    except ValidationError as exc:
        raise PlanImportError(_readable_validation_error(exc)) from exc

    return AITagesformBody(
        einheiten=gelesen.einheiten, begruendung=gelesen.begruendung
    )


def pruefe_tagesform(
    body: AITagesformBody, sessions: Sequence[PlanSession]
) -> list[str]:
    """Nicht-blockierende Hinweise zur Tagesanpassung.

    Dieselbe Linie wie überall im Import: Was sich melden lässt, wird gemeldet;
    abgelehnt wird nichts. Eine Antwort, die eine von drei Einheiten vergisst,
    hat immer noch zwei richtig — sie deswegen ganz zu verwerfen wäre die
    teuerste denkbare Reaktion auf eine Formalie.
    """
    warnings: list[str] = []
    gueltig = set(range(1, len(sessions) + 1))
    genannt = [e.nr for e in body.einheiten]

    for nr in sorted(set(genannt) - gueltig):
        warnings.append(
            f"Die Antwort nennt eine Einheit {nr}, die es heute nicht gibt. "
            "Der Eintrag wurde übergangen."
        )
    for nr in sorted(gueltig - set(genannt)):
        warnings.append(
            f"Zur Einheit {nr} stand nichts in der Antwort. Sie bleibt, wie sie "
            "geplant war."
        )
    for nr in sorted({nr for nr in genannt if genannt.count(nr) > 1}):
        warnings.append(
            f"Die Einheit {nr} kam mehrfach in der Antwort vor. Es gilt der "
            "erste Eintrag."
        )

    for eintrag in body.einheiten:
        if not eintrag.unveraendert and eintrag.einheit is None:
            warnings.append(
                f"Zur Einheit {eintrag.nr} war eine Änderung angekündigt, aber "
                "keine neue Fassung dabei. Sie bleibt, wie sie geplant war."
            )
        # Jede Einheit einzeln durch dieselbe Prüfung wie bei der
        # Einzelanpassung: Ein fehlender Bauplan ist hier derselbe Mangel.
        if eintrag.einheit is not None:
            warnings += [
                f"Einheit {eintrag.nr}: {hinweis}"
                for hinweis in pruefe_einheit(
                    AIEinheitBody(einheit=eintrag.einheit)
                )
            ]

    return warnings


def uebernimm_tagesform(
    db: Session,
    sessions: Sequence[PlanSession],
    raw: str,
    struktur: dict[str, Any] | None = None,
    *,
    streng: bool = False,
) -> TagesformUebernahme:
    """Schreibt die angepassten Fassungen in die bestehenden Planeinheiten.

    **Dieselben Zeilen, nicht neue** — aus demselben Grund wie bei der
    Einzelanpassung: `GarminWorkoutLink` zeigt auf `plan_session_id`, und eine
    neue Einheit ließe die alte samt ihrem Termin im fremden Kalender zurück.

    Was nicht zugeordnet werden kann, bleibt stehen. Die Begründung gilt für
    den ganzen Tag und wird an jede angefasste Einheit geschrieben: Der Athlet
    öffnet eine einzelne Einheit, nicht den Tag.

    `streng` verlangt zu jeder angekündigten Änderung auch die Fassung dazu und
    wirft sonst — **bevor irgendetwas geschrieben ist**. Das Strukturschema
    kann das nicht erzwingen: `einheit` steht dort bewusst nicht in `required`,
    weil sie bei `unveraendert: true` fehlen *soll*, und ein `oneOf` darüber
    wäre genau die Fessel, an der eine sonst brauchbare Antwort stürbe (siehe
    `docs/ki-und-prompt.md`). Der Anspruch gehört also hierher, und der Wurf
    ist die Eintrittskarte in den bestehenden Reparaturlauf.
    """
    body = (
        tagesform_aus_objekt(struktur)
        if struktur is not None
        else parse_tagesform_antwort(raw)
    )
    warnings = pruefe_tagesform(body, sessions)

    # Vor der Schreibschleife: Ein Wurf mitten im Schreiben ließe die Hälfte
    # der Einheiten geändert zurück, und der Reparaturlauf schriebe sie danach
    # ein zweites Mal.
    unvollstaendig = [
        eintrag.nr
        for eintrag in body.einheiten
        if not eintrag.unveraendert
        and eintrag.einheit is None
        and 1 <= eintrag.nr <= len(sessions)
    ]
    if streng and unvollstaendig:
        nummern = ", ".join(str(nr) for nr in unvollstaendig)
        raise PlanImportError(
            f"Zu Einheit {nummern} steht `unveraendert: false`, aber keine "
            '"einheit" mit der neuen Fassung. Entweder `unveraendert: true` '
            "setzen oder die vollständige Einheit mitliefern."
        )

    ergebnis = TagesformUebernahme(
        begruendung=body.begruendung,
        warnings=warnings,
        unvollstaendig=unvollstaendig,
    )
    erledigt: set[int] = set()

    for eintrag in body.einheiten:
        if not 1 <= eintrag.nr <= len(sessions) or eintrag.nr in erledigt:
            continue
        erledigt.add(eintrag.nr)
        session = sessions[eintrag.nr - 1]

        if eintrag.unveraendert or eintrag.einheit is None:
            ergebnis.unveraendert.append(session)
            continue

        _schreibe_einheit(session, eintrag.einheit, None, body.begruendung)
        ergebnis.geaendert.append(session)

    # Was in der Antwort gar nicht vorkam, bleibt geplant — und zählt als
    # unverändert, damit der Aufrufer den Tag vollständig beschreiben kann.
    ergebnis.unveraendert += [
        session
        for nr, session in enumerate(sessions, start=1)
        if nr not in erledigt
    ]

    db.commit()
    for session in ergebnis.geaendert:
        db.refresh(session)

    return ergebnis
