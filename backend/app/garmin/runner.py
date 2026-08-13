"""Führt einen Sync-Lauf aus und schreibt seinen Fortschritt fort.

Warum ein eigener Thread und nicht `BackgroundTasks`: Ein Backfill läuft
Minuten. Er muss abfragbar, abbrechbar und nach einem Neustart fortsetzbar sein
— nichts davon leistet ein Hintergrundauftrag von Starlette, der außerdem
minutenlang einen Platz im Threadpool belegte, über den auch normale Anfragen
laufen.

Warum ein **globales** Schloss und keines je Nutzer: Garmin bemisst seine
Anfragegrenze auch an der Herkunftsadresse. Zwei gleichzeitige Läufe erzeugen
genau die Anfragedichte, gegen die sich die Grenze richtet — auch bei zwei
verschiedenen Konten im selben Haushalt.
"""

import logging
import threading
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from ..crypto import EntschluesselungFehlgeschlagen, entschluessle, verschluessle
from ..database import SessionLocal
from ..models import GarminAccount, GarminSyncJob
from . import sync as sync_modul
from .client import client_aus_token, token_aktualisieren
from .errors import GarminFehler, GarminRateLimit, GarminTokenUngueltig
from .sync import Fortschritt, SyncAbbruch, SyncErgebnis, fuehre_sync_aus

logger = logging.getLogger(__name__)

ENDZUSTAENDE = frozenset(
    {"done", "failed", "cancelled", "rate_limited", "interrupted"}
)

