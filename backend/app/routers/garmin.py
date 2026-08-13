"""Endpunkte der Garmin-Anbindung."""

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from ..crypto import verschluessle
from ..deps import CurrentUser, DbSession
from ..garmin.client import (
    erzeuge_client,
    hole_anmeldung,
    loese_mfa_ein,
    melde_an,
    merke_anmeldung,
    pruefe_anmeldeversuche,
    vergiss_anmeldeversuche,
    vergiss_anmeldung,
)
from ..garmin.errors import GarminFehler, GarminRateLimit
from ..garmin.runner import ENDZUSTAENDE, runner
from ..garmin.sync import standard_zeitraum
from ..models import GarminAccount, GarminSyncJob, SessionLog, WellnessDay
from ..zeit import als_utc, jetzt_utc, liegt_in_der_zukunft
from ..schemas import (
    GarminAccountOut,
    GarminBackfillIn,
    GarminConnectIn,
    GarminDubletteOut,
    GarminJobOut,
    GarminMfaIn,
    GarminSettingsIn,
    GarminStatusOut,
    WellnessDayOut,
)

router = APIRouter(prefix="/api/garmin", tags=["garmin"])

# Wie weit ein Backfill höchstens zurückreichen darf. Zwei Jahre sind großzügig;
# alles darüber wäre für die Planung wertlos und nur ein Sperr-Risiko.
MAX_BACKFILL_TAGE = 730


def _konto(db, user_id: int) -> GarminAccount | None:
    return db.scalar(select(GarminAccount).where(GarminAccount.user_id == user_id))


def _konto_oder_fehler(db, user_id: int) -> GarminAccount:
    konto = _konto(db, user_id)
    if konto is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Es ist kein Garmin-Konto verbunden. Bitte verbinde zuerst dein Konto.",
        )
    return konto


def _pruefe_startbar(db, konto: GarminAccount) -> None:
    """Alles, was einem neuen Lauf im Weg stehen kann."""
    if konto.status == "token_expired":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            konto.status_message
            or "Die Anmeldung bei Garmin ist abgelaufen. Bitte verbinde dein Konto erneut.",
        )

    if liegt_in_der_zukunft(konto.rate_limited_until):
        rest = als_utc(konto.rate_limited_until) - jetzt_utc()
        minuten = max(1, int(rest.total_seconds() // 60))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Garmin hat die Verbindung vorerst gesperrt. Bitte warte noch etwa "
            f"{minuten} Minuten — weitere Versuche verlängern die Sperre.",
        )

    if runner.laeuft_gerade() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Es läuft bereits ein Abgleich. Bitte warte, bis er fertig ist.",
        )


# --------------------------------------------------------------------------
# Verbinden
# --------------------------------------------------------------------------


@router.post("/connect")
def verbinde(data: GarminConnectIn, user: CurrentUser, db: DbSession) -> dict:
    """Erster Anmeldeschritt. Bei aktivem MFA folgt `/connect/mfa`."""
    try:
        pruefe_anmeldeversuche(data.email)
        api = erzeuge_client(data.email, data.password)
        mfa_noetig, token = melde_an(api)
    except GarminRateLimit as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, exc.meldung) from exc
    except GarminFehler as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, exc.meldung) from exc

    if mfa_noetig:
        pending_id = uuid.uuid4().hex
        merke_anmeldung(pending_id, api, user.id)
        return {
            "status": "mfa_erforderlich",
            "pending_id": pending_id,
            "hinweis": (
                "Garmin hat dir einen Bestätigungscode geschickt. "
                "Bitte gib ihn innerhalb der nächsten zehn Minuten ein."
            ),
        }

    _speichere_verbindung(db, user.id, data.email, token or "")
    vergiss_anmeldeversuche(data.email)
    return {"status": "verbunden"}


