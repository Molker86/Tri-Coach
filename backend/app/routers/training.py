"""Kraft- und Mobility-Workouts in der iOS-App: Ablauf holen, Ergebnis melden.

Siehe `docs/app-training.md` und `garmin/app_training.py`.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from ..animation import schluessel as schl
from ..animation.bibliothek import verzeichnis
from ..deps import CurrentUser, DbSession
from ..garmin import app_training
from ..garmin.ablauf import baue_ablauf
from ..models import AppTraining
from ..schemas import (
    AblaufOut,
    AblaufSchrittOut,
    AblaufUebungOut,
    AppTrainingIn,
    AppTrainingOut,
)
from .animationen import als_ausgabe
from .plans import _eigene_einheit

router = APIRouter(prefix="/api/training", tags=["training"])


@router.get("/einheit/{plan_session_id}/ablauf", response_model=AblaufOut)
def ablauf(plan_session_id: int, user: CurrentUser, db: DbSession) -> AblaufOut:
    """Die Einheit Satz für Satz — so, wie das Workout auf der Uhr sie führt.

    Die Animationen stehen gleich mit darin: Die App zeigt sie während des
    Workouts, und hinter dem Ingress kostet jede weitere Anfrage Zeit.
    """
    session = _eigene_einheit(db, plan_session_id, user.id)
    try:
        plan = baue_ablauf(session)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    idx, zeilen = verzeichnis(db)
    uebungen = []
    for u in plan.uebungen:
        schluessel = idx.get(u.schluessel) or (idx.get(schl.normalisiert(u.name_en)) if u.name_en else None)
        zeile = zeilen.get(schluessel) if schluessel else None
        uebungen.append(AblaufUebungOut(
            nummer=u.nummer,
            titel=u.titel,
            name_en=u.name_en,
            zeile=u.zeile,
            je_seite=u.je_seite,
            kategorie=u.kategorie,
            garmin_name=u.garmin_name,
            animation=als_ausgabe(zeile) if zeile else None,
        ))
    return AblaufOut(
        plan_session_id=session.id,
        sport=session.sport,
        titel=session.title,
        quelle=plan.quelle,
        uebungen=uebungen,
        schritte=[
            AblaufSchrittOut(
                uebung=s.uebung, art=s.art, dauer_s=s.dauer_s, wiederholungen=s.wiederholungen,
                satz=s.satz, saetze=s.saetze, seite=s.seite,
            )
            for s in plan.schritte
        ],
    )


@router.post("/einheit/{plan_session_id}/abschluss", response_model=AppTrainingOut)
def abschluss(
    plan_session_id: int, data: AppTrainingIn, user: CurrentUser, db: DbSession
) -> AppTraining:
    """Das absolvierte Workout annehmen und nach Garmin hochladen.

    Gespeichert wird der Bericht in jedem Fall, auch wenn Garmin gerade nicht
    will — die Antwort sagt, ob es angekommen ist (`zustand`). Ein zweiter
    Aufruf mit derselben `kennung` legt nichts neu an: Er versucht einen
    gescheiterten Upload erneut und gibt einen geglückten unverändert zurück.
    """
    session = _eigene_einheit(db, plan_session_id, user.id)
    if session.sport not in app_training.fit_schreiben.SPORTART:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Nur Kraft- und Mobility-Einheiten lassen sich in der App absolvieren.",
        )

    training = db.scalar(select(AppTraining).where(AppTraining.kennung == data.kennung))
    if training is not None and training.user_id != user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Diese Kennung ist schon vergeben.")
    if training is None:
        training = AppTraining(
            user_id=user.id,
            plan_session_id=session.id,
            kennung=data.kennung,
            sport=session.sport,
            beginn=data.beginn,
            ende=data.ende,
            daten=data.model_dump(mode="json"),
            zustand="offen",
        )
        db.add(training)
        db.commit()
        db.refresh(training)

    return app_training.lade_hoch(db, training)


@router.get("/einheit/{plan_session_id}", response_model=list[AppTrainingOut])
def trainings_der_einheit(plan_session_id: int, user: CurrentUser, db: DbSession) -> list[AppTraining]:
    """Was die App zu dieser Einheit schon gemeldet hat — jüngstes zuerst."""
    _eigene_einheit(db, plan_session_id, user.id)
    return (
        db.query(AppTraining)
        .filter(AppTraining.user_id == user.id, AppTraining.plan_session_id == plan_session_id)
        .order_by(AppTraining.erstellt_am.desc())
        .all()
    )
