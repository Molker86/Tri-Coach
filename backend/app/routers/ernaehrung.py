"""Der Ernährungsplan: ansehen, löschen, von Hand übernehmen, individualisieren.

Der **Auslöser** eines KI-Laufs steht bewusst nicht hier, sondern als
`POST /api/ki/ernaehrung` im KI-Router — genau wie bei der Einzelanpassung: Dort
stehen `_pruefe_startbar()` und der Runner, und der Riegel „es läuft schon ein
Lauf" gilt für alle Jobarten gleich. Die inhaltliche Grenze kommt umgekehrt von
hier (`ernaehrungsrahmen`, `pruefe_zeitraum`), damit beide Wege in einen
Ernährungsplan dieselbe ziehen — dieselbe Aufteilung wie zwischen
`plans.anpassbare_einheit` und `ki.passe_einheit_an`.
"""

from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from .. import ai_export, ernaehrung_import
from ..deps import CurrentUser, DbSession
from ..models import Ernaehrungsplan, Plan
from ..plan_import import PlanImportError
from ..schemas import (
    ErnaehrungImportIn,
    ExportOut,
    ErnaehrungsImportOut,
    ErnaehrungsplanOut,
    ErnaehrungsProfilIn,
    ErnaehrungsProfilOut,
    ErnaehrungsSpielraumOut,
)
from ..zeit import jetzt_utc

router = APIRouter(prefix="/api/ernaehrung", tags=["ernaehrung"])


# --------------------------------------------------------------------------
# Was sich planen lässt
# --------------------------------------------------------------------------


def aktiver_trainingsplan(db, user_id: int) -> Plan | None:
    """Der Block, nach dem sich die Ernährung richtet."""
    return (
        db.query(Plan)
        .filter(Plan.user_id == user_id, Plan.is_active.is_(True))
        .order_by(Plan.created_at.desc())
        .first()
    )


def ernaehrungsrahmen(
    db, user_id: int, start_date: date | None = None
) -> ErnaehrungsSpielraumOut:
    """Startdatum und Obergrenze der Tageszahl — die eine Stelle dafür.

    Öffentlich, weil drei Aufrufer dieselbe Rechnung brauchen: die Oberfläche
    (für das Zahlenfeld), der KI-Router (für den Lauf) und der Handweg über die
    Zwischenablage. Drei Rechnungen liefen auseinander, und dann plante der
    Knopf einen anderen Zeitraum, als das Feld daneben anzeigt.
    """
    plan = aktiver_trainingsplan(db, user_id)
    start = start_date or date.today()

    if plan is None:
        return ErnaehrungsSpielraumOut(
            hat_trainingsblock=False,
            start_date=start,
            max_tage=0,
            vorgabe_tage=0,
            hinweis=(
                "Es liegt kein aktiver Trainingsplan vor. Ein Ernährungsplan "
                "richtet sich nach dem geplanten Training — plane zuerst einen "
                "Trainingsblock."
            ),
        )

    # Nie vor dem Blockbeginn: Für die Tage davor gibt es kein geplantes
    # Training, an dem sich die Deckung ausrichten könnte.
    start = max(start, plan.beginn)
    moeglich = max(0, (plan.end_date - start).days + 1)

    hinweis = None
    if moeglich == 0:
        hinweis = (
            f"Der Trainingsplan „{plan.title}“ endet am "
            f"{plan.end_date.isoformat()} und deckt den gewählten Zeitraum "
            "nicht mehr ab. Plane zuerst den nächsten Trainingsblock."
        )

    return ErnaehrungsSpielraumOut(
        hat_trainingsblock=True,
        start_date=start,
        max_tage=moeglich,
        vorgabe_tage=moeglich,
        block_titel=plan.title,
        block_start=plan.beginn,
        block_ende=plan.end_date,
        hinweis=hinweis,
    )


def pruefe_zeitraum(
    db, user_id: int, start_date: date | None, days: int | None
) -> tuple[Plan, date, int]:
    """Der Block und der zulässige Zeitraum — oder ein 409 mit lesbarem Grund."""
    rahmen = ernaehrungsrahmen(db, user_id, start_date)
    if not rahmen.hat_trainingsblock or rahmen.max_tage < 1:
        raise HTTPException(status.HTTP_409_CONFLICT, rahmen.hinweis)

    if days is not None and days > rahmen.max_tage:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Der Trainingsplan reicht nur bis zum "
            f"{rahmen.block_ende.isoformat()}. Ab dem "
            f"{rahmen.start_date.isoformat()} lassen sich deshalb höchstens "
            f"{rahmen.max_tage} Tage planen.",
        )

    plan = aktiver_trainingsplan(db, user_id)
    return plan, rahmen.start_date, days or rahmen.vorgabe_tage


def _eigener_plan(db, user_id: int) -> Ernaehrungsplan:
    plan = ernaehrung_import.aktiver_ernaehrungsplan(db, user_id)
    if plan is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Es liegt kein Ernährungsplan vor."
        )
    return plan


# --------------------------------------------------------------------------
# Ansehen und löschen
# --------------------------------------------------------------------------