@router.post("/connect/mfa")
def verbinde_mfa(data: GarminMfaIn, user: CurrentUser, db: DbSession) -> dict:
    """Zweiter Anmeldeschritt mit dem Bestätigungscode."""
    api = hole_anmeldung(data.pending_id, user.id)
    if api is None:
        raise HTTPException(
            status.HTTP_410_GONE,
            "Der Anmeldevorgang ist abgelaufen. Bitte beginne von vorn.",
        )

    try:
        token = loese_mfa_ein(api, data.code)
    except GarminRateLimit as exc:
        vergiss_anmeldung(data.pending_id)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, exc.meldung) from exc
    except GarminFehler as exc:
        # Der Vorgang bleibt bewusst offen: Ein Tippfehler im Code soll nicht
        # bedeuten, dass Passwort und MFA komplett neu eingegeben werden müssen.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Der Code stimmt nicht. Bitte prüfe ihn und versuche es erneut.",
        ) from exc

    email = getattr(api, "username", "") or ""
    vergiss_anmeldung(data.pending_id)
    _speichere_verbindung(db, user.id, email, token)
    vergiss_anmeldeversuche(email)
    return {"status": "verbunden"}


def _speichere_verbindung(db, user_id: int, email: str, token: str) -> None:
    konto = _konto(db, user_id)
    if konto is None:
        konto = GarminAccount(user_id=user_id, email=email)
        db.add(konto)
    konto.email = email or konto.email
    konto.token_encrypted = verschluessle(token)
    konto.status = "connected"
    konto.status_message = None
    konto.rate_limited_until = None
    konto.connected_at = jetzt_utc()
    db.commit()


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
def trenne(user: CurrentUser, db: DbSession) -> None:
    """Löst die Verbindung. Importierte Daten bleiben erhalten."""
    konto = _konto(db, user.id)
    if konto is not None:
        db.delete(konto)
        db.commit()


@router.put("/settings", response_model=GarminAccountOut)
def aendere_einstellungen(
    data: GarminSettingsIn, user: CurrentUser, db: DbSession
) -> GarminAccount:
    konto = _konto_oder_fehler(db, user.id)
    for feld, wert in data.model_dump(exclude_unset=True).items():
        setattr(konto, feld, wert)
    db.commit()
    db.refresh(konto)
    return konto


# --------------------------------------------------------------------------
# Zustand
# --------------------------------------------------------------------------


@router.get("/status", response_model=GarminStatusOut)
def zustand(user: CurrentUser, db: DbSession) -> GarminStatusOut:
    konto = _konto(db, user.id)

    jobs = db.scalars(
        select(GarminSyncJob)
        .where(GarminSyncJob.user_id == user.id)
        .order_by(GarminSyncJob.id.desc())
        .limit(5)
    ).all()
    aktiv = next((j for j in jobs if j.state not in ENDZUSTAENDE), None)

    return GarminStatusOut(
        konto=GarminAccountOut.model_validate(konto) if konto else None,
        aktiver_job=GarminJobOut.model_validate(aktiv) if aktiv else None,
        letzter_job=GarminJobOut.model_validate(jobs[0]) if jobs else None,
        trainings_gesamt=db.scalar(
            select(func.count(SessionLog.id)).where(
                SessionLog.user_id == user.id, SessionLog.source == "garmin"
            )
        )
        or 0,
        fitness_tage_gesamt=db.scalar(
            select(func.count(WellnessDay.id)).where(WellnessDay.user_id == user.id)
        )
        or 0,
    )


@router.get("/jobs/{job_id}", response_model=GarminJobOut)
def job(job_id: int, user: CurrentUser, db: DbSession) -> GarminSyncJob:
    eintrag = db.get(GarminSyncJob, job_id)
    if eintrag is None or eintrag.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Abgleich nicht gefunden.")
    return eintrag


@router.post("/jobs/{job_id}/abbrechen", response_model=GarminJobOut)
def brich_ab(job_id: int, user: CurrentUser, db: DbSession) -> GarminSyncJob:
    eintrag = db.get(GarminSyncJob, job_id)
    if eintrag is None or eintrag.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Abgleich nicht gefunden.")
    if eintrag.state in ENDZUSTAENDE:
        return eintrag
    runner.brich_ab(job_id)
    return eintrag


# --------------------------------------------------------------------------
# Abgleich starten
# --------------------------------------------------------------------------


