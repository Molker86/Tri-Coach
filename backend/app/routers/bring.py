"""Die Einkaufsliste: Bring-Konto einstellen, Vorschau ansehen, übertragen.

**Synchron und ohne Job**, anders als Garmin und die KI: Ein Lauf ist eine
Anmeldung, ein Lesen und ein Schreiben — Sekunden, nicht Minuten. Ein
Fortschrittsbalken über drei HTTP-Aufrufe wäre Aufwand ohne Auskunft.

Die Vorschau (`GET /einkaufsliste`) fragt Bring **gar nicht**: Was auf die Liste
ginge, steht schon in der Datenbank. So lässt sich der Dialog auch ohne
verbundenes Konto zeigen — und wer nichts einträgt, sieht trotzdem, was er
verpasst.
"""

from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from .. import einkaufsliste, ernaehrung_import
from ..bring import client as bring_client
from ..bring import uebertragung
from ..bring.errors import (
    BringAnmeldungFehlgeschlagen,
    BringFehler,
    BringListeFehlt,
    BringNichtVerbunden,
)
from ..crypto import EntschluesselungFehlgeschlagen, entschluessle, verschluessle
from ..deps import CurrentUser, DbSession
from ..models import BringAccount, Ernaehrungsplan
from ..schemas import (
    BringAccountOut,
    BringListeOut,
    BringSettingsIn,
    BringStatusOut,
    BringUebertragungOut,
    EinkaufslistenVorschauOut,
    EinkaufspostenOut,
)

router = APIRouter(prefix="/api/bring", tags=["bring"])


def _konto(db, user_id: int) -> BringAccount | None:
    return db.scalar(select(BringAccount).where(BringAccount.user_id == user_id))


def _passwort_status(konto: BringAccount) -> str:
    if not konto.password_encrypted:
        return "fehlt"
    try:
        entschluessle(konto.password_encrypted)
    except EntschluesselungFehlgeschlagen:
        return "unlesbar"
    return "hinterlegt"


def _ausgabe(konto: BringAccount) -> BringAccountOut:
    daten = BringAccountOut.model_validate(konto)
    daten.passwort_status = _passwort_status(konto)
    return daten


def _als_http(fehler: BringFehler) -> HTTPException:
    # 409 für alles, was der Nutzer selbst richtigstellen kann, 502 für das,
    # was auf Brings Seite liegt — sonst suchte er den Fehler am falschen Ende.
    code = (
        status.HTTP_409_CONFLICT
        if isinstance(
            fehler,
            (BringNichtVerbunden, BringAnmeldungFehlgeschlagen, BringListeFehlt),
        )
        else status.HTTP_502_BAD_GATEWAY
    )
    return HTTPException(code, fehler.meldung)


def _listen(konto: BringAccount) -> list[BringListeOut]:
    """Die Listen des Kontos — und zugleich die Probe, ob der Zugang trägt.

    Schlägt sie fehl, wird das am Konto vermerkt statt geworfen: Die Statusseite
    soll den Grund nennen können, ohne dass der ganze Aufruf scheitert.
    """
    if not konto.email or not konto.password_encrypted:
        return []
    try:
        gefunden = bring_client.hole_listen(
            konto.email, entschluessle(konto.password_encrypted)
        )
    except (BringFehler, EntschluesselungFehlgeschlagen) as exc:
        konto.status = "error"
        konto.status_message = getattr(exc, "meldung", str(exc))
        return []

    konto.status = "connected"
    konto.status_message = None

    # Den Namen der gewählten Liste mitziehen: Wer sie in Bring umbenennt, soll
    # hier nicht den alten Namen lesen.
    for liste in gefunden:
        if liste.uuid == konto.list_uuid:
            konto.list_name = liste.name

    return [BringListeOut(uuid=liste.uuid, name=liste.name) for liste in gefunden]


# --------------------------------------------------------------------------
# Konto
# --------------------------------------------------------------------------


@router.get("/status", response_model=BringStatusOut)
def zustand(user: CurrentUser, db: DbSession) -> BringStatusOut:
    konto = _konto(db, user.id)
    if konto is None:
        return BringStatusOut()

    listen = _listen(konto)
    db.commit()
    return BringStatusOut(konto=_ausgabe(konto), listen=listen)


