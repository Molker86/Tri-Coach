from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import AfterValidator
from sqlalchemy.orm import selectinload

from .. import ai_export, plan_import
from ..deps import CurrentUser, DbSession
from ..garmin import uebertragung
from ..garmin.errors import GarminFehler, GarminNichtVerbunden
from ..garmin.verbindung import als_http, garmin_sitzung
from ..garmin import automatik
from ..models import (
    GarminWorkoutLink,
    Plan,
    PlanSession,
    SessionLog,
)
from ..schemas import (
    WUNSCH_MAX,
    EinheitAnpassenIn,
    EinheitAnpassungOut,
    ExportOut,
    PlanDeleteOut,
    PlanImportIn,
    PlanImportOut,
    PlanOut,
    PlanSessionOut,
    PlanSummaryOut,
    SessionLogOut,
    VerknuepfungIn,
    putze_wunsch,
)
from ..zeit import jetzt_utc

# Damit ein Training in der Auswahlliste genauso aussieht wie im Verlauf —
# samt errechnetem TRIMP. Zwei Wege, dieselbe Zeile zu bauen, liefen früher
# oder später auseinander.
from .logs import _to_out as log_zu_ausgabe

router = APIRouter(prefix="/api/plans", tags=["plans"])


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------


def _active_plan(db, user_id: int) -> Plan | None:
    return (
        db.query(Plan)
        .options(selectinload(Plan.sessions))
        .filter(Plan.user_id == user_id, Plan.is_active.is_(True))
        .order_by(Plan.created_at.desc())
        .first()
    )


def _owned_plan(db, plan_id: int, user_id: int) -> Plan:
    plan = (
        db.query(Plan)
        .options(selectinload(Plan.sessions))
        .filter(Plan.id == plan_id)
        .first()
    )
    if plan is None or plan.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan nicht gefunden.")
    return plan


def anpassbare_einheit(db, plan_session_id: int, user_id: int) -> PlanSession:
    """Die Einheit — sofern sie dem Nutzer gehört und sich noch ändern lässt.

    Öffentlich, weil der KI-Router dieselbe Prüfung braucht: Beide Wege in eine
    Anpassung (Knopf und eingefügte Antwort) müssen dieselben Grenzen ziehen,
    sonst ließe der eine zu, was der andere ablehnt.

    Zwei Grenzen, und beide sind inhaltlich:

    * **Vergangene Tage nicht.** „Nachträglich ändern" heißt: nach der Planung
      des Blocks, nicht nach dem Tag. Eine Einheit von gestern umzuschreiben
      änderte nichts mehr an dem, was stattgefunden hat — es verfälschte nur
      die Umsetzungsquote und das, was in Garmin liegt.
    * **Bereits absolvierte nicht.** Hängt ein Training daran, ist die Einheit
      Vergangenheit, auch wenn ihr Tag noch läuft.
    """
    session = db.get(PlanSession, plan_session_id)
    if session is None or session.plan.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Einheit nicht gefunden.")

    if session.date < date.today():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Diese Einheit liegt in der Vergangenheit und lässt sich nicht mehr "
            "anpassen. Für die kommenden Tage kannst du stattdessen neu planen.",
        )

    if db.query(SessionLog.id).filter(
        SessionLog.plan_session_id == session.id
    ).first():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Zu dieser Einheit ist bereits ein Training erfasst — sie lässt "
            "sich nicht mehr anpassen.",
        )

    return session


def _eigene_einheit(db, plan_session_id: int, user_id: int) -> PlanSession:
    """Eine Planeinheit des Nutzers — oder 404.

    Ohne inhaltliche Grenzen, anders als `anpassbare_einheit()`: Zugeordnet und
    gelöst wird gerade an vergangenen Einheiten, und dass eine schon ein
    Training trägt, ist für das Lösen die Voraussetzung.
    """
    session = db.get(PlanSession, plan_session_id)
    if session is None or session.plan.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Einheit nicht gefunden.")
    return session


def _to_plan_out(db, plan: Plan, user_id: int) -> PlanOut:
    logged_ids = {
        row[0]
        for row in db.query(SessionLog.plan_session_id)
        .filter(SessionLog.user_id == user_id, SessionLog.plan_session_id.isnot(None))
        .all()
    }

    sessions = sorted(plan.sessions, key=lambda s: (s.date, s.order_in_day))
    out = PlanOut.model_validate(plan)
    out.sessions = []
    for session in sessions:
        session_out = PlanSessionOut.model_validate(session)
        session_out.logged = session.id in logged_ids
        out.sessions.append(session_out)
    return out


