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
from typing import NamedTuple

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

# Welche Job-Art zu welcher Aktion gehört. `cleanup` sendet nichts nach Garmin:
# Der Lauf existiert nur, um den Kalender auf den Stand des aktiven Blocks zu
# bringen — nötig, wenn ein neuer Block einen übertragenen ablöst, aber selbst
# nicht auf die Uhr geht (automatische Übertragung abgeschaltet, oder der Block
# besteht nur aus Ruhetagen).
JOBARTEN = {
    "push": "workout_push",
    "remove": "workout_remove",
    "cleanup": "workout_cleanup",
}


class Aufraeumbilanz(NamedTuple):
    """Was ein Nachlauf aus Garmin genommen hat — nach Grund getrennt.

    Getrennt gezählt, weil beide Fälle verschieden klingen müssen: Ein
    vergangener Tag ist Altpapier, ein abgelöster Block stand dem neuen im Weg.
    Eine gemeinsame Zahl hätte die eine Hälfte unter der Überschrift der anderen
    gemeldet.
    """

    vergangen: int = 0
    ersetzt: int = 0
    # Ob der Nachlauf gar nicht durchkam. Für einen Abgleich oder eine
    # Übertragung ist das eine Randnotiz — deren Ziel war ein anderes. Ein
    # reiner Aufräumlauf hat dagegen nichts erreicht und muss das melden.
    fehlgeschlagen: bool = False

    @property
    def gesamt(self) -> int:
        return self.vergangen + self.ersetzt


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
                # Die Schwellenwerte kosten eigene Anfragen. Wer die
                # Nachführung abgeschaltet hat, soll sie nicht bezahlen.
                mit_leistungswerten=konto.profile_sync_enabled,
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
            # Das gedeckte Fenster fortschreiben — **nur hier**, im Erfolgsfall.
            # Ein abgebrochener oder gesperrter Lauf hat seinen Zeitraum nur
            # teilweise geschrieben; würde er trotzdem als gedeckt gelten,
            # bliebe der Rest für immer eine Lücke, weil der nächste Abgleich
            # nur noch das Aktualisierungsfenster holte.
            if konto.backfill_from is None or von < konto.backfill_from:
                konto.backfill_from = von
            if konto.synced_through is None or bis > konto.synced_through:
                konto.synced_through = bis
            db.commit()

            self._fuehre_profil_nach(db, konto, user_id, ergebnis.leistungswerte)

            # Der tägliche Abgleich ist der Zeitpunkt, an dem sich „vorbei"
            # ändert — und der Zugang steht hier ohnehin schon.
            bilanz = self._raeume_workouts_auf(db, konto, api, user_id)
            if bilanz.gesamt:
                job.workouts_removed = bilanz.gesamt
                job.message = f"{job.message} {_aufraeummeldung(bilanz)}"
                db.commit()

        except SyncAbbruch:
            job.state = "cancelled"
            job.message = "Der Abgleich wurde abgebrochen."
            job.cursor_date = _wiederaufsetzpunkt(ergebnis, tagesschleife_von)
            job.finished_at = _now()
            db.commit()

        except GarminRateLimit as exc:
            _notiere_fehler(job, konto, exc, "Der Abgleich")
            # Nur hier sinnvoll: Ein gesperrter Lauf soll dort weitermachen, wo
            # er stand, statt dieselben Tage noch einmal anzufragen.
            job.cursor_date = _wiederaufsetzpunkt(ergebnis, tagesschleife_von)
            db.commit()

        except Exception as exc:  # noqa: BLE001
            if not isinstance(exc, (GarminFehler, EntschluesselungFehlgeschlagen)):
                logger.exception("Garmin-Abgleich fehlgeschlagen")
            _notiere_fehler(job, konto, exc, "Der Abgleich")
            db.commit()

    # -- Übertragung in die Gegenrichtung -----------------------------------

    def starte_uebertragung(
        self,
        user_id: int,
        plan_id: int,
        aktion: str,
        *,
        ab: date | None = None,
        im_hintergrund: bool | None = None,
        pause_s: float | None = None,
    ) -> int:
        """Schiebt einen Plan nach Garmin, holt ihn zurück oder räumt nur auf.

        `aktion`: „push", „remove" oder „cleanup" (siehe `JOBARTEN`).

        Läuft durch dasselbe Schloss wie der Abgleich: Zwei Zugriffe auf Garmin
        gleichzeitig sind genau die Anfragedichte, gegen die sich die Sperre
        richtet — ob sie nun lesen oder schreiben.
        """
        im_hintergrund = IM_HINTERGRUND if im_hintergrund is None else im_hintergrund
        with SessionLocal() as db:
            job = GarminSyncJob(
                user_id=user_id,
                kind=JOBARTEN[aktion],
                state="queued",
                message={
                    "push": "Die Übertragung wird vorbereitet …",
                    "remove": "Das Entfernen wird vorbereitet …",
                    "cleanup": "Der Garmin-Kalender wird aufgeräumt …",
                }[aktion],
            )
            db.add(job)
            db.commit()
            job_id = job.id

        self._abbruch[job_id] = threading.Event()

        if im_hintergrund:
            threading.Thread(
                target=self._fuehre_uebertragung_aus,
                args=(job_id, user_id, plan_id, aktion, ab, pause_s),
                name=f"garmin-workouts-{job_id}",
                daemon=True,
            ).start()
        else:
            self._fuehre_uebertragung_aus(job_id, user_id, plan_id, aktion, ab, pause_s)

        return job_id

    def _fuehre_uebertragung_aus(
        self,
        job_id: int,
        user_id: int,
        plan_id: int,
        aktion: str,
        ab: date | None,
        pause_s: float | None,
    ) -> None:
        with self._schloss, SessionLocal() as db:
            self._aktiver_job = job_id
            try:
                self._uebertragungslauf(db, job_id, user_id, plan_id, aktion, ab, pause_s)
            finally:
                self._aktiver_job = None
                self._abbruch.pop(job_id, None)

    def _uebertragungslauf(
        self,
        db,
        job_id: int,
        user_id: int,
        plan_id: int,
        aktion: str,
        ab: date | None,
        pause_s: float | None,
    ) -> None:
        from ..models import Plan
        from . import uebertragung

        job = db.get(GarminSyncJob, job_id)
        konto = db.scalar(
            select(GarminAccount).where(GarminAccount.user_id == user_id)
        )
        plan = db.get(Plan, plan_id)
        if job is None or konto is None or plan is None:
            return

        job.state = "running"
        job.message = "Verbindung zu Garmin wird hergestellt …"
        db.commit()

        abbruch = self._abbruch.get(job_id, threading.Event())

        def melde(schritt: str, index: int, gesamt: int, meldung: str | None) -> None:
            job.step = schritt
            job.step_index = index
            job.step_total = gesamt
            # `max(0, …)`: Der Bestandsabgleich meldet sich vor der ersten
            # Einheit mit Index 0 und ergäbe sonst einen negativen Fortschritt.
            job.progress_pct = (
                max(0, min(99, int((index - 1) / gesamt * 100))) if gesamt else 0
            )
            job.message = meldung or f"{schritt} …"
            db.commit()

        fortschritt = Fortschritt(melde=melde, abgebrochen=abbruch.is_set)

        try:
            api = client_aus_token(entschluessle(konto.token_encrypted))

            vorab_entfernt = 0
            if aktion == "push":
                # Erst räumen, dann legen — die Reihenfolge trägt die
                # Neuplanung (siehe `_raeume_ersetzte_vorab`).
                vorab_entfernt = self._raeume_ersetzte_vorab(
                    db, api, user_id, plan.id, fortschritt, pause_s
                )
                ergebnis = uebertragung.uebertrage_plan(
                    db, api, user_id, plan,
                    profil=konto.user.profile,
                    ab=ab,
                    fortschritt=fortschritt,
                    pause_s=pause_s,
                )
            elif aktion == "cleanup":
                # Hier geht nichts nach Garmin: Der Lauf besteht allein aus dem
                # Nachlauf unten, der Vergangenes und Abgelöstes wegnimmt.
                ergebnis = uebertragung.UebertragungsErgebnis()
            else:
                ergebnis = uebertragung.entferne_plan(
                    db, api, plan, fortschritt=fortschritt, pause_s=pause_s
                )

            if frisch := token_aktualisieren(api):
                konto.token_encrypted = verschluessle(frisch)

            gelungen = ergebnis.uebertragen + ergebnis.entfernt + ergebnis.unveraendert
            job.state = "failed" if ergebnis.fehler and not gelungen else "done"
            job.progress_pct = 100
            job.workouts_pushed = ergebnis.uebertragen
            job.workouts_removed = ergebnis.entfernt + vorab_entfernt
            job.message = _uebertragungsmeldung(ergebnis, aktion)
            if vorab_entfernt:
                job.message = f"{job.message} {_ersatzmeldung(vorab_entfernt)}"
            job.finished_at = _now()

            # `last_sync_at` bleibt unberührt: Hier wurden keine Daten geholt,
            # und der tägliche Abgleich hängt an diesem Zeitstempel.
            if job.state == "done":
                konto.status = "connected"
                konto.status_message = None
                konto.rate_limited_until = None
            db.commit()

            # Der zweite Zeitpunkt zum Aufräumen: Wer den nächsten Block
            # überträgt, hat den vorigen hinter sich — ohne das bliebe die
            # Bibliothek voll, solange der tägliche Abgleich abgeschaltet ist.
            # Bewusst **nach** dem Festschreiben: Läuft das Aufräumen in die
            # Anfragesperre, setzten die Zeilen darüber sie sonst gleich wieder
            # zurück.
            if aktion in ("push", "cleanup"):
                bilanz = self._raeume_workouts_auf(
                    db, konto, api, user_id, ausser_plan_id=plan.id, pause_s=pause_s
                )
                job.workouts_removed += bilanz.gesamt
                if aktion == "cleanup":
                    # Der Nachlauf *ist* dieser Job — also berichtet allein er,
                    # und ein Fehlschlag darf hier nicht als „done" durchgehen.
                    job.message = _aufraeumlauf_meldung(bilanz)
                    if bilanz.fehlgeschlagen:
                        job.state = "failed"
                elif bilanz.gesamt:
                    job.message = f"{job.message} {_aufraeummeldung(bilanz)}"
                db.commit()

        except SyncAbbruch:
            job.state = "cancelled"
            job.message = (
                "Die Übertragung wurde abgebrochen. Bereits übertragene "
                "Einheiten bleiben in Garmin stehen."
            )
            job.finished_at = _now()
            db.commit()

        except Exception as exc:  # noqa: BLE001
            if not isinstance(exc, (GarminFehler, EntschluesselungFehlgeschlagen)):
                logger.exception("Übertragung nach Garmin fehlgeschlagen")
            db.rollback()
            job = db.get(GarminSyncJob, job_id)
            konto = db.scalar(
                select(GarminAccount).where(GarminAccount.user_id == user_id)
            )
            if job is not None and konto is not None:
                _notiere_fehler(job, konto, exc, "Die Übertragung")
                db.commit()

    def _raeume_ersetzte_vorab(
        self,
        db,
        api,
        user_id: int,
        plan_id: int,
        fortschritt: Fortschritt,
        pause_s: float | None,
    ) -> int:
        """Nimmt den abgelösten Block aus Garmin, **bevor** der neue hineingeht.

        Warum vorher und nicht am Ende wie das Aufräumen vergangener Tage: Beide
        Blöcke decken dieselben Tage ab. Bricht die Übertragung auf halbem Weg
        ab — eine Anfragesperre genügt dafür —, stünden auf der Uhr zwei
        Trainings am selben Tag, und welches davon überholt ist, sieht der
        Athlet vor dem Start nicht. Andersherum ist der schlimmste Fall ein Tag
        ohne Vorgabe: ärgerlich, aber nicht irreführend.

        Ein Fehlschlag hält die Übertragung nicht auf — sie ist das eigentliche
        Ziel des Laufs. Die Anfragesperre bleibt davon ausgenommen: Sie gilt für
        alles Folgende, und weiterzumachen verlängerte sie nur.
        """
        from . import uebertragung

        fortschritt.schritt(
            "aufraeumen", 0, 1, "Der abgelöste Block wird aus Garmin genommen …"
        )
        try:
            ergebnis = uebertragung.raeume_ersetzte_auf(
                db, api, user_id, ausser_plan_id=plan_id, pause_s=pause_s
            )
        except GarminRateLimit:
            # `_entferne_reihe` übersetzt auch die Form aus der Bibliothek
            # bereits in diesen Fehler — hier reicht das Durchlassen.
            raise
        except Exception:  # noqa: BLE001
            logger.warning("Abgelösten Block nicht aufgeräumt", exc_info=True)
            db.rollback()
            return 0

        if ergebnis.fehler:
            logger.warning("Nicht aufgeräumt: %s", "; ".join(ergebnis.fehler[:5]))
        return ergebnis.entfernt

    def _raeume_workouts_auf(
        self,
        db,
        konto: GarminAccount,
        api,
        user_id: int,
        *,
        ausser_plan_id: int | None = None,
        pause_s: float | None = None,
    ) -> Aufraeumbilanz:
        """Löscht Einheiten, deren Tag vorbei ist oder deren Block abgelöst wurde.

        Am Ende eines Laufs statt als eigener Job: Der Zugang steht, das Schloss
        ist gehalten, und ein Fortschrittsbalken für eine Handvoll Löschungen
        wäre Umstand ohne Nutzen.

        Kein Fehlschlag hier darf den Lauf umwerten — der hat sein eigentliches
        Ziel bereits erreicht. Nur die Anfragesperre wird festgehalten: Sie gilt
        für alles Folgende, und der Erfolgspfad hat sie gerade erst zurückgesetzt.
        """
        from .. import plan_aufraeumen
        from . import uebertragung

        try:
            ergebnis = uebertragung.raeume_vergangene_auf(
                db, api, user_id, pause_s=pause_s
            )
            # Ein abgelöster Block ist auf der Uhr genauso Altpapier wie ein
            # vergangener Tag — nur fällt er mehr auf, weil er neben dem neuen
            # Training auf demselben Tag steht. Eine Übertragung hat ihn schon
            # vorweg geräumt; hier greift es für den Abgleich, der ohne Knopf
            # auskommt.
            ersetzt = uebertragung.raeume_ersetzte_auf(
                db, api, user_id, ausser_plan_id=ausser_plan_id, pause_s=pause_s
            )
            ergebnis.fehler.extend(ersetzt.fehler)
            # Jetzt erst: Ein abgelöster Block darf nur verschwinden, wenn nichts
            # mehr von ihm in Garmin steht — die Zuordnung dorthin stirbt mit ihm.
            plan_aufraeumen.raeume_abgeloeste_plaene(db, user_id)
        except GarminRateLimit as exc:
            db.rollback()
            konto.status = "rate_limited"
            konto.status_message = exc.meldung
            konto.rate_limited_until = _now() + timedelta(hours=1)
            db.commit()
            return Aufraeumbilanz(fehlgeschlagen=True)
        except Exception:  # noqa: BLE001 — der Lauf selbst war erfolgreich
            logger.exception("Aufräumen vergangener Workouts fehlgeschlagen")
            db.rollback()
            return Aufraeumbilanz(fehlgeschlagen=True)

        if ergebnis.fehler:
            logger.warning(
                "Nicht aufgeräumt: %s", "; ".join(ergebnis.fehler[:5])
            )
        return Aufraeumbilanz(vergangen=ergebnis.entfernt, ersetzt=ersetzt.entfernt)

    def _fuehre_profil_nach(
        self,
        db,
        konto: GarminAccount,
        user_id: int,
        leistungswerte: dict | None = None,
    ) -> None:
        """Trägt Fitness- und Schwellenwerte ins Profil nach.

        Aus den Fitnessdaten kommen Gewicht, Ruhepuls, HRV und VO2max; FTP,
        Schwellenpace und Schwellenpuls hat der Lauf bereits geholt und reicht
        sie hier durch — geschrieben wird beides in einem Zug.
        """
        if not konto.profile_sync_enabled:
            return
        try:
            from ..profile_sync import uebernehme_aus_garmin

            uebernehme_aus_garmin(db, user_id, leistungswerte=leistungswerte)
        except Exception:  # noqa: BLE001 — der Abgleich selbst war erfolgreich
            logger.exception("Profil-Nachführung fehlgeschlagen")
            db.rollback()