@router.post("/sync", response_model=GarminJobOut, status_code=status.HTTP_202_ACCEPTED)
def sync(user: CurrentUser, db: DbSession) -> GarminSyncJob:
    """Holt die jüngsten Daten nach — der Knopf für den Alltag."""
    konto = _konto_oder_fehler(db, user.id)
    _pruefe_startbar(db, konto)

    von, bis, tagesschleife = standard_zeitraum("incremental", date.today())
    job_id = runner.starte(user.id, "incremental", von, bis, tagesschleife)
    return db.get(GarminSyncJob, job_id)


@router.post(
    "/backfill", response_model=GarminJobOut, status_code=status.HTTP_202_ACCEPTED
)
def backfill(
    data: GarminBackfillIn, user: CurrentUser, db: DbSession
) -> GarminSyncJob:
    """Holt einen längeren Zeitraum — für den einmaligen Rückblick."""
    konto = _konto_oder_fehler(db, user.id)
    _pruefe_startbar(db, konto)

    heute = date.today()
    bis = min(data.bis or heute, heute)
    von = data.von or (heute - timedelta(days=365))
    if von > bis:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Das Startdatum liegt nach dem Enddatum.",
        )
    if (bis - von).days > MAX_BACKFILL_TAGE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Der Zeitraum darf höchstens zwei Jahre umfassen.",
        )

    # Bei `tagesschleife_voll` werden Trainingsreife, Trainingsstatus und Stress
    # für den ganzen Zeitraum geholt — vier Anfragen je Tag, entsprechend lange.
    tagesschleife = von if data.tagesschleife_voll else max(
        von, standard_zeitraum("backfill", heute, von)[2]
    )

    job_id = runner.starte(user.id, "backfill", von, bis, tagesschleife)
    return db.get(GarminSyncJob, job_id)


# --------------------------------------------------------------------------
# Daten
# --------------------------------------------------------------------------


@router.get("/wellness", response_model=list[WellnessDayOut])
def wellness(
    user: CurrentUser, db: DbSession, weeks: int = Query(4, ge=1, le=52)
) -> list[WellnessDay]:
    grenze = date.today() - timedelta(weeks=weeks)
    return db.scalars(
        select(WellnessDay)
        .where(WellnessDay.user_id == user.id, WellnessDay.date >= grenze)
        .order_by(WellnessDay.date.desc())
    ).all()


@router.get("/dubletten", response_model=list[GarminDubletteOut])
def dubletten(user: CurrentUser, db: DbSession) -> list[GarminDubletteOut]:
    """Manuelle Einträge, die es nun auch aus Garmin gibt.

    Wer vor der Anbindung von Hand nachgetragen hat, bekommt dieselben Einheiten
    ein zweites Mal — beide zählen dann in Wochenübersicht und Belastung. Sie
    automatisch zu löschen wäre übergriffig; hier werden sie nur benannt.
    """
    logs = db.scalars(
        select(SessionLog).where(SessionLog.user_id == user.id)
    ).all()

    manuell = [lg for lg in logs if lg.source != "garmin"]
    aus_garmin = [lg for lg in logs if lg.source == "garmin"]

    treffer: list[GarminDubletteOut] = []
    for eintrag in manuell:
        for gegenstueck in aus_garmin:
            if gegenstueck.date != eintrag.date or gegenstueck.sport != eintrag.sport:
                continue
            if not _dauer_aehnlich(eintrag.duration_min, gegenstueck.duration_min):
                continue
            treffer.append(
                GarminDubletteOut(
                    manual_log_id=eintrag.id,
                    garmin_log_id=gegenstueck.id,
                    date=eintrag.date,
                    sport=eintrag.sport,
                    manual_duration_min=eintrag.duration_min,
                    garmin_duration_min=gegenstueck.duration_min,
                )
            )
            break
    return treffer


def _dauer_aehnlich(a: int | None, b: int | None, toleranz: float = 0.15) -> bool:
    """Ohne Dauerangabe reichen Tag und Sportart als Verdacht."""
    if a is None or b is None:
        return True
    if a == 0 or b == 0:
        return a == b
    return abs(a - b) / max(a, b) <= toleranz