# --------------------------------------------------------------------------
# KI-Export
# --------------------------------------------------------------------------


@router.get("/export", response_model=ExportOut)
def export_for_ai(
    user: CurrentUser,
    db: DbSession,
    request_id: int | None = Query(None),
    start_date: date | None = Query(None),
    days: int = Query(
        ai_export.PLAN_DAYS_DEFAULT,
        ge=ai_export.PLAN_DAYS_MIN,
        le=ai_export.PLAN_DAYS_MAX,
        description="Länge des geplanten Blocks in Tagen.",
    ),
) -> ExportOut:
    """Stellt Prompt + Datenpaket zum Kopieren in eine KI bereit."""
    try:
        export = ai_export.erzeuge_export(
            db, user, request_id=request_id, start_date=start_date, days=days
        )
    except ai_export.ExportFehler as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    return ExportOut(
        prompt=export.prompt, payload=export.payload, combined=export.prompt
    )


# --------------------------------------------------------------------------
# Import
# --------------------------------------------------------------------------


@router.post("/import", response_model=PlanImportOut, status_code=status.HTTP_201_CREATED)
def import_plan(data: PlanImportIn, user: CurrentUser, db: DbSession) -> PlanImportOut:
    try:
        ergebnis = plan_import.uebernimm_plan(
            db, user.id, data.raw, request_id=data.request_id, days=data.days
        )
    except plan_import.PlanImportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    return PlanImportOut(
        plan=_to_plan_out(db, ergebnis.plan, user.id),
        warnings=ergebnis.warnings,
        garmin_job_id=ergebnis.garmin_job_id,
        garmin_hinweis=ergebnis.garmin_hinweis,
    )


@router.post("/validate", response_model=PlanImportOut)
def validate_plan(data: PlanImportIn, user: CurrentUser, db: DbSession) -> PlanImportOut:
    """Prüft eine KI-Antwort, ohne sie zu speichern (Vorschau vor dem Import)."""
    try:
        body = plan_import.parse_ai_response(data.raw)
        # Derselbe geprüfte Fragebogen wie beim Import — die Vorschau darf
        # weder an einer fremden Kennung hängen noch gegen andere Vorgaben
        # prüfen als der Import gleich darauf.
        fragebogen = plan_import.gepruefter_fragebogen(db, user.id, data.request_id)
    except plan_import.PlanImportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    disziplin, zusatztraining = plan_import.vorgaben_des_fragebogens(
        db, user.id, fragebogen
    )
    preview = plan_import.build_plan(body, user.id, fragebogen)
    sessions = sorted(preview.sessions, key=lambda s: (s.date, s.order_in_day))

    return PlanImportOut(
        plan=PlanOut(
            id=0,
            title=preview.title,
            summary=preview.summary,
            coaching_notes=preview.coaching_notes,
            start_date=preview.start_date,
            end_date=preview.end_date,
            is_active=False,
            # Reine Vorschau (id=0) — landet nie in der Datenbank. Trotzdem
            # UTC: Seit die Zeitstempel der API ihre Zeitzone mitführen,
            # käme eine Ortszeit hier als UTC beschriftet heraus.
            created_at=jetzt_utc(),
            # Von Hand mitgezogen: Anders als `_to_plan_out` baut die Vorschau
            # `PlanOut` Feld für Feld, und das Feld hat eine Vorgabe — vergessen
            # käme es still als `null` heraus.
            request_id=fragebogen,
            sessions=[
                PlanSessionOut(
                    id=0,
                    date=s.date,
                    week_number=s.week_number,
                    order_in_day=s.order_in_day,
                    sport=s.sport,
                    session_type=s.session_type,
                    title=s.title,
                    description=s.description,
                    structure=s.structure,
                    purpose=s.purpose,
                    duration_min=s.duration_min,
                    distance_km=s.distance_km,
                    intensity_zone=s.intensity_zone,
                    target_hr_low=s.target_hr_low,
                    target_hr_high=s.target_hr_high,
                    target_pace=s.target_pace,
                    target_power=s.target_power,
                    rpe_target=s.rpe_target,
                )
                for s in sessions
            ],
        ),
        # Die Vorschau soll dieselben Hinweise zeigen wie der Import — sonst
        # taucht die Warnung erst auf, wenn der Block schon steht.
        warnings=plan_import.validate_coverage(
            body, data.days, disziplin, zusatztraining
        ),
    )