def _notiere_fehler(job: GarminSyncJob, konto: GarminAccount, exc: Exception, was: str) -> None:
    """Trägt einen Fehlschlag in Job und Konto ein — für alle Laufarten gleich.

    `was` benennt den Lauf im Klartext, damit die Meldung für den unerwarteten
    Fall nicht von einem Abgleich spricht, wenn Trainings übertragen wurden.
    """
    job.error = str(exc)
    job.finished_at = _now()

    if isinstance(exc, GarminRateLimit):
        job.state = "rate_limited"
        job.message = exc.meldung
        konto.status = "rate_limited"
        konto.status_message = exc.meldung
        # Eine Stunde Ruhe. Kürzer wäre gefährlich: Jeder weitere Versuch
        # verlängert die Sperre auf der Gegenseite.
        konto.rate_limited_until = _now() + timedelta(hours=1)
        return

    job.state = "failed"
    if isinstance(exc, (GarminTokenUngueltig, EntschluesselungFehlgeschlagen)):
        meldung = getattr(exc, "meldung", None) or (
            "Der Sicherheitsschlüssel der App hat sich geändert. "
            "Bitte verbinde dein Garmin-Konto erneut."
        )
        konto.status = "token_expired"
    elif isinstance(exc, GarminFehler):
        meldung = exc.meldung
        konto.status = "error"
    else:
        meldung = f"{was} ist mit einem unerwarteten Fehler abgebrochen."
        konto.status = "error"

    job.message = meldung
    konto.status_message = meldung


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


