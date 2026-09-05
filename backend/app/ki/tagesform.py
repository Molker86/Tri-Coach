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
from ..zeit import jetzt_utc, ortsdatum
from .client import ist_angemeldet, token_aus
from .runner import LaeuftBereits, TAGESFORM, runner

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Warum heute nicht geprüft wurde
#
# Sieben Riegel standen hier einmal als sieben stille `return None`. Sie sind
# alle richtig — aber zusammen bedeuteten sie, dass der Athlet eine Funktion
# eingeschaltet hatte, die still nichts tat, und nirgends erfuhr, woran es lag.
# Jeder Ausstieg hinterlässt jetzt einen Code an `KiSettings`; den Satz dazu
# schlägt der Endpunkt hier nach, damit der Wortlaut sich ändern darf, ohne
# dass ihn jede Datenbank mitschleppt.
# --------------------------------------------------------------------------

AUSFALL_AUS = "aus"
AUSFALL_KEIN_ABGLEICH = "kein_abgleich"
AUSFALL_SCHON_GELAUFEN = "schon_gelaufen"
AUSFALL_PLANUNGSTAG = "planungstag"
AUSFALL_NICHTS_GEPLANT = "nichts_geplant"
AUSFALL_SELBST_ANGEPASST = "selbst_angepasst"
AUSFALL_KEIN_ZUGANG = "kein_zugang"
AUSFALL_LAUF_AKTIV = "lauf_aktiv"
AUSFALL_FEHLER = "fehler"

AUSFALLTEXT: dict[str, str] = {
    AUSFALL_AUS: "Die tägliche Anpassung ist ausgeschaltet.",
    AUSFALL_KEIN_ABGLEICH: (
        "Heute wurden noch keine Garmin-Daten geholt. Ohne Schlaf, HRV und "
        "Erholung von heute gibt es nichts zu entscheiden."
    ),
    AUSFALL_SCHON_GELAUFEN: "Der heutige Tag wurde bereits geprüft.",
    AUSFALL_PLANUNGSTAG: (
        "Heute ist Planungstag — der frische Block entsteht ohnehin aus "
        "denselben Werten."
    ),
    AUSFALL_NICHTS_GEPLANT: (
        "Für heute stand nichts an, was sich anpassen ließe — Ruhetag, oder "
        "alles schon absolviert."
    ),
    AUSFALL_SELBST_ANGEPASST: (
        "Du hast heute selbst eine Einheit angepasst. Das wird nicht Stunden "
        "später überschrieben."
    ),
    AUSFALL_KEIN_ZUGANG: (
        "Es fehlt ein nutzbarer Claude-Zugang. Unter Einstellungen → "
        "KI-Planung eintragen oder prüfen."
    ),
    AUSFALL_LAUF_AKTIV: "Für dieses Konto lief gerade schon ein KI-Lauf.",
    AUSFALL_FEHLER: (
        "Die Prüfung ist abgebrochen, bevor sie beginnen konnte. Näheres steht "
        "im Protokoll des Servers."
    ),
}


def ausfalltext(grund: str | None) -> str:
    """Der deutsche Satz zu einem Code — auch zu einem, den es noch nicht gab.

    Ein Code aus einer neueren Fassung, die einmal auf dieselbe Datenbank
    gesehen hat, soll die Anzeige nicht zerreißen.
    """
    if grund is None:
        return ""
    return AUSFALLTEXT.get(grund, "Die Prüfung ist heute nicht gelaufen.")


def passe_an(user_id: int) -> int | None:
    """Passt die heutigen Einheiten an — falls fällig.

    Gibt die Kennung des gestarteten Laufs zurück, sonst `None`. Wirft nie: Der
    Aufrufer ist der Garmin-Abgleich, der davon nicht sterben darf.
    """
    try:
        return _passe_an(user_id)
    except LaeuftBereits:
        # Kein Fehler, sondern das Rennen mit einem Klick des Nutzers in
        # derselben Sekunde: Zwischen dem Riegel unten und `runner.starte()`
        # wird die Sitzung geschlossen. Ohne diesen Zweig stünde dafür ein
        # Stacktrace im Log.
        return None
    except Exception:  # noqa: BLE001
        logger.exception("Automatische Tagesanpassung fehlgeschlagen")
        # Auch ein Absturz **vor** dem Job ist ein Befund. Ohne diesen Vermerk
        # wäre er die einzige Art des Scheiterns, die spurlos bliebe: Ein Job,
        # an dem er hinge, ist an dieser Stelle noch gar nicht angelegt.
        _vermerke_ausfall(user_id, AUSFALL_FEHLER)
        return None


