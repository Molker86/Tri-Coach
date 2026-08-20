"""Was ohne Zutun läuft: der tägliche Abgleich und der Weg auf die Uhr.

Zwei Auslöser, ein Gedanke — der Athlet soll nichts anstoßen müssen, was die
App selbst weiß. Der Abgleich hängt an der Uhrzeit, die Übertragung am
Übernehmen eines Blocks (`starte_uebertragung_fuer_neuen_plan`).

Kein Cron und kein Zeitplaner-Paket: Das Add-on ist ein einziger
Uvicorn-Prozess, ein zweites Laufzeitteil wäre mehr Betrieb als Nutzen.

Die Schleife wacht viertelstündlich auf und *prüft*, ob heute schon abgeglichen
wurde, statt auf einen festen Zeitpunkt zu zielen. Das ist gegen Neustarts
robust: Der letzte Lauf steht in der Datenbank, nicht in einem Wecker. War der
Rechner um neun Uhr aus, holt es der erste Aufwacher nach dem Start nach.
Gestartet wird deshalb ab `GARMIN_SYNC_HOUR`, nicht auf die Minute genau — der
Lauf beginnt innerhalb der Viertelstunde danach.

Der Abgleich läuft im Server, nicht im Browser — es muss niemand die Seite
offen haben.
"""

import asyncio
import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import GARMIN_SYNC_HOUR
from ..database import SessionLocal
from ..models import (
    AthleteProfile,
    GarminAccount,
    GarminWorkoutLink,
    Plan,
    PlanSession,
)
from ..zeit import liegt_in_der_zukunft
from . import uebertragung, workouts
from .errors import GarminFehler, GarminNichtVerbunden
from .runner import runner
from .sync import standard_zeitraum
from .verbindung import garmin_sitzung

logger = logging.getLogger(__name__)

WECKINTERVALL_S = 900


async def automatik_schleife() -> None:
    while True:
        await asyncio.sleep(WECKINTERVALL_S)
        try:
            # In einen Thread ausgelagert: Der Abgleich ist blockierendes I/O
            # und würde die Ereignisschleife sonst für Minuten anhalten.
            await asyncio.to_thread(starte_faellige_syncs)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Automatischer Garmin-Abgleich fehlgeschlagen")


def starte_faellige_syncs(jetzt: datetime | None = None) -> int:
    """Startet für jedes fällige Konto einen Abgleich. Gibt deren Anzahl zurück."""
    jetzt = jetzt or datetime.now()
    if runner.laeuft_gerade() is not None:
        return 0

    heute = date.today()
    gestartet = 0

    with SessionLocal() as db:
        konten = db.scalars(
            select(GarminAccount).where(
                GarminAccount.auto_sync_enabled.is_(True),
                GarminAccount.status == "connected",
            )
        ).all()

        for konto in konten:
            # Die Stunde steht am Konto, nicht global: Sie ist in den
            # Einstellungen wählbar, und `GARMIN_SYNC_HOUR` ist nur noch die
            # Vorgabe. Der Preis ist, dass jeder Aufwacher eine Sitzung öffnet,
            # statt vorher billig zurückzukehren — bei SQLite auf demselben
            # Rechner folgenlos, und anders geht „je Nutzer eine Stunde" nicht.
            if jetzt.hour < _abgleichstunde(konto):
                continue
            if konto.last_sync_at is not None and _als_datum(konto.last_sync_at) >= heute:
                continue
            if liegt_in_der_zukunft(konto.rate_limited_until):
                continue

            # Derselbe Zuschnitt wie beim Knopf: ein Jahr beim ersten Mal,
            # danach nur noch, was seither dazugekommen ist.
            von, bis, tagesschleife = standard_zeitraum(
                "incremental",
                heute,
                gedeckt_von=konto.backfill_from,
                gedeckt_bis=konto.synced_through,
            )
            runner.starte(konto.user_id, "auto", von, bis, tagesschleife)
            gestartet += 1
            # Nur ein Konto je Aufwachen: Zwei Läufe gleichzeitig sind ohnehin
            # durch das Schloss im Runner ausgeschlossen, und nacheinander
            # gestartet erzeugten sie genau die Anfragedichte, gegen die Garmins
            # Sperre gerichtet ist. Der nächste ist in einer Viertelstunde dran.
            break

    return gestartet


def _abgleichstunde(konto: GarminAccount) -> int:
    """Ab welcher Ortszeit-Stunde dieses Konto abgeglichen werden darf.

    Ausdrücklich gegen `None` geprüft und nicht `or`: Mitternacht ist eine
    gültige Einstellung, und `0 or 10` ergäbe zehn — der Nutzer bekäme lautlos
    eine andere Zeit als die eingestellte.
    """
    return konto.sync_hour if konto.sync_hour is not None else GARMIN_SYNC_HOUR


def _als_datum(zeitpunkt: datetime) -> date:
    return zeitpunkt.date()


# --------------------------------------------------------------------------
# Ein frisch übernommener Block geht von selbst auf die Uhr
# --------------------------------------------------------------------------