def _uebertragungsmeldung(ergebnis, aktion: str) -> str:
    teile: list[str] = []
    if aktion == "push":
        if ergebnis.neu:
            teile.append(
                "1 Einheit übertragen"
                if ergebnis.neu == 1
                else f"{ergebnis.neu} Einheiten übertragen"
            )
        if ergebnis.aktualisiert:
            teile.append(f"{ergebnis.aktualisiert} aktualisiert")
        if ergebnis.unveraendert:
            teile.append(f"{ergebnis.unveraendert} waren bereits aktuell")
        if teile:
            meldung = "Im Garmin-Kalender steht alles: " + ", ".join(teile) + "."
        elif ergebnis.fehler:
            # Ohne diesen Fall stünde „Es gab keine Einheit zu übertragen"
            # direkt vor der Liste der Einheiten, bei denen es nicht klappte.
            meldung = "Keine Einheit konnte übertragen werden."
        else:
            meldung = "Es gab keine Einheit zu übertragen."
    elif aktion == "cleanup":
        # Ein Aufräumlauf sendet nichts; was er geleistet hat, weiß erst der
        # Nachlauf. `_aufraeumlauf_meldung` überschreibt diesen Platzhalter.
        meldung = "Der Garmin-Kalender wird geprüft …"
    else:
        meldung = (
            f"{ergebnis.entfernt} Einheiten aus Garmin entfernt."
            if ergebnis.entfernt
            else "Es stand nichts mehr in Garmin."
        )

    if ergebnis.fehler:
        meldung += " Nicht geklappt hat es bei: " + "; ".join(ergebnis.fehler[:5])
    return meldung


