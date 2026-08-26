"""Profilwerte setzen und ihren Verlauf mitschreiben.

Aus `routers/profile.py` herausgezogen, weil der Garmin-Abgleich dieselbe Regel
braucht: Ein neuer Gewichts- oder HRV-Wert muss im Verlauf auftauchen, gleich ob
er von Hand kam oder vom Gerät. Läge die Logik weiterhin im Router, hätte die
Trendkurve Lücken genau dort, wo die Daten am dichtesten sind.
"""

import statistics
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AthleteProfile, ProfileHistory, WellnessDay

# Werte, deren Verlauf für die Trainingssteuerung interessant ist.
TRACKED_FIELDS = ("weight_kg", "resting_hr", "hrv_rmssd", "vo2max", "max_hr", "ftp_watts")


def uebernehme_profilwerte(
    db: Session, user_id: int, profil: AthleteProfile, updates: dict[str, Any]
) -> bool:
    """Setzt Profilwerte und schreibt bei Bedarf einen Verlaufseintrag.

    Gibt zurück, ob ein Verlaufseintrag entstanden ist. Committet **nicht** —
    das bleibt beim Aufrufer, damit ein Profil-Update eine Transaktion bleibt.
    """
    verlaufswert_geaendert = any(
        feld in updates and updates[feld] != getattr(profil, feld)
        for feld in TRACKED_FIELDS
    )

    for feld, wert in updates.items():
        setattr(profil, feld, wert)

    if verlaufswert_geaendert:
        db.add(
            ProfileHistory(
                user_id=user_id,
                **{feld: getattr(profil, feld) for feld in TRACKED_FIELDS},
            )
        )
    return verlaufswert_geaendert


# Ab welcher Abweichung ein Wert überhaupt neu geschrieben wird. Ohne diese
# Schwellen entstünde bei jedem täglichen Abgleich ein Verlaufseintrag, der
# nichts aussagt, und der Verlauf wäre nach einem Monat unlesbar.
_MINDESTABWEICHUNG: dict[str, float] = {
    "weight_kg": 0.2,
    "body_fat_pct": 0.3,
    "resting_hr": 1,
    "hrv_rmssd": 1,
    "vo2max": 0.1,
    "lthr": 1,
}


def _juengster(tage: list[WellnessDay], feld: str) -> Any:
    for tag in tage:  # absteigend sortiert
        wert = getattr(tag, feld)
        if wert is not None:
            return wert
    return None


def uebernehme_aus_garmin(
    db: Session,
    user_id: int,
    heute: date | None = None,
    leistungswerte: dict[str, Any] | None = None,
) -> list[str]:
    """Trägt die Werte aus Garmin ins Profil: Fitnessdaten und Schwellenpuls.

    Aus den Fitnessdaten kommen Gewicht, Körperfett, Ruhepuls, HRV und VO2max;
    `leistungswerte` bringt mit, was nur hinter eigenen Endpunkten steht
    (Schwellenpuls und Bestzeiten — geholt in
    `garmin.sync.hole_leistungswerte`). Beides geht bewusst durch **eine**
    Übernahme: Zwei Aufrufe hinterließen je Abgleich zwei fast gleiche Einträge
    im Werteverlauf.

    Bewusst **nicht** übernommen wird der Maximalpuls: Garmin schätzt ihn, liegt
    dabei oft daneben, und er steuert sämtliche Herzfrequenzzonen dieser App.
    Er bleibt Handarbeit — ebenso FTP, Schwellenpace Laufen und die kritische
    Schwimmgeschwindigkeit.

    Gibt die geänderten Felder zurück.
    """
    heute = heute or date.today()
    profil = db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user_id))
    if profil is None:
        return []

    tage = db.scalars(
        select(WellnessDay)
        .where(
            WellnessDay.user_id == user_id,
            WellnessDay.date >= heute - timedelta(days=30),
        )
        .order_by(WellnessDay.date.desc())
    ).all()

    neu: dict[str, Any] = dict(leistungswerte or {})
    if not tage:
        return _schreibe(db, user_id, profil, neu)

    # Gewicht und Körperfett sind Punktmessungen — der jüngste Wert gilt.
    if (gewicht := _juengster(tage, "weight_kg")) is not None:
        neu["weight_kg"] = gewicht
    if (fett := _juengster(tage, "body_fat_pct")) is not None:
        neu["body_fat_pct"] = fett

    # Ruhepuls dagegen als Median der letzten sieben Tage: Ein einzelner
    # Ausreißer (schlechte Nacht, Infekt) würde sonst alle Karvonen-Zonen
    # verschieben, und die stehen in jedem Trainingsplan.
    letzte_woche = [
        tag.resting_hr
        for tag in tage
        if tag.resting_hr is not None and tag.date >= heute - timedelta(days=7)
    ]
    if letzte_woche:
        neu["resting_hr"] = int(round(statistics.median(letzte_woche)))

    if (hrv := _juengster(tage, "hrv_last_night_ms")) is not None:
        # `hrv_rmssd` ist nur noch ein Altname der Spalte — geführt wird der
        # Wert überall als HRV in ms. Umbenennen wäre eine Migration ohne Gewinn.
        neu["hrv_rmssd"] = hrv

    vo2 = _juengster(tage, "vo2max_run") or _juengster(tage, "vo2max_bike")
    if vo2 is not None:
        neu["vo2max"] = vo2

    return _schreibe(db, user_id, profil, neu)


def _schreibe(
    db: Session, user_id: int, profil: AthleteProfile, neu: dict[str, Any]
) -> list[str]:
    """Übernimmt nur, was sich wirklich unterscheidet. Gibt die Felder zurück."""
    relevant = {
        feld: wert
        for feld, wert in neu.items()
        if _weicht_ab(getattr(profil, feld), wert, _MINDESTABWEICHUNG.get(feld, 0))
    }
    if not relevant:
        return []

    uebernehme_profilwerte(db, user_id, profil, relevant)
    db.commit()
    return sorted(relevant)


def _weicht_ab(alt: Any, neu: Any, schwelle: float) -> bool:
    if neu is None:
        return False
    if alt is None:
        return True
    try:
        return abs(float(neu) - float(alt)) >= schwelle
    except (TypeError, ValueError):
        return alt != neu
