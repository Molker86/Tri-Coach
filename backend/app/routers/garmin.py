"""Endpunkte der Garmin-Anbindung."""

import uuid
from collections import Counter
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from ..crypto import verschluessle
from ..deps import CurrentUser, DbSession
from ..garmin import kalender as kalender_modul
from ..garmin import uebertragung, workouts
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
from ..garmin.verbindung import als_http, garmin_sitzung, nachsichtig
from ..models import (
    GarminAccount,
    GarminSyncJob,
    GarminWorkoutLink,
    GarminWorkoutPoolSlot,
    Plan,
    PlanSession,
    SessionLog,
    WellnessDay,
)
from ..zeit import als_utc, jetzt_utc, liegt_in_der_zukunft
from ..schemas import (
    GarminAccountOut,
    GarminBackfillIn,
    GarminConnectIn,
    GarminDubletteOut,
    GarminEinheitStatusOut,
    GarminJobOut,
    GarminKalenderEintragOut,
    GarminKalenderOut,
    GarminMfaIn,
    GarminPlanUebertragungOut,
    GarminSettingsIn,
    GarminStatusOut,
    GarminVerschiebenIn,
    GarminWorkoutPushIn,
    WellnessDayOut,
)
# Bewusst aus dem Plan-Router geliehen statt nachgebaut: Ein zweites „welcher
# Plan gehört diesem Nutzer" liefe früher oder später auseinander.
from .plans import _active_plan, _owned_plan

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
    """Holt nach, was fehlt — der Knopf für den Alltag.

    Beim ersten Mal ist das ein volles Jahr, danach nur noch das
    Aktualisierungsfenster; was dazwischen liegt, steht bereits in der
    Datenbank (siehe `sync.standard_zeitraum`).
    """
    konto = _konto_oder_fehler(db, user.id)
    _pruefe_startbar(db, konto)

    von, bis, tagesschleife = standard_zeitraum(
        "incremental",
        date.today(),
        gedeckt_von=konto.backfill_from,
        gedeckt_bis=konto.synced_through,
    )
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
# Trainings nach Garmin übertragen
#
# Die Gegenrichtung zum Abgleich. Ein Block umfasst eine Handvoll Einheiten und
# jede kostet zwei Anfragen (Vorlage anlegen, Termin eintragen) — zusammen also
# eine halbe Minute. Das läuft deshalb als Job im Runner, mit demselben
# Fortschritt und demselben Schloss wie ein Abgleich, statt eine Anfrage
# minutenlang offen zu halten.
# --------------------------------------------------------------------------


def _plan_oder_fehler(db, user_id: int, plan_id: int | None) -> Plan:
    """Der genannte Plan — oder der aktive, wenn keiner genannt ist."""
    if plan_id is not None:
        return _owned_plan(db, plan_id, user_id)
    plan = _active_plan(db, user_id)
    if plan is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Es gibt keinen aktiven Trainingsplan, der übertragen werden könnte.",
        )
    return plan


def _uebertragungsstatus(db, user, plan: Plan) -> GarminPlanUebertragungOut:
    heute = date.today()
    zustaende = uebertragung.zustand_der_einheiten(
        db, plan, profil=user.profile, ab=heute
    )
    gezaehlt = Counter(zustand for _, _, zustand in zustaende)

    return GarminPlanUebertragungOut(
        plan_id=plan.id,
        plan_title=plan.title,
        garmin_verbunden=_konto(db, user.id) is not None,
        offen=gezaehlt["offen"],
        aktuell=gezaehlt["aktuell"],
        geaendert=gezaehlt["geaendert"],
        fehler=gezaehlt["fehler"],
        vergangen=len(uebertragung.planbare_einheiten(plan))
        - len(uebertragung.planbare_einheiten(plan, heute)),
        einheiten=[
            GarminEinheitStatusOut(
                plan_session_id=session.id,
                date=session.date,
                title=session.title,
                sport=session.sport,
                zustand=zustand,
                garmin_workout_id=link.garmin_workout_id if link else None,
                garmin_schedule_id=link.garmin_schedule_id if link else None,
                last_error=link.last_error if link else None,
            )
            for session, link, zustand in zustaende
        ],
    )


