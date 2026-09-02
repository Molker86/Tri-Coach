"""Der nächste Block entsteht einmal die Woche — wenn er bestellt ist.

**Einmal die Woche, nicht täglich.** Ein Block deckt sieben Tage ab; ihn jeden
Morgen zu überschreiben hieß, dass von jedem Block nur der erste Tag je erreicht
wurde — und jeder Lauf kostet Kontingent. Wochentag und Uhrzeit stehen je Nutzer
in `KiSettings` (Vorgabe Sonntag 09:00).

**Keine eigene Schleife.** Es gab hier einmal eine zweite Viertelstundenschleife
neben der von Garmin; sie ist nicht zurückgekommen. Geweckt wird aus
`garmin/automatik.starte_faellige_planung()` — es gibt genau einen Zeitgeber im
Prozess.

**Aber nicht mehr am Abgleich hängend.** Ausgelöst wurde das einmal am Ende
eines erfolgreichen automatischen Abgleichs. Das garantierte zwar die
Reihenfolge „erst die Daten, dann der Block", band die Planung aber an dessen
Uhrzeit: Wer den Abgleich auf 06:00 legte und die Planung auf Sonntag 09:00,
bekam nie einen Block. Die Reihenfolge trägt jetzt die Uhrzeit — der Abgleich
läuft täglich, die Planung wöchentlich; wer sie nach dem Abgleich haben will,
stellt sie später ein. Dass die Daten einen Tag alt sein können, sagt der Prompt
über `trainingshistorie.datenstand` ohnehin ausdrücklich.

**Und nichts entsteht ungefragt.** Der Schalter steht je Nutzer in
`KiSettings.auto_plan_enabled` und ist ab Werk aus. Ein Lauf mit Opus bei
`--effort max` nimmt spürbar vom Fünf-Stunden-Fenster des Abos, das man daneben
selbst braucht — was Kontingent verbraucht, schaltet der Nutzer selbst ein.
"""

import logging
from datetime import date, datetime

from sqlalchemy import select

from ..ai_export import PLAN_DAYS_DEFAULT
from ..database import SessionLocal
from ..models import KiSettings, TrainingRequest
from .client import ist_angemeldet, token_aus
from .runner import LaeuftBereits, runner

logger = logging.getLogger(__name__)

# Die Jobart eines Laufs, den niemand angestoßen hat. Sie unterscheidet sich von
# „manual" nur in der Herkunft, nicht in der Ausführung — `runner._lauf`
# verzweigt allein auf `EINHEIT`.
AUTO = "auto"


def plane(user_id: int) -> int | None:
    """Legt den nächsten Block an — falls fällig.

    Gibt die Kennung des gestarteten Laufs zurück, sonst `None`. Wirft nie: Der
    Aufrufer ist eine Schleife, die weiterlaufen muss.
    """
    try:
        return _plane(user_id)
    except LaeuftBereits:
        # Kein Fehler, sondern das Rennen mit einem Klick des Nutzers in
        # derselben Sekunde: Zwischen dem Riegel unten und `runner.starte()`
        # wird die Sitzung geschlossen. Ohne diesen Zweig stünde dafür ein
        # Stacktrace im Log.
        return None
    except Exception:  # noqa: BLE001
        logger.exception("Automatische Planung fehlgeschlagen")
        return None


def ist_faellig(einstellungen: KiSettings, jetzt: datetime, heute: date) -> bool:
    """Ob für diese Einstellungen jetzt ein Block entstehen soll.

    Drei Bedingungen, und die dritte ist die wichtige: Der Wochentag muss
    stimmen, die Uhrzeit erreicht sein, und seit dem letzten Lauf müssen sieben
    Tage vergangen sein. Die Wochensperre zählt Tage, statt den Wochentag als
    Sperre zu nehmen — sonst liefe ein zweiter Block in derselben Woche, sobald
    jemand den Wochentag mitten in der Woche umstellt.
    """
    if not einstellungen.auto_plan_enabled:
        return False
    if heute.weekday() != einstellungen.auto_plan_weekday:
        return False
    if (jetzt.hour, jetzt.minute) < (
        einstellungen.auto_plan_hour,
        einstellungen.auto_plan_minute,
    ):
        return False
    letzter = einstellungen.last_auto_plan_on
    return letzter is None or (heute - letzter).days >= 7


def _plane(user_id: int) -> int | None:
    heute = date.today()
    jetzt = datetime.now()

    with SessionLocal() as db:
        einstellungen = db.scalar(
            select(KiSettings).where(KiSettings.user_id == user_id)
        )
        # Der Riegel steht hier **nochmal**, obwohl der Weckruf ihn schon
        # geprüft hat: Zwischen Prüfung und Start liegt eine zweite Sitzung, und
        # der Vermerk wird erst hier gesetzt.
        if einstellungen is None or not ist_faellig(einstellungen, jetzt, heute):
            return None

        # Ohne Fragebogen hat der Export nichts, woraus er einen Block bauen
        # könnte — der Lauf scheiterte sicher und kostete trotzdem.
        if not db.query(TrainingRequest.id).filter(
            TrainingRequest.user_id == user_id
        ).first():
            return None

        if not ist_angemeldet(token_aus(einstellungen.token_encrypted)):
            return None

        # Dieses Konto plant schon — von Hand oder aus einem Lauf, der noch
        # nicht fertig ist. Anders als beim Knopf wird hier **nicht** gewartet:
        # Ein zweiter Block wäre keine Hilfe, und der nächste Aufwacher ist in
        # einer Minute dran, während der Wochentag noch dauert. Läufe fremder
        # Konten stehen nicht im Weg — der Riegel gilt je Konto.
        if runner.laeuft_fuer(user_id) is not None:
            return None

        # Erst vormerken, dann starten: Der Lauf läuft in einem eigenen Faden
        # und meldet sich nicht zurück. Bliebe der Vermerk aus, liefe eine
        # Minute später derselbe Tag noch einmal. Der Preis der Reihenfolge ist
        # das schmale Fenster darunter — drückt der Nutzer in derselben Sekunde
        # selbst, ist die Woche verbraucht, ohne dass etwas entstanden wäre.
        einstellungen.last_auto_plan_on = heute
        db.commit()

    # Ab heute, nicht ab morgen — der laufende Block wird ersetzt, und genau das
    # ist der Sinn eines Blocks, der zur heutigen Belastungslage passt.
    job_id = runner.starte(
        user_id,
        AUTO,
        start_date=heute,
        days=PLAN_DAYS_DEFAULT,
        # Ohne Kennung, also der aktuellste Fragebogen. Hier stand einmal der
        # des laufenden Blocks — als Schutz davor, dass eine *bearbeitete*
        # Zeile übersehen wird, weil `created_at` beim Bearbeiten stehen
        # bleibt. Seit `TRAININGSWUNSCH_AKTUALITAET` das trägt, ist der Schutz
        # überflüssig, und die Festlegung richtete den größeren Schaden an: Ein
        # frisch ausgefüllter Fragebogen wurde von der Automatik nie gesehen,
        # solange der alte Block lief.
        request_id=None,
    )
    logger.info("Automatischer Planungslauf %s für Nutzer %s gestartet", job_id, user_id)
    return job_id
