"""Übungsanimationen — nachschlagen, ansehen, freigeben, verwerfen.

Angestoßen wird die Erzeugung nicht hier, sondern unter `POST /api/ki/animationen`:
Dort stehen die Riegel, die für jeden Lauf gegen die KI gelten.

Freigeben und Verwerfen darf **jedes** Konto, und es gilt für alle: Die
Animationen sind gemeinsam (siehe `models.UebungsAnimation`), und die Konten
eines Add-ons sind ein Haushalt.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from ..animation import einheit
from ..animation import schluessel as schl
from ..animation.bibliothek import verzeichnis
from ..animation.bibliothek_datei import FORMAT
from ..animation.erzeugung import letzter_versuch
from ..deps import CurrentUser, DbSession
from ..models import UebungsAnimation
from ..schemas import (
    AnimationKurzOut,
    AnimationOut,
    AnimationVerwerfenIn,
    EinheitUebungenOut,
    EinheitUebungOut,
    KiJobOut,
)
from ..zeit import jetzt_utc
from .plans import _eigene_einheit

router = APIRouter(prefix="/api/animationen", tags=["animationen"])


def als_ausgabe(zeile: UebungsAnimation) -> AnimationOut:
    return AnimationOut(
        schluessel=zeile.schluessel,
        name=zeile.name,
        aliase=list(zeile.aliase or []),
        herkunft=zeile.herkunft,
        zustand=zeile.zustand,
        format=FORMAT,
        bewegung=zeile.daten,
        hinweise=zeile.hinweise,
        rueckmeldung=zeile.rueckmeldung,
        model_used=zeile.model_used,
        geaendert_am=zeile.geaendert_am,
    )


def _zeile_oder_fehler(db, schluessel: str) -> UebungsAnimation:
    zeile = db.scalar(select(UebungsAnimation).where(UebungsAnimation.schluessel == schluessel))
    if zeile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Animation nicht gefunden.")
    return zeile


@router.get("", response_model=list[AnimationKurzOut])
def liste(user: CurrentUser, db: DbSession, zustand: str | None = None) -> list[UebungsAnimation]:
    """Alle Animationen, wahlweise nur eines Zustands („ungeprueft“)."""
    abfrage = db.query(UebungsAnimation)
    if zustand:
        abfrage = abfrage.filter(UebungsAnimation.zustand == zustand)
    return abfrage.order_by(UebungsAnimation.name).all()


@router.get("/einheit/{plan_session_id}", response_model=EinheitUebungenOut)
def uebungen_der_einheit(plan_session_id: int, user: CurrentUser, db: DbSession) -> EinheitUebungenOut:
    """Die Übungen einer Planeinheit in Reihenfolge — jede mit ihrer Animation.

    Die Bewegung steht gleich mit darin, statt je Übung nachgeladen zu werden:
    Eine Einheit hat selten mehr als zehn Übungen, zusammen ein paar Dutzend
    Kilobyte, und hinter dem Ingress kostet jede Anfrage spürbar Zeit.
    """
    session = _eigene_einheit(db, plan_session_id, user.id)
    idx, zeilen = verzeichnis(db)

    ausgabe: list[EinheitUebungOut] = []
    for u in einheit.uebungen(session.sport, session.structure, session.steps_json):
        schluessel = idx.get(u.schluessel) or (idx.get(schl.normalisiert(u.name_en)) if u.name_en else None)
        zeile = zeilen.get(schluessel) if schluessel else None
        ausgabe.append(
            EinheitUebungOut(
                zeile=u.zeile,
                name_en=u.name_en,
                schluessel=u.schluessel,
                animation=als_ausgabe(zeile) if zeile else None,
            )
        )

    job = letzter_versuch(db, user.id)
    return EinheitUebungenOut(
        plan_session_id=session.id,
        uebungen=ausgabe,
        fehlend=sum(1 for u in ausgabe if u.animation is None),
        erzeugung=KiJobOut.model_validate(job) if job else None,
    )


@router.get("/{schluessel}", response_model=AnimationOut)
def animation(schluessel: str, user: CurrentUser, db: DbSession) -> AnimationOut:
    """Eine Animation — über ihren Schlüssel oder einen ihrer Namen."""
    idx, zeilen = verzeichnis(db)
    gefunden = idx.get(schl.normalisiert(schluessel))
    if gefunden:
        return als_ausgabe(zeilen[gefunden])
    # Eine verworfene gibt es auch noch — nur nicht über ihre Aliase.
    return als_ausgabe(_zeile_oder_fehler(db, schluessel))


@router.post("/{schluessel}/freigeben", response_model=AnimationOut)
def freigeben(schluessel: str, user: CurrentUser, db: DbSession) -> AnimationOut:
    zeile = _zeile_oder_fehler(db, schluessel)
    zeile.zustand = "freigegeben"
    zeile.rueckmeldung = None
    zeile.geaendert_am = jetzt_utc()
    db.commit()
    return als_ausgabe(zeile)


@router.post("/{schluessel}/verwerfen", response_model=AnimationOut)
def verwerfen(
    schluessel: str, data: AnimationVerwerfenIn, user: CurrentUser, db: DbSession
) -> AnimationOut:
    """Die Animation zurückweisen — der nächste Lauf erzeugt eine neue.

    Auch eine aus der Bibliothek lässt sich verwerfen: Dann ersetzt sie die
    KI, und erst eine geänderte Bibliotheksfassung holt die kuratierte zurück.
    Die Rückmeldung bleibt an der Zeile stehen, bis der Ersatz da ist; sie geht
    wörtlich in dessen Auftrag ein.
    """
    zeile = _zeile_oder_fehler(db, schluessel)
    zeile.zustand = "verworfen"
    rueckmeldung = (data.rueckmeldung or "").strip()
    zeile.rueckmeldung = rueckmeldung or None
    zeile.geaendert_am = jetzt_utc()
    db.commit()
    return als_ausgabe(zeile)