@router.get("/workouts/status", response_model=GarminPlanUebertragungOut)
def uebertragungsstatus(
    user: CurrentUser, db: DbSession, plan_id: int | None = Query(None)
) -> GarminPlanUebertragungOut:
    """Was von einem Plan bereits in Garmin steht — ohne eine einzige Anfrage."""
    return _uebertragungsstatus(db, user, _plan_oder_fehler(db, user.id, plan_id))


@router.post(
    "/workouts/uebertragen",
    response_model=GarminJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def uebertrage_workouts(
    data: GarminWorkoutPushIn, user: CurrentUser, db: DbSession
) -> GarminSyncJob:
    """Legt die Einheiten des Plans als Workouts an und terminiert sie."""
    konto = _konto_oder_fehler(db, user.id)
    _pruefe_startbar(db, konto)
    plan = _plan_oder_fehler(db, user.id, data.plan_id)

    ab = date.today() if data.ab_heute else None
    if not uebertragung.planbare_einheiten(plan, ab):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Dieser Plan enthält keine Einheit, die sich übertragen ließe — "
            "Ruhetage und vergangene Tage bleiben außen vor.",
        )

    job_id = runner.starte_uebertragung(user.id, plan.id, "push", ab=ab)
    return db.get(GarminSyncJob, job_id)


@router.post(
    "/workouts/entfernen",
    response_model=GarminJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def entferne_workouts(
    data: GarminWorkoutPushIn, user: CurrentUser, db: DbSession
) -> GarminSyncJob:
    """Nimmt alle übertragenen Einheiten des Plans aus Garmin zurück."""
    konto = _konto_oder_fehler(db, user.id)
    _pruefe_startbar(db, konto)
    plan = _plan_oder_fehler(db, user.id, data.plan_id)

    if not uebertragung.links_zum_plan(db, plan):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Von diesem Plan steht nichts in Garmin.",
        )

    job_id = runner.starte_uebertragung(user.id, plan.id, "remove")
    return db.get(GarminSyncJob, job_id)


@router.post("/workouts/einheit/{plan_session_id}", response_model=GarminEinheitStatusOut)
def uebertrage_einzelne_einheit(
    plan_session_id: int, user: CurrentUser, db: DbSession
) -> GarminEinheitStatusOut:
    """Einzelne Einheit übertragen — zwei Anfragen, deshalb ohne Job."""
    session = _eigene_einheit(db, user.id, plan_session_id)
    if not workouts.ist_uebertragbar(session.sport):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Ein Ruhetag lässt sich nicht auf die Uhr legen.",
        )

    try:
        with runner.exklusiver_direktaufruf():
            with garmin_sitzung(db, user.id) as api:
                uebertragung.uebertrage_einheit(
                    db,
                    api,
                    user.id,
                    session,
                    zonen=workouts.zonen_aus_profil(user.profile),
                    ftp=getattr(user.profile, "ftp_watts", None),
                )
    except GarminFehler as exc:
        raise als_http(exc) from exc

    link = db.scalar(
        select(GarminWorkoutLink).where(
            GarminWorkoutLink.plan_session_id == session.id
        )
    )
    return GarminEinheitStatusOut(
        plan_session_id=session.id,
        date=session.date,
        title=session.title,
        sport=session.sport,
        zustand="aktuell",
        garmin_workout_id=link.garmin_workout_id if link else None,
        garmin_schedule_id=link.garmin_schedule_id if link else None,
    )


@router.delete(
    "/workouts/einheit/{plan_session_id}", status_code=status.HTTP_204_NO_CONTENT
)
def entferne_einzelne_einheit(
    plan_session_id: int, user: CurrentUser, db: DbSession
) -> None:
    session = _eigene_einheit(db, user.id, plan_session_id)
    link = db.scalar(
        select(GarminWorkoutLink).where(
            GarminWorkoutLink.plan_session_id == session.id
        )
    )
    if link is None:
        return

    try:
        with garmin_sitzung(db, user.id) as api:
            fehler = uebertragung.entferne_link(db, api, link)
    except GarminFehler as exc:
        raise als_http(exc) from exc

    if fehler:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Garmin hat das Training nicht gelöscht: {fehler[:200]}",
        )