# --------------------------------------------------------------------------
# Eine einzelne Einheit anpassen
#
# Der Weg über die Zwischenablage, Gegenstück zu `POST /api/ki/einheit`. Beide
# benutzen dieselben zwei Funktionen (`ai_export.erzeuge_einheit_export` und
# `plan_import.uebernimm_einheit`) — der Handweg ist hier keine Notlösung,
# sondern die Rückfallebene für einen abgelaufenen Zugang, ein aufgebrauchtes
# Kontingent oder eine andere KI.
# --------------------------------------------------------------------------


@router.get("/sessions/{plan_session_id}/anpassung-export", response_model=ExportOut)
def einheit_anpassung_export(
    plan_session_id: int,
    user: CurrentUser,
    db: DbSession,
    # Dieselbe Prüfung wie am Anfragekörper (`EinheitAnpassenIn`): Ein Feld
    # voller Leerzeichen käme sonst als leere Aufgabe im Prompt an.
    wunsch: Annotated[
        str,
        Query(
            max_length=WUNSCH_MAX,
            description="Was an der Einheit anders werden soll, im Wortlaut.",
        ),
        AfterValidator(putze_wunsch),
    ],
) -> ExportOut:
    """Prompt + Datenpaket, um genau diese Einheit anpassen zu lassen."""
    session = anpassbare_einheit(db, plan_session_id, user.id)
    try:
        export = ai_export.erzeuge_einheit_export(db, user, session, wunsch)
    except ai_export.ExportFehler as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    return ExportOut(
        prompt=export.prompt, payload=export.payload, combined=export.prompt
    )


@router.post("/sessions/{plan_session_id}/anpassen", response_model=EinheitAnpassungOut)
def einheit_anpassen(
    plan_session_id: int,
    data: EinheitAnpassenIn,
    user: CurrentUser,
    db: DbSession,
) -> EinheitAnpassungOut:
    """Übernimmt die angepasste Einheit und bringt sie auf die Uhr."""
    session = anpassbare_einheit(db, plan_session_id, user.id)

    try:
        ergebnis = plan_import.uebernimm_einheit(db, session, data.raw, data.wunsch)
    except plan_import.PlanImportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    return _anpassung_antwort(db, user.id, ergebnis)


def _anpassung_antwort(db, user_id: int, ergebnis) -> EinheitAnpassungOut:
    """Die gemeinsame Antwort beider Wege — samt dem Gang nach Garmin.

    Der Gang nach Garmin steht **hier** und nicht in `uebernimm_einheit`: Das
    Übernehmen soll auch ohne verbundenes Konto vollständig sein, und der
    Import einer Antwort hat nichts mit dem Kalender einer Gegenstelle zu tun.
    Denselben Schnitt macht `plan_import.uebernimm_plan`, nur dass dort ein Job
    anläuft — für eine einzelne Einheit sind es zwei Anfragen.
    """
    garmin, hinweis = automatik.uebertrage_geaenderte_einheit(
        db, user_id, ergebnis.session
    )
    ausgabe = PlanSessionOut.model_validate(ergebnis.session)
    return EinheitAnpassungOut(
        session=ausgabe,
        begruendung=ergebnis.begruendung,
        warnings=ergebnis.warnings,
        garmin=garmin,
        garmin_hinweis=hinweis,
    )


@router.delete(
    "/sessions/{plan_session_id}/verknuepfung",
    status_code=status.HTTP_204_NO_CONTENT,
)
def verknuepfung_loesen(
    plan_session_id: int,
    user: CurrentUser,
    db: DbSession,
) -> None:
    """Nimmt einer Planeinheit das Training, das ihr zugeschrieben wurde.

    Die einzige Korrektur, die es an einer importierten Einheit gibt — und sie
    ändert nichts an ihr, sondern nur an der Behauptung, sie habe eine Vorgabe
    erfüllt. Das Training selbst bleibt vollständig in der Historie und zählt
    weiter in Wochenlast, sRPE, ACWR und Export; allein die Umsetzungsquote
    lässt es los.

    Nötig, weil die Zuordnung über die Workout-Kennung läuft
    (`garmin/matching.py`) und die Uhr sie auch dann setzt, wenn der Athlet die
    Vorlage nur zum Aufzeichnen gestartet und etwas ganz anderes gemacht hat.
    """
    session = _eigene_einheit(db, plan_session_id, user.id)

    log = (
        db.query(SessionLog)
        .filter(
            SessionLog.user_id == user.id,
            SessionLog.plan_session_id == session.id,
        )
        .first()
    )
    if log is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Zu dieser Einheit ist kein Training erfasst.",
        )

    log.plan_session_id = None
    log.zuordnung_manuell = True
    db.commit()