def starte_uebertragung_fuer_neuen_plan(
    db: Session, user_id: int, plan: Plan
) -> tuple[int | None, str | None]:
    """Schiebt einen gerade übernommenen Block nach Garmin — und räumt den alten weg.

    Der Knopf im Trainingsplan bleibt, aber er soll die Ausnahme sein: Ein Block
    reicht nur wenige Tage weit, und einer, der erst nach einem zusätzlichen
    Handgriff auf der Uhr landet, hat die erste Einheit oft schon hinter sich.

    Der Lauf räumt dabei selbst auf — der abgelöste Block verlässt den Kalender,
    bevor der neue hineingeht (`runner._raeume_ersetzte_vorab`). Deshalb genügt
    hier ein einziger Anstoß für beides.

    **Aufgeräumt wird auch dann, wenn nichts hinausgeht** (`aktion="cleanup"`).
    Wer die automatische Übertragung abgeschaltet hat oder einen Block aus lauter
    Ruhetagen übernimmt, hätte sonst den *alten* Block allein im Kalender stehen
    — die überholte Vorgabe ohne die neue daneben, also genau der irreführende
    Zustand, den das Aufräumen verhindern soll. Dass der neue Block nicht von
    selbst auf die Uhr geht, ist eine Entscheidung über das Hinlegen; das
    Wegräumen dessen, was diese App selbst einmal hingelegt hat, hängt nicht
    daran.

    **Kein `runner.laeuft_gerade()`-Riegel wie beim Knopf.** Ein Nutzer, der
    selbst drückt, kann warten und es gleich nochmal versuchen; ein Import, der
    zufällig in den täglichen Abgleich fällt, hätte niemanden, der das
    nachholt. Der Job wartet stattdessen im eigenen Faden auf das globale
    Schloss und läuft danach — sichtbar als „in der Warteschlange".

    Rückgabe: Job-Kennung und ein Hinweis, falls der Nutzer wissen muss, warum
    nichts losging.
    """
    konto = db.scalar(select(GarminAccount).where(GarminAccount.user_id == user_id))
    if konto is None:
        return None, None

    # Ein Block, der nur aus Ruhetagen oder vergangenen Tagen besteht, hat
    # nichts zu übertragen. Ohne diese Prüfung liefe ein Job an, der sofort mit
    # „Es gab keine Einheit zu übertragen" endet.
    uebertragen = bool(konto.auto_push_enabled) and bool(
        uebertragung.planbare_einheiten(plan, date.today())
    )
    # Kostet keine Anfrage an Garmin: Die Frage beantwortet die eigene
    # Zuordnungstabelle. Erst damit lässt sich der Lauf auf die Fälle
    # beschränken, in denen er etwas bewirkt.
    aufzuraeumen = bool(
        uebertragung.ersetzte_links(db, user_id, ausser_plan_id=plan.id)
    )
    if not uebertragen and not aufzuraeumen:
        return None, None

    was = "der Block wurde nicht auf die Uhr übertragen" if uebertragen else (
        "der abgelöste Block steht noch im Kalender"
    )

    if konto.status == "token_expired":
        return None, (
            konto.status_message
            or f"Die Anmeldung bei Garmin ist abgelaufen — {was}. "
            "Bitte verbinde dein Konto erneut."
        )

    if liegt_in_der_zukunft(konto.rate_limited_until):
        return None, (
            f"Garmin hat die Verbindung vorerst gesperrt — {was}. "
            "Du kannst es später von Hand anstoßen."
        )

    return runner.starte_uebertragung(
        user_id, plan.id, "push" if uebertragen else "cleanup", ab=date.today()
    ), None


# --------------------------------------------------------------------------
# Eine einzeln geänderte Einheit auf die Uhr bringen
# --------------------------------------------------------------------------