def _vermerke_ausfall(user_id: int, grund: str) -> None:
    """Schreibt den Grund an die Einstellungen — in eigener Sitzung.

    Eigene Sitzung, weil der Aufrufer die seine gerade an einem Fehler verloren
    hat. Und selbst wieder gekapselt: Ein Vermerk, der scheitert, darf den
    Abgleich nicht mitnehmen, der ihn ausgelöst hat.
    """
    try:
        with SessionLocal() as db:
            einstellungen = db.scalar(
                select(KiSettings).where(KiSettings.user_id == user_id)
            )
            if einstellungen is None:
                return
            _notiere_ausfall(db, einstellungen, grund)
    except Exception:  # noqa: BLE001
        logger.exception("Ausfallgrund der Tagesanpassung ließ sich nicht ablegen")


def ausfallgrund(
    einstellungen: KiSettings, konto: GarminAccount | None, heute: date
) -> str | None:
    """Warum jetzt **nicht** geprüft wird — `None` heißt: es wird geprüft.

    Keine eigene Uhrzeit: Die des Abgleichs ist die richtige, und eine zweite
    daneben liefe ihr entweder hinterher oder voraus. Gefragt wird stattdessen,
    ob der Abgleich **heute schon durch** ist — `last_sync_at` setzt nur ein
    erfolgreicher Lauf.

    Gibt einen Grund statt eines `bool` zurück, damit der Athlet erfährt, woran
    es lag. `ist_faellig()` bleibt daneben stehen: Die Frage „läuft sie jetzt?"
    ist an einigen Stellen die einzige, die interessiert.
    """
    if not einstellungen.auto_tagesform_enabled:
        return AUSFALL_AUS
    if konto is None or konto.last_sync_at is None:
        return AUSFALL_KEIN_ABGLEICH
    if ortsdatum(konto.last_sync_at) != heute:
        return AUSFALL_KEIN_ABGLEICH
    if einstellungen.last_tagesform_on == heute:
        return AUSFALL_SCHON_GELAUFEN
    # Nicht am Planungstag. Der frische Block entsteht ohnehin aus denselben
    # Werten — beides an einem Morgen zahlte zwei Opus-Läufe, von denen einer
    # verworfen wird. Geprüft wird in beide Richtungen: schon gelaufen, und
    # heute noch fällig.
    if einstellungen.auto_plan_enabled and (
        einstellungen.last_auto_plan_on == heute
        or heute.weekday() == einstellungen.auto_plan_weekday
    ):
        return AUSFALL_PLANUNGSTAG
    return None


def ist_faellig(
    einstellungen: KiSettings, konto: GarminAccount | None, heute: date
) -> bool:
    """Ob für diese Einstellungen jetzt der heutige Tag geprüft werden soll."""
    return ausfallgrund(einstellungen, konto, heute) is None


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


def _notiere_ausfall(db: Session, einstellungen: KiSettings, grund: str) -> None:
    """Hält fest, warum heute nicht geprüft wurde — samt Zeitpunkt.

    Der Zeitstempel trägt die Entscheidung im Endpunkt: Dort treffen dieser
    Vermerk und der letzte `KiJob` aufeinander, und der jüngere gewinnt. Ohne
    ihn zeigte ein Ausfall von gestern über dem Befund von heute.
    """
    einstellungen.tagesform_ausfall = grund
    einstellungen.tagesform_ausfall_am = jetzt_utc()
    db.commit()
    logger.info(
        "Tagesanpassung für Nutzer %s heute nicht gelaufen: %s",
        einstellungen.user_id,
        grund,
    )