# Wie weit um den Plantag herum nach einem Training gesucht wird. Drei Tage,
# weil die Zuordnung über die Kennung selbst gar keinen Tagesbezug kennt (siehe
# `garmin/matching.py`) — die Spanne ist allein eine Bequemlichkeit für die
# Auswahlliste, keine Regel darüber, was zusammengehört.
ZUORDNUNG_FENSTER_TAGE = 3


@router.get(
    "/sessions/{plan_session_id}/zuordenbar",
    response_model=list[SessionLogOut],
)
def zuordenbare_trainings(
    plan_session_id: int,
    user: CurrentUser,
    db: DbSession,
) -> list[SessionLogOut]:
    """Die Trainings, die für diese Einheit in Frage kommen.

    Alles aus dem Fenster um den Plantag, was noch an keiner Einheit hängt —
    **ohne** Rücksicht auf die Sportart. Die Zuordnung über die Workout-Kennung
    fragt auch nicht danach, und die Uhr zeichnet eine Einheit gern einmal unter
    der falschen Sportart auf. Wer das hier filterte, versteckte genau den Fall,
    für den die Auswahl gebaut ist.
    """
    session = _eigene_einheit(db, plan_session_id, user.id)
    fenster = timedelta(days=ZUORDNUNG_FENSTER_TAGE)

    logs = (
        db.query(SessionLog)
        .filter(
            SessionLog.user_id == user.id,
            SessionLog.plan_session_id.is_(None),
            SessionLog.date >= session.date - fenster,
            SessionLog.date <= session.date + fenster,
        )
        .order_by(SessionLog.date.desc(), SessionLog.id.desc())
        .all()
    )
    return [log_zu_ausgabe(log, user.profile) for log in logs]


@router.post(
    "/sessions/{plan_session_id}/verknuepfung",
    status_code=status.HTTP_204_NO_CONTENT,
)
def verknuepfung_setzen(
    plan_session_id: int,
    data: VerknuepfungIn,
    user: CurrentUser,
    db: DbSession,
) -> None:
    """Schreibt einer Planeinheit ein bereits importiertes Training zu.

    Die Gegenprobe zu `verknuepfung_loesen` und aus demselben Grund nötig: Die
    Zuordnung entsteht allein aus der Workout-Kennung (`garmin/matching.py`),
    und die fehlt, sobald auf der Uhr ein älterer Kalendereintrag gestartet
    wurde oder Garmin das Aktivitätsdetail nicht herausrückte. Ohne diesen Weg
    bliebe eine tatsächlich absolvierte Einheit für immer als nicht umgesetzt
    stehen.

    Erfunden wird dabei nichts: Es wird ein Training benannt, das der Abgleich
    schon geholt hat. Garmin bleibt die einzige Quelle — hier wird nur die
    Behauptung gesetzt, dieses Training habe jene Vorgabe erfüllt.

    `zuordnung_manuell` hält den nächsten Abgleich davon ab, die Entscheidung
    wieder anzufassen. Es heißt nach wie vor „der Athlet hat entschieden", nur
    diesmal in die andere Richtung.
    """
    session = _eigene_einheit(db, plan_session_id, user.id)

    if session.sport == "rest":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Das ist ein Ruhetag — dazu gibt es nichts zuzuordnen.",
        )

    log = (
        db.query(SessionLog)
        .filter(SessionLog.id == data.log_id, SessionLog.user_id == user.id)
        .first()
    )
    if log is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Training nicht gefunden.")

    if log.plan_session_id == session.id:
        return  # Schon zugeordnet — kein Grund, das als Fehler zu melden.

    if log.plan_session_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Dieses Training zählt bereits für eine andere Einheit. Löse die "
            "Zuordnung dort zuerst.",
        )

    # `uq_log_plan_session` ließe ohnehin nur einen Log je Einheit zu; die
    # Prüfung steht hier, damit statt eines Datenbankfehlers ein Satz herauskommt.
    if (
        db.query(SessionLog.id)
        .filter(SessionLog.plan_session_id == session.id)
        .first()
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Zu dieser Einheit ist bereits ein Training erfasst.",
        )

    log.plan_session_id = session.id
    log.zuordnung_manuell = True
    db.commit()


# --------------------------------------------------------------------------
# Lesen und Verwalten
# --------------------------------------------------------------------------


@router.get("", response_model=list[PlanSummaryOut])
def list_plans(user: CurrentUser, db: DbSession) -> list[PlanSummaryOut]:
    plans = (
        db.query(Plan)
        .options(selectinload(Plan.sessions))
        .filter(Plan.user_id == user.id)
        .order_by(Plan.created_at.desc())
        .all()
    )
    result = []
    for plan in plans:
        summary = PlanSummaryOut.model_validate(plan)
        summary.session_count = len(plan.sessions)
        result.append(summary)
    return result


