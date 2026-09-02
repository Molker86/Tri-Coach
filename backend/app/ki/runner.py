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

import json
import logging
import subprocess
import threading
from datetime import date, datetime, timezone

from ..database import SessionLocal
from ..models import KiJob, KiSettings, User
from .errors import KiFehler, KiKontingentErschoepft, KiTokenUngueltig

logger = logging.getLogger(__name__)

ENDZUSTAENDE = frozenset({"done", "failed", "cancelled", "interrupted"})

# Die Jobart, die eine einzelne Planeinheit anpasst statt einen ganzen Block.
# Als Konstante, weil drei Stellen sie prüfen und ein Tippfehler still den
# falschen Lauf startete.
EINHEIT = "einheit"

# Die Jobart, die den Ernährungsplan zum aktiven Trainingsblock schreibt.
ERNAEHRUNG = "ernaehrung"

# Die Jobart, die den heutigen Tag an die Tagesverfassung anpasst. Wird nicht
# von einem Knopf gestartet, sondern nach jedem automatischen Garmin-Abgleich —
# siehe `ki/tagesform.py`.
TAGESFORM = "tagesform"

# Womit ein Lauf startet. Als Tabelle statt als Kette von Bedingungen: Beim
# dritten Fall wurde der Ausdruck unlesbar.
_STARTMELDUNG = {
    EINHEIT: "Die Anpassung wird vorbereitet …",
    ERNAEHRUNG: "Der Ernährungsplan wird vorbereitet …",
    TAGESFORM: "Der heutige Tag wird geprüft …",
}
_STARTMELDUNG_VORGABE = "Der Planungslauf wird vorbereitet …"

# Der Reparaturlauf denkt nicht nach, er räumt auf: Die Trainingsentscheidung
# ist längst gefallen und steht im kaputten JSON. `max` wäre dafür Denkzeit ohne
# Gegenwert, und der Nutzer wartet ohnehin schon.
REPARATUR_EFFORT = "low"
REPARATUR_TIMEOUT_S = 180

# Wie viel von der Antwort aufgehoben wird. Ein Block liegt bei gut 20 kB; die
# Grenze fängt nur den Fall ab, dass eine entgleiste Antwort die Datenbank
# aufbläht.
_ROHANTWORT_MAX = 200_000