# Ob Läufe in einen eigenen Thread abgegeben werden. Die Tests stellen das ab
# und lassen synchron laufen — sonst müsste jeder Test den Fortschritt abfragen
# und wäre von der Zeit abhängig.
IM_HINTERGRUND = True


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SyncRunner:
    """Ein Lauf zur Zeit, im eigenen Thread, Fortschritt in der Datenbank."""

    def __init__(self) -> None:
        self._schloss = threading.Lock()
        self._abbruch: dict[int, threading.Event] = {}
        self._aktiver_job: int | None = None

    # -- Steuerung ----------------------------------------------------------

    def laeuft_gerade(self) -> int | None:
        return self._aktiver_job

    def brich_ab(self, job_id: int) -> bool:
        ereignis = self._abbruch.get(job_id)
        if ereignis is None:
            return False
        ereignis.set()
        return True

    def starte(
        self,
        user_id: int,
        kind: str,
        von: date,
        bis: date,
        tagesschleife_von: date,
        *,
        im_hintergrund: bool | None = None,
        pause_s: float | None = None,
    ) -> int:
        """Legt den Job an und startet ihn. Gibt die Job-Kennung zurück.

        `im_hintergrund=False` führt den Lauf synchron aus — so kommen die Tests
        ohne Abfrageschleife aus und werden nicht zeitabhängig.
        """
        im_hintergrund = IM_HINTERGRUND if im_hintergrund is None else im_hintergrund
        with SessionLocal() as db:
            job = GarminSyncJob(
                user_id=user_id,
                kind=kind,
                state="queued",
                range_start=von,
                range_end=bis,
                day_loop_start=tagesschleife_von,
                message="Der Abgleich wird vorbereitet …",
            )
            db.add(job)
            db.commit()
            job_id = job.id

        self._abbruch[job_id] = threading.Event()

        if im_hintergrund:
            threading.Thread(
                target=self._fuehre_aus,
                args=(job_id, user_id, von, bis, tagesschleife_von, pause_s),
                name=f"garmin-sync-{job_id}",
                daemon=True,
            ).start()
        else:
            self._fuehre_aus(job_id, user_id, von, bis, tagesschleife_von, pause_s)

        return job_id

    # -- Ausführung ---------------------------------------------------------

    def _fuehre_aus(
        self,
        job_id: int,
        user_id: int,
        von: date,
        bis: date,
        tagesschleife_von: date,
        pause_s: float | None,
    ) -> None:
        # Der Thread bekommt seine **eigene** Sitzung: Eine Sitzung aus einer
        # Anfrage weiterzureichen wäre über Threadgrenzen hinweg nicht sicher
        # und stürbe mit der Anfrage.
        with self._schloss, SessionLocal() as db:
            self._aktiver_job = job_id
            try:
                self._lauf(db, job_id, user_id, von, bis, tagesschleife_von, pause_s)
            finally:
                self._aktiver_job = None
                self._abbruch.pop(job_id, None)

    def _lauf(
        self,
        db,
        job_id: int,
        user_id: int,
        von: date,
        bis: date,
        tagesschleife_von: date,
        pause_s: float | None,
    ) -> None:
        job = db.get(GarminSyncJob, job_id)
        konto = db.scalar(
            select(GarminAccount).where(GarminAccount.user_id == user_id)
        )
        if job is None or konto is None:
            return

        job.state = "running"
        job.message = "Verbindung zu Garmin wird hergestellt …"
        db.commit()

        abbruch = self._abbruch.get(job_id, threading.Event())

        def melde(schritt: str, index: int, gesamt: int, meldung: str | None) -> None:
            job.step = schritt
            job.step_index = index
            job.step_total = gesamt
            job.progress_pct = min(99, int(index / gesamt * 100)) if gesamt else 0
            job.message = meldung or f"{schritt} werden geladen …"
            if sync_modul.PAUSE_SEKUNDEN:
                db.commit()

        fortschritt = Fortschritt(melde=melde, abgebrochen=abbruch.is_set)
        # Vorab angelegt, damit der zuletzt verarbeitete Tag auch dann
        # verfügbar ist, wenn der Lauf mit einer Ausnahme endet.
        ergebnis = SyncErgebnis()

        try:
            api = client_aus_token(entschluessle(konto.token_encrypted))

            fuehre_sync_aus(
                db,
                api,
                user_id,
                von,
                bis,
                tagesschleife_von,
                fortschritt,
                pause_s=sync_modul.PAUSE_SEKUNDEN if pause_s is None else pause_s,
                ergebnis=ergebnis,
            )

            # Die Bibliothek erneuert den Zugangsschlüssel unterwegs still.
            # Ohne Zurückschreiben liefe die gespeicherte Kopie irgendwann ab.
            if frisch := token_aktualisieren(api):
                konto.token_encrypted = verschluessle(frisch)

            job.state = "done"
            job.progress_pct = 100
            job.activities_new = ergebnis.aktivitaeten_neu
            job.activities_updated = ergebnis.aktivitaeten_aktualisiert
            job.wellness_days = ergebnis.fitness_tage
            job.message = _erfolgsmeldung(ergebnis)
            job.finished_at = _now()
            job.cursor_date = None

            konto.last_sync_at = _now()
            konto.status = "connected"
            konto.status_message = None
            konto.rate_limited_until = None
            if konto.backfill_from is None or von < konto.backfill_from:
                konto.backfill_from = von
            db.commit()

            self._fuehre_profil_nach(db, konto, user_id)

        except SyncAbbruch:
            job.state = "cancelled"
            job.message = "Der Abgleich wurde abgebrochen."
            job.cursor_date = _wiederaufsetzpunkt(ergebnis, tagesschleife_von)
            job.finished_at = _now()
            db.commit()

        except GarminRateLimit as exc:
            job.state = "rate_limited"
            job.cursor_date = _wiederaufsetzpunkt(ergebnis, tagesschleife_von)
            job.message = exc.meldung
            job.finished_at = _now()
            konto.status = "rate_limited"
            konto.status_message = exc.meldung
            # Eine Stunde Ruhe. Kürzer wäre gefährlich: Jeder weitere Versuch
            # verlängert die Sperre auf der Gegenseite.
            konto.rate_limited_until = _now() + timedelta(hours=1)
            db.commit()

        except (GarminTokenUngueltig, EntschluesselungFehlgeschlagen) as exc:
            meldung = getattr(exc, "meldung", None) or (
                "Der Sicherheitsschlüssel der App hat sich geändert. "
                "Bitte verbinde dein Garmin-Konto erneut."
            )
            job.state = "failed"
            job.message = meldung
            job.error = str(exc)
            job.finished_at = _now()
            konto.status = "token_expired"
            konto.status_message = meldung
            db.commit()

        except GarminFehler as exc:
            job.state = "failed"
            job.message = exc.meldung
            job.error = str(exc)
            job.finished_at = _now()
            konto.status = "error"
            konto.status_message = exc.meldung
            db.commit()

        except Exception as exc:  # noqa: BLE001
            logger.exception("Garmin-Abgleich fehlgeschlagen")
            job.state = "failed"
            job.message = "Der Abgleich ist mit einem unerwarteten Fehler abgebrochen."
            job.error = str(exc)
            job.finished_at = _now()
            konto.status = "error"
            konto.status_message = job.message
            db.commit()

    def _fuehre_profil_nach(self, db, konto: GarminAccount, user_id: int) -> None:
        """Trägt Gewicht, Ruhepuls, HRV und VO2max ins Profil nach."""
        if not konto.profile_sync_enabled:
            return
        try:
            from ..profile_sync import uebernehme_aus_garmin

            uebernehme_aus_garmin(db, user_id)
        except Exception:  # noqa: BLE001 — der Abgleich selbst war erfolgreich
            logger.exception("Profil-Nachführung fehlgeschlagen")
            db.rollback()