@router.get("/active", response_model=PlanOut | None)
def get_active_plan(user: CurrentUser, db: DbSession) -> PlanOut | None:
    plan = _active_plan(db, user.id)
    return _to_plan_out(db, plan, user.id) if plan else None


@router.get("/{plan_id}", response_model=PlanOut)
def get_plan(plan_id: int, user: CurrentUser, db: DbSession) -> PlanOut:
    return _to_plan_out(db, _owned_plan(db, plan_id, user.id), user.id)


@router.post("/{plan_id}/activate", response_model=PlanOut)
def activate_plan(plan_id: int, user: CurrentUser, db: DbSession) -> PlanOut:
    plan = _owned_plan(db, plan_id, user.id)
    db.query(Plan).filter(Plan.user_id == user.id).update({"is_active": False})
    plan.is_active = True
    db.commit()
    db.refresh(plan)
    return _to_plan_out(db, plan, user.id)


@router.delete("/{plan_id}", response_model=PlanDeleteOut)
def delete_plan(
    plan_id: int,
    user: CurrentUser,
    db: DbSession,
    garmin_uebergehen: bool = Query(
        False,
        description=(
            "Den Plan auch dann löschen, wenn seine Einheiten nicht aus Garmin "
            "genommen werden konnten. Sie bleiben dann dort stehen."
        ),
    ),
) -> PlanDeleteOut:
    plan = _owned_plan(db, plan_id, user.id)
    entfernt, fehler = _nimm_aus_garmin(db, user.id, plan, uebergehen=garmin_uebergehen)

    einheiten = [s.id for s in plan.sessions] or [-1]
    # Logs überleben den Plan — die Referenz wird gelöst, nicht der Verlauf.
    db.query(SessionLog).filter(
        SessionLog.plan_session_id.in_(einheiten)
    ).update({"plan_session_id": None}, synchronize_session=False)
    # Was oben nicht wegging, geht hier für immer verloren: Angefasst wird in
    # Garmin ausschließlich über `GarminWorkoutLink`. Deshalb bleibt nur der
    # ausdrücklich übergangene Fall übrig — der Kalender dieser App zeigt solche
    # Reste weiterhin zum Entfernen an.
    db.query(GarminWorkoutLink).filter(
        GarminWorkoutLink.plan_session_id.in_(einheiten)
    ).delete(synchronize_session=False)
    db.delete(plan)
    db.commit()

    return PlanDeleteOut(garmin_entfernt=entfernt, garmin_fehler=fehler)


def _nimm_aus_garmin(
    db, user_id: int, plan: Plan, *, uebergehen: bool
) -> tuple[int, list[str]]:
    """Räumt Termine des Plans aus Garmin — **vor** dem Löschen.

    Die Reihenfolge ist die ganze Pointe: In Garmin fasst diese App nur an, was
    in `GarminWorkoutLink` steht, und der stirbt mit der Planeinheit. Wer den
    Plan zuerst löschte, ließe seine Einheiten für immer im fremden Kalender
    stehen — und dort gälte dann eine Vorgabe weiter, die es in der App gar
    nicht mehr gibt.

    Anders als eine Übertragung läuft das hier **im Anfrage-Thread** statt als
    Job: Es sind zwei Anfragen je Einheit und höchstens eine Handvoll Einheiten
    (Vergangenes hat der letzte Abgleich schon geräumt), und ein Löschen, das
    erst später wirkt, wäre schwerer zu verstehen als eines, das ein paar
    Sekunden dauert.

    Scheitert der Zugang, wird **nicht** gelöscht: Ein Plan ist schnell noch
    einmal gelöscht, ein verwaister Termin im fremden Kalender nie mehr. Der
    Nutzer bekommt den Grund und kann mit `garmin_uebergehen` darauf bestehen.
    """
    if not uebertragung.links_zum_plan(db, plan) or uebergehen:
        return 0, []

    try:
        with garmin_sitzung(db, user_id) as api:
            ergebnis = uebertragung.entferne_plan(db, api, plan)
    except GarminNichtVerbunden:
        # Ohne Konto führt kein Weg mehr dorthin, und die Zuordnung ist ohnehin
        # wertlos. Das Löschen daran zu hindern, hülfe niemandem.
        return 0, []
    except GarminFehler as exc:
        antwort = als_http(exc)
        raise HTTPException(
            antwort.status_code,
            f"{antwort.detail} Der Plan wurde deshalb nicht gelöscht — seine "
            "Einheiten stünden sonst für immer im Garmin-Kalender.",
        ) from exc

    return ergebnis.entfernt, ergebnis.fehler
