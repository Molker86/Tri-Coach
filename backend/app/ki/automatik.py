"""Der nächste Block entsteht nach dem täglichen Abgleich — wenn er bestellt ist.

**Keine eigene Schleife.** Es gab hier einmal eine zweite Viertelstundenschleife
neben der von Garmin; sie ist nicht zurückgekommen, und das ist keine Sparsamkeit,
sondern die bessere Bauart: Ausgelöst wird am Ende eines erfolgreichen
*automatischen* Abgleichs (`garmin/runner.py`), und damit ist die Reihenfolge
garantiert, die der Prompt ohnehin voraussetzt — erst die Daten, dann der Block.
Liefe beides unabhängig, könnte die Planung dem Abgleich zuvorkommen; die KI
läse die Lücke als Ruhetag und plante Aufbau auf einen Tag, an dem hart
trainiert wurde (siehe `ai_export._datenstand` und Punkt 2 der Prinzipien).

**Und nichts entsteht ungefragt.** Der Schalter steht je Nutzer in
`KiSettings.auto_plan_enabled` und ist ab Werk aus. Ein Lauf mit Opus bei
`--effort max` nimmt spürbar vom Fünf-Stunden-Fenster des Abos, das man daneben
selbst braucht — was Kontingent verbraucht, schaltet der Nutzer selbst ein.
"""

import logging
from datetime import date

from sqlalchemy import select

from ..ai_export import PLAN_DAYS_DEFAULT
from ..database import SessionLocal
from ..models import GarminSyncJob, KiSettings, Plan, TrainingRequest
from .client import ist_angemeldet, token_aus
from .runner import runner

logger = logging.getLogger(__name__)

# Die Jobart eines Laufs, den niemand angestoßen hat. Sie unterscheidet sich von
# „manual" nur in der Herkunft, nicht in der Ausführung — `runner._lauf`
# verzweigt allein auf `EINHEIT`.
AUTO = "auto"


def plane_nach_abgleich(user_id: int, sync_job_id: int) -> int | None:
    """Legt nach dem täglichen Abgleich den nächsten Block an — falls fällig.

    Gibt die Kennung des gestarteten Laufs zurück, sonst `None`. Wirft nie: Der
    Aufrufer ist ein Abgleich, der gerade erfolgreich war, und ein Fehlschlag
    hier darf ihn nicht nachträglich zu einem Fehlschlag machen.
    """
    try:
        return _plane(user_id, sync_job_id)
    except Exception:  # noqa: BLE001
        logger.exception("Automatische Planung nach dem Abgleich fehlgeschlagen")
        return None


def _plane(user_id: int, sync_job_id: int) -> int | None:
    heute = date.today()

    with SessionLocal() as db:
        sync = db.get(GarminSyncJob, sync_job_id)
        # Nur der Abgleich, den die Automatik selbst angestoßen hat. Wer
        # „Jetzt synchronisieren" drückt, will Daten — dass ihn das zusätzlich
        # Kontingent kostete, sähe er der Schaltfläche nicht an.
        if sync is None or sync.kind != "auto" or sync.state != "done":
            return None

        einstellungen = db.scalar(
            select(KiSettings).where(KiSettings.user_id == user_id)
        )
        if einstellungen is None or not einstellungen.auto_plan_enabled:
            return None

        # Der Tagesriegel. Ein zweiter automatischer Abgleich am selben Tag ist
        # durch `last_sync_at` schon ausgeschlossen; das hier hält auch dann,
        # wenn jemand ihn von Hand zurücksetzt oder die App neu startet.
        if einstellungen.last_auto_plan_on == heute:
            return None

        # Ohne Fragebogen hat der Export nichts, woraus er einen Block bauen
        # könnte — der Lauf scheiterte sicher und kostete trotzdem.
        if not db.query(TrainingRequest.id).filter(
            TrainingRequest.user_id == user_id
        ).first():
            return None

        if not ist_angemeldet(token_aus(einstellungen.token_encrypted)):
            return None

        # Anders als beim Knopf wird hier **nicht** gewartet: Ein Lauf, der in
        # einen anderen fällt, hat niemanden, der ihn nachholt — aber ein
        # zweiter Block am selben Tag wäre auch keine Hilfe. Morgen ist der
        # nächste Abgleich.
        if runner.laeuft_gerade() is not None:
            return None

        # Der Fragebogen des laufenden Blocks statt des zuletzt *angelegten*.
        # Wer seinen Fragebogen anpasst, statt einen neuen auszufüllen, ändert
        # `created_at` nicht — `_letzter_fragebogen()` sortiert danach und
        # griffe daneben, sobald irgendwo eine jüngere Zeile liegt. Die
        # Anpassung wirkte dann nie, ohne dass etwas fehlschlüge. Ohne aktiven
        # Block und an Altbestand (`request_id = NULL`) bleibt es beim
        # bisherigen Rückfall.
        aktiv = db.scalar(
            select(Plan).where(Plan.user_id == user_id, Plan.is_active.is_(True))
        )
        fragebogen = aktiv.request_id if aktiv is not None else None

        # Erst vormerken, dann starten: Der Lauf hängt sich an ein eigenes
        # Schloss und meldet sich nicht zurück. Bliebe der Vermerk aus, liefe
        # nach einem Neustart derselbe Tag noch einmal.
        einstellungen.last_auto_plan_on = heute
        db.commit()

    # Ab heute, nicht ab morgen — der laufende Block wird ersetzt, und genau das
    # ist der Sinn eines Blocks, der zur heutigen Belastungslage passt.
    job_id = runner.starte(
        user_id,
        AUTO,
        start_date=heute,
        days=PLAN_DAYS_DEFAULT,
        request_id=fragebogen,
    )
    logger.info("Automatischer Planungslauf %s für Nutzer %s gestartet", job_id, user_id)
    return job_id