def _wiederaufsetzpunkt(ergebnis: SyncErgebnis, standard: date) -> date:
    """Wo ein unterbrochener Lauf wieder ansetzen soll.

    Der Tag *nach* dem letzten vollständig verarbeiteten. Ein doppelt
    verarbeiteter Tag wäre zwar folgenlos — alle Schreibvorgänge sind Upserts —,
    kostet aber vier Anfragen an eine Gegenstelle, die uns gerade erst gebremst
    hat.
    """
    if ergebnis.letzter_tag is None:
        return standard
    return ergebnis.letzter_tag + timedelta(days=1)


def _erfolgsmeldung(ergebnis) -> str:
    teile: list[str] = []
    if ergebnis.aktivitaeten_neu:
        teile.append(
            "1 neues Training"
            if ergebnis.aktivitaeten_neu == 1
            else f"{ergebnis.aktivitaeten_neu} neue Trainings"
        )
    if ergebnis.aktivitaeten_aktualisiert:
        teile.append(f"{ergebnis.aktivitaeten_aktualisiert} aktualisiert")
    if ergebnis.fitness_tage:
        teile.append(f"{ergebnis.fitness_tage} Tage Fitnessdaten")

    meldung = "Abgleich abgeschlossen: " + ", ".join(teile) if teile else (
        "Abgleich abgeschlossen — es gab nichts Neues."
    )
    if ergebnis.hinweise:
        meldung += " Hinweis: " + " ".join(dict.fromkeys(ergebnis.hinweise))
    return meldung


def markiere_unterbrochene_jobs() -> int:
    """Räumt Läufe auf, die einen Neustart der App nicht überlebt haben.

    Ihr Thread ist mit dem Prozess gestorben; der Zustand `running` in der
    Datenbank wäre sonst für immer eine Lüge und blockierte die Oberfläche mit
    einem Fortschrittsbalken, der sich nie bewegt.
    """
    with SessionLocal() as db:
        offen = db.scalars(
            select(GarminSyncJob).where(GarminSyncJob.state.in_(["running", "queued"]))
        ).all()
        for job in offen:
            job.state = "interrupted"
            job.finished_at = _now()
            job.message = (
                "Der Abgleich wurde durch einen Neustart der App unterbrochen. "
                "Du kannst ihn erneut starten."
            )
        db.commit()
        return len(offen)


runner = SyncRunner()