def _ersatzmeldung(anzahl: int) -> str:
    """Was vom abgelösten Block aus dem Kalender genommen wurde.

    Eigene Meldung statt `_aufraeummeldung`: Hier ging nichts *Vergangenes* weg,
    sondern die überholte Vorgabe für dieselben Tage, die der neue Block gerade
    belegt hat.
    """
    if anzahl == 1:
        return "1 Einheit des abgelösten Blocks wurde aus dem Kalender genommen."
    return f"{anzahl} Einheiten des abgelösten Blocks wurden aus dem Kalender genommen."


def _aufraeummeldung(bilanz: Aufraeumbilanz) -> str:
    """Was der Nachlauf weggenommen hat — nach Grund getrennt benannt.

    Beides in einer Zahl zusammenzufassen hieße, den abgelösten Block als
    „vergangenes Training" zu melden. Er liegt aber in der Zukunft, und wer die
    Meldung liest, will genau das unterscheiden können.
    """
    teile: list[str] = []
    if bilanz.vergangen:
        teile.append(
            "1 vergangenes Training wurde aus Garmin aufgeräumt."
            if bilanz.vergangen == 1
            else f"{bilanz.vergangen} vergangene Trainings wurden aus Garmin aufgeräumt."
        )
    if bilanz.ersetzt:
        teile.append(_ersatzmeldung(bilanz.ersetzt))
    return " ".join(teile)


def _aufraeumlauf_meldung(bilanz: Aufraeumbilanz) -> str:
    """Die Meldung eines Laufs, der *nur* aufräumt.

    Er hat kein zweites Ziel, hinter dem ein Fehlschlag verschwinden dürfte:
    Kommt er nicht durch, steht der abgelöste Block weiter im Kalender — und
    genau das muss dort stehen, statt einer Erfolgsmeldung über nichts.
    """
    if bilanz.fehlgeschlagen:
        return (
            "Der Garmin-Kalender ließ sich nicht aufräumen — der abgelöste Block "
            "steht dort weiter. Der nächste Abgleich holt es nach."
        )
    if not bilanz.gesamt:
        return "Im Garmin-Kalender stand nichts Überholtes."
    return _aufraeummeldung(bilanz)


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