@router.put("/settings", response_model=BringStatusOut)
def aendere_einstellungen(
    data: BringSettingsIn, user: CurrentUser, db: DbSession
) -> BringStatusOut:
    """Teil-Update wie bei den KI-Einstellungen; leeres Passwort löscht."""
    konto = _konto(db, user.id)
    if konto is None:
        konto = BringAccount(user_id=user.id)
        db.add(konto)

    daten = data.model_dump(exclude_unset=True)

    if "passwort" in daten:
        roh = (daten.pop("passwort") or "").strip()
        konto.password_encrypted = verschluessle(roh) if roh else ""

    for feld, wert in daten.items():
        if wert is not None:
            setattr(konto, feld, wert)

    # Eine Liste, die es nicht mehr gibt, behält sonst ihren alten Namen.
    if "list_uuid" in daten:
        konto.list_name = None

    db.commit()
    db.refresh(konto)

    listen = _listen(konto)
    db.commit()
    return BringStatusOut(konto=_ausgabe(konto), listen=listen)


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
def trenne(user: CurrentUser, db: DbSession) -> None:
    konto = _konto(db, user.id)
    if konto is not None:
        db.delete(konto)
        db.commit()


# --------------------------------------------------------------------------
# Einkaufsliste
# --------------------------------------------------------------------------


def _plan(db, user_id: int) -> Ernaehrungsplan:
    plan = ernaehrung_import.aktiver_ernaehrungsplan(db, user_id)
    if plan is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Es liegt kein Ernährungsplan vor."
        )
    return plan


def _hinweis(auswahl: uebertragung.Auswahl, posten: list) -> str | None:
    if not auswahl.tage:
        if auswahl.bereits_uebertragen:
            return (
                "Alle noch offenen Tage dieses Plans stehen bereits auf der "
                "Einkaufsliste."
            )
        return "Der Ernährungsplan deckt keine künftigen Tage mehr ab."
    if not posten:
        return (
            "Die Mahlzeiten dieses Plans nennen keine einzelnen Zutaten. Er "
            "stammt aus der Zeit vor der Einkaufsliste — beim nächsten "
            "Ernährungsplan sind sie dabei."
        )
    return None


@router.get("/einkaufsliste", response_model=EinkaufslistenVorschauOut)
def vorschau(
    user: CurrentUser,
    db: DbSession,
    alles: bool = Query(False),
) -> EinkaufslistenVorschauOut:
    """Was übertragen würde. Rechnet nur — Bring wird dafür nicht gefragt."""
    plan = _plan(db, user.id)
    auswahl = uebertragung.waehle_tage(plan, date.today(), alles=alles)
    posten = einkaufsliste.sammle(auswahl.tage)

    return EinkaufslistenVorschauOut(
        von=auswahl.von,
        bis=auswahl.bis,
        posten=[
            EinkaufspostenOut(name=p.name, menge_text=p.text) for p in posten
        ],
        tage_offen=len(auswahl.tage),
        tage_bereits_uebertragen=auswahl.bereits_uebertragen,
        hinweis=_hinweis(auswahl, posten),
    )


@router.post("/einkaufsliste", response_model=BringUebertragungOut)
def uebertrage(
    user: CurrentUser,
    db: DbSession,
    alles: bool = Query(False),
) -> BringUebertragungOut:
    plan = _plan(db, user.id)
    konto = _konto(db, user.id)

    auswahl = uebertragung.waehle_tage(plan, date.today(), alles=alles)
    posten = einkaufsliste.sammle(auswahl.tage)
    if not posten:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            _hinweis(auswahl, posten) or "Es gibt nichts zu übertragen.",
        )

    try:
        ergebnis = uebertragung.uebertrage(db, konto, auswahl, posten)
    except BringFehler as exc:
        db.rollback()
        if konto is not None:
            konto.status = "error"
            konto.status_message = exc.meldung
            db.commit()
        raise _als_http(exc) from exc

    return BringUebertragungOut(
        hinzugefuegt=ergebnis.hinzugefuegt,
        ergaenzt=ergebnis.ergaenzt,
        liste=ergebnis.liste,
    )
