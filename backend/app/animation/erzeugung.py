"""Fehlende Animationen finden, von der KI erzeugen lassen, übernehmen.

**Wann erzeugt wird.** Automatisch aus der Weckschleife (`erzeuge_faellige`),
sobald der aktive Plan eine Übung enthält, zu der es keine Animation gibt —
und auf Knopfdruck in der App. Beides nur mit Claude-Zugang, beides höchstens
alle `PAUSE` Stunden je Konto: Ein Lauf, der an einer Übung scheitert, soll
nicht jede Minute wieder Kontingent kosten. In der Praxis ist das selten: Die
Bibliothek deckt ab, was die Pläne bisher enthalten, und eine einmal erzeugte
Animation gilt für alle Konten.

**Was übernommen wird.** Die Antwort geht durch denselben Löser wie die
Bibliothek. Eine Animation, die danach sichtbar im Boden steckt, wird
verworfen, statt dem Athleten eine falsche Bewegung vorzuführen; alles andere
wird als „ungeprüft“ gespeichert und in der App zur Freigabe angeboten.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import KiJob, KiSettings, Plan, PlanSession, UebungsAnimation
from ..zeit import als_utc
from . import einheit
from . import schluessel as schl
from .bibliothek import verzeichnis
from .format import Bewegung, Rezept
from .ki import MAX_JE_LAUF, Auftrag
from .koerper import tiefster_ueberstand
from .loeser import loese_ablauf

logger = logging.getLogger(__name__)

# Frühestens nach so vielen Stunden versucht es die Automatik für ein Konto
# erneut. Nach einem gescheiterten Lauf länger: Scheitert er an etwas, das
# sich nicht von selbst gibt (eine Übung, die der Löser nie annimmt), kostet
# er sonst viermal am Tag Kontingent für nichts.
PAUSE = timedelta(hours=6)
PAUSE_NACH_FEHLER = timedelta(hours=24)

# Ab wie viel Zentimetern im Boden eine KI-Animation nicht übernommen wird.
# Die Bibliothek bleibt überall unter drei; sechs sieht man deutlich.
_MAX_UEBERSTAND_M = 0.06

__all__ = ["MAX_JE_LAUF", "fehlende", "uebernimm", "meldung", "erzeuge_faellige"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def fehlende(db: Session, user_id: int) -> list[Auftrag]:
    """Übungen des aktiven Plans ohne (sichtbare) Animation — je Schlüssel einmal."""
    idx, _ = verzeichnis(db)
    verworfen = {
        a.schluessel: a
        for a in db.query(UebungsAnimation).filter(UebungsAnimation.zustand == "verworfen")
    }
    einheiten = (
        db.query(PlanSession)
        .join(Plan, PlanSession.plan_id == Plan.id)
        .filter(Plan.user_id == user_id, Plan.is_active.is_(True))
        .filter(PlanSession.sport.in_(einheit.UEBUNGSSPORTARTEN))
        .order_by(PlanSession.date, PlanSession.order_in_day)
        .all()
    )
    gesammelt: dict[str, dict] = {}
    for e in einheiten:
        for u in einheit.uebungen(e.sport, e.structure, e.steps_json):
            if idx.get(u.schluessel) or idx.get(schl.normalisiert(u.name_en)):
                continue
            eintrag = gesammelt.setdefault(u.schluessel, {"name": u.name_en, "zeilen": [], "sport": e.sport})
            if u.zeile not in eintrag["zeilen"] and len(eintrag["zeilen"]) < 3:
                eintrag["zeilen"].append(u.zeile)
    return [
        Auftrag(
            schluessel=k,
            name_en=v["name"] or k,
            zeilen=tuple(v["zeilen"]),
            sport=v["sport"],
            rueckmeldung=verworfen[k].rueckmeldung if k in verworfen else None,
        )
        for k, v in gesammelt.items()
    ]


@dataclass
class Uebernahme:
    gespeichert: list[str] = field(default_factory=list)
    fehler: list[str] = field(default_factory=list)


def _rezepte_aus(antwort) -> list[dict]:
    daten = antwort.struktur
    if daten is None:
        text = (antwort.text or "").strip()
        try:
            daten = json.loads(text)
        except json.JSONDecodeError:
            treffer = re.search(r"\{.*\}", text, re.S)
            daten = json.loads(treffer.group(0)) if treffer else {}
    liste = daten.get("animationen") if isinstance(daten, dict) else None
    return [r for r in liste if isinstance(r, dict)] if isinstance(liste, list) else []


def uebernimm(db: Session, auftraege: list[Auftrag], antwort, job_id: int | None) -> Uebernahme:
    """Die Rezepte der Antwort prüfen, lösen und als „ungeprüft“ ablegen."""
    ergebnis = Uebernahme()
    nach_schluessel = {a.schluessel: a for a in auftraege}
    beantwortet: set[str] = set()
    try:
        rezepte = _rezepte_aus(antwort)
    except (json.JSONDecodeError, AttributeError) as exc:
        ergebnis.fehler.append(f"Antwort nicht lesbar ({exc})")
        return ergebnis

    for roh in rezepte:
        auftrag = nach_schluessel.get(str(roh.get("schluessel", ""))) or nach_schluessel.get(
            schl.normalisiert(str(roh.get("name", "")))
        )
        if auftrag is None:
            ergebnis.fehler.append(f"„{roh.get('schluessel')}“ war nicht bestellt")
            continue
        beantwortet.add(auftrag.schluessel)
        roh = {**roh, "schluessel": auftrag.schluessel, "name": roh.get("name") or auftrag.name_en}
        try:
            rezept = Rezept.model_validate(roh)
            bewegung, hinweise = loese_ablauf(rezept.als_dict())
            bewegung = Bewegung.model_validate(bewegung).model_dump(exclude_none=True)
        except Exception as exc:  # noqa: BLE001 — eine kaputte Übung kippt nicht die anderen
            ergebnis.fehler.append(f"{auftrag.name_en}: {str(exc).splitlines()[0][:160]}")
            continue
        ueberstand = max(tiefster_ueberstand(b["pose"]) for b in bewegung["ablauf"])
        if ueberstand > _MAX_UEBERSTAND_M:
            ergebnis.fehler.append(f"{auftrag.name_en}: Körper steckt {ueberstand * 100:.0f} cm im Boden")
            continue

        zeile = db.scalar(select(UebungsAnimation).where(UebungsAnimation.schluessel == auftrag.schluessel))
        if zeile is None:
            zeile = UebungsAnimation(schluessel=auftrag.schluessel)
            db.add(zeile)
        elif zeile.herkunft == "bibliothek" and zeile.zustand != "verworfen":
            # Die kuratierte Fassung ist in der Zwischenzeit (wieder) da.
            continue
        zeile.name = bewegung["name"]
        zeile.aliase = list(bewegung.get("aliase") or [])
        zeile.daten = {k: v for k, v in bewegung.items() if k not in ("schluessel", "name", "aliase")}
        zeile.herkunft = "ki"
        zeile.zustand = "ungeprueft"
        zeile.fassung = None
        zeile.hinweise = hinweise or None
        zeile.rueckmeldung = None
        zeile.ki_job_id = job_id
        zeile.model_used = getattr(antwort, "modell", None)
        zeile.geaendert_am = _now()
        ergebnis.gespeichert.append(auftrag.name_en)

    if not rezepte:
        ergebnis.fehler.append("Die Antwort enthielt keine Rezepte")
    elif fehlend := [a.name_en for a in auftraege if a.schluessel not in beantwortet]:
        ergebnis.fehler.append(f"Ohne Antwort: {', '.join(fehlend)}")
    db.flush()
    return ergebnis


def meldung(ergebnis: Uebernahme) -> str:
    n = len(ergebnis.gespeichert)
    text = (
        f"{n} Animation{'en' if n != 1 else ''} erstellt ({', '.join(ergebnis.gespeichert)}) — "
        "bitte in der App ansehen und freigeben."
    )
    if ergebnis.fehler:
        text += f" Nicht verwertbar: {'; '.join(ergebnis.fehler[:3])}."
    return text


def letzter_versuch(db: Session, user_id: int) -> KiJob | None:
    from ..ki.runner import ANIMATION

    return (
        db.query(KiJob)
        .filter(KiJob.user_id == user_id, KiJob.kind == ANIMATION)
        .order_by(KiJob.started_at.desc())
        .first()
    )


def erzeuge_faellige(jetzt: datetime | None = None) -> int:
    """Für jedes Konto mit fehlenden Animationen einen Lauf starten, wenn es darf.

    Gibt die Zahl der gestarteten Läufe zurück. Wirft nie — der Aufrufer ist
    die Weckschleife.
    """
    from ..database import SessionLocal
    from ..ki.client import ist_angemeldet, token_aus
    from ..ki.runner import ANIMATION, LaeuftBereits, runner

    jetzt = als_utc(jetzt) if jetzt else _now()
    gestartet = 0
    try:
        with SessionLocal() as db:
            konten = [u for (u,) in db.query(Plan.user_id).filter(Plan.is_active.is_(True)).distinct()]
            kandidaten = []
            for user_id in konten:
                if not fehlende(db, user_id):
                    continue
                letzter = letzter_versuch(db, user_id)
                if letzter is not None:
                    pause = PAUSE_NACH_FEHLER if letzter.state == "failed" else PAUSE
                    if jetzt - als_utc(letzter.started_at) < pause:
                        continue
                if runner.laeuft_fuer(user_id) is not None:
                    continue
                einstellungen = db.scalar(select(KiSettings).where(KiSettings.user_id == user_id))
                token = token_aus(einstellungen.token_encrypted) if einstellungen else None
                kandidaten.append((user_id, token))
        for user_id, token in kandidaten:
            # Der teuerste Test zuletzt: Er fragt die CLI (60 s gecacht).
            if not ist_angemeldet(token):
                continue
            try:
                job_id = runner.starte(user_id, ANIMATION)
            except LaeuftBereits:
                continue
            logger.info("Animationslauf %s für Nutzer %s gestartet", job_id, user_id)
            gestartet += 1
    except Exception:  # noqa: BLE001
        logger.exception("Automatische Animationserzeugung fehlgeschlagen")
    return gestartet