def _gekuerzte_antwort(antwort) -> str | None:
    """Die Antwort so, wie sie gespeichert wird — Text oder geparste Struktur.

    Kam die Antwort über ein erzwungenes Schema, steht im Text dasselbe wie in
    `struktur`; kam sie ohne, gibt es nur den Text. Gespeichert wird, was sich
    wieder einfügen lässt.
    """
    text = (antwort.text or "").strip()
    if not text and antwort.struktur is not None:
        text = json.dumps(antwort.struktur, ensure_ascii=False)
    return text[:_ROHANTWORT_MAX] or None

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
        self._aktiver_nutzer: int | None = None
        self._prozesse: dict[int, subprocess.Popen] = {}
        self._abgebrochen: set[int] = set()
        # Das Schema des laufenden Aufrufs, damit der Reparaturlauf dasselbe
        # mitgeben kann. Es läuft immer nur ein Job — dafür sorgt das Schloss.
        self._letztes_schema: dict | None = None

    # -- Steuerung ----------------------------------------------------------

    def laeuft_gerade(self) -> int | None:
        return self._aktiver_job

    def besitzer(self) -> int | None:
        """Wem der laufende Lauf gehört — für die Meldung, nicht für den Riegel."""
        return self._aktiver_nutzer

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
        plan_session_id: int | None = None,
        wunsch: str | None = None,
        im_hintergrund: bool | None = None,
    ) -> int:
        """Legt den Job an und startet ihn. Gibt die Job-Kennung zurück.

        `kind="einheit"` passt eine einzelne Planeinheit an — dann sind
        `plan_session_id` und `wunsch` belegt und `request_id`/`start_date`
        bedeutungslos, weil Fragebogen und Tag aus der Einheit selbst kommen.
        """
        im_hintergrund = IM_HINTERGRUND if im_hintergrund is None else im_hintergrund
        with SessionLocal() as db:
            job = KiJob(
                user_id=user_id,
                kind=kind,
                state="queued",
                request_id=request_id,
                start_date=start_date,
                days=days,
                plan_session_id=plan_session_id,
                wunsch=wunsch,
                message=_STARTMELDUNG.get(kind, _STARTMELDUNG_VORGABE),
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
            self._aktiver_nutzer = user_id
            try:
                self._lauf(db, job_id, user_id)
            finally:
                self._aktiver_job = None
                self._aktiver_nutzer = None
                self._prozesse.pop(job_id, None)
                self._abgebrochen.discard(job_id)

    def _lauf(self, db, job_id: int, user_id: int) -> None:
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
            if job.kind == EINHEIT:
                self._einheit_lauf(db, job, user, einstellungen)
            elif job.kind == ERNAEHRUNG:
                self._ernaehrung_lauf(db, job, user, einstellungen)
            elif job.kind == TAGESFORM:
                self._tagesform_lauf(db, job, user, einstellungen)
            else:
                # Der Auffangfall ist die Blockplanung („manual" und das alte
                # „auto"). Eine neue Jobart gehört deshalb **davor** als `elif`
                # — hier hineinzufallen hieße, still einen Trainingsblock zu
                # planen, den niemand bestellt hat.
                self._block_lauf(db, job, user, einstellungen)
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
                    job.message = "Der Lauf wurde abgebrochen."
                    db.commit()
                return

            from .. import plan_import

            if not isinstance(exc, (KiFehler, plan_import.PlanImportError)):
                logger.exception("Lauf gegen die KI fehlgeschlagen")
            # Zurückrollen, bevor der Fehler notiert wird: Ein halb geschriebener
            # Plan darf nicht stehen bleiben, und die Sitzung wäre sonst
            # unbrauchbar.
            db.rollback()
            job = db.get(KiJob, job_id)
            einstellungen = _einstellungen(db, user_id)
            if job is not None:
                _notiere_fehler(job, einstellungen, exc)
                db.commit()

    def _mit_reparatur(self, db, job, einstellungen, antwort, uebernehmen):
        """Übernimmt die Antwort — und lässt sie einmal nachbessern, wenn nicht.

        Ein zweiter voller Planungslauf wäre die teuerste Antwort auf ein
        fehlendes Feld: Er dauert Minuten, kostet Kontingent und plant dabei
        einen *anderen* Block. Der Reparaturlauf bekommt stattdessen nur die
        Fehlerliste und das kaputte JSON, keinen Datenpaket und keine
        Trainingslehre — er soll nichts entscheiden, sondern ausbessern.

        Genau ein Versuch. Scheitert auch der, endet der Lauf wie bisher als
        gescheitert, aber mit erhaltener Rohantwort in `job.roh_antwort`.
        """
        from .. import plan_import

        try:
            return uebernehmen(antwort)
        except plan_import.PlanImportError as exc:
            # Festhalten, bevor der Block endet: Python löscht den Namen hinter
            # `as` beim Verlassen des `except`.
            fehler = str(exc)
            logger.info("Antwort unbrauchbar, ein Reparaturlauf: %s", fehler)

        job.progress_pct = 85
        job.message = "Die Antwort war unvollständig und wird nachgebessert …"
        db.commit()

        if job.id in self._abgebrochen:
            raise _Abgebrochen()

        from . import client
        from ..ai_export import baue_reparatur_prompt

        nachbesserung = client.rufe_claude(
            baue_reparatur_prompt(antwort.text or "", fehler),
            modell=einstellungen.model or None,
            effort=REPARATUR_EFFORT,
            timeout_s=REPARATUR_TIMEOUT_S,
            token=client.token_aus(einstellungen.token_encrypted),
            json_schema=self._letztes_schema,
            bei_start=lambda prozess: self._prozesse.__setitem__(job.id, prozess),
        )
        job.roh_antwort = _gekuerzte_antwort(nachbesserung)
        db.commit()
        return uebernehmen(nachbesserung)

    def _block_lauf(self, db, job: KiJob, user: User, einstellungen: KiSettings) -> None:
        """Der ganze nächste Block — der Regelfall."""
        from .. import ai_export, plan_import

        export = ai_export.erzeuge_export(
            db,
            user,
            request_id=job.request_id,
            start_date=job.start_date,
            days=job.days,
        )

        antwort = self._frage_claude(
            db,
            job,
            einstellungen,
            export.prompt,
            "Claude plant den Block — das dauert einige Minuten …",
            json_schema=export.schema,
        )

        job.message = "Die Antwort wird geprüft und übernommen …"
        db.commit()

        ergebnis = self._mit_reparatur(
            db,
            job,
            einstellungen,
            antwort,
            lambda a: plan_import.uebernimm_plan(
                db,
                user.id,
                a.text,
                request_id=job.request_id,
                days=job.days,
                struktur=a.struktur,
            ),
        )

        job.plan_id = ergebnis.plan.id
        _fertig(job, _erfolgsmeldung(ergebnis, antwort.modell))

    def _einheit_lauf(
        self, db, job: KiJob, user: User, einstellungen: KiSettings
    ) -> None:
        """Genau eine Einheit, angepasst an den Wunsch des Athleten.

        Derselbe Ablauf wie beim Block, nur mit einem anderen Export, einem
        anderen Parser und einem Nachlauf: Die geänderte Einheit geht sofort auf
        die Uhr, und was von der alten dort steht, wird dabei ersetzt oder
        entfernt. Der Nachlauf steht **im Lauf** und nicht dahinter, damit sein
        Ergebnis in derselben Meldung landet — sonst stünde „angepasst" da,
        während auf der Uhr noch die alte Vorgabe liegt.
        """
        from .. import ai_export, plan_import
        from ..garmin import automatik
        from ..models import PlanSession

        # Ob die Einheit *angepasst werden darf*, hat der Endpunkt geprüft
        # (`routers.plans.anpassbare_einheit`) — hier bleibt die Frage, ob es
        # sie überhaupt noch gibt: Zwischen dem Knopfdruck und diesem Punkt
        # liegen Minuten, in denen ihr Plan gelöscht worden sein kann.
        session = db.get(PlanSession, job.plan_session_id)
        if session is None or session.plan.user_id != user.id:
            raise _EinheitFehlt()
        wunsch = job.wunsch or ""

        export = ai_export.erzeuge_einheit_export(db, user, session, wunsch)

        antwort = self._frage_claude(
            db,
            job,
            einstellungen,
            export.prompt,
            "Claude passt die Einheit an …",
            json_schema=export.schema,
        )

        job.message = "Die Antwort wird geprüft und übernommen …"
        db.commit()

        ergebnis = self._mit_reparatur(
            db,
            job,
            einstellungen,
            antwort,
            lambda a: plan_import.uebernimm_einheit(
                db, session, a.text, wunsch, struktur=a.struktur
            ),
        )
        job.plan_id = session.plan_id

        garmin, hinweis = automatik.uebertrage_geaenderte_einheit(db, user.id, session)
        _fertig(job, _einheit_meldung(ergebnis, garmin, hinweis))

    def _tagesform_lauf(
        self, db, job: KiJob, user: User, einstellungen: KiSettings
    ) -> None:
        """Die Einheiten von heute, geprüft gegen die Werte von heute Morgen.

        Derselbe Ablauf wie bei der Einzelanpassung, nur über alle Einheiten des
        Tages und mit einem Ausstieg davor: Ohne Fitnessdaten hat die Aufgabe
        keinen Gegenstand, und der Lauf endet, **bevor** er Kontingent kostet.

        Der Nachlauf auf die Uhr steht wie dort im Lauf und nicht dahinter, damit
        sein Ergebnis in derselben Meldung landet — und er läuft nur über die
        tatsächlich geänderten Einheiten: Was unverändert bleibt, liegt in Garmin
        schon richtig.
        """
        from .. import ai_export, plan_import
        from ..garmin import automatik
        from . import tagesform

        # Was zwischen Anstoß und Lauf noch stehen geblieben ist. Dieselbe
        # Vorsicht wie bei `_EinheitFehlt`: Dazwischen liegen Minuten, in denen
        # der Block gelöscht oder das Training schon erfasst worden sein kann.
        tag = job.start_date or date.today()
        plan, sessions = tagesform.anpassbare_einheiten(db, user.id, tag)
        if plan is None or not sessions:
            _fertig(job, "Für heute stand nichts an, was sich anpassen ließe.")
            return

        export = ai_export.erzeuge_tagesform_export(db, user, plan, sessions, tag)

        # Der Prompt fragt nach den Werten von heute. Fehlen sie, bliebe eine
        # Aufgabe ohne Gegenstand übrig — und die Antwort darauf wäre geraten.
        if not export.payload.get("fitnessdaten"):
            _fertig(
                job,
                "Keine Fitnessdaten vorhanden — ohne Schlaf, HRV und Erholung "
                "gibt es am heutigen Tag nichts zu entscheiden.",
            )
            return

        antwort = self._frage_claude(
            db,
            job,
            einstellungen,
            export.prompt,
            "Claude prüft die heutigen Einheiten …",
            json_schema=export.schema,
        )

        job.message = "Die Antwort wird geprüft und übernommen …"
        db.commit()

        ergebnis = self._mit_reparatur(
            db,
            job,
            einstellungen,
            antwort,
            lambda a: plan_import.uebernimm_tagesform(
                db, sessions, a.text, struktur=a.struktur
            ),
        )
        job.plan_id = plan.id

        hinweise: list[str] = []
        for session in ergebnis.geaendert:
            _, hinweis = automatik.uebertrage_geaenderte_einheit(
                db, user.id, session
            )
            if hinweis:
                hinweise.append(hinweis)

        _fertig(job, _tagesform_meldung(ergebnis, hinweise))

    def _ernaehrung_lauf(
        self, db, job: KiJob, user: User, einstellungen: KiSettings
    ) -> None:
        """Der Ernährungsplan zum aktiven Trainingsblock.

        Derselbe Ablauf wie beim Block, nur mit einem anderen Export und einem
        anderen Parser — und **ohne Nachlauf**: Ein Ernährungsplan geht nirgends
        hin, er steht in der App. Auf die Uhr kommt er nicht.
        """
        from .. import ai_export, ernaehrung_import
        from ..models import Plan

        # Ob überhaupt geplant werden darf, hat der Endpunkt geprüft
        # (`routers.ernaehrung.pruefe_zeitraum`) — hier bleibt die Frage, ob es
        # den Block noch gibt: Zwischen dem Knopfdruck und diesem Punkt liegen
        # Minuten, in denen er gelöscht worden sein kann. Dieselbe Vorsicht wie
        # bei `_EinheitFehlt`.
        plan = (
            db.query(Plan)
            .filter(Plan.user_id == user.id, Plan.is_active.is_(True))
            .order_by(Plan.created_at.desc())
            .first()
        )
        if plan is None:
            raise _TrainingsplanFehlt()

        profil = ernaehrung_import.profil_hinweise(db, user.id)

        try:
            export = ai_export.erzeuge_ernaehrung_export(
                db,
                user,
                plan=plan,
                start_date=job.start_date,
                days=job.days,
                hinweise=profil,
            )
        except ai_export.ExportFehler as exc:
            raise _TrainingsplanFehlt(str(exc)) from exc

        antwort = self._frage_claude(
            db,
            job,
            einstellungen,
            export.prompt,
            "Claude stellt den Ernährungsplan zusammen — das dauert einige "
            "Minuten …",
        )

        job.message = "Die Antwort wird geprüft und übernommen …"
        db.commit()

        ergebnis = ernaehrung_import.uebernimm_ernaehrungsplan(
            db,
            user.id,
            antwort.text,
            trainingsplan=plan,
            start_date=job.start_date,
            days=job.days,
        )

        job.ernaehrungsplan_id = ergebnis.plan.id
        _fertig(job, _ernaehrung_meldung(ergebnis, antwort.modell))

    def _frage_claude(
        self,
        db,
        job: KiJob,
        einstellungen: KiSettings,
        prompt: str,
        meldung: str,
        json_schema: dict | None = None,
    ):
        """Der Aufruf selbst — für beide Aufgaben derselbe.

        Hier steht auch die Buchführung darüber, **welches Modell tatsächlich
        geantwortet hat**: Es gibt keinen stillen Rückfall, und ein Block oder
        eine Einheit von einem schwächeren Modell sähe sonst aus wie eine von
        Opus.
        """
        from . import client

        job.progress_pct = 20
        job.message = meldung
        # Der Reparaturlauf braucht dasselbe Schema. Am Runner und nicht als
        # Parameter durchgereicht: Es hängt am laufenden Job, und es läuft immer
        # nur einer — das Schloss steht darüber.
        self._letztes_schema = json_schema
        db.commit()

        # Wer abbricht, während der Lauf noch am Schloss wartet, hat noch
        # keinen Prozess zum Töten — deshalb hier noch einmal nachsehen.
        if job.id in self._abgebrochen:
            raise _Abgebrochen()

        antwort = client.rufe_claude(
            prompt,
            modell=einstellungen.model or None,
            effort=einstellungen.effort or None,
            token=client.token_aus(einstellungen.token_encrypted),
            json_schema=json_schema,
            bei_start=lambda prozess: self._prozesse.__setitem__(job.id, prozess),
        )

        job.progress_pct = 80
        job.model_used = antwort.modell
        job.cost_usd = antwort.kosten_usd
        job.duration_ms = antwort.dauer_ms
        # **Vor** dem Import und mit eigenem Commit: Scheitert das Übernehmen,
        # rollt `_lauf` die Sitzung zurück, und alles, was danach geschrieben
        # würde, wäre wieder weg. Genau dann wird die Antwort aber gebraucht.
        job.roh_antwort = _gekuerzte_antwort(antwort)
        db.commit()
        return antwort

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


class _EinheitFehlt(Exception):
    """Die anzupassende Einheit war beim Übernehmen nicht mehr da."""

    meldung = (
        "Die Einheit, die angepasst werden sollte, gibt es nicht mehr — "
        "vermutlich wurde ihr Plan inzwischen gelöscht oder abgelöst."
    )


class _TrainingsplanFehlt(Exception):
    """Ohne aktiven Trainingsblock gibt es nichts zu decken."""

    vorgabe = (
        "Es liegt kein aktiver Trainingsplan mehr vor. Ein Ernährungsplan "
        "richtet sich nach dem geplanten Training — plane zuerst einen Block."
    )

    def __init__(self, meldung: str | None = None) -> None:
        self.meldung = meldung or self.vorgabe
        super().__init__(self.meldung)


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
    elif isinstance(exc, (_EinheitFehlt, _TrainingsplanFehlt)):
        # Am Zugang zur KI liegt es nicht: Sie hat sauber geantwortet, nur ist
        # der Empfänger der Antwort verschwunden. Den Status stehen zu lassen
        # ist hier richtig — sonst stünde an jedem Knopf der App eine Warnung
        # über einen Zugang, mit dem nichts ist.
        status = None
    else:
        # Auch der Importfehler landet hier — die KI hat geantwortet, nur nicht
        # in einer Form, die sich lesen ließ.
        status = "error"
        meldung = meldung or "Der Lauf ist mit einem Fehler abgebrochen."

    job.message = meldung
    if status is not None:
        _setze_status(einstellungen, status, meldung)


def _fertig(job: KiJob, meldung: str) -> None:
    """Schließt einen Lauf erfolgreich ab."""
    job.state = "done"
    job.progress_pct = 100
    job.finished_at = _now()
    job.message = meldung


def _einheit_meldung(ergebnis, garmin: str, hinweis: str | None) -> str:
    """Was aus der Anpassung geworden ist — in einem Satz.

    Die Begründung der KI steht mit drin, weil sie die einzige Stelle ist, an
    der der Athlet erfährt, ob sie seinem Wunsch gefolgt ist. Sie kann lang
    werden; die Meldung ist der Ort, an dem sie ohnehin gelesen wird, also
    bleibt sie ganz stehen.
    """
    teile = [f'Einheit angepasst: „{ergebnis.session.title}".']
    if ergebnis.begruendung:
        teile.append(ergebnis.begruendung)
    if garmin == "uebertragen":
        teile.append("Sie liegt in der neuen Fassung im Garmin-Kalender.")
    elif garmin == "entfernt":
        teile.append("Der Tag ist jetzt frei — die alte Vorgabe wurde aus dem "
                     "Garmin-Kalender genommen.")
    if hinweis:
        teile.append(hinweis)
    if ergebnis.warnings:
        teile.append("Hinweis: " + " ".join(ergebnis.warnings[:2]))
    return " ".join(teile)


def _tagesform_meldung(ergebnis, hinweise: list[str]) -> str:
    """Was aus dem heutigen Tag geworden ist.

    Die Begründung steht ganz drin — sie ist die einzige Stelle, an der der
    Athlet erfährt, warum sein Tag anders aussieht. Anders als bei der Anpassung
    von Hand liest er sie allerdings kaum hier: Der Lauf ist vorbei, bevor
    jemand die App öffnet, und die Meldung eines abgeschlossenen Jobs rutscht
    aus der Liste. Deshalb steht sie zusätzlich an jeder angefassten Einheit.
    """
    anzahl = len(ergebnis.geaendert)
    if anzahl == 0:
        teile = ["Der heutige Tag bleibt, wie er geplant war."]
    elif anzahl == 1:
        teile = [f'Eine Einheit angepasst: „{ergebnis.geaendert[0].title}".']
    else:
        teile = [f"{anzahl} Einheiten an die Tagesverfassung angepasst."]
    if ergebnis.begruendung:
        teile.append(ergebnis.begruendung)
    teile += hinweise
    if ergebnis.warnings:
        teile.append("Hinweis: " + " ".join(ergebnis.warnings[:3]))
    return " ".join(teile)


def _ernaehrung_meldung(ergebnis, modell: str | None) -> str:
    tage = len(ergebnis.plan.tage)
    mahlzeiten = sum(len(tag.mahlzeiten) for tag in ergebnis.plan.tage)
    meldung = (
        f"Ernährungsplan übernommen: {tage} Tag(e), {mahlzeiten} Mahlzeiten"
    )
    if modell:
        meldung += f" (geschrieben von {modell})"
    meldung += "."
    if ergebnis.plan.supplemente:
        meldung += f" Dazu {len(ergebnis.plan.supplemente)} Supplement(e)."
    if ergebnis.warnings:
        meldung += " Hinweis: " + " ".join(ergebnis.warnings[:3])
    return meldung


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
