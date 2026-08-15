"""Führt einen Planungslauf aus und schreibt seinen Fortschritt fort.

Warum ein eigener Thread und keine lange HTTP-Antwort: Ein Lauf mit
`--effort max` dauert gemessen rund anderthalb Minuten. Hinter dem
Home-Assistant-Ingress ist eine minutenlange Antwort ein Risiko, und der Nutzer
säße vor einem Balken ohne jede Rückmeldung. Dasselbe Muster wie beim
Garmin-Abgleich (`garmin/runner.py`), bis hin zu den Zustandsnamen — damit die
Abfrageschleife im Frontend für beide Jobarten gilt.

Warum ein **eigenes** Schloss und nicht das des Garmin-Runners: Anthropic und
Garmin haben nichts miteinander zu tun. Gemeinsam genutzt müsste ein
Planungslauf hinter einem Jahresrückblick warten — und der Import am Ende stößt
seinerseits eine Garmin-Übertragung an, die dann auf ein Schloss liefe, das der
Planungslauf selbst noch hält.
"""

import logging
import subprocess
import threading
from datetime import date, datetime, timezone

from ..database import SessionLocal
from ..models import KiJob, KiSettings, User
from .errors import KiFehler, KiKontingentErschoepft, KiTokenUngueltig

logger = logging.getLogger(__name__)

ENDZUSTAENDE = frozenset({"done", "failed", "cancelled", "interrupted"})

# Ob Läufe in einen eigenen Thread abgegeben werden. Die Tests stellen das ab
# und lassen synchron laufen — sonst müsste jeder Test den Fortschritt abfragen
# und wäre von der Zeit abhängig.
IM_HINTERGRUND = True


def _now() -> datetime:
    return datetime.now(timezone.utc)


class KiRunner:
    """Ein Lauf zur Zeit, im eigenen Thread, Fortschritt in der Datenbank."""

    def __init__(self) -> None:
        self._schloss = threading.Lock()
        self._aktiver_job: int | None = None
        self._prozesse: dict[int, subprocess.Popen] = {}
        self._abgebrochen: set[int] = set()

    # -- Steuerung ----------------------------------------------------------

    def laeuft_gerade(self) -> int | None:
        return self._aktiver_job

    def brich_ab(self, job_id: int) -> bool:
        """Beendet den Unterprozess des Laufs. Gibt zurück, ob es einen gab."""
        prozess = self._prozesse.get(job_id)
        self._abgebrochen.add(job_id)
        if prozess is None:
            return False
        prozess.kill()
        return True

    def starte(
        self,
        user_id: int,
        kind: str,
        *,
        request_id: int | None = None,
        start_date: date | None = None,
        days: int = 7,
        im_hintergrund: bool | None = None,
    ) -> int:
        """Legt den Job an und startet ihn. Gibt die Job-Kennung zurück."""
        im_hintergrund = IM_HINTERGRUND if im_hintergrund is None else im_hintergrund
        with SessionLocal() as db:
            job = KiJob(
                user_id=user_id,
                kind=kind,
                state="queued",
                request_id=request_id,
                start_date=start_date,
                days=days,
                message="Der Planungslauf wird vorbereitet …",
            )
            db.add(job)
            db.commit()
            job_id = job.id

        if im_hintergrund:
            threading.Thread(
                target=self._fuehre_aus,
                args=(job_id, user_id),
                name=f"ki-planung-{job_id}",
                daemon=True,
            ).start()
        else:
            self._fuehre_aus(job_id, user_id)

        return job_id

    # -- Ausführung ---------------------------------------------------------

    def _fuehre_aus(self, job_id: int, user_id: int) -> None:
        # Der Thread bekommt seine **eigene** Sitzung: Eine aus einer Anfrage
        # weitergereichte wäre über Threadgrenzen hinweg nicht sicher und stürbe
        # mit der Anfrage.
        with self._schloss, SessionLocal() as db:
            self._aktiver_job = job_id
            try:
                self._lauf(db, job_id, user_id)
            finally:
                self._aktiver_job = None
                self._prozesse.pop(job_id, None)
                self._abgebrochen.discard(job_id)

    def _lauf(self, db, job_id: int, user_id: int) -> None:
        from .. import ai_export, plan_import
        from . import client

        job = db.get(KiJob, job_id)
        user = db.get(User, user_id)
        if job is None or user is None:
            return

        einstellungen = _einstellungen(db, user_id)

        job.state = "running"
        job.progress_pct = 5
        job.message = "Das Datenpaket wird gebaut …"
        db.commit()

        try:
            export = ai_export.erzeuge_export(
                db,
                user,
                request_id=job.request_id,
                start_date=job.start_date,
                days=job.days,
            )

            job.progress_pct = 20
            job.message = "Claude plant den Block — das dauert einige Minuten …"
            db.commit()

            # Wer abbricht, während der Lauf noch am Schloss wartet, hat noch
            # keinen Prozess zum Töten — deshalb hier noch einmal nachsehen.
            if job_id in self._abgebrochen:
                raise _Abgebrochen()

            antwort = client.rufe_claude(
                export.prompt,
                modell=einstellungen.model or None,
                effort=einstellungen.effort or None,
                bei_start=lambda prozess: self._prozesse.__setitem__(job_id, prozess),
            )

            job.progress_pct = 80
            job.model_used = antwort.modell
            job.cost_usd = antwort.kosten_usd
            job.duration_ms = antwort.dauer_ms
            job.message = "Die Antwort wird geprüft und übernommen …"
            db.commit()

            ergebnis = plan_import.uebernimm_plan(
                db,
                user_id,
                antwort.text,
                request_id=job.request_id,
                days=job.days,
            )

            job.state = "done"
            job.progress_pct = 100
            job.plan_id = ergebnis.plan.id
            job.finished_at = _now()
            job.message = _erfolgsmeldung(ergebnis, antwort.modell)
            _setze_status(einstellungen, "ready", None)
            db.commit()

        except Exception as exc:  # noqa: BLE001
            # Ein Abbruch tötet den Unterprozess, und der meldet sich dann als
            # gescheiterter Aufruf. Ohne diese Abfrage stünde am Job ein Fehler,
            # obwohl der Nutzer selbst auf „Abbrechen" gedrückt hat — deshalb
            # entscheidet die Absicht, nicht die Form des Fehlers.
            if job_id in self._abgebrochen or isinstance(exc, _Abgebrochen):
                db.rollback()
                job = db.get(KiJob, job_id)
                if job is not None:
                    job.state = "cancelled"
                    job.finished_at = _now()
                    job.message = "Der Planungslauf wurde abgebrochen."
                    db.commit()
                return

            if not isinstance(exc, (KiFehler, plan_import.PlanImportError)):
                logger.exception("Planungslauf fehlgeschlagen")
            # Zurückrollen, bevor der Fehler notiert wird: Ein halb geschriebener
            # Plan darf nicht stehen bleiben, und die Sitzung wäre sonst
            # unbrauchbar.
            db.rollback()
            job = db.get(KiJob, job_id)
            einstellungen = _einstellungen(db, user_id)
            if job is not None:
                _notiere_fehler(job, einstellungen, exc)
                db.commit()

    def markiere_unterbrochene_jobs(self) -> int:
        """Räumt Läufe auf, die einen Neustart der App nicht überlebt haben.

        Ihr Thread ist mit dem Prozess gestorben; der Zustand `running` in der
        Datenbank wäre sonst für immer eine Lüge und blockierte die Oberfläche
        mit einem Fortschrittsbalken, der sich nie bewegt.
        """
        from sqlalchemy import select

        with SessionLocal() as db:
            offen = db.scalars(
                select(KiJob).where(KiJob.state.in_(["running", "queued"]))
            ).all()
            for job in offen:
                job.state = "interrupted"
                job.finished_at = _now()
                job.message = (
                    "Der Planungslauf wurde durch einen Neustart der App "
                    "unterbrochen. Du kannst ihn erneut starten."
                )
            db.commit()
            return len(offen)


