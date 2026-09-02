"""Der heutige Tag wird nachgeschärft, sobald die Werte von heute da sind.

**Am Abgleich, und zwar mit Absicht.** Die wöchentliche Planung wurde bewusst
vom Abgleich gelöst — sie braucht ihn nicht, und ihn abzuwarten kostete sie
ihre eigene Uhrzeit (siehe `ki/automatik.py`). Hier gilt das Gegenteil: Der
ganze Gegenstand dieser Aufgabe sind Schlaf, HRV, Ruhepuls und Erholung, die
der Lauf gerade geholt hat. Vor dem Abgleich gäbe es nichts zu entscheiden,
danach ist es genau eine Frage — trägt der heutige Tag, was für ihn geplant
war? Der Anstoß hängt deshalb hinten am Abgleich (`garmin/runner._fuehre_aus`),
und zwar **außerhalb** von dessen Schloss: Der Lauf schiebt am Ende geänderte
Einheiten nach Garmin und liefe sonst in ein Schloss, das der Abgleich selbst
noch hält.

**Nur nach einem automatischen Lauf.** Wer abends „Jetzt abgleichen" drückt,
will seine Historie sehen und nicht seine Einheit umgeschrieben bekommen.

**Und es bleibt beim Nachschärfen.** Ein Ruhetag bleibt ein Ruhetag — er ist
eine Entscheidung des Blocks über die ganze Woche und kein Mangel an Lust.
Die Sportart bleibt, der Tag bleibt, die Zahl der Einheiten bleibt; geändert
werden Umfang, Intensität und Aufbau. Was der Block für heute vorsah, ist der
Ausgangspunkt und nicht der Verdächtige: Der Prompt sagt ausdrücklich, dass
„unverändert" der Regelfall ist.

**Ab Werk aus.** Ein Lauf mit Opus bei `--effort max` nimmt spürbar vom
Fünf-Stunden-Fenster des Abos — und anders als die Planung fiele er *täglich*
an. Was Kontingent verbraucht, schaltet der Nutzer selbst ein.
"""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import GarminAccount, KiSettings, Plan, PlanSession, SessionLog
from ..zeit import ortsdatum
from .client import ist_angemeldet, token_aus
from .runner import TAGESFORM, runner

logger = logging.getLogger(__name__)

def passe_an(user_id: int) -> int | None:
    """Passt die heutigen Einheiten an — falls fällig.

    Gibt die Kennung des gestarteten Laufs zurück, sonst `None`. Wirft nie: Der
    Aufrufer ist der Garmin-Abgleich, der davon nicht sterben darf.
    """
    try:
        return _passe_an(user_id)
    except Exception:  # noqa: BLE001
        logger.exception("Automatische Tagesanpassung fehlgeschlagen")
        return None


def ist_faellig(
    einstellungen: KiSettings, konto: GarminAccount | None, heute: date
) -> bool:
    """Ob für diese Einstellungen jetzt der heutige Tag geprüft werden soll.

    Keine eigene Uhrzeit: Die des Abgleichs ist die richtige, und eine zweite
    daneben liefe ihr entweder hinterher oder voraus. Gefragt wird stattdessen,
    ob der Abgleich **heute schon durch** ist — `last_sync_at` setzt nur ein
    erfolgreicher Lauf.
    """
    if not einstellungen.auto_tagesform_enabled:
        return False
    if konto is None or konto.last_sync_at is None:
        return False
    if ortsdatum(konto.last_sync_at) != heute:
        return False
    if einstellungen.last_tagesform_on == heute:
        return False
    # Nicht am Planungstag. Der frische Block entsteht ohnehin aus denselben
    # Werten — beides an einem Morgen zahlte zwei Opus-Läufe, von denen einer
    # verworfen wird. Geprüft wird in beide Richtungen: schon gelaufen, und
    # heute noch fällig.
    if einstellungen.auto_plan_enabled and (
        einstellungen.last_auto_plan_on == heute
        or heute.weekday() == einstellungen.auto_plan_weekday
    ):
        return False
    return True


def anpassbare_einheiten(
    db: Session, user_id: int, tag: date
) -> tuple[Plan | None, list[PlanSession]]:
    """Der aktive Block und was an diesem Tag noch geändert werden darf.

    Dieselben zwei Grenzen wie bei der Einzelanpassung
    (`routers.plans.anpassbare_einheit`), aus denselben Gründen: Ein Ruhetag
    steht nicht zur Debatte, und was schon absolviert ist, ist Vergangenheit —
    auch wenn sein Tag noch läuft. Die Reihenfolge ist die des Tages, denn an
    ihr hängt die `nr`, über die die Antwort zurückfindet.
    """
    plan = db.scalar(
        select(Plan).where(Plan.user_id == user_id, Plan.is_active.is_(True))
    )
    if plan is None:
        return None, []

    sessions = db.scalars(
        select(PlanSession)
        .outerjoin(SessionLog, SessionLog.plan_session_id == PlanSession.id)
        .where(
            PlanSession.plan_id == plan.id,
            PlanSession.date == tag,
            PlanSession.sport != "rest",
            SessionLog.id.is_(None),
        )
        .order_by(PlanSession.order_in_day, PlanSession.id)
    ).all()
    return plan, list(sessions)


def _passe_an(user_id: int) -> int | None:
    heute = date.today()

    with SessionLocal() as db:
        einstellungen = db.scalar(
            select(KiSettings).where(KiSettings.user_id == user_id)
        )
        konto = db.scalar(
            select(GarminAccount).where(GarminAccount.user_id == user_id)
        )
        if einstellungen is None or not ist_faellig(einstellungen, konto, heute):
            return None

        plan, sessions = anpassbare_einheiten(db, user_id, heute)
        if plan is None or not sessions:
            # Ruhetag, alles absolviert oder gar kein Block: Es gibt nichts zu
            # entscheiden, und der Lauf kostete umsonst. **Kein** Merker — es
            # ist nichts geschehen, was ein zweites Mal geschähe.
            return None

        # Wer heute schon selbst angepasst hat, hat der App gerade gesagt, was
        # er will. Das Stunden später zu überschreiben wäre die unangenehmste
        # Art, hilfreich sein zu wollen.
        if any(
            s.angepasst_am is not None and ortsdatum(s.angepasst_am) == heute
            for s in sessions
        ):
            return None

        if not ist_angemeldet(token_aus(einstellungen.token_encrypted)):
            return None

        # Nicht warten: Der Aufrufer ist der Abgleichthread, und ein Lauf, der
        # in einen anderen fällt, hat niemanden, der ihn nachholt. Der Fall ist
        # ohnehin selten — der Abgleich hält sein eigenes Schloss, nicht dieses.
        if runner.laeuft_gerade() is not None:
            return None

        # Erst vormerken, dann starten — dieselbe Reihenfolge und derselbe
        # Grund wie bei der wöchentlichen Planung: Der Lauf hängt an einem
        # eigenen Schloss und meldet sich nicht zurück.
        einstellungen.last_tagesform_on = heute
        db.commit()

    job_id = runner.starte(user_id, TAGESFORM, start_date=heute, days=1)
    logger.info(
        "Tagesanpassung %s für Nutzer %s gestartet (%s Einheiten)",
        job_id,
        user_id,
        len(sessions),
    )
    return job_id