def _eigene_einheit(db, user_id: int, plan_session_id: int) -> PlanSession:
    session = db.get(PlanSession, plan_session_id)
    if session is None or session.plan.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Einheit nicht gefunden.")
    return session


# --------------------------------------------------------------------------
# Der Garmin-Kalender
#
# Wird bei jedem Aufruf frisch geholt statt zwischengespeichert: Ein Monat
# kostet genau eine Anfrage, und eine Kopie in der Datenbank wäre nach der
# ersten Änderung in Garmin Connect falsch — womit die Ansicht ihren Zweck
# verlöre, den echten Stand zu zeigen.
# --------------------------------------------------------------------------


@router.get("/kalender", response_model=GarminKalenderOut)
def kalender(
    user: CurrentUser,
    db: DbSession,
    jahr: int = Query(..., ge=2000, le=2100),
    monat: int = Query(..., ge=1, le=12),
) -> GarminKalenderOut:
    try:
        with garmin_sitzung(db, user.id) as api:
            eintraege = kalender_modul.hole_monat(api, jahr, monat)
            # Der Monat liegt hier ohnehin vor: Damit lässt sich prüfen, ob die
            # eigenen Zuordnungen noch stimmen — ohne eine weitere Anfrage. Ohne
            # das zeigte diese Ansicht einen leeren Kalender, während der
            # Trainingsplan daneben behauptete, alles liege auf der Uhr.
            _gleiche_zuordnungen_ab(db, api, user.id, jahr, monat, eintraege)
    except GarminFehler as exc:
        raise als_http(exc) from exc

    links = {
        link.garmin_workout_id: link
        for link in db.scalars(
            select(GarminWorkoutLink).where(GarminWorkoutLink.user_id == user.id)
        ).all()
    }
    pool_ids = set(
        db.scalars(
            select(GarminWorkoutPoolSlot.garmin_workout_id).where(
                GarminWorkoutPoolSlot.user_id == user.id,
                GarminWorkoutPoolSlot.garmin_workout_id.is_not(None),
            )
        ).all()
    )

    antwort = GarminKalenderOut(jahr=jahr, monat=monat)
    for eintrag in eintraege:
        workout_id = eintrag["workout_id"] or ""
        link = links.get(workout_id)
        antwort.eintraege.append(
            GarminKalenderEintragOut(
                **eintrag,
                aus_tri_coach=workout_id in pool_ids,
                plan_session_id=link.plan_session_id if link else None,
            )
        )
    return antwort


