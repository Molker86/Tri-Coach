"""Die Bibliothek in die Datenbank — und das Nachschlagen dort.

Beim Start spielt `einspielen()` die kuratierten Bewegungen ein: neue kommen
dazu, geänderte (andere `fassung`) werden nachgezogen. Eine KI-Animation mit
demselben Schlüssel weicht der kuratierten — die ist von Hand geprüft.
Was die Bibliothek nicht mehr führt, bleibt stehen: Es kann an einem alten Plan
hängen, und Löschen hat hier keinen Nutzen.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import UebungsAnimation
from . import schluessel as schl
from .bibliothek_datei import bibliothek, fassung

logger = logging.getLogger(__name__)

# Welche Zustände als „vorhanden“ zählen. Eine verworfene Animation zählt
# nicht — für sie wird eine neue erzeugt.
SICHTBAR = ("freigegeben", "ungeprueft")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def daten_aus(bewegung: dict) -> dict:
    """Die abspielbaren Teile einer Bewegung — ohne Schlüssel, Name, Aliase."""
    return {k: v for k, v in bewegung.items() if k not in ("schluessel", "name", "aliase")}


def einspielen(db: Session) -> int:
    """Kuratierte Bewegungen einspielen. Gibt zurück, wie viele neu oder geändert sind."""
    vorhanden = {a.schluessel: a for a in db.query(UebungsAnimation).all()}
    geaendert = 0
    for bewegung in bibliothek():
        f = fassung(bewegung)
        zeile = vorhanden.get(bewegung["schluessel"])
        if zeile is not None and zeile.herkunft == "bibliothek" and zeile.fassung == f:
            continue
        if zeile is None:
            zeile = UebungsAnimation(schluessel=bewegung["schluessel"])
            db.add(zeile)
        zeile.name = bewegung["name"]
        zeile.aliase = list(bewegung.get("aliase") or [])
        zeile.daten = daten_aus(bewegung)
        zeile.herkunft = "bibliothek"
        zeile.zustand = "freigegeben"
        zeile.fassung = f
        zeile.hinweise = None
        zeile.geaendert_am = _now()
        geaendert += 1
    if geaendert:
        db.commit()
        logger.info("%d Übungsanimationen aus der Bibliothek eingespielt", geaendert)
    return geaendert


def verzeichnis(db: Session) -> tuple[dict[str, str], dict[str, UebungsAnimation]]:
    """Name/Alias → Schlüssel, und Schlüssel → Zeile — alles, was nicht verworfen ist.

    Die Bibliothek zuerst: Bei einem Alias, den zwei Animationen führen,
    gewinnt die kuratierte.
    """
    zeilen = (
        db.query(UebungsAnimation)
        .filter(UebungsAnimation.zustand.in_(SICHTBAR))
        .all()
    )
    zeilen.sort(key=lambda z: (z.herkunft != "bibliothek", z.schluessel))
    return schl.index(zeilen), {z.schluessel: z for z in zeilen}