def uebertrage_geaenderte_einheit(
    db: Session, user_id: int, session: PlanSession
) -> tuple[str, str | None]:
    """Bringt eine gerade angepasste Einheit in den Garmin-Kalender.

    **Im Anfrage- bzw. Planungsthread, nicht als Job** — dieselbe Abwägung wie
    beim Löschen einer einzelnen Einheit: Es sind zwei bis drei Anfragen, und
    ein Fortschrittsbalken dafür wäre Umstand ohne Nutzen. Das globale Schloss
    wird trotzdem genommen (nicht blockierend), damit nicht daneben ein
    Übertragungslauf denselben Pool-Slot belegt.

    Drei Fälle, und der zweite ist der eigentliche Grund für diese Funktion:

    * Die Einheit ist weiter übertragbar → `uebertrage_einheit` ersetzt den
      Inhalt der Pool-Vorlage an derselben Kennung und behält den Termin. Auf
      der Uhr steht danach die neue Fassung, nicht zwei nebeneinander.
    * Aus der Einheit ist **Ruhe** geworden → sie gehört nicht mehr auf die Uhr,
      und was von ihr in Garmin steht, muss weg. Ohne diesen Zweig bliebe die
      alte Vorgabe an einem Tag stehen, an dem der Athlet ausdrücklich nicht
      trainieren soll — der irreführendste aller Zustände.
    * Nichts zu tun (kein Konto, nichts in Garmin und Automatik aus,
      vergangener Tag).

    **Ein Fehlschlag wird gemeldet, nicht geworfen.** Die Einheit ist zu diesem
    Zeitpunkt bereits angepasst und gespeichert; den ganzen Vorgang an Garmin
    scheitern zu lassen nähme dem Athleten seine Anpassung für einen Grund, der
    nichts mit ihr zu tun hat. Er bekommt stattdessen den Satz dazu und den
    Knopf im Trainingsplan.

    Rückgabe: was geschehen ist ("uebertragen", "entfernt", "keine") und ein
    Hinweis, falls der Nutzer wissen muss, warum nichts geschah.
    """
    konto = db.scalar(select(GarminAccount).where(GarminAccount.user_id == user_id))
    if konto is None:
        return "keine", None

    link = db.scalar(
        select(GarminWorkoutLink).where(
            GarminWorkoutLink.plan_session_id == session.id
        )
    )
    uebertragbar = workouts.ist_uebertragbar(session.sport)

    # Ein Workout von gestern hilft auf der Uhr niemandem mehr — dieselbe Grenze
    # wie in `planbare_einheiten`. Steht dort noch etwas, räumt es der nächste
    # Abgleich über `raeume_vergangene_auf` weg.
    if session.date < date.today():
        return "keine", None

    # Ohne Zuordnung steht von dieser Einheit nichts in Garmin. Dann entscheidet
    # die Automatik, ob sie überhaupt hinkommt — genau wie bei einem frisch
    # übernommenen Block. Liegt sie dagegen schon dort, wird sie auf jeden Fall
    # angefasst: Das Wegräumen dessen, was diese App selbst hingelegt hat, hängt
    # nicht am Schalter fürs Hinlegen.
    if link is None and not (uebertragbar and konto.auto_push_enabled):
        return "keine", None

    was = (
        "die geänderte Einheit steht nicht auf der Uhr"
        if uebertragbar
        else "die entfallene Einheit steht weiter im Garmin-Kalender"
    )
    # Wohin der Nutzer sich wenden kann, ist je Fall ein anderer Ort: Eine
    # Einheit, aus der Ruhe geworden ist, taucht im Trainingsplan gar nicht
    # mehr auf (`planbare_einheiten` lässt Ruhetage aus) — dort führte der
    # Verweis ins Leere. Der Kalender dieser App zeigt sie dagegen weiterhin.
    wohin = (
        " Du kannst sie im Trainingsplan erneut übertragen."
        if uebertragbar
        else " Im Garmin-Kalender dieser App lässt sie sich von Hand entfernen."
    )

    if konto.status == "token_expired":
        return "keine", (
            konto.status_message
            or f"Die Anmeldung bei Garmin ist abgelaufen — {was}."
        ) + wohin

    if liegt_in_der_zukunft(konto.rate_limited_until):
        return "keine", (
            f"Garmin hat die Verbindung vorerst gesperrt — {was}." + wohin
        )

    try:
        with runner.exklusiver_direktaufruf():
            with garmin_sitzung(db, user_id) as api:
                if not uebertragbar:
                    fehler = uebertragung.entferne_link(db, api, link)
                    if fehler:
                        raise GarminFehler(fehler)
                    return "entfernt", None

                profil = _profil(db, user_id)
                uebertragung.uebertrage_einheit(
                    db,
                    api,
                    user_id,
                    session,
                    zonen=workouts.zonen_aus_profil(profil),
                    ftp=getattr(profil, "ftp_watts", None),
                )
    except GarminNichtVerbunden:
        return "keine", None
    except GarminFehler as exc:
        db.rollback()
        return "keine", f"{exc.meldung} — {was}." + wohin
    except Exception:  # noqa: BLE001
        # Bewusst **alles**: Die Bibliothek wirft nicht nur übersetzte Fehler,
        # sondern auch alles, was `requests` unterwegs auslöst. Der Athlet hat
        # seine Anpassung an dieser Stelle längst; sie an einem Netzfehler
        # scheitern zu lassen, wäre die falsche Rangfolge — und im Planungslauf
        # stünde am Ende „fehlgeschlagen" über einer Einheit, die tadellos
        # angepasst wurde.
        logger.exception("Übertragung der angepassten Einheit fehlgeschlagen")
        # Zurückrollen, bevor der Lauf weitergeht: Was der abgebrochene
        # Schreibweg an halben Änderungen hinterlassen hat, dürfte sonst mit
        # dem nächsten `commit` des Aufrufers mitgehen.
        db.rollback()
        return "keine", (
            f"Die Übertragung an Garmin ist fehlgeschlagen — {was}." + wohin
        )

    return "uebertragen", None


def _profil(db: Session, user_id: int) -> AthleteProfile | None:
    """Das Athletenprofil — daraus kommen Herzfrequenzzonen und FTP."""
    return db.scalar(select(AthleteProfile).where(AthleteProfile.user_id == user_id))
