"""Die KI plant den nächsten Block — Knopf, Einstellungen und Fortschritt."""

from datetime import date, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from ..config import KI_EFFORT, KI_MODELL
from ..crypto import verschluessle
from ..deps import CurrentUser, DbSession
from ..ki import tagesform
from ..ki.client import ist_angemeldet, token_aus
from ..ki.runner import (
    EINHEIT,
    ENDZUSTAENDE,
    ERNAEHRUNG,
    TAGESFORM,
    LaeuftBereits,
    runner,
)
from ..models import GarminAccount, KiJob, KiSettings, TrainingRequest
from ..schemas import (
    KiEinheitIn,
    KiErnaehrungIn,
    KiJobOut,
    KiPlanenIn,
    KiSettingsIn,
    KiSettingsOut,
    KiStatusOut,
    TagesformBefundOut,
)
from ..zeit import als_utc, ortsdatum
from .ernaehrung import pruefe_zeitraum
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


def _ausgabe(einstellungen: KiSettings) -> KiSettingsOut:
    """Die Einstellungen für die Oberfläche — mit der Lage des Tokens statt des Tokens.

    `token_status` steht nicht am Modell, weil es keine Spalte ist, sondern eine
    Auskunft über zwei: Ist einer hinterlegt, und lässt er sich noch lesen?
    """
    daten = KiSettingsOut.model_validate(einstellungen)
    if not einstellungen.token_encrypted:
        daten.token_status = "fehlt"
    elif token_aus(einstellungen.token_encrypted):
        daten.token_status = "hinterlegt"
    else:
        daten.token_status = "unlesbar"
    return daten


@router.get("/status", response_model=KiStatusOut)
def zustand(user: CurrentUser, db: DbSession) -> KiStatusOut:
    return _zustand(db, user.id)


@router.post("/pruefen", response_model=KiStatusOut)
def pruefe_zugang(user: CurrentUser, db: DbSession) -> KiStatusOut:
    """Fragt Claude Code erneut, ob der Zugang trägt — am Cache vorbei.

    Ohne diesen Weg zeigte der Knopf „Verbindung prüfen" bis zu einer Minute
    lang die alte Auskunft (`client._ANMELDUNG_CACHE_S`) — also ausgerechnet
    dann nichts Neues, wenn der Nutzer gerade ein Token eingetragen hat.
    """
    return _zustand(db, user.id, erzwinge=True)


def _zustand(db, user_id: int, *, erzwinge: bool = False) -> KiStatusOut:
    einstellungen = _einstellungen(db, user_id)

    aktiv_id = runner.laeuft_fuer(user_id)
    aktiver = db.get(KiJob, aktiv_id) if aktiv_id else None

    letzter = (
        db.query(KiJob)
        .filter(KiJob.user_id == user_id)
        .order_by(KiJob.started_at.desc())
        .first()
    )

    return KiStatusOut(
        verfuegbar=ist_angemeldet(
            token_aus(einstellungen.token_encrypted), erzwinge=erzwinge
        ),
        modell=einstellungen.model or KI_MODELL,
        effort=einstellungen.effort or KI_EFFORT,
        einstellungen=_ausgabe(einstellungen),
        aktiver_job=KiJobOut.model_validate(aktiver) if aktiver else None,
        letzter_job=KiJobOut.model_validate(letzter) if letzter else None,
    )


@router.put("/settings", response_model=KiSettingsOut)
def aendere_einstellungen(
    data: KiSettingsIn, user: CurrentUser, db: DbSession
) -> KiSettingsOut:
    einstellungen = _einstellungen(db, user.id)
    daten = data.model_dump(exclude_unset=True)

    # Der Token eigens, aus zwei Gründen: Das Feld heißt anders als die Spalte,
    # und ein leerer String soll hier ausdrücklich löschen statt übergangen zu
    # werden — das ist der Knopf „Entfernen".
    if "token" in daten:
        roh = (daten.pop("token") or "").strip()
        einstellungen.token_encrypted = verschluessle(roh) if roh else None
        # Ein neuer Zugang macht den vermerkten Fehlschlag des alten
        # gegenstandslos; bliebe er stehen, wiese die Oberfläche weiter auf ein
        # abgelaufenes Token hin, das es nicht mehr gibt.
        if einstellungen.status in {"token_expired", "rate_limited"}:
            einstellungen.status = "ready"
            einstellungen.status_message = None

    # Teil-Update wie beim Profil: Was nicht geschickt wurde, bleibt stehen.
    for feld, wert in daten.items():
        if wert is not None:
            setattr(einstellungen, feld, wert)
    db.commit()
    db.refresh(einstellungen)
    return _ausgabe(einstellungen)


