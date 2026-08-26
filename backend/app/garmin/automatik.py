"""Was ohne Zutun läuft: der tägliche Abgleich und der Weg auf die Uhr.

Drei Auslöser, ein Gedanke — der Athlet soll nichts anstoßen müssen, was die
App selbst weiß. Der Abgleich hängt an der Uhrzeit, die Wochenplanung an
Wochentag und Uhrzeit, die Übertragung am Übernehmen eines Blocks
(`starte_uebertragung_fuer_neuen_plan`).

Kein Cron und kein Zeitplaner-Paket: Das Add-on ist ein einziger
Uvicorn-Prozess, ein zweites Laufzeitteil wäre mehr Betrieb als Nutzen.

Die Schleife wacht minütlich auf und *prüft*, ob das Fällige schon gelaufen ist,
statt auf einen festen Zeitpunkt zu zielen. Das ist gegen Neustarts robust: Der
letzte Lauf steht in der Datenbank, nicht in einem Wecker. War der Rechner um
neun Uhr aus, holt es der erste Aufwacher nach dem Start nach.

Minütlich und nicht mehr viertelstündlich, seit beide Automatiken eine eigene
Uhrzeit **mit Minute** haben: Eine eingestellte 09:05 muss auch um 09:05
losgehen und nicht irgendwann bis 09:20. Der Preis ist eine kurze DB-Sitzung je
Minute — bei SQLite auf demselben Rechner folgenlos.

**Zwei unabhängige Zweige.** Der Garmin-Abgleich läuft täglich zu seiner
Uhrzeit; die KI-Planung wöchentlich an ihrem Wochentag zu ihrer eigenen. Die
Planung hing einmal am Abgleich und lief nur unmittelbar danach — dann fiel sie
aus, sobald jemand die beiden Uhrzeiten auseinanderlegte oder den Abgleich
abschaltete. Sie hat trotzdem **keine eigene Schleife**: Der Weckruf kommt
weiterhin von hier, es gibt genau einen Zeitgeber im Prozess.

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
from ..ki import automatik as ki_automatik
from ..models import (
    AthleteProfile,
    GarminAccount,
    GarminWorkoutLink,
    KiSettings,
    Plan,
    PlanSession,
)
from ..zeit import als_utc, liegt_in_der_zukunft
from . import uebertragung, workouts
from .errors import GarminFehler, GarminNichtVerbunden
from .runner import runner
from .sync import standard_zeitraum
from .verbindung import garmin_sitzung

logger = logging.getLogger(__name__)

WECKINTERVALL_S = 60


async def automatik_schleife() -> None:
    while True:
        await asyncio.sleep(WECKINTERVALL_S)
        # Getrennte `try`-Blöcke: Ein Fehler im Abgleich darf die Planung nicht
        # mit ausfallen lassen — sie hängt nicht mehr an ihm.
        try:
            # In einen Thread ausgelagert: Der Abgleich ist blockierendes I/O
            # und würde die Ereignisschleife sonst für Minuten anhalten.
            await asyncio.to_thread(starte_faellige_syncs)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Automatischer Garmin-Abgleich fehlgeschlagen")

        try:
            await asyncio.to_thread(starte_faellige_planung)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Automatische Planung fehlgeschlagen")


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
            if (jetzt.hour, jetzt.minute) < _abgleichzeit(konto):
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
            # Sperre gerichtet ist. Der nächste ist in einer Minute dran.
            break

    return gestartet


def starte_faellige_planung(jetzt: datetime | None = None) -> int:
    """Startet für jeden fälligen Nutzer einen Planungslauf. Gibt deren Anzahl zurück.

    Das Gegenstück zu `starte_faellige_syncs`, und bewusst **unabhängig** davon:
    Wer den Abgleich abschaltet oder auf eine andere Uhrzeit legt, soll trotzdem
    seinen Wochenblock bekommen. Beide Zweige teilen sich nur den Zeitgeber.

    Die Fälligkeit selbst steht in `ki.automatik.ist_faellig()` — hier wird sie
    nur vorgeprüft, damit nicht für jeden Nutzer eine zweite Sitzung aufgeht.
    """
    jetzt = jetzt or datetime.now()
    heute = date.today()
    gestartet = 0

    with SessionLocal() as db:
        einstellungen = db.scalars(
            select(KiSettings).where(KiSettings.auto_plan_enabled.is_(True))
        ).all()
        faellig = [
            e.user_id for e in einstellungen if ki_automatik.ist_faellig(e, jetzt, heute)
        ]

    for user_id in faellig:
        if ki_automatik.plane(user_id) is not None:
            gestartet += 1
            # Nur ein Lauf je Aufwachen, aus demselben Grund wie beim Abgleich:
            # Das Schloss im KI-Runner ließe den zweiten ohnehin nicht durch,
            # und der nächste Aufwacher ist in einer Minute dran.
            break

    return gestartet


def _abgleichzeit(konto: GarminAccount) -> tuple[int, int]:
    """Ab welcher Ortszeit dieses Konto abgeglichen werden darf.

    Ausdrücklich gegen `None` geprüft und nicht `or`: Mitternacht und die volle
    Stunde sind gültige Einstellungen, und `0 or 10` ergäbe zehn — der Nutzer
    bekäme lautlos eine andere Zeit als die eingestellte.
    """
    stunde = konto.sync_hour if konto.sync_hour is not None else GARMIN_SYNC_HOUR
    minute = konto.sync_minute if konto.sync_minute is not None else 0
    return stunde, minute


def _als_datum(zeitpunkt: datetime) -> date:
    """Das **Ortszeit**-Datum eines Zeitstempels aus der Datenbank.

    `last_sync_at` wird in UTC geschrieben, verglichen wird gegen das lokale
    `date.today()`. Ohne die Umrechnung fiel ein Lauf kurz nach Mitternacht
    Ortszeit als „gestern" in die Datenbank, und die Tagessperre griff nicht.
    """
    return als_utc(zeitpunkt).astimezone().date()


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
