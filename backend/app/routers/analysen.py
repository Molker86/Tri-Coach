"""Gespeicherte Trainingsanalysen — Zwischenablage-Weg, Liste, Detail, Löschen.

Angestoßen wird ein KI-Lauf im ki-Router (`POST /api/ki/analysieren`), weil
dort `_pruefe_startbar()` und der Runner stehen. Hier liegt der Rest: der Weg
über die Zwischenablage (`/export` + `/import`, das Muster von Plan und
Ernährung) und die Ablage — nachlesen und löschen, mehr kann man mit einem
fertigen Bericht nicht tun (bewusst kein Nachbearbeiten, siehe
docs/analyse.md).
"""

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query, status

from .. import ai_export
from ..analyse_import import lese_analyse_antwort
from ..deps import CurrentUser, DbSession
from ..garmin import fitdaten
from ..garmin.errors import GarminFehler
from ..garmin.verbindung import als_http, garmin_sitzung
from ..models import TrainingsAnalyse
from ..plan_import import PlanImportError
from ..schemas import AnalyseDetailOut, AnalyseImportIn, AnalyseOut, ExportOut

router = APIRouter(prefix="/api/analysen", tags=["analysen"])


def _analyse_oder_fehler(db, analyse_id: int, user_id: int) -> TrainingsAnalyse:
    eintrag = db.get(TrainingsAnalyse, analyse_id)
    if eintrag is None or eintrag.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analyse nicht gefunden.")
    return eintrag


# Vor `/{analyse_id}` deklariert, sonst versuchte FastAPI, „export" als
# Kennung zu lesen.
@router.get("/export", response_model=ExportOut)
def export_fuer_ki(
    user: CurrentUser,
    db: DbSession,
    tage: int = Query(1, ge=1, le=7),
) -> ExportOut:
    """Prompt samt Original-Daten zum Kopieren in eine beliebige KI.

    Anders als die Exporte von Plan und Ernährung kein reiner Datenbankgriff:
    Die Original-Aufzeichnungen kommen live von Garmin, der Aufruf dauert also
    ein paar Sekunden je Aktivität. Ein leerer Zeitraum ist eine klare Absage
    statt eines leeren Prompts — dieselbe Linie wie der Frühausstieg des Laufs.
    """
    heute = date.today()
    von = heute - timedelta(days=tage - 1)
    try:
        with garmin_sitzung(db, user.id) as api:
            aktivitaeten = fitdaten.hole_aktivitaeten(api, von, heute)
    except GarminFehler as exc:
        raise als_http(exc) from exc

    if not aktivitaeten:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Im Zeitraum {von.isoformat()} bis {heute.isoformat()} liegen "
            "keine Aktivitäten — es gibt nichts auszuwerten.",
        )

    export = ai_export.erzeuge_analyse_export(
        db,
        user,
        aktivitaeten=[a.als_dict() for a in aktivitaeten],
        von=von,
        bis=heute,
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

    Der Zeitraum wird beim Einfügen gerechnet, nicht beim Export — dieselbe
    Lesart wie beim Start eines Laufs, und die einzige, die ohne gemerkten
    Zustand auskommt. `model_used` bleibt leer: Welche KI geantwortet hat,
    weiß beim Handweg niemand.
    """
    try:
        daten = lese_analyse_antwort(data.raw)
    except PlanImportError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
        ) from exc

    heute = date.today()
    analyse = TrainingsAnalyse(
        user_id=user.id,
        zeitraum_von=heute - timedelta(days=data.tage - 1),
        zeitraum_bis=heute,
        aktivitaeten_anzahl=data.aktivitaeten_anzahl or 0,
        kurzfazit=daten["kurzfazit"],
        bericht_html=daten["bericht_html"],
    )
    db.add(analyse)
    db.commit()
    db.refresh(analyse)
    return analyse


@router.get("", response_model=list[AnalyseOut])
def liste(user: CurrentUser, db: DbSession) -> list[TrainingsAnalyse]:
    """Alle Analysen des Kontos, jüngste zuerst — kompakt, ohne den Bericht."""
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
