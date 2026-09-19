"""Gespeicherte Trainingsanalysen — Zwischenablage-Weg, Liste, Detail, Löschen.

Angestoßen wird ein KI-Lauf im ki-Router (`POST /api/ki/analysieren`), weil
dort `_pruefe_startbar()` und der Runner stehen. Hier liegt der Rest: der Weg
über die Zwischenablage (`/export` + `/import`, das Muster von Plan und
Ernährung) und die Ablage — nachlesen und löschen, mehr kann man mit einem
fertigen Bericht nicht tun (bewusst kein Nachbearbeiten, siehe
docs/analyse.md).

Jede Analyse hängt an genau **einem** absolvierten Training
(`TrainingsAnalyse.session_log_id`). Die Liste trägt deshalb keine eigenen
Datums- und Sportangaben: Das Frontend heftet sie über die Kennung an die
Trainingszeilen, und die tragen beides schon.
"""

from fastapi import APIRouter, HTTPException, Query, status

from .. import ai_export
from ..analyse_import import lese_analyse_antwort
from ..deps import CurrentUser, DbSession
from ..garmin import fitdaten
from ..garmin.errors import GarminFehler
from ..garmin.verbindung import als_http, garmin_sitzung
from ..models import SessionLog, TrainingsAnalyse
from ..plan_import import PlanImportError
from ..schemas import AnalyseDetailOut, AnalyseImportIn, AnalyseOut, ExportOut
from ..zeit import jetzt_utc

router = APIRouter(prefix="/api/analysen", tags=["analysen"])


def _analyse_oder_fehler(db, analyse_id: int, user_id: int) -> TrainingsAnalyse:
    eintrag = db.get(TrainingsAnalyse, analyse_id)
    if eintrag is None or eintrag.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analyse nicht gefunden.")
    return eintrag


def _training_oder_fehler(db, session_log_id: int, user_id: int) -> SessionLog:
    log = db.get(SessionLog, session_log_id)
    if log is None or log.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Training nicht gefunden.")
    return log


def _aufzeichnung(db, user, log: SessionLog) -> list[dict]:
    """Die Original-Aufzeichnung des Trainings — oder nichts, mit Vermerk.

    Derselbe Weg und dieselbe Nachsicht wie im Runner (`_aufzeichnung`): Ohne
    Garmin-Kennung gab es nie eine Datei, und ein gescheiterter Download einer
    einzelnen Datei ist kein Grund, den Export zu verweigern — Garmins
    Listendaten stehen im Paket ohnehin. Nur ein Fehler an der Verbindung
    selbst wird zur HTTP-Antwort: Den soll der Athlet reparieren und nicht als
    halbblinden Prompt in eine KI kopieren.
    """
    if not log.garmin_activity_id:
        return []
    try:
        with garmin_sitzung(db, user.id) as api:
            try:
                return [
                    a.als_dict()
                    for a in fitdaten.hole_aktivitaet(api, log.garmin_activity_id)
                ]
            except GarminFehler:
                raise
            except Exception:  # noqa: BLE001 — eine Datei kippt den Export nicht
                return []
    except GarminFehler as exc:
        raise als_http(exc) from exc


# Vor `/{analyse_id}` deklariert, sonst versuchte FastAPI, „export" als
# Kennung zu lesen.
@router.get("/export", response_model=ExportOut)
def export_fuer_ki(
    user: CurrentUser,
    db: DbSession,
    session_log_id: int = Query(..., description="Das zu bewertende Training"),
) -> ExportOut:
    """Prompt samt Original-Daten zum Kopieren in eine beliebige KI.

    Anders als die Exporte von Plan und Ernährung kein reiner Datenbankgriff:
    Die Original-Aufzeichnung kommt live von Garmin, der Aufruf dauert also ein
    paar Sekunden. Ein leerer Zeitraum ist hier kein Fall mehr — es gibt immer
    genau ein Training, und ohne ladbare Aufzeichnung wird aus den Listendaten
    bewertet.
    """
    log = _training_oder_fehler(db, session_log_id, user.id)
    export = ai_export.erzeuge_analyse_export(
        db, user, log=log, aktivitaeten=_aufzeichnung(db, user, log)
    )
    return ExportOut(
        prompt=export.prompt, payload=export.payload, combined=export.prompt
    )


@router.post(
    "/import", response_model=AnalyseDetailOut, status_code=status.HTTP_201_CREATED
)
def importiere(
    data: AnalyseImportIn, user: CurrentUser, db: DbSession
) -> TrainingsAnalyse:
    """Übernimmt eine von Hand eingefügte KI-Antwort als Analyse.

    Ersetzt einen bestehenden Bericht zu demselben Training, statt einen
    zweiten danebenzustellen — dieselbe Regel wie beim Lauf über den Knopf.
    `model_used` bleibt leer: Welche KI geantwortet hat, weiß beim Handweg
    niemand.
    """
    log = _training_oder_fehler(db, data.session_log_id, user.id)
    try:
        daten = lese_analyse_antwort(data.raw)
    except PlanImportError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
        ) from exc

    analyse = log.analyse or TrainingsAnalyse(user_id=user.id, log=log)
    analyse.kurzfazit = daten["kurzfazit"]
    analyse.bericht_html = daten["bericht_html"]
    analyse.model_used = None
    # Ein ersetzter Bericht ist ein neuer: Bliebe das alte Datum stehen, stünde
    # an der Zeile „Analyse vom 12.09.", während der Text von heute ist.
    analyse.created_at = jetzt_utc()
    db.add(analyse)
    db.commit()
    db.refresh(analyse)
    return analyse


@router.get("", response_model=list[AnalyseOut])
def liste(user: CurrentUser, db: DbSession) -> list[TrainingsAnalyse]:
    """Alle Analysen des Kontos, jüngste zuerst — kompakt, ohne den Bericht.

    Ohne Fenster über die Wochen, anders als die Trainingsliste: Es sind wenige
    Zeilen ohne Bericht, und das Frontend braucht sie **vollständig**, um an
    jedem Training zu erkennen, ob es schon eine hat. Ein Fenster hieße, dass
    ein älteres Training fälschlich als unbewertet dastünde.
    """
    return (
        db.query(TrainingsAnalyse)
        .filter(TrainingsAnalyse.user_id == user.id)
        .order_by(TrainingsAnalyse.created_at.desc())
        .all()
    )


@router.get("/{analyse_id}", response_model=AnalyseDetailOut)
def detail(analyse_id: int, user: CurrentUser, db: DbSession) -> TrainingsAnalyse:
    return _analyse_oder_fehler(db, analyse_id, user.id)


@router.delete("/{analyse_id}", status_code=status.HTTP_204_NO_CONTENT)
def loesche(analyse_id: int, user: CurrentUser, db: DbSession) -> None:
    db.delete(_analyse_oder_fehler(db, analyse_id, user.id))
    db.commit()