@router.get("/spielraum", response_model=ErnaehrungsSpielraumOut)
def spielraum(
    user: CurrentUser,
    db: DbSession,
    start_date: date | None = Query(None),
) -> ErnaehrungsSpielraumOut:
    return ernaehrungsrahmen(db, user.id, start_date)


@router.get("/aktiv", response_model=ErnaehrungsplanOut | None)
def aktiv(user: CurrentUser, db: DbSession) -> Ernaehrungsplan | None:
    return ernaehrung_import.aktiver_ernaehrungsplan(db, user.id)


@router.delete("/aktiv", status_code=status.HTTP_204_NO_CONTENT)
def loesche(user: CurrentUser, db: DbSession) -> None:
    """Löscht den Ernährungsplan samt Tagen, Mahlzeiten und Supplementen.

    Anders als beim Trainingsblock hängt daran nichts nach außen — kein
    Garmin-Kalender, keine Zuordnung, kein erfasstes Training. Deshalb keine
    Rückfrage und keine Antwort: 204 und weg. Der Freitext aus
    „individualisieren" bleibt ausdrücklich stehen (`ErnaehrungsProfil`): Eine
    Unverträglichkeit endet nicht, weil ein Plan weg ist.
    """
    db.delete(_eigener_plan(db, user.id))
    db.commit()


# --------------------------------------------------------------------------
# Der Weg über die Zwischenablage
# --------------------------------------------------------------------------


@router.get("/export", response_model=ExportOut)
def export_fuer_ki(
    user: CurrentUser,
    db: DbSession,
    start_date: date | None = Query(None),
    days: int | None = Query(None, ge=1, le=31),
) -> ExportOut:
    """Prompt und Datenpaket zum Kopieren in eine beliebige KI."""
    plan, start, tage = pruefe_zeitraum(db, user.id, start_date, days)
    try:
        export = ai_export.erzeuge_ernaehrung_export(
            db,
            user,
            plan=plan,
            start_date=start,
            days=tage,
            hinweise=ernaehrung_import.profil_hinweise(db, user.id),
        )
    except ai_export.ExportFehler as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    return ExportOut(
        prompt=export.prompt, payload=export.payload, combined=export.prompt
    )


@router.post(
    "/import",
    response_model=ErnaehrungsImportOut,
    status_code=status.HTTP_201_CREATED,
)
def importiere(
    data: ErnaehrungImportIn, user: CurrentUser, db: DbSession
) -> ErnaehrungsImportOut:
    """Übernimmt eine von Hand eingefügte KI-Antwort."""
    try:
        ergebnis = ernaehrung_import.uebernimm_ernaehrungsplan(
            db,
            user.id,
            data.raw,
            trainingsplan=aktiver_trainingsplan(db, user.id),
            start_date=data.start_date,
            days=data.days,
        )
    except PlanImportError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
        ) from exc

    return ErnaehrungsImportOut(plan=ergebnis.plan, warnings=ergebnis.warnings)


@router.post("/validate", response_model=ErnaehrungsImportOut)
def pruefe(
    data: ErnaehrungImportIn, user: CurrentUser, db: DbSession
) -> ErnaehrungsImportOut:
    """Prüft eine Antwort, ohne sie zu speichern — die Vorschau vor dem Import."""
    try:
        body = ernaehrung_import.parse_ernaehrung_antwort(data.raw)
    except PlanImportError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
        ) from exc

    warnings = ernaehrung_import.pruefe_ernaehrungsplan(
        body, start_date=data.start_date, days=data.days
    )
    # Reine Vorschau: gebaut, aber nie zur Sitzung hinzugefügt. `id=0` steht
    # dafür wie bei `plans.validate_plan`.
    vorschau = ernaehrung_import.baue_ernaehrungsplan(body, user.id, None)

    return ErnaehrungsImportOut(
        plan=ErnaehrungsplanOut(
            id=0,
            plan_id=None,
            # Auch die Vorschau in UTC: Seit die Zeitstempel der API ihre
            # Zeitzone mitführen, käme eine Ortszeit hier als UTC beschriftet
            # heraus.
            created_at=jetzt_utc(),
            start_date=vorschau.start_date,
            end_date=vorschau.end_date,
            title=vorschau.title,
            summary=vorschau.summary,
            begruendung=vorschau.begruendung,
            tage=[],
            supplemente=[],
        ),
        warnings=warnings,
    )


# --------------------------------------------------------------------------
# Der dauerhafte Freitext
# --------------------------------------------------------------------------


@router.get("/profil", response_model=ErnaehrungsProfilOut)
def profil(user: CurrentUser, db: DbSession):
    return ernaehrung_import.hole_profil(db, user.id)


@router.put("/profil", response_model=ErnaehrungsProfilOut)
def aendere_profil(data: ErnaehrungsProfilIn, user: CurrentUser, db: DbSession):
    """Speichert den Freitext. Ein leerer Text löscht ihn ausdrücklich.

    Kein Überspringen leerer Werte wie beim Teil-Update des Profils: „Text
    löschen" ist hier ein eigener Knopf und braucht einen Weg, der nicht
    stillschweigend nichts tut — dieselbe Regel wie beim Claude-Token.
    """
    eintrag = ernaehrung_import.hole_profil(db, user.id)
    eintrag.hinweise = data.hinweise.strip() or None
    db.commit()
    db.refresh(eintrag)
    return eintrag