@router.get("/jobs/{job_id}", response_model=KiJobOut)
def job(job_id: int, user: CurrentUser, db: DbSession) -> KiJob:
    return _job_oder_fehler(db, job_id, user.id)


@router.get("/jobs/{job_id}/rohantwort")
def rohantwort(job_id: int, user: CurrentUser, db: DbSession) -> dict[str, str]:
    """Die Antwort der KI im Original — der Rettungsweg für einen Fehlschlag.

    Ein Lauf dauert Minuten und kostet Kontingent. Kam die Antwort zurück, ließ
    sich aber nicht übernehmen, wäre sie ohne diese Route verloren: Der Athlet
    kann sie hier holen, von Hand ausbessern und über den bestehenden
    Einfügeweg übernehmen.
    """
    eintrag = _job_oder_fehler(db, job_id, user.id)
    if not eintrag.roh_antwort:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Zu diesem Lauf ist keine Antwort gespeichert.",
        )
    return {"raw": eintrag.roh_antwort}


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
    _pruefe_startbar(_einstellungen(db, user.id))

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

    job_id = _starte(
        user.id,
        "manual",
        request_id=data.request_id,
        start_date=data.start_date,
        days=data.days,
    )
    return db.get(KiJob, job_id)


LAEUFT_BEREITS = (
    "Es läuft bereits ein Lauf gegen die KI. Bitte warte, bis er fertig ist."
)


def _pruefe_startbar(einstellungen: KiSettings) -> None:
    """Die beiden Riegel, die vor jedem Lauf gelten.

    Der zweite gilt **je Konto**, nicht je Prozess: Anders als bei Garmin steht
    dahinter keine geteilte Anfragegrenze, sondern ein Unterprozess und das
    Kontingent des Kontos, das ihn anstößt — beides gehört diesem Konto allein,
    und ein Lauf eines anderen steht ihm nicht im Weg.

    Innerhalb eines Kontos bleibt es bewusst ein Riegel und keine
    Warteschlange: Wer selbst drückt, kann warten und es gleich noch einmal
    versuchen — anders als beim automatisch angestoßenen Lauf, den niemand
    nachholen würde.

    Geprüft wird hier nur *freundlich*, damit die Meldung kommt, bevor die
    Route ihre übrige Arbeit tut. Verbindlich entscheidet `runner.starte()`,
    weil erst dort Prüfen und Vormerken ein Zug sind.
    """
    if not ist_angemeldet(token_aus(einstellungen.token_encrypted)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Es ist kein Claude-Zugang hinterlegt. Trage unter Einstellungen → "
            "KI-Planung ein mit `claude setup-token` erzeugtes Token ein.",
        )

    if runner.laeuft_fuer(einstellungen.user_id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, LAEUFT_BEREITS)


def _starte(*args, **kwargs) -> int:
    """Startet den Lauf und übersetzt das Rennen zweier Klicks in eine 409.

    `_pruefe_startbar` prüft eine Anfrage früher; zwischen ihr und hier liegt
    noch die Feldprüfung der Route. Zwei Klicks in derselben Sekunde kamen
    früher beide durch — aufgefangen hat das nur das globale Schloss, und das
    gibt es nicht mehr.
    """
    try:
        return runner.starte(*args, **kwargs)
    except LaeuftBereits as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, LAEUFT_BEREITS) from exc


# --------------------------------------------------------------------------
# Der heutige Tag
#
# Die Tagesanpassung lief bis hierher **nur** hinten am automatischen Abgleich,
# und ihr Ergebnis erreichte die Oberfläche an keiner Stelle: Ein Lauf, der zu
# dem Schluss kam, dass alles passt, schreibt an keine Einheit etwas — und sah
# damit für den Athleten aus wie einer, der nie stattgefunden hat. Die beiden
# Routen hier schließen das: eine, die sagt, was war, und eine, die es auslöst.
# --------------------------------------------------------------------------