def _gleiche_zuordnungen_ab(
    db, api, user_id: int, jahr: int, monat: int, eintraege: list[dict]
) -> None:
    """Prüft die Zuordnungen dieses Monats gegen den frisch geholten Kalender.

    Bewusst nur die Zuordnungen *dieses* Monats: Für die übrigen liegt hier
    keine Auskunft vor, und sie deshalb anzufassen hieße raten.
    """
    verknuepft = db.scalars(
        select(GarminWorkoutLink).where(
            GarminWorkoutLink.user_id == user_id,
            GarminWorkoutLink.scheduled_date >= date(jahr, monat, 1),
            GarminWorkoutLink.scheduled_date
            < date(jahr + monat // 12, monat % 12 + 1, 1),
        )
    ).all()
    if not verknuepft:
        return
    try:
        uebertragung.gleiche_mit_garmin_ab(
            db, api, list(verknuepft), bekannt={(jahr, monat): eintraege}
        )
    except GarminRateLimit:
        raise
    except Exception:  # noqa: BLE001 — die Ansicht selbst ist schon fertig
        db.rollback()


@router.delete("/kalender/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def loesche_kalendereintrag(
    schedule_id: str,
    user: CurrentUser,
    db: DbSession,
    workout_id: str | None = Query(
        None,
        description=(
            "Fremde Vorlage, die zusätzlich aus der Bibliothek gelöscht werden "
            "soll. Tri-Coach-Poolvorlagen bleiben immer erhalten."
        ),
    ),
) -> None:
    """Nimmt ein Workout aus dem Kalender — auf Wunsch samt Vorlage.

    Zwei getrennte Dinge, deshalb zwei Schritte: Ohne `workout_id` bleibt die
    Vorlage in der Bibliothek und lässt sich erneut einplanen. Absolvierte
    Aktivitäten stehen hier bewusst nicht zur Wahl — sie zu löschen hieße, die
    Trainingsdaten zu vernichten, aus denen diese App ihre Planung ableitet.
    """
    ist_pool_vorlage = bool(
        workout_id
        and db.scalar(
            select(GarminWorkoutPoolSlot.id).where(
                GarminWorkoutPoolSlot.user_id == user.id,
                GarminWorkoutPoolSlot.garmin_workout_id == workout_id,
            )
        )
    )
    try:
        with garmin_sitzung(db, user.id) as api:
            fehler = nachsichtig(lambda: api.unschedule_workout(schedule_id))
            if fehler is None and workout_id and not ist_pool_vorlage:
                fehler = nachsichtig(lambda: api.delete_workout(workout_id))
    except GarminFehler as exc:
        raise als_http(exc) from exc

    if fehler:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Garmin hat den Eintrag nicht entfernt: {fehler[:200]}",
        )

    _raeume_verknuepfung_auf(db, user.id, workout_id, schedule_id)


@router.post(
    "/kalender/{schedule_id}/verschieben", status_code=status.HTTP_204_NO_CONTENT
)
def verschiebe_kalendereintrag(
    schedule_id: str, data: GarminVerschiebenIn, user: CurrentUser, db: DbSession
) -> None:
    """Legt ein Workout auf einen anderen Tag.

    Garmin kennt kein Verschieben: Der alte Termin wird gelöscht und ein neuer
    angelegt. Die Vorlage bleibt dieselbe, am Inhalt ändert sich also nichts —
    und die Kennung der Vorlage bleibt gültig, weshalb die Zuordnung zur
    Planeinheit erhalten bleibt.

    **Die Planeinheit zieht mit um.** Wer hier verschiebt, trainiert an einem
    anderen Tag — das ist eine Entscheidung über den Plan, nicht nur über einen
    Kalendereintrag. Bliebe die Einheit auf ihrem alten Tag stehen, liefe beides
    auseinander: Die Übertragung sähe einen abweichenden Termin, schöbe ihn
    zurück auf den Plantag und machte die Verschiebung wortlos rückgängig.
    """
    try:
        with garmin_sitzung(db, user.id) as api:
            nachsichtig(lambda: api.unschedule_workout(schedule_id))
            neue_kennung = uebertragung.plane_ein(api, data.workout_id, data.datum)
    except GarminFehler as exc:
        raise als_http(exc) from exc

    link = db.scalar(
        select(GarminWorkoutLink).where(
            GarminWorkoutLink.user_id == user.id,
            GarminWorkoutLink.garmin_workout_id == data.workout_id,
        )
    )
    if link is not None:
        link.garmin_schedule_id = neue_kennung
        link.scheduled_date = data.datum
        einheit = db.get(PlanSession, link.plan_session_id)
        if einheit is not None:
            einheit.date = data.datum
        db.commit()


def _raeume_verknuepfung_auf(
    db, user_id: int, workout_id: str | None, schedule_id: str
) -> None:
    """Hält die eigene Zuordnung mit dem nach, was in Garmin passiert ist."""
    link = db.scalar(
        select(GarminWorkoutLink).where(
            GarminWorkoutLink.user_id == user_id,
            GarminWorkoutLink.garmin_schedule_id == schedule_id,
        )
    )
    if link is None:
        return
    if workout_id:
        db.delete(link)
    else:
        # Nur der Termin ist weg: Die Vorlage steht noch in der Bibliothek und
        # die Einheit gilt wieder als offen.
        link.garmin_schedule_id = None
    db.commit()


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