def _passe_an(user_id: int) -> int | None:
    heute = date.today()

    with SessionLocal() as db:
        einstellungen = db.scalar(
            select(KiSettings).where(KiSettings.user_id == user_id)
        )
        konto = db.scalar(
            select(GarminAccount).where(GarminAccount.user_id == user_id)
        )
        if einstellungen is None:
            # Ohne Einstellungszeile kann der Schalter nicht an sein. Eine
            # anzulegen, nur um „aus" zu vermerken, wäre Betrieb ohne Nutzen.
            return None

        grund = ausfallgrund(einstellungen, konto, heute)
        if grund is not None:
            # „Schon gelaufen" wird nicht vermerkt: Für heute gibt es einen Job,
            # und der ist die genauere Auskunft. Ein Code daneben überschriebe
            # sie — jeder Aufwacher käme hier vorbei und stellte den Befund des
            # Laufs auf „bereits geprüft" zurück.
            if grund != AUSFALL_SCHON_GELAUFEN:
                _notiere_ausfall(db, einstellungen, grund)
            return None

        plan, sessions = anpassbare_einheiten(db, user_id, heute)
        if plan is None or not sessions:
            # Ruhetag, alles absolviert oder gar kein Block: Es gibt nichts zu
            # entscheiden, und der Lauf kostete umsonst. **Kein** Tagesriegel —
            # es ist nichts geschehen, was ein zweites Mal geschähe; der Vermerk
            # dagegen gehört hierher, sonst stünde der Athlet vor einer
            # Funktion, die stumm nichts tut.
            _notiere_ausfall(db, einstellungen, AUSFALL_NICHTS_GEPLANT)
            return None

        # Wer heute schon selbst angepasst hat, hat der App gerade gesagt, was
        # er will. Das Stunden später zu überschreiben wäre die unangenehmste
        # Art, hilfreich sein zu wollen.
        heute_angefasst = [
            s
            for s in sessions
            if s.angepasst_am is not None and ortsdatum(s.angepasst_am) == heute
        ]
        if heute_angefasst:
            # Unterschieden am Wunsch, wie überall: Steht einer dran, war es der
            # Athlet. Steht keiner, war es die Tagesanpassung selbst — über den
            # Knopf „Jetzt prüfen", der `last_tagesform_on` bewusst nicht setzt.
            # Beides hält den Lauf an, aber „Du hast selbst angepasst" wäre in
            # diesem Fall schlicht falsch.
            if any(s.anpassungswunsch for s in heute_angefasst):
                _notiere_ausfall(db, einstellungen, AUSFALL_SELBST_ANGEPASST)
            # `schon_gelaufen` bekommt keinen Vermerk — der Job von heute ist
            # die genauere Auskunft, und ein Code daneben verdeckte sie.
            return None

        if not ist_angemeldet(token_aus(einstellungen.token_encrypted)):
            _notiere_ausfall(db, einstellungen, AUSFALL_KEIN_ZUGANG)
            return None

        # Dieses Konto hat schon einen Lauf. Nicht warten: Der Aufrufer ist der
        # Abgleichthread, und ein Lauf, der in einen anderen fällt, hat
        # niemanden, der ihn nachholt. Der Fall ist ohnehin selten — der
        # Abgleich hält sein eigenes Schloss, nicht dieses.
        if runner.laeuft_fuer(user_id) is not None:
            _notiere_ausfall(db, einstellungen, AUSFALL_LAUF_AKTIV)
            return None

        # Erst vormerken, dann starten — dieselbe Reihenfolge und derselbe
        # Grund wie bei der wöchentlichen Planung: Der Lauf läuft in einem
        # eigenen Faden und meldet sich nicht zurück.
        einstellungen.last_tagesform_on = heute
        # Und der Grund von gestern muss weg: Ab jetzt trägt der Job den Befund,
        # und ein stehen gebliebener Code mit älterem Zeitstempel verlöre zwar
        # den Vergleich, stünde aber als Altlast in der Datenbank.
        einstellungen.tagesform_ausfall = None
        einstellungen.tagesform_ausfall_am = None
        db.commit()

    job_id = runner.starte(user_id, TAGESFORM, start_date=heute, days=1)
    logger.info(
        "Tagesanpassung %s für Nutzer %s gestartet (%s Einheiten)",
        job_id,
        user_id,
        len(sessions),
    )
    return job_id