@router.get("/tagesform", response_model=TagesformBefundOut)
def tagesbefund(user: CurrentUser, db: DbSession) -> TagesformBefundOut:
    """Was heute mit den Einheiten des Tages geschehen ist — oder warum nichts.

    **Drei Quellen, in dieser Reihenfolge.** Gibt es einen Lauf von heute, ist
    sein `KiJob` die Auskunft — er ist das Genaueste, was der Tag hergibt, und
    trägt die Begründung der KI im Wortlaut. Gibt es keinen, aber einen Vermerk
    von heute, gilt der. Und gibt es beides nicht, wird der Grund **jetzt**
    ausgerechnet.

    Der dritte Fall ist kein Randfall, sondern der wahrscheinlichste: Die
    Vermerke schreibt `ki/tagesform._passe_an`, und das läuft nur hinten am
    automatischen Abgleich. Ist das Garmin-Token abgelaufen, überspringt
    `starte_faellige_syncs` das Konto — dann findet gar kein Abgleich statt, es
    wird nichts vermerkt, und ohne diesen Zweig stünde der Athlet vor einem
    „unbekannt", obwohl der Grund glasklar ist und in derselben Funktion steht,
    die auch die Automatik fragt.

    Zusammengesetzt wird das hier und nicht in der Oberfläche: Sonst läge die
    Deutung zweimal vor, einmal je Seite, die sie anzeigt.
    """
    einstellungen = _einstellungen(db, user.id)
    heute = date.today()

    job = (
        db.query(KiJob)
        .filter(KiJob.user_id == user.id, KiJob.kind == TAGESFORM)
        .order_by(KiJob.started_at.desc())
        .first()
    )
    job_am = als_utc(job.started_at) if job is not None else None
    if job is not None and job_am is not None and ortsdatum(job_am) == heute:
        return TagesformBefundOut(
            aktiv=einstellungen.auto_tagesform_enabled,
            stand=_stand_aus_job(job),
            text=job.message or job.error or "",
            geprueft_am=job_am,
            von_heute=True,
            job_id=job.id,
            progress_pct=job.progress_pct,
            roh_antwort_vorhanden=bool(job.roh_antwort),
        )

    ausfall_am = als_utc(einstellungen.tagesform_ausfall_am)
    if (
        einstellungen.tagesform_ausfall is not None
        and ausfall_am is not None
        and ortsdatum(ausfall_am) == heute
    ):
        return _ausfall_befund(
            einstellungen, einstellungen.tagesform_ausfall, ausfall_am, True
        )

    # Nichts von heute. Der Grund lässt sich trotzdem sagen — es ist derselbe
    # Ausdruck, den die Automatik auswertet.
    konto = db.scalar(
        select(GarminAccount).where(GarminAccount.user_id == user.id)
    )
    grund = tagesform.ausfallgrund(einstellungen, konto, heute)
    if grund is not None and grund != tagesform.AUSFALL_SCHON_GELAUFEN:
        return _ausfall_befund(einstellungen, grund, None, False)

    # Fällig, aber noch nicht gelaufen: Der Abgleich kommt erst später am Tag,
    # oder er ist gerade unterwegs. Kein Mangel, sondern ein Zwischenstand.
    return TagesformBefundOut(
        aktiv=einstellungen.auto_tagesform_enabled,
        stand="unbekannt",
        text="Der heutige Tag wurde noch nicht geprüft.",
    )


def _ausfall_befund(
    einstellungen: KiSettings,
    grund: str,
    wann: datetime | None,
    von_heute: bool,
) -> TagesformBefundOut:
    """Ein Ausfallgrund als Befund.

    `aus` bekommt einen eigenen Stand, weil die Oberfläche dafür **nichts**
    zeigt: Ein Schalter, den der Athlet bewusst aus gelassen hat, ist kein
    Grund, ihn jeden Morgen daran zu erinnern.
    """
    return TagesformBefundOut(
        aktiv=einstellungen.auto_tagesform_enabled,
        stand="aus" if grund == tagesform.AUSFALL_AUS else "ausgefallen",
        text=tagesform.ausfalltext(grund),
        geprueft_am=wann,
        von_heute=von_heute,
    )