class _Abgebrochen(Exception):
    """Der Nutzer hat den Lauf beendet — kein Fehler, sondern eine Entscheidung."""


def _einstellungen(db, user_id: int) -> KiSettings:
    """Die Einstellungen des Nutzers, notfalls frisch angelegt.

    Eine Zeile je Nutzer, die beim ersten Zugriff entsteht — so muss weder die
    Registrierung daran denken noch eine Migration bestehende Konten nachrüsten.
    """
    from sqlalchemy import select

    einstellungen = db.scalar(select(KiSettings).where(KiSettings.user_id == user_id))
    if einstellungen is None:
        einstellungen = KiSettings(user_id=user_id)
        db.add(einstellungen)
        db.commit()
        db.refresh(einstellungen)
    return einstellungen


def _setze_status(einstellungen: KiSettings, status: str, meldung: str | None) -> None:
    einstellungen.status = status
    einstellungen.status_message = meldung


def _notiere_fehler(job: KiJob, einstellungen: KiSettings, exc: Exception) -> None:
    job.state = "failed"
    job.finished_at = _now()
    job.error = str(exc)

    meldung = getattr(exc, "meldung", None) or str(exc)
    if isinstance(exc, KiTokenUngueltig):
        status = "token_expired"
    elif isinstance(exc, KiKontingentErschoepft):
        status = "rate_limited"
    elif isinstance(exc, KiFehler):
        status = "error"
    else:
        # Auch der Importfehler landet hier — die KI hat geantwortet, nur nicht
        # in einer Form, die sich lesen ließ.
        status = "error"
        meldung = meldung or "Der Planungslauf ist mit einem Fehler abgebrochen."

    job.message = meldung
    _setze_status(einstellungen, status, meldung)


def _erfolgsmeldung(ergebnis, modell: str | None) -> str:
    anzahl = len(ergebnis.plan.sessions)
    einheiten = "1 Einheit" if anzahl == 1 else f"{anzahl} Einheiten"
    meldung = f"Block übernommen: {einheiten}"
    if modell:
        meldung += f" (geplant von {modell})"
    meldung += "."
    if ergebnis.warnings:
        meldung += " Hinweis: " + " ".join(ergebnis.warnings[:3])
    if ergebnis.garmin_hinweis:
        meldung += f" {ergebnis.garmin_hinweis}"
    return meldung


runner = KiRunner()
