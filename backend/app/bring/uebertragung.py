"""Die Einkaufsliste geht nach Bring — und addiert sich auf, was dort steht.

Der Kern ist `plane_auftraege()`: reine Rechnung, ohne Netz, deshalb einzeln
prüfbar. `uebertrage()` reicht sie als Rückruf in die eine Bring-Sitzung hinein,
in der gelesen und geschrieben wird.

**Warum ein Riegel je Tag.** Bring kennt keine Mengenfelder; addiert wird über
den Freitext. Ein zweiter Knopfdruck würde deshalb jede Menge ein zweites Mal
draufrechnen, ohne dass das jemand bemerkt. `ErnaehrungsTag.bring_uebertragen_am`
hält fest, was schon drüben ist — wer trotzdem alles will, sagt es ausdrücklich.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from .. import einkaufsliste
from ..crypto import EntschluesselungFehlgeschlagen, entschluessle
from ..einkaufsliste import Posten
from ..models import BringAccount, Ernaehrungsplan, ErnaehrungsTag
from ..zeit import jetzt_utc
from . import client
from .client import Eintrag, Schreibauftrag
from .errors import BringFehler, BringListeFehlt, BringNichtVerbunden


@dataclass(slots=True)
class Auswahl:
    """Welche Tage des Plans übertragen werden — und was davon schon drüben war."""

    tage: list[ErnaehrungsTag] = field(default_factory=list)
    bereits_uebertragen: int = 0
    von: date | None = None
    bis: date | None = None


@dataclass(slots=True)
class Ergebnis:
    """Was die Übertragung bewirkt hat."""

    hinzugefuegt: int = 0
    ergaenzt: int = 0
    liste: str = ""


def waehle_tage(
    plan: Ernaehrungsplan, heute: date, *, alles: bool = False
) -> Auswahl:
    """Die Tage ab heute bis Planende — ohne die, die schon übertragen sind.

    Vergangene Tage bleiben draußen: Was gestern gegessen wurde, muss heute
    niemand mehr einkaufen.
    """
    kuenftig = [t for t in plan.tage if t.date >= heute]
    schon = [t for t in kuenftig if t.bring_uebertragen_am is not None]
    offen = kuenftig if alles else [t for t in kuenftig if t.bring_uebertragen_am is None]

    return Auswahl(
        tage=offen,
        bereits_uebertragen=len(schon),
        von=offen[0].date if offen else None,
        bis=offen[-1].date if offen else None,
    )


def plane_auftraege(
    vorhanden: list[Eintrag], posten: list[Posten]
) -> tuple[list[Schreibauftrag], Ergebnis]:
    """Entscheidet je Posten: neuen Eintrag anlegen oder vorhandenen aufstocken.

    Getroffen wird über den normalisierten Namen. Steht ein Lebensmittel
    mehrfach auf der Bring-Liste, gewinnt der erste — auf alle aufzuaddieren
    würde die Menge vervielfachen.
    """
    treffer: dict[str, Eintrag] = {}
    for eintrag in vorhanden:
        treffer.setdefault(einkaufsliste.schluessel(eintrag.name), eintrag)

    auftraege: list[Schreibauftrag] = []
    ergebnis = Ergebnis()

    for eines in posten:
        alt = treffer.get(einkaufsliste.schluessel(eines.name))
        if alt is None:
            auftraege.append(Schreibauftrag(name=eines.name, spezifikation=eines.text))
            ergebnis.hinzugefuegt += 1
        else:
            auftraege.append(
                Schreibauftrag(
                    # Brings eigene Schreibweise behalten: Ein Eintrag, dessen
                    # Name sich ändert, wird in der App erst nach einem
                    # vollständigen Neuladen richtig angezeigt.
                    name=alt.name,
                    spezifikation=einkaufsliste.verschmelze(
                        alt.spezifikation, eines.menge, eines.einheit
                    ),
                    uuid=alt.uuid,
                )
            )
            ergebnis.ergaenzt += 1

    return auftraege, ergebnis


def zugangsdaten(konto: BringAccount | None) -> tuple[str, str, str]:
    """E-Mail, Passwort und Listenkennung — oder ein sprechender Fehler."""
    if konto is None or not konto.email or not konto.password_encrypted:
        raise BringNichtVerbunden()
    if not konto.list_uuid:
        raise BringListeFehlt()
    try:
        return konto.email, entschluessle(konto.password_encrypted), konto.list_uuid
    except EntschluesselungFehlgeschlagen as exc:
        raise BringFehler(
            "Das gespeicherte Bring-Passwort lässt sich nicht mehr lesen. "
            "Bitte trage es in den Einstellungen erneut ein."
        ) from exc


def uebertrage(
    db: Session, konto: BringAccount, auswahl: Auswahl, posten: list[Posten]
) -> Ergebnis:
    """Schreibt die Posten auf die Liste und vermerkt die übertragenen Tage.

    Vermerkt wird erst **nach** dem erfolgreichen Schreiben: Ein Tag, der als
    übertragen gilt, ohne es zu sein, fehlt im Einkauf und fällt niemandem auf.
    """
    email, passwort, list_uuid = zugangsdaten(konto)
    gemeldet = Ergebnis()

    def _plane(vorhanden: list[Eintrag]) -> list[Schreibauftrag]:
        auftraege, ergebnis = plane_auftraege(vorhanden, posten)
        gemeldet.hinzugefuegt = ergebnis.hinzugefuegt
        gemeldet.ergaenzt = ergebnis.ergaenzt
        return auftraege

    client.uebertrage(email, passwort, list_uuid, _plane)

    jetzt = jetzt_utc()
    for tag in auswahl.tage:
        tag.bring_uebertragen_am = jetzt
    konto.last_push_at = jetzt
    konto.status = "connected"
    konto.status_message = None
    db.commit()

    gemeldet.liste = konto.list_name or "deiner Einkaufsliste"
    return gemeldet