def _stand_aus_job(job: KiJob) -> str:
    """Der Zustand eines Tagesform-Laufs, übersetzt für die Anzeige.

    `done` **ohne** `model_used` ist die Feinheit: Genau so enden die beiden
    Frühausstiege in `ki/runner._tagesform_lauf` — kein Plan mehr da, oder keine
    Fitnessdaten für heute. Der Lauf ist sauber zu Ende gegangen, aber Claude
    wurde nie gefragt. Das als „geprüft" anzuschreiben wäre falsch, und ein
    eigenes Feld dafür bräuchte es nicht: `model_used` setzt allein
    `_frage_claude`.
    """
    if job.state in {"queued", "running"}:
        return "laeuft"
    if job.state == "done":
        return "geprueft" if job.model_used else "ausgefallen"
    return "fehlgeschlagen"


@router.post(
    "/tagesform", response_model=KiJobOut, status_code=status.HTTP_202_ACCEPTED
)
def pruefe_tagesform_jetzt(user: CurrentUser, db: DbSession) -> KiJob:
    """Prüft die Einheiten von heute jetzt — von Hand angestoßen.

    **Die Riegel aus `tagesform.ausfallgrund()` gelten hier ausdrücklich
    nicht.** Sie beantworten alle dieselbe Frage: Soll das ungefragt Kontingent
    kosten? Wer drückt, hat gefragt. Ohne diesen Weg gäbe es die Funktion nur
    für Konten mit laufendem Garmin-Abgleich — wessen Token abgelaufen ist oder
    wer schlicht wissen will, ob die Sache arbeitet, hätte keinen.

    Was bleibt, sind die sachlichen Grenzen: Es muss heute etwas zu ändern
    geben, und ein zweiter Lauf desselben Kontos wird abgewiesen.

    **`last_tagesform_on` wird bewusst nicht gesetzt.** Wer um sieben selbst
    drückt, soll den automatischen Lauf um zehn nicht verbrauchen — der liest
    dann frischere Werte. Der Preis steht in `docs/grenzen.md`: Beides an einem
    Morgen kostet zwei Läufe.
    """
    _pruefe_startbar(_einstellungen(db, user.id))

    heute = date.today()
    plan, sessions = tagesform.anpassbare_einheiten(db, user.id, heute)
    if plan is None or not sessions:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Für heute steht nichts an, was sich anpassen ließe — Ruhetag, "
            "kein aktiver Block, oder alles schon absolviert.",
        )

    job_id = _starte(user.id, TAGESFORM, start_date=heute, days=1)
    return db.get(KiJob, job_id)


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
    _pruefe_startbar(_einstellungen(db, user.id))
    session = anpassbare_einheit(db, data.plan_session_id, user.id)

    job_id = _starte(
        user.id,
        EINHEIT,
        plan_session_id=session.id,
        wunsch=data.wunsch,
    )
    return db.get(KiJob, job_id)


@router.post(
    "/ernaehrung", response_model=KiJobOut, status_code=status.HTTP_202_ACCEPTED
)
def plane_ernaehrung(
    data: KiErnaehrungIn, user: CurrentUser, db: DbSession
) -> KiJob:
    """Lässt Claude den Ernährungsplan zum aktiven Trainingsblock schreiben.

    Steht hier und nicht im Ernährungsrouter — genau wie `POST /einheit`: An
    dieser Stelle stehen `_pruefe_startbar()` und der Runner, und der Riegel „es
    läuft schon ein Lauf dieses Kontos" gilt für alle Jobarten gleich. Die inhaltliche Grenze
    kommt umgekehrt von dort (`pruefe_zeitraum`), damit Knopf und Zwischenablage
    denselben Zeitraum zulassen.
    """
    _pruefe_startbar(_einstellungen(db, user.id))
    _, start, tage = pruefe_zeitraum(db, user.id, data.start_date, data.days)

    job_id = _starte(user.id, ERNAEHRUNG, start_date=start, days=tage)
    return db.get(KiJob, job_id)
