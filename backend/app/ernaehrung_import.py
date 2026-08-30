"""Liest die KI-Antwort auf einen Ernährungsplan und übernimmt sie.

Eigenes Modul und kein Anbau an `plan_import.py`: Dort steht die ganze
Planlogik — Wochen auffalten, Sportarten normalisieren, Bauplan prüfen —, und
davon braucht die Ernährung nichts. Wiederverwendet wird nur, was tatsächlich
allgemein ist: der klammerzählende Leser (`_gelesene_objekte`), die lesbare
Fehlermeldung aus einem Pydantic-Fehler und `PlanImportError` selbst. Letzteres
ist wichtig: `ki/runner._lauf` behandelt genau diesen Typ als Importfehler und
protokolliert ihn nicht als Absturz.

Dieselbe Linie wie überall beim Import: **warnen, nicht ablehnen.** Die Antwort
wird nirgends gespeichert — ein abgelehnter Lauf ist ganz verloren und hat
trotzdem Kontingent gekostet.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from .einkaufsliste import normalisiere
from .models import (
    Ernaehrungsplan,
    ErnaehrungsProfil,
    ErnaehrungsMahlzeit,
    ErnaehrungsSupplement,
    ErnaehrungsTag,
    ErnaehrungsZutat,
    Plan,
)
from .paketformat import ist_datenpaket
from .plan_import import (
    PlanImportError,
    _gekuerzt,
    _gelesene_objekte,
    _readable_validation_error,
)
from .schemas import AIErnaehrungBody, AIErnaehrungImport

# Schlüssel, unter denen Modelle den Block ablegen. Die App verlangt
# `ernaehrungsplan`; die übrigen kosten nichts und fangen die naheliegenden
# Rückfälle ab — auch den mit „ä", den ein deutsches Modell gern schreibt.
_HUELLEN = (
    "ernaehrungsplan",
    "ernährungsplan",
    "ernaehrung",
    "ernährung",
    "nutrition_plan",
    "plan",
)

# Ab wie viel Prozent Abweichung zwischen genannten Kalorien und der Summe aus
# den Makronährstoffen gemeldet wird. Das ist die **einzige** Zusage im ganzen
# Plan, die die App nachrechnen kann — dieselbe Rolle wie `_dauer_weicht_ab`
# beim Bauplan. Großzügig, weil Ballaststoffe und Rundungen echte Abweichungen
# erzeugen und eine Warnung an jedem Tag niemandem hilft.
MAKRO_TOLERANZ_PCT = 15

# Wie weit ein neuer Plan in die Vergangenheit erbt. Ohne Grenze schleppt ein
# oft neu geplanter Ernährungsplan jeden je geplanten Tag mit sich.
ERBE_TAGE = 7


# Woran ein Ernährungstag zu erkennen ist. Positiv formuliert und nicht über
# die Abwesenheit von `sessions`: Ein Trainingsblock trägt dieselbe Liste unter
# `days`, und „hat eine Tagesliste" allein hätte ihn hier als Ernährungsplan
# durchgehen lassen — samt der Feldliste statt der benannten Verwechslung.
_TAGESSCHLUESSEL = ("tage", "days")
_TAGESMARKER = ("datum", "mahlzeiten", "meals")


def _ist_ernaehrungsform(wert: Any) -> bool:
    """Trägt das Objekt eine Tagesliste, die nach Ernährung aussieht?

    Gewählt wird nach der **Form** und nicht nach der Reihenfolge — dieselbe
    Regel wie bei `plan_import._plan_darin`: Schreibt die KI eine Notiz davor
    oder benennt die Hülle anders, ist das erste Objekt nicht der Plan.
    """
    if not isinstance(wert, dict):
        return False
    for schluessel in _TAGESSCHLUESSEL:
        liste = wert.get(schluessel)
        if isinstance(liste, list) and liste and isinstance(liste[0], dict):
            if any(marker in liste[0] for marker in _TAGESMARKER):
                return True
    return False


def _plan_darin(daten: Any, tiefe: int = 2) -> dict | None:
    """Sucht das Planobjekt, egal unter welchem Namen und in welcher Hülle."""
    if _ist_ernaehrungsform(daten):
        return daten
    if tiefe <= 0 or not isinstance(daten, dict):
        return None
    for schluessel in _HUELLEN:
        treffer = _plan_darin(daten.get(schluessel), tiefe - 1)
        if treffer is not None:
            return treffer
    # Auch unter einem Namen, den niemand vorhergesehen hat.
    for wert in daten.values():
        treffer = _plan_darin(wert, tiefe - 1)
        if treffer is not None:
            return treffer
    return None


_DATENPAKET_EINGEFUEGT = (
    "Das ist das Datenpaket, das an die KI geht — nicht ihre "
    "Antwort. Kopiere den Text in eine KI und füge hier ein, was "
    "sie zurückgibt."
)


def _falsche_antwort(objekte: list[dict], roh: str = "") -> str | None:
    """Benennt die beiden naheliegenden Verwechslungen.

    „Field required" beschreibt, was fehlt — der Athlet muss aber wissen, *was*
    dasteht, denn der nächste Handgriff ist in beiden Fällen ein anderer.

    Das Datenpaket am Rohtext, nicht mehr an obersten Schlüsseln: Sein Datenteil
    ist seit der Umstellung auf Tabellen kein JSON-Objekt mehr — dieselbe
    Überlegung wie in `plan_import._falsche_antwort`.
    """
    if roh and ist_datenpaket(roh):
        return _DATENPAKET_EINGEFUEGT

    for daten in objekte:
        if "athlet" in daten or "trainingswunsch" in daten:
            return _DATENPAKET_EINGEFUEGT
        # Auch eine Ebene tiefer: Der Trainingsblock steckt fast immer in einer
        # `plan`-Hülle, und nur nach den obersten Schlüsseln zu fragen ließe
        # genau den häufigsten Fall durchrutschen.
        ebenen = [daten, *(w for w in daten.values() if isinstance(w, dict))]
        if any(
            k in ebene for ebene in ebenen for k in ("days", "weeks", "sessions")
        ):
            return (
                "Die Antwort enthält einen Trainingsblock, erwartet war ein "
                "Ernährungsplan. Ein Trainingsblock wird im Trainingsplan "
                "übernommen, nicht hier."
            )
    return None


def parse_ernaehrung_antwort(raw: str) -> AIErnaehrungBody:
    """Liest die Antwort auf einen Ernährungsplan.

    Toleriert dieselben Formen wie der Blockparser: die verlangte Hülle, ein
    anders benanntes Feld darum herum und das nackte Planobjekt.
    """
    objekte = _gelesene_objekte(raw)

    kandidat: dict | None = None
    for daten in objekte:
        kandidat = _plan_darin(daten)
        if kandidat is not None:
            break

    if kandidat is None:
        # Erst wenn nichts mit Tagesliste da ist, wird nach der Verwechslung
        # gefragt — sonst scheiterte ein gültiger Plan an einem Objekt, das
        # zufällig danebensteht.
        if (meldung := _falsche_antwort(objekte, raw)) is not None:
            raise PlanImportError(meldung)
        felder = ", ".join(sorted(objekte[0].keys())[:8]) if objekte else ""
        raise PlanImportError(
            "In der Antwort war kein Ernährungsplan zu finden. Erwartet wird "
            'ein Objekt mit dem Schlüssel "ernaehrungsplan" und einer Liste '
            '"tage" darin.'
            + (f" Gefunden wurden stattdessen: {felder}." if felder else "")
        )

    # `days` als Rückfall auf `tage`: Ein englisch antwortendes Modell trifft
    # sonst die Form, aber nicht den Namen.
    if "tage" not in kandidat and isinstance(kandidat.get("days"), list):
        kandidat = {**kandidat, "tage": kandidat["days"]}

    try:
        gelesen = AIErnaehrungImport.model_validate({"ernaehrungsplan": kandidat})
    except ValidationError as exc:
        raise PlanImportError(_readable_validation_error(exc)) from exc

    return gelesen.ernaehrungsplan


def _makros_passen_nicht(tag: Any) -> str | None:
    """Rechnet die Tagessumme gegen ihre Makronährstoffe.

    4 kcal je Gramm Kohlenhydrat und Eiweiß, 9 je Gramm Fett. Nur, wenn alle
    vier Angaben da sind — aus zwei von dreien lässt sich nichts folgern.
    """
    if None in (tag.kalorien_kcal, tag.kohlenhydrate_g, tag.protein_g, tag.fett_g):
        return None
    if not tag.kalorien_kcal:
        return None
    gerechnet = 4 * tag.kohlenhydrate_g + 4 * tag.protein_g + 9 * tag.fett_g
    abweichung = abs(gerechnet - tag.kalorien_kcal) / tag.kalorien_kcal * 100
    if abweichung <= MAKRO_TOLERANZ_PCT:
        return None
    return (
        f"{tag.datum.isoformat()} ({tag.kalorien_kcal} kcal genannt, "
        f"{gerechnet} kcal aus den Makros)"
    )


def pruefe_ernaehrungsplan(
    body: AIErnaehrungBody,
    *,
    start_date: date | None = None,
    days: int | None = None,
) -> list[str]:
    """Nicht-blockierende Hinweise zum gelieferten Ernährungsplan."""
    warnings: list[str] = []
    tage = body.tage

    if not tage:
        return ["Der Ernährungsplan kam ohne einen einzigen Tag."]

    daten = sorted(t.datum for t in tage)

    if start_date is not None and days:
        erwartet = {start_date + timedelta(days=i) for i in range(days)}
        fehlend = sorted(erwartet - set(daten))
        if fehlend:
            warnings.append(
                f"Für {len(fehlend)} Tag(e) kam kein Eintrag: "
                f"{_gekuerzt([d.isoformat() for d in fehlend])}."
            )
        ueberzaehlig = sorted(set(daten) - erwartet)
        if ueberzaehlig:
            warnings.append(
                f"{len(ueberzaehlig)} Tag(e) liegen außerhalb des angeforderten "
                f"Zeitraums: {_gekuerzt([d.isoformat() for d in ueberzaehlig])}."
            )

    doppelt = sorted({d.isoformat() for d in daten if daten.count(d) > 1})
    if doppelt:
        warnings.append(f"Doppelt geliefert: {_gekuerzt(doppelt)}.")

    ohne_mahlzeit = [t.datum.isoformat() for t in tage if not t.mahlzeiten]
    if ohne_mahlzeit:
        warnings.append(
            f"An {len(ohne_mahlzeit)} Tag(en) steht keine Mahlzeit: "
            f"{_gekuerzt(ohne_mahlzeit)}. Auch an einem Ruhetag wird gegessen."
        )

    ohne_summe = [
        t.datum.isoformat()
        for t in tage
        if t.kalorien_kcal is None and t.kohlenhydrate_g is None
    ]
    if ohne_summe:
        warnings.append(
            f"An {len(ohne_summe)} Tag(en) fehlen die Tagessummen: "
            f"{_gekuerzt(ohne_summe)}."
        )

    # Ohne Zutaten bleibt die Einkaufsliste leer. Kein Grund abzulehnen — der
    # Plan ist deshalb nicht schlechter —, aber einer, es zu sagen.
    if not any(m.zutaten for t in tage for m in t.mahlzeiten):
        warnings.append(
            "Keine Mahlzeit nennt einzelne Zutaten. Der Plan lässt sich lesen, "
            "aber nicht auf die Einkaufsliste übertragen."
        )

    if schief := [m for t in tage if (m := _makros_passen_nicht(t))]:
        warnings.append(
            "Kalorien und Makronährstoffe passen nicht zusammen: "
            f"{_gekuerzt(schief)}. Gerechnet mit 4 kcal je Gramm Kohlenhydrat "
            "und Eiweiß, 9 je Gramm Fett."
        )

    return warnings


def baue_ernaehrungsplan(
    body: AIErnaehrungBody, user_id: int, trainingsplan: Plan | None
) -> Ernaehrungsplan:
    """Baut den Plan samt Tagen, Mahlzeiten und Supplementen — ohne zu committen."""
    daten = sorted(t.datum for t in body.tage)
    plan = Ernaehrungsplan(
        user_id=user_id,
        plan_id=trainingsplan.id if trainingsplan else None,
        start_date=daten[0],
        end_date=daten[-1],
        title=(body.titel or "Ernährungsplan").strip()[:255],
        summary=body.ausrichtung,
        begruendung=body.begruendung,
        raw_json=body.model_dump(mode="json"),
    )

    for eintrag in sorted(body.tage, key=lambda t: t.datum):
        tag = ErnaehrungsTag(
            date=eintrag.datum,
            trainingshinweis=eintrag.trainingshinweis,
            kalorien_kcal=eintrag.kalorien_kcal,
            kohlenhydrate_g=eintrag.kohlenhydrate_g,
            protein_g=eintrag.protein_g,
            fett_g=eintrag.fett_g,
            fluessigkeit_ml=eintrag.fluessigkeit_ml,
            notiz=eintrag.notiz,
        )
        for i, mahlzeit in enumerate(eintrag.mahlzeiten):
            eintragung = ErnaehrungsMahlzeit(
                order_in_day=i,
                zeitpunkt=(mahlzeit.zeitpunkt or "").strip()[:48],
                name=(mahlzeit.name or "").strip()[:120],
                beschreibung=mahlzeit.beschreibung,
                bezug=mahlzeit.bezug,
                kalorien_kcal=mahlzeit.kalorien_kcal,
                kohlenhydrate_g=mahlzeit.kohlenhydrate_g,
                protein_g=mahlzeit.protein_g,
                fett_g=mahlzeit.fett_g,
            )
            for j, zutat in enumerate(mahlzeit.zutaten):
                menge, einheit = normalisiere(zutat.menge, zutat.einheit)
                eintragung.zutaten.append(
                    ErnaehrungsZutat(
                        order_index=j,
                        name=zutat.name[:120],
                        menge=menge,
                        einheit=einheit,
                    )
                )
            tag.mahlzeiten.append(eintragung)
        plan.tage.append(tag)

    for i, supplement in enumerate(body.supplemente):
        plan.supplemente.append(
            ErnaehrungsSupplement(
                order_index=i,
                name=supplement.name.strip()[:120],
                dosierung=supplement.dosierung,
                zeitpunkt=supplement.zeitpunkt,
                begruendung=supplement.begruendung,
            )
        )

    return plan


@dataclass(slots=True)
class ErnaehrungsUebernahme:
    plan: Ernaehrungsplan
    warnings: list[str] = field(default_factory=list)


def _erbe_frueheres(
    db: Session, neu: Ernaehrungsplan, alt: Ernaehrungsplan, grenze: date
) -> None:
    """Zieht die Tage des abgelösten Plans, die vor `grenze` liegen, um.

    Dieselbe Überlegung wie beim Trainingsblock (`uebernimm_vergangenheit`): Wer
    morgen neu plant, soll heute nicht verlieren — auf der Seite stünde sonst
    ein leerer Montag über einem Plan, der ab Dienstag gilt. Die Zeile zieht um,
    statt zu sterben, damit weder eine zweite Liste noch ein zweiter aktiver
    Plan nötig wird.

    Geerbt wird aber nur die letzte Woche (`ERBE_TAGE`). Anders als der
    Trainingsblock trägt die Ernährung nichts nach: Es gibt keine
    Umsetzungsquote und keinen Abgleich, der einen alten Tag noch einmal liest —
    er wäre reiner Ballast, der sich mit jeder Neuplanung um ein paar Tage
    verlängert.

    `grenze` kommt von außen und ist der **ursprüngliche** Beginn des neuen
    Plans. Ihn hier aus `neu.start_date` zu lesen wäre falsch, sobald ein
    zweiter Vorgänger folgt: Der erste hat den Beginn dann schon nach hinten
    gezogen, und die zweite Runde erbte zu wenig.
    """
    fruehestens = grenze - timedelta(days=ERBE_TAGE)
    umzug = [tag for tag in alt.tage if fruehestens <= tag.date < grenze]
    if not umzug:
        return
    # Über die **Beziehung** umhängen, nicht über die Fremdschlüsselspalte: An
    # `alt.tage` hängt `cascade="all, delete-orphan"`, und die Sammlung im
    # Speicher weiß von einer direkt gesetzten Spalte nichts. Das anschließende
    # `db.delete(alt)` nähme die gerade geerbten Zeilen sonst wieder mit — der
    # Umzug wäre folgenlos, und niemand sähe es.
    for tag in umzug:
        neu.tage.append(tag)
    neu.start_date = min(neu.start_date, *(tag.date for tag in umzug))
    db.flush()


def uebernimm_ernaehrungsplan(
    db: Session,
    user_id: int,
    raw: str,
    *,
    trainingsplan: Plan | None = None,
    start_date: date | None = None,
    days: int | None = None,
) -> ErnaehrungsUebernahme:
    """Macht aus einer KI-Antwort den Ernährungsplan des Nutzers.

    Eine Funktion für beide Auslöser — den eingefügten Text und die Antwort, die
    der Server selbst geholt hat. Wirft `PlanImportError`; dann bleibt die
    Datenbank unberührt.

    Anders als beim Trainingsblock hängt hier nichts nach außen: kein
    Garmin-Kalender, keine Umsetzungsquote, kein `SessionLog`. Der abgelöste
    Plan gibt deshalb seine früheren Tage ab und verschwindet — es gibt immer
    genau einen.
    """
    body = parse_ernaehrung_antwort(raw)
    warnings = pruefe_ernaehrungsplan(body, start_date=start_date, days=days)

    plan = baue_ernaehrungsplan(body, user_id, trainingsplan)
    db.add(plan)
    db.flush()

    # Der eigene Beginn, bevor das Erbe ihn nach hinten zieht.
    grenze = plan.start_date
    vorgaenger = (
        db.query(Ernaehrungsplan)
        .filter(Ernaehrungsplan.user_id == user_id, Ernaehrungsplan.id != plan.id)
        .all()
    )
    for alt in vorgaenger:
        _erbe_frueheres(db, plan, alt, grenze)
        db.delete(alt)

    db.commit()
    db.refresh(plan)
    return ErnaehrungsUebernahme(plan=plan, warnings=warnings)


def aktiver_ernaehrungsplan(db: Session, user_id: int) -> Ernaehrungsplan | None:
    """Der eine Ernährungsplan des Nutzers, falls es einen gibt."""
    return (
        db.query(Ernaehrungsplan)
        .filter(Ernaehrungsplan.user_id == user_id)
        .order_by(Ernaehrungsplan.created_at.desc())
        .first()
    )


def hole_profil(db: Session, user_id: int) -> ErnaehrungsProfil:
    """Das Ernährungsprofil des Nutzers, notfalls frisch angelegt.

    Eine Zeile je Nutzer, die beim ersten Zugriff entsteht — so muss weder die
    Registrierung daran denken noch eine Migration bestehende Konten
    nachrüsten. Dieselbe Handhabung wie bei `ki.runner._einstellungen()`.
    """
    profil = (
        db.query(ErnaehrungsProfil)
        .filter(ErnaehrungsProfil.user_id == user_id)
        .first()
    )
    if profil is None:
        profil = ErnaehrungsProfil(user_id=user_id)
        db.add(profil)
        db.commit()
        db.refresh(profil)
    return profil


def profil_hinweise(db: Session, user_id: int) -> str | None:
    """Nur der Freitext — ohne die Zeile anzulegen, wenn es keine gibt.

    Der Export ist ein reiner Leser; eine Zeile anzulegen, bloß weil geplant
    wird, wäre ein Schreibvorgang aus einem Lesevorgang heraus.
    """
    zeile = (
        db.query(ErnaehrungsProfil.hinweise)
        .filter(ErnaehrungsProfil.user_id == user_id)
        .first()
    )
    return (zeile[0] or "").strip() or None if zeile else None
