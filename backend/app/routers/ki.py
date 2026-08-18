"""Die KI plant den nächsten Block — Knopf, Einstellungen und Fortschritt."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from ..config import KI_EFFORT, KI_MODELL
from ..deps import CurrentUser, DbSession
from ..ki.client import ist_angemeldet
from ..ki.runner import EINHEIT, ENDZUSTAENDE, runner
from ..models import KiJob, KiSettings, TrainingRequest
from ..schemas import (
    KiEinheitIn,
    KiJobOut,
    KiPlanenIn,
    KiSettingsIn,
    KiSettingsOut,
    KiStatusOut,
)
from .plans import anpassbare_einheit

router = APIRouter(prefix="/api/ki", tags=["ki"])


def _einstellungen(db, user_id: int) -> KiSettings:
    """Die Einstellungen des Nutzers, notfalls frisch angelegt."""
    einstellungen = db.scalar(select(KiSettings).where(KiSettings.user_id == user_id))
    if einstellungen is None:
        einstellungen = KiSettings(user_id=user_id)
        db.add(einstellungen)
        db.commit()
        db.refresh(einstellungen)
    return einstellungen


def _job_oder_fehler(db, job_id: int, user_id: int) -> KiJob:
    eintrag = db.get(KiJob, job_id)
    if eintrag is None or eintrag.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Planungslauf nicht gefunden.")
    return eintrag


@router.get("/status", response_model=KiStatusOut)
def zustand(user: CurrentUser, db: DbSession) -> KiStatusOut:
    einstellungen = _einstellungen(db, user.id)

    aktiv_id = runner.laeuft_gerade()
    aktiver = db.get(KiJob, aktiv_id) if aktiv_id else None
    if aktiver is not None and aktiver.user_id != user.id:
        aktiver = None

    letzter = (
        db.query(KiJob)
        .filter(KiJob.user_id == user.id)
        .order_by(KiJob.started_at.desc())
        .first()
    )

    return KiStatusOut(
        verfuegbar=ist_angemeldet(),
        modell=einstellungen.model or KI_MODELL,
        effort=einstellungen.effort or KI_EFFORT,
        einstellungen=KiSettingsOut.model_validate(einstellungen),
        aktiver_job=KiJobOut.model_validate(aktiver) if aktiver else None,
        letzter_job=KiJobOut.model_validate(letzter) if letzter else None,
    )


@router.put("/settings", response_model=KiSettingsOut)
def aendere_einstellungen(
    data: KiSettingsIn, user: CurrentUser, db: DbSession
) -> KiSettings:
    einstellungen = _einstellungen(db, user.id)
    # Teil-Update wie beim Profil: Was nicht geschickt wurde, bleibt stehen.
    for feld, wert in data.model_dump(exclude_unset=True).items():
        if wert is not None:
            setattr(einstellungen, feld, wert)
    db.commit()
    db.refresh(einstellungen)
    return einstellungen


@router.get("/jobs/{job_id}", response_model=KiJobOut)
def job(job_id: int, user: CurrentUser, db: DbSession) -> KiJob:
    return _job_oder_fehler(db, job_id, user.id)


@router.post("/jobs/{job_id}/abbrechen", response_model=KiJobOut)
def brich_ab(job_id: int, user: CurrentUser, db: DbSession) -> KiJob:
    eintrag = _job_oder_fehler(db, job_id, user.id)
    if eintrag.state in ENDZUSTAENDE:
        return eintrag
    runner.brich_ab(job_id)
    return eintrag


@router.post("/planen", response_model=KiJobOut, status_code=status.HTTP_202_ACCEPTED)
def planen(data: KiPlanenIn, user: CurrentUser, db: DbSession) -> KiJob:
    """Stößt einen Planungslauf an — der Knopf neben dem Weg über die Zwischenablage."""
    _pruefe_startbar()

    if data.request_id is not None:
        fragebogen = db.get(TrainingRequest, data.request_id)
        if fragebogen is None or fragebogen.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Fragebogen nicht gefunden.")
    elif not db.query(TrainingRequest.id).filter(
        TrainingRequest.user_id == user.id
    ).first():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Es liegt noch kein ausgefüllter Fragebogen vor. Lege zuerst ein "
            "neues Training an.",
        )

    job_id = runner.starte(
        user.id,
        "manual",
        request_id=data.request_id,
        start_date=data.start_date,
        days=data.days,
    )
    return db.get(KiJob, job_id)


def _pruefe_startbar() -> None:
    """Die beiden Riegel, die vor jedem Lauf gelten.

    Der zweite ist bewusst ein Riegel und keine Warteschlange: Wer selbst
    drückt, kann warten und es gleich noch einmal versuchen — anders als beim
    automatisch angestoßenen Lauf, den niemand nachholen würde.
    """
    if not ist_angemeldet():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Es ist kein Claude-Zugang hinterlegt. Trage in den "
            "Add-on-Einstellungen ein mit `claude setup-token` erzeugtes "
            "Token ein.",
        )

    if runner.laeuft_gerade() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Es läuft bereits ein Lauf gegen die KI. Bitte warte, bis er "
            "fertig ist.",
        )


@router.post(
    "/einheit", response_model=KiJobOut, status_code=status.HTTP_202_ACCEPTED
)
def passe_einheit_an(data: KiEinheitIn, user: CurrentUser, db: DbSession) -> KiJob:
    """Lässt Claude genau eine Einheit des Plans nach einem Wunsch umschreiben.

    Derselbe Lauf wie beim Planen eines Blocks — eigener Thread, Fortschritt in
    der Datenbank, abbrechbar. Ein Anpassungslauf dauert kürzer als ein ganzer
    Block, aber immer noch zu lange für eine offene HTTP-Antwort hinter dem
    Ingress.

    Kein Fragebogen nötig: Die Einheit steht in einem Block, der aus einem
    entstanden ist — der Export nimmt den des Plans.
    """
    _pruefe_startbar()
    session = anpassbare_einheit(db, data.plan_session_id, user.id)

    job_id = runner.starte(
        user.id,
        EINHEIT,
        plan_session_id=session.id,
        wunsch=data.wunsch,
    )
    return db.get(KiJob, job_id)
