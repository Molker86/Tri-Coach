"""Die einzige Stelle, an der die Bring-Bibliothek betreten wird.

**Warum synchron, obwohl `bring_api` async ist.** Der Rest des Backends ist
durchgehend synchron — Sitzungen, Jobs, Endpunkte. Eine async-Insel würde sich
durch jede aufrufende Schicht ziehen. Stattdessen läuft hier je Vorgang eine
eigene Ereignisschleife (`asyncio.run`) samt eigener `aiohttp`-Sitzung. Das ist
zulässig, weil FastAPI synchrone Endpunkte ohnehin in einem Arbeitsthread
ausführt: Dort läuft keine Schleife, in die diese hineinfallen könnte.

Ein Vorgang ist immer der **ganze** Ablauf (anmelden, lesen, schreiben) und nie
ein einzelner Aufruf: Bring gibt beim Anmelden ein Zugriffstoken heraus, das die
Bibliothek im Arbeitsspeicher hält. Über mehrere `asyncio.run()` hinweg wäre es
verloren, und jede Zeile Einkaufsliste käme mit einer neuen Anmeldung.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

import aiohttp
from bring_api import (
    Bring,
    BringAuthException,
    BringEMailInvalidException,
    BringItemOperation,
    BringItemsResponse,
    BringListResponse,
    BringParseException,
    BringRequestException,
    BringUserUnknownException,
)

from .errors import (
    BringAnmeldungFehlgeschlagen,
    BringFehler,
    BringNichtErreichbar,
)

T = TypeVar("T")

# Unter Windows schließt die Vorgabe-Ereignisschleife ihre Sockets so spät, dass
# `aiohttp` beim Aufräumen in einen bereits geschlossenen Loop schreibt. Die
# Selector-Schleife hat das Problem nicht.
if sys.platform == "win32":  # pragma: no cover -- plattformabhängig
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@dataclass(slots=True)
class Liste:
    """Eine Einkaufsliste des Kontos."""

    uuid: str
    name: str


@dataclass(slots=True)
class Eintrag:
    """Ein Posten, der auf der Liste steht.

    `spezifikation` ist Brings Freitext neben dem Namen — dort steht die Menge,
    sofern überhaupt eine dasteht.
    """

    uuid: str | None
    name: str
    spezifikation: str = ""


@dataclass(slots=True)
class Schreibauftrag:
    """Was an Bring geschickt wird: ein Posten mit seiner neuen Angabe.

    `uuid` gesetzt heißt „diesen vorhandenen Eintrag überschreiben", leer heißt
    „neu anlegen". Bring gleicht ohne uuid über den Namen ab und würde den
    ältesten Treffer erwischen — bei zwei gleichnamigen Posten der falsche.
    """

    name: str
    spezifikation: str
    uuid: str | None = None


def _uebersetze(fehler: Exception) -> BringFehler:
    if isinstance(fehler, BringFehler):
        return fehler
    if isinstance(
        fehler,
        (BringAuthException, BringEMailInvalidException, BringUserUnknownException),
    ):
        return BringAnmeldungFehlgeschlagen()
    if isinstance(
        fehler,
        (
            BringRequestException,
            BringParseException,
            aiohttp.ClientError,
            TimeoutError,
        ),
    ):
        return BringNichtErreichbar()
    return BringFehler()


def _lauf(arbeit: Callable[[Bring], Awaitable[T]], email: str, passwort: str) -> T:
    """Meldet an und führt `arbeit` mit dem angemeldeten Client aus."""

    async def _innen() -> T:
        async with aiohttp.ClientSession() as sitzung:
            bring = Bring(sitzung, email, passwort)
            await bring.login()
            return await arbeit(bring)

    try:
        return asyncio.run(_innen())
    except Exception as exc:  # noqa: BLE001 -- an genau einer Stelle übersetzt
        raise _uebersetze(exc) from exc


def _als_listen(antwort: BringListResponse) -> list[Liste]:
    return [
        Liste(uuid=e.listUuid, name=e.name or "Liste")
        for e in antwort.lists
        if e.listUuid
    ]


def _als_eintraege(antwort: BringItemsResponse) -> list[Eintrag]:
    return [
        Eintrag(
            uuid=e.uuid or None,
            name=e.itemId,
            spezifikation=e.specification or "",
        )
        for e in antwort.items.purchase
        if e.itemId
    ]


def hole_listen(email: str, passwort: str) -> list[Liste]:
    """Meldet an und gibt die Listen des Kontos zurück — zugleich die Probe."""

    async def _arbeit(bring: Bring) -> list[Liste]:
        return _als_listen(await bring.load_lists())

    return _lauf(_arbeit, email, passwort)


def uebertrage(
    email: str,
    passwort: str,
    list_uuid: str,
    plane: Callable[[list[Eintrag]], list[Schreibauftrag]],
) -> list[Schreibauftrag]:
    """Liest die Liste, lässt `plane` daraus die Aufträge bauen und schreibt sie.

    Lesen und Schreiben liegen bewusst in **einem** Vorgang, mit der
    Entscheidung dazwischen: Worauf aufaddiert wird, muss auf dem beruhen, was
    im selben Atemzug dort stand. Zwischen zwei Anmeldungen hätte jemand anders
    die Liste ändern können.

    `plane` bekommt nur die offenen Posten — die abgehakten (`recently`) bleiben
    draußen. Wer Milch letzte Woche gekauft hat, will sie diese Woche neu auf
    der Liste und nicht an einem erledigten Eintrag aufaddiert.
    """

    async def _arbeit(bring: Bring) -> list[Schreibauftrag]:
        auftraege = plane(_als_eintraege(await bring.get_list(list_uuid)))
        if auftraege:
            await bring.batch_update_list(
                list_uuid,
                [_als_json(a) for a in auftraege],
                BringItemOperation.ADD,
            )
        return auftraege

    return _lauf(_arbeit, email, passwort)


def _als_json(auftrag: Schreibauftrag) -> dict[str, str]:
    posten = {"itemId": auftrag.name, "spec": auftrag.spezifikation}
    if auftrag.uuid:
        posten["uuid"] = auftrag.uuid
    return posten
