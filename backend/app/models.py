"""SQLAlchemy-Modelle.

Bewusst als Strings statt DB-Enums modelliert: Die Validierung passiert in den
Pydantic-Schemas, und SQLite bekommt so keine Migrationsprobleme, wenn später
eine Sportart oder ein Einheitentyp dazukommt.
"""

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .config import GARMIN_SYNC_HOUR
from .database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Die Anmeldung läuft über Kontoauswahl, nicht über ein Passwort. Die Spalte
    # bleibt (leer) bestehen, weil ihr Entfernen ohne Alembic ein Neuaufbauen
    # der Tabelle erfordern und bestehende Datenbanken brechen würde.
    hashed_password: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    profile: Mapped["AthleteProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    requests: Mapped[list["TrainingRequest"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    plans: Mapped[list["Plan"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    logs: Mapped[list["SessionLog"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    garmin_account: Mapped["GarminAccount | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    ki_settings: Mapped["KiSettings | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class AthleteProfile(Base):
    """Physiologische Stammdaten. Jederzeit änderbar; jede Änderung wird in
    `ProfileHistory` mitgeschrieben, damit Trendverläufe im KI-Export landen."""

    __tablename__ = "athlete_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)

    # Anthropometrie
    birth_date: Mapped[date | None] = mapped_column(Date)
    sex: Mapped[str | None] = mapped_column(String(16))  # female | male | diverse | none
    height_cm: Mapped[float | None] = mapped_column(Float)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    body_fat_pct: Mapped[float | None] = mapped_column(Float)

    # Kardiale Marker
    resting_hr: Mapped[int | None] = mapped_column(Integer)
    max_hr: Mapped[int | None] = mapped_column(Integer)
    lthr: Mapped[int | None] = mapped_column(Integer)  # Laktatschwellen-Herzfrequenz
    vo2max: Mapped[float | None] = mapped_column(Float)
    hrv_rmssd: Mapped[float | None] = mapped_column(Float)

    # Sportartspezifische Leistungswerte
    ftp_watts: Mapped[int | None] = mapped_column(Integer)  # Rad
    threshold_pace_run: Mapped[str | None] = mapped_column(String(16))  # "4:15" min/km
    css_swim: Mapped[str | None] = mapped_column(String(16))  # "1:45" min/100m

    # Trainingskontext
    current_weekly_hours: Mapped[float | None] = mapped_column(Float)
    stress_level: Mapped[int | None] = mapped_column(Integer)  # 1-5 (Beruf/Alltag)
    injuries: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    # Bestzeiten in zwei Feldern, weil sie zwei Herkünfte haben: `personal_bests`
    # ist der Freitext des Athleten (Schwimmen, Rad, alte Wettkämpfe),
    # `garmin_personal_bests` die Laufrekorde, die Garmin selbst erkannt hat —
    # eine Liste aus {sportart, strecke, zeit, datum}.
    personal_bests: Mapped[str | None] = mapped_column(Text)
    garmin_personal_bests: Mapped[list | None] = mapped_column(JSON)

    # Altlasten: Trainingserfahrung und selbst geschätzter Schlaf wurden aus
    # Oberfläche und Export entfernt (Schlaf misst Garmin, Erfahrung sagt über
    # den nächsten Block nichts, was die Historie nicht besser sagt). Die
    # Spalten bleiben stehen, damit bestehende Datenbanken weiterlaufen.
    experience_years: Mapped[float | None] = mapped_column(Float)
    sleep_hours: Mapped[float | None] = mapped_column(Float)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    user: Mapped[User] = relationship(back_populates="profile")


class ProfileHistory(Base):
    """Schnappschuss der veränderlichen Werte — für Gewichts-/HRV-Trends."""

    __tablename__ = "profile_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    resting_hr: Mapped[int | None] = mapped_column(Integer)
    hrv_rmssd: Mapped[float | None] = mapped_column(Float)
    vo2max: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[int | None] = mapped_column(Integer)
    ftp_watts: Mapped[int | None] = mapped_column(Integer)


class TrainingRequest(Base):
    """Eine ausgefüllte Fragebogen-Runde ("Neues Training")."""

    __tablename__ = "training_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    discipline: Mapped[str] = mapped_column(String(32))  # run|swim|bike|triathlon

    # Zielsetzung
    goal_type: Mapped[str | None] = mapped_column(String(64))
    goal_text: Mapped[str | None] = mapped_column(Text)
    race_date: Mapped[date | None] = mapped_column(Date)
    race_distance: Mapped[str | None] = mapped_column(String(64))

    # Verfügbarkeit
    available_days: Mapped[list] = mapped_column(JSON, default=list)
    day_sport_map: Mapped[dict] = mapped_column(JSON, default=dict)
    day_time_budget: Mapped[dict] = mapped_column(JSON, default=dict)  # Minuten je Tag
    long_session_day: Mapped[str | None] = mapped_column(String(16))
    weekly_hours_target: Mapped[float | None] = mapped_column(Float)

    # Ergänzendes Training
    supplemental: Mapped[list] = mapped_column(JSON, default=list)  # strength/mobility/...
    equipment: Mapped[list] = mapped_column(JSON, default=list)

    # Freitexte je Fragen-Cluster: {"goal": "...", "availability": "...", ...}
    free_text: Mapped[dict] = mapped_column(JSON, default=dict)

    user: Mapped[User] = relationship(back_populates="requests")
    plans: Mapped[list["Plan"]] = relationship(back_populates="request")


class Plan(Base):
    """Ein von der KI generierter Trainingsblock über wenige Tage."""

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("training_requests.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    coaching_notes: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    # Der Tag, ab dem dieser Block selbst geplant wurde — anders als
    # `start_date` wandert er nie. Ein Block übernimmt die Vergangenheit des
    # Blocks, den er ablöst (`plan_aufraeumen.uebernimm_vergangenheit`), und
    # `start_date` reicht danach weiter zurück als das, was diese KI-Antwort je
    # vorgesehen hat. Wer wissen will, was *dieser* Block vorhatte — der
    # Kalender, die Umsetzungsquote, `aktueller_plan` im Export, das
    # Blockumfeld der Einzelanpassung, die Übertragung —, fragt hier. Ohne die
    # Spalte bräuchte jede der fünf Stellen ihre eigene Grenze, und fünf
    # Grenzen laufen auseinander.
    geplant_ab: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)  # KI-Antwort im Original

    @property
    def beginn(self) -> date:
        """`geplant_ab` mit Rückfall — Blöcke von vor der Spalte kennen sie nicht.

        Dort galten beide Daten noch dasselbe: Vor der Übernahme der
        Vergangenheit wanderte `start_date` nie.
        """
        return self.geplant_ab or self.start_date

    user: Mapped[User] = relationship(back_populates="plans")
    request: Mapped["TrainingRequest | None"] = relationship(back_populates="plans")
    sessions: Mapped[list["PlanSession"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class PlanSession(Base):
    """Eine geplante Trainingseinheit."""

    __tablename__ = "plan_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"), index=True)

    date: Mapped[date] = mapped_column(Date, index=True)
    week_number: Mapped[int] = mapped_column(Integer)
    order_in_day: Mapped[int] = mapped_column(Integer, default=0)

    sport: Mapped[str] = mapped_column(String(32))
    session_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    structure: Mapped[str | None] = mapped_column(Text)  # Aufbau der Einheit
    purpose: Mapped[str | None] = mapped_column(Text)  # Trainingswirkung

    duration_min: Mapped[int | None] = mapped_column(Integer)
    distance_km: Mapped[float | None] = mapped_column(Float)
    intensity_zone: Mapped[str | None] = mapped_column(String(16))
    target_hr_low: Mapped[int | None] = mapped_column(Integer)
    target_hr_high: Mapped[int | None] = mapped_column(Integer)
    target_pace: Mapped[str | None] = mapped_column(String(64))
    target_power: Mapped[str | None] = mapped_column(String(64))
    rpe_target: Mapped[int | None] = mapped_column(Integer)

    # Becken oder Freiwasser. Nur bei `sport == "swim"` belegt und die einzige
    # Angabe, die eine Schwimmeinheit sonst nirgends trägt: Aus Titel und
    # Aufbau ist sie nicht sicher abzulesen, und ohne sie ging jede Einheit als
    # Beckentraining auf die Uhr — samt Bahnlänge, die im See nichts zählt.
    swim_location: Mapped[str | None] = mapped_column(String(16))

    # Drinnen auf der Rolle oder draußen auf der Straße. Nur bei
    # `sport == "bike"` (und am Radteil einer Koppeleinheit) belegt, und die
    # Angabe entscheidet, **womit die Uhr steuert**: Watt kann sie nur vorgeben,
    # wo die Leistung auch gemessen wird — auf dem Smart Trainer immer, draußen
    # nur mit Wattmessung am Rad. Ohne sie ging jede Radeinheit mit
    # Leistungskorridor auf die Uhr, und wer ohne Powermeter draußen fuhr, sah
    # dort ein Ziel, das sein Rad nicht messen kann.
    bike_location: Mapped[str | None] = mapped_column(String(16))

    # Der Bauplan der Einheit, so wie die KI ihn geliefert hat: die Schrittliste
    # aus `AIStepIn`. `structure` bleibt daneben stehen und ist der Text, den
    # der Athlet liest — hier steht dieselbe Einheit für die Uhr. Leer heißt,
    # dass der Block aus der Zeit vor dem Feld stammt oder von einer KI kam,
    # die den Prompt nicht kennt; dann zerlegt `workouts.py` wie bisher den
    # Fließtext.
    steps_json: Mapped[list | None] = mapped_column(JSON)

    # Einzeln nachträglich angepasst: Der Wunsch des Athleten im Wortlaut und
    # wann die KI ihn umgesetzt hat. Steht an der Einheit und nicht bloß am
    # Job, weil der Job irgendwann aus der Liste rutscht — die Einheit trägt
    # ihre Abweichung vom ursprünglichen Block dagegen dauerhaft, und ohne den
    # Wortlaut wäre in der Ansicht nicht mehr zu erkennen, warum sie anders
    # aussieht als der Rest.
    angepasst_am: Mapped[datetime | None] = mapped_column(DateTime)
    anpassungswunsch: Mapped[str | None] = mapped_column(Text)

    # Als welches Garmin-Workout diese Einheit auf der Uhr lag und seit wann.
    # Sieht aus wie eine Kopie von `GarminWorkoutLink` und ist das Gegenteil:
    # Der Link beschreibt den **jetzigen** Zustand in Garmin und stirbt, sobald
    # der Termin vorbei ist (`uebertragung.raeume_vergangene_auf`) — genau
    # bevor das Training des Tages hier ankommt. `garmin/matching.py` braucht
    # die Angabe aber danach, um die Aktivität ihrer Vorgabe zuzuordnen.
    # Deshalb hier, wo sie mit der Einheit lebt und mit ihr stirbt.
    garmin_workout_id: Mapped[str | None] = mapped_column(String(32))
    garmin_pushed_at: Mapped[datetime | None] = mapped_column(DateTime)

    plan: Mapped[Plan] = relationship(back_populates="sessions")
    log: Mapped["SessionLog | None"] = relationship(
        back_populates="plan_session", uselist=False
    )


class SessionLog(Base):
    """Tatsächlich absolviertes Training."""

    __tablename__ = "session_logs"
    __table_args__ = (UniqueConstraint("plan_session_id", name="uq_log_plan_session"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_session_id: Mapped[int | None] = mapped_column(ForeignKey("plan_sessions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    date: Mapped[date] = mapped_column(Date, index=True)
    sport: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="completed")
    # completed | partial | skipped

    duration_min: Mapped[int | None] = mapped_column(Integer)
    distance_km: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[int | None] = mapped_column(Integer)
    max_hr: Mapped[int | None] = mapped_column(Integer)
    # Einheit hängt an `sport`: Laufen min/km, Schwimmen min/100m, Rad km/h.
    avg_pace: Mapped[str | None] = mapped_column(String(32))
    avg_power: Mapped[int | None] = mapped_column(Integer)
    avg_cadence: Mapped[int | None] = mapped_column(Integer)
    elevation_gain_m: Mapped[int | None] = mapped_column(Integer)
    calories: Mapped[int | None] = mapped_column(Integer)

    # Meistens geschätzt (`mapping.schaetze_rpe`), weil Garmin je Aktivität kein
    # RPE *berechnet*. Der Athlet kann es in Connect aber selbst eintragen; dann
    # steht hier sein Wert und `rpe_source` sagt es. Muskelkater,
    # Schlafqualität, Morgenpuls und Morgen-HRV kamen aus dem
    # Erfassungsformular; mit ihm sind auch ihre Spalten weg
    # (`database._ENTFALLENE_SPALTEN`). Was sie beschrieben, misst die Uhr
    # ohnehin genauer und Nacht für Nacht — siehe `WellnessDay`.
    rpe: Mapped[int | None] = mapped_column(Integer)  # 1-10 (Borg CR10)

    # Garmins „Wie hast du dich gefühlt?" auf der Skala, die der Athlet in
    # Connect vor sich hat: 0 sehr schwach, 5 normal, 10 sehr stark. Die einzige
    # Angabe dieser App neben einem selbst vergebenen RPE, die er gesetzt hat —
    # und deshalb meist leer: Sie steht nur an den Einheiten, die er bewertet
    # hat. `NULL` heißt „nicht bewertet" und ist ausdrücklich keine Aussage über
    # die Einheit; 0 dagegen ist eine. Kommalos ist der Wert nicht: Die Uhr
    # kennt fünf Stufen und trifft damit 2,5 und 7,5
    # (`mapping.bewertung_aus_detail`).
    garmin_feel: Mapped[float | None] = mapped_column(Float)

    notes: Mapped[str | None] = mapped_column(Text)

    # Herkunft. `garmin_activity_id` trägt die Idempotenz des Imports: Ein
    # zweiter Sync über denselben Zeitraum aktualisiert den Eintrag, statt ihn
    # zu verdoppeln (Index `uq_log_garmin_activity` in `database.py`).
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | garmin
    garmin_activity_id: Mapped[str | None] = mapped_column(String(32))
    garmin_activity_type: Mapped[str | None] = mapped_column(String(48))  # roher typeKey

    # Garmins eigene Lastgrößen. Sie ersetzen die sRPE-Rechnung der App nicht
    # (andere Skala, siehe `sportscience.acute_chronic_ratio`), gehen aber
    # zusätzlich in den KI-Export — dort ist die gemessene Last die härtere
    # Aussage als ein geschätztes RPE.
    garmin_training_load: Mapped[float | None] = mapped_column(Float)
    garmin_aerobic_te: Mapped[float | None] = mapped_column(Float)
    garmin_anaerobic_te: Mapped[float | None] = mapped_column(Float)

    # Wie die Einheit *ausgeführt* wurde, nicht nur dass sie stattfand. Die
    # Zeitverteilung über die Herzfrequenzzonen stand immer schon in derselben
    # Listenantwort, aus der die Einheit entsteht — `mapping.schaetze_rpe()`
    # las sie, schätzte daraus das RPE und warf sie weg. Ohne sie steht eine
    # Schwelleneinheit als „37 min, HF-Schnitt 148" da, und niemand sieht, ob
    # die Intervalle standen. Sekunden je Zone, nur belegte Zonen; `None` heißt
    # „die Uhr hat keine Zonen aufgezeichnet" und ist etwas anderes als „alles
    # in Z1".
    hr_zone_seconds: Mapped[dict | None] = mapped_column(JSON)

    # Garmins eigene Zusammenfassung der Abschnitte (`splitSummaries` im
    # Aktivitätsdetail): wie viele Arbeitsabschnitte, Pausen, Ein- und
    # Ausrollen tatsächlich absolviert wurden, jeweils mit Dauer und Puls. Das
    # Detail wird für jede Einheit der letzten 42 Tage ohnehin geholt
    # (`sync.BEWERTUNGSFENSTER_TAGE`) — es kostet keine zusätzliche Anfrage.
    garmin_abschnitte: Mapped[list | None] = mapped_column(JSON)

    # Die Übungen, die die Uhr in einer Kraft- oder Mobility-Einheit gezählt
    # hat (`get_activity_exercise_sets`, `mapping.uebungen_aus_saetzen`) — mit
    # Garmins Katalognamen, Satzzahl und Wiederholungen bzw. Haltedauer. Bis
    # hierher stand im Export nur, was geplant *war*: Für Ausdauereinheiten
    # schließt `garmin_abschnitte` die Lücke zwischen Vorgabe und Ausführung,
    # für diese beiden Sportarten klaffte sie weiter. Anders als die vier
    # Nachbarn kostet die Spalte eine **eigene** Anfrage je Einheit — deshalb
    # nur für `workouts.UEBUNGSSPORTARTEN` und nur innerhalb von
    # `sync.BEWERTUNGSFENSTER_TAGE`.
    garmin_uebungen: Mapped[list | None] = mapped_column(JSON)

    # Garmins Urteil, wie gut das zugrunde liegende Workout eingehalten wurde
    # (0-100). Steht nur an Einheiten, die aus einem Workout gestartet wurden.
    # An der Schlüsseleinheit vom 19.08. stand hier 48 — die Einheit brach nach
    # zwei Dritteln ab, und keine andere Zahl im Export sagte das.
    garmin_compliance: Mapped[int | None] = mapped_column(Integer)

    # Die Kennung des Workouts, aus dem diese Aktivität gestartet wurde
    # (`metadataDTO.associatedWorkoutId`). Der **einzige** Rückbezug auf die
    # Planeinheit: `garmin/matching.py` löst sie über `GarminWorkoutLink` auf
    # und führt damit ohne jeden Bezug auf den Tag zur Vorgabe. Leer heißt frei
    # aufgezeichnet — oder älter als `sync.BEWERTUNGSFENSTER_TAGE`, wo das
    # Detail gar nicht erst geholt wird.
    garmin_workout_id: Mapped[str | None] = mapped_column(String(32))

    # Der Athlet hat die Zuordnung zur Planeinheit selbst gelöst
    # (`DELETE /api/plans/sessions/{id}/verknuepfung`). Ohne diese Marke käme
    # sie beim nächsten Abgleich sofort zurück: Die Workout-Kennung bleibt an
    # der Aktivität stehen und führt wieder auf dieselbe Einheit.
    zuordnung_manuell: Mapped[bool] = mapped_column(Boolean, default=False)
    # Woher `rpe` stammt. Ohne Schätzung fielen sRPE, ACWR und die Abstandsregel
    # für intensive Einheiten für die meisten Einheiten aus. Die Quelle geht in
    # den KI-Export, damit die KI die Belastbarkeit der Zahl einordnen kann:
    # `athlet` ist seine eigene Bewertung aus Connect und wiegt schwerer als
    # jede Schätzung. `manual` ist dagegen nur noch ein Altwert — er steht an
    # Einträgen aus der Zeit, als es ein Erfassungsformular gab.
    rpe_source: Mapped[str] = mapped_column(String(20), default="manual")
    # athlet | hf_zonen | trainingseffekt | hf_schnitt | manual (Altwert)

    user: Mapped[User] = relationship(back_populates="logs")
    plan_session: Mapped["PlanSession | None"] = relationship(back_populates="log")


class GarminAccount(Base):
    """Verbindung zu einem Garmin-Connect-Konto.

    Bewusst **ohne Passwortspalte**: Das Passwort wird einmal zum Anmelden
    benutzt und danach verworfen; dauerhaft bleibt nur das Token, und zwar
    verschlüsselt (`crypto.py`). Die Datenbank liegt im Add-on-Datenverzeichnis
    und wandert damit in jedes Home-Assistant-Backup — ein Klartext-Token mit
    Dauerzugriff auf ein fremdes Gesundheitskonto hätte dort nichts zu suchen.
    """

    __tablename__ = "garmin_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    email: Mapped[str] = mapped_column(String(255))  # nur Anzeige und Wieder-Anmeldung
    token_encrypted: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[str] = mapped_column(String(24), default="connected")
    # connected | token_expired | rate_limited | error
    status_message: Mapped[str | None] = mapped_column(Text)

    connected_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Der bereits geholte Zeitraum, als lückenloses Fenster: der früheste und
    # der späteste Tag, für die Daten angefragt wurden. Daraus bestimmt
    # `sync.standard_zeitraum()`, was ein Abgleich überhaupt noch holen muss —
    # ohne das würde jeder Lauf dasselbe Jahr erneut abfragen. Beide werden nur
    # nach einem *erfolgreichen* Lauf fortgeschrieben: Ein Anspruch auf Daten,
    # die nie ankamen, wäre eine Lücke für immer.
    backfill_from: Mapped[date | None] = mapped_column(Date)
    synced_through: Mapped[date | None] = mapped_column(Date)
    # Nach einem 429 gesetzt. Garmin sperrt bis zu 48 Stunden, und jeder weitere
    # Versuch verlängert die Sperre — deshalb wird sie hier festgehalten, statt
    # es einfach nochmal zu probieren.
    rate_limited_until: Mapped[datetime | None] = mapped_column(DateTime)

    auto_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Ab welcher Ortszeit-Stunde ein neuer Tag abgeglichen werden darf. Am Konto
    # und nicht in der Umgebung, weil `config.py` beim Import gelesen wird und im
    # laufenden Prozess unveränderlich ist — eine Umgebungsvariable ließe sich in
    # der Oberfläche nicht umstellen. `config.GARMIN_SYNC_HOUR` ist damit nur
    # noch die Vorgabe für ein neu verbundenes Konto.
    sync_hour: Mapped[int] = mapped_column(Integer, default=GARMIN_SYNC_HOUR)
    # Dazu die Minute. Die Schleife wacht minütlich auf, seit die Planung an
    # einer eigenen Uhrzeit hängt — damit ist eine Minutenangabe keine
    # Scheingenauigkeit mehr, sondern trifft wirklich.
    sync_minute: Mapped[int] = mapped_column(Integer, default=0)
    profile_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Ob ein frisch übernommener Block von selbst auf die Uhr geht. Vorgabe an:
    # Wer ein Konto verbindet, will seinen Plan dort haben — und ein Block über
    # wenige Tage, der erst nach einem zusätzlichen Knopfdruck ankommt, ist bis
    # dahin die Hälfte seiner Zeit schon vorbei.
    auto_push_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(back_populates="garmin_account")


class WellnessDay(Base):
    """Ein Tag Fitnessdaten aus Garmin — der Zustand des Athleten.

    Flach statt verschachtelt und eine Zeile pro Tag: Jede Quelle füllt nur
    ihre eigenen Spalten, und ein fehlender Endpunkt hinterlässt Lücken statt
    eines fehlenden Tages. Der Import ist ein Upsert über (user_id, date), damit
    ein wiederholter Sync nichts verdoppelt.
    """

    __tablename__ = "wellness_days"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_wellness_user_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    # Schlaf
    sleep_seconds: Mapped[int | None] = mapped_column(Integer)
    sleep_deep_seconds: Mapped[int | None] = mapped_column(Integer)
    sleep_light_seconds: Mapped[int | None] = mapped_column(Integer)
    sleep_rem_seconds: Mapped[int | None] = mapped_column(Integer)
    sleep_awake_seconds: Mapped[int | None] = mapped_column(Integer)
    sleep_score: Mapped[int | None] = mapped_column(Integer)
    sleep_stress_avg: Mapped[float | None] = mapped_column(Float)
    sleep_body_battery_change: Mapped[int | None] = mapped_column(Integer)

    # Herzfrequenzvariabilität in ms, wie Garmin sie über die Nacht liefert.
    hrv_last_night_ms: Mapped[float | None] = mapped_column(Float)
    hrv_weekly_avg_ms: Mapped[float | None] = mapped_column(Float)
    hrv_status: Mapped[str | None] = mapped_column(String(24))
    # BALANCED | UNBALANCED | LOW | POOR | NOT_ENOUGH_DATA
    hrv_baseline_low: Mapped[float | None] = mapped_column(Float)
    hrv_baseline_high: Mapped[float | None] = mapped_column(Float)

    resting_hr: Mapped[int | None] = mapped_column(Integer)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    body_fat_pct: Mapped[float | None] = mapped_column(Float)
    vo2max_run: Mapped[float | None] = mapped_column(Float)
    vo2max_bike: Mapped[float | None] = mapped_column(Float)

    # Trainingsreife (Garmins „bin ich heute bereit?")
    readiness_score: Mapped[int | None] = mapped_column(Integer)
    readiness_level: Mapped[str | None] = mapped_column(String(24))
    readiness_feedback: Mapped[str | None] = mapped_column(String(64))
    # Garmins `recoveryTime` kommt in **Minuten** — der Wert hieß hier einmal
    # `recovery_time_h` und wurde ungerechnet übernommen. Ein Eintrag von 911
    # stand damit als "911 Stunden Erholung" im Export, und der Prompt macht
    # daraus "in diesem Zeitfenster nichts über Z2" — 38 Tage lang. Der Name
    # sagt jetzt die Einheit, umgerechnet wird erst zur Anzeige.
    recovery_time_min: Mapped[int | None] = mapped_column(Integer)
    readiness_hrv_factor_pct: Mapped[int | None] = mapped_column(Integer)
    readiness_acwr_factor_pct: Mapped[int | None] = mapped_column(Integer)
    acute_load: Mapped[float | None] = mapped_column(Float)

    # Trainingsstatus und Garmins eigenes Belastungsverhältnis
    training_status: Mapped[str | None] = mapped_column(String(32))
    training_status_feedback: Mapped[str | None] = mapped_column(String(64))
    weekly_training_load: Mapped[float | None] = mapped_column(Float)
    garmin_acwr: Mapped[float | None] = mapped_column(Float)
    garmin_load_acute: Mapped[float | None] = mapped_column(Float)
    garmin_load_chronic: Mapped[float | None] = mapped_column(Float)
    garmin_acwr_status: Mapped[str | None] = mapped_column(String(24))
    # Garmins optimales Lastfenster zur Akutlast — die Grenzen, zwischen denen
    # die Uhr die Belastung dieses Athleten für passend hält. Gemessen, nicht
    # geraten: Der Prompt gibt sie als Grenze weiter, statt eine eigene zu
    # erfinden.
    garmin_load_min: Mapped[float | None] = mapped_column(Float)
    garmin_load_max: Mapped[float | None] = mapped_column(Float)

    body_battery_high: Mapped[int | None] = mapped_column(Integer)
    body_battery_low: Mapped[int | None] = mapped_column(Integer)
    stress_avg: Mapped[int | None] = mapped_column(Integer)
    stress_max: Mapped[int | None] = mapped_column(Integer)


class GarminSyncJob(Base):
    """Ein Sync-Lauf mit seinem Fortschritt.

    Der Fortschritt steht in der Datenbank und nicht in einem Dict im Speicher,
    weil ein Backfill Minuten läuft: Die Oberfläche muss ihn abfragen können,
    und nach einem Neustart der App muss erkennbar sein, wo der Lauf stand
    (`cursor_date`), damit er fortgesetzt statt wiederholt wird.
    """

    __tablename__ = "garmin_sync_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # backfill | incremental | auto
    state: Mapped[str] = mapped_column(String(16), default="queued")
    # queued | running | done | failed | cancelled | rate_limited | interrupted

    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    range_start: Mapped[date | None] = mapped_column(Date)
    range_end: Mapped[date | None] = mapped_column(Date)
    day_loop_start: Mapped[date | None] = mapped_column(Date)
    cursor_date: Mapped[date | None] = mapped_column(Date)  # Wiederaufsetzpunkt

    step: Mapped[str | None] = mapped_column(String(48))
    step_index: Mapped[int] = mapped_column(Integer, default=0)
    step_total: Mapped[int] = mapped_column(Integer, default=0)
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)

    activities_new: Mapped[int] = mapped_column(Integer, default=0)
    activities_updated: Mapped[int] = mapped_column(Integer, default=0)
    wellness_days: Mapped[int] = mapped_column(Integer, default=0)
    # Zählwerke der Gegenrichtung (`kind` = workout_push | workout_remove).
    workouts_pushed: Mapped[int] = mapped_column(Integer, default=0)
    workouts_removed: Mapped[int] = mapped_column(Integer, default=0)

    message: Mapped[str | None] = mapped_column(Text)  # deutscher Klartext
    error: Mapped[str | None] = mapped_column(Text)


class GarminWorkoutPoolSlot(Base):
    """Eine dauerhafte, von Tri-Coach verwaltete Garmin-Workout-Vorlage.

    Der Slot gehört dem Nutzer und nicht einer Planeinheit. Dadurch überlebt
    seine Garmin-Kennung das Aufräumen alter Blöcke und kann mit neuem Inhalt
    wiederverwendet werden.
    """

    __tablename__ = "garmin_workout_pool_slots"
    __table_args__ = (
        UniqueConstraint("user_id", "slot_index", name="uq_garmin_pool_user_slot"),
        UniqueConstraint(
            "user_id", "garmin_workout_id", name="uq_garmin_pool_user_workout"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    slot_index: Mapped[int] = mapped_column(Integer)
    garmin_workout_id: Mapped[str | None] = mapped_column(String(32))

    sport: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255), default="")
    fingerabdruck: Mapped[str] = mapped_column(String(64), default="")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)


class GarminWorkoutLink(Base):
    """Was eine geplante Einheit in Garmin geworden ist.

    Ohne diese Zeile gäbe es keinen Weg zurück: Ein zweiter Druck auf
    „Trainings übertragen“ legte dieselbe Einheit noch einmal an, und das
    Entfernen aus dem Kalender wüsste nicht, welches der zwanzig Workouts in
    der Garmin-Bibliothek gemeint ist.

    Garmin führt zwei getrennte Dinge, und beide werden hier festgehalten: die
    **Vorlage** in der Workout-Bibliothek (`garmin_workout_id`) und ihren
    **Termin** im Kalender (`garmin_schedule_id`). Eine Vorlage ohne Termin
    steht in der Bibliothek, kommt aber nie auf die Uhr; ein Termin ohne
    Vorlage kann nicht existieren.

    `fingerabdruck` ist der Inhalt der zuletzt übertragenen Fassung. Stimmt er
    noch, kostet ein erneutes Übertragen keine einzige Anfrage — das ist die
    Voraussetzung dafür, dass der Knopf gefahrlos zweimal gedrückt werden darf.
    """

    __tablename__ = "garmin_workout_links"
    __table_args__ = (
        UniqueConstraint("plan_session_id", name="uq_garmin_workout_session"),
        UniqueConstraint("pool_slot_id", name="uq_garmin_workout_pool_slot_link"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_session_id: Mapped[int] = mapped_column(
        ForeignKey("plan_sessions.id", ondelete="CASCADE"), index=True
    )
    pool_slot_id: Mapped[int | None] = mapped_column(
        ForeignKey("garmin_workout_pool_slots.id", ondelete="SET NULL"), index=True
    )

    garmin_workout_id: Mapped[str] = mapped_column(String(32))
    garmin_schedule_id: Mapped[str | None] = mapped_column(String(32))
    scheduled_date: Mapped[date] = mapped_column(Date, index=True)

    title: Mapped[str] = mapped_column(String(255), default="")
    fingerabdruck: Mapped[str] = mapped_column(String(64), default="")

    pushed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    last_error: Mapped[str | None] = mapped_column(Text)

    # Nur in diese Richtung und ohne Gegenstück: Der Abgleich löst über die
    # Workout-Kennung die Planeinheit auf (`garmin/matching.py`), und eine
    # Rückrichtung an `PlanSession` bräuchte niemand. Gelöscht wird der
    # Link weiterhin über `ondelete="CASCADE"` an der Fremdschlüsselspalte.
    plan_session: Mapped["PlanSession"] = relationship()


# --------------------------------------------------------------------------
# KI-Planung
# --------------------------------------------------------------------------


class KiSettings(Base):
    """Einstellungen der KI-Planung, eine Zeile je Nutzer.

    Eigene Tabelle statt Spalten an `AthleteProfile`: Das Profil trägt
    Athletenwerte — Puls, Gewicht, Schwellen —, keine Einstellungen einer
    Anbindung. Dieselbe Trennung wie bei `GarminAccount`.

    Der Token steht hier — je Nutzer und verschlüsselt. Er stand einmal nur in
    der Umgebung (`config.CLAUDE_OAUTH_TOKEN`, gespeist aus den
    Add-on-Optionen); dafür musste man die App verlassen, ihn in Home Assistant
    eintragen und das Add-on neu starten, und er lag als Klartext in
    `/data/options.json` und damit in jedem Backup. Beides fällt weg. Die
    Umgebungsvariable bleibt als Rückfall, wenn hier nichts steht.
    """

    __tablename__ = "ki_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)

    # Leer heißt: die Vorgabe aus der Konfiguration.
    model: Mapped[str] = mapped_column(String(48), default="")
    effort: Mapped[str] = mapped_column(String(12), default="")

    # Der Abo-Zugang, mit demselben Verfahren wie das Garmin-Token gesichert
    # (`crypto.py`). Gedeckt ist damit die Kopie der Datenbank ohne den
    # Schlüssel — genau der Fall, den ein Home-Assistant-Backup erzeugt.
    token_encrypted: Mapped[str | None] = mapped_column(Text)

    # Ob nach dem täglichen Garmin-Abgleich von selbst ein Block entsteht.
    # Vorgabe aus: Ein Lauf kostet spürbar vom Kontingent des Abos, und was
    # Kontingent verbraucht, schaltet der Nutzer selbst ein.
    auto_plan_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Wann. Einmal die Woche reicht: Ein Block deckt sieben Tage ab, und jeder
    # Lauf kostet Kontingent. Wochentag wie `date.weekday()` — Montag 0, Sonntag
    # 6; die Vorgabe ist Sonntag 09:00, also der Abend vor der neuen Woche.
    auto_plan_weekday: Mapped[int] = mapped_column(Integer, default=6)
    auto_plan_hour: Mapped[int] = mapped_column(Integer, default=9)
    auto_plan_minute: Mapped[int] = mapped_column(Integer, default=0)
    # Der Riegel dazu — verhindert einen zweiten Lauf in derselben Woche, etwa
    # nach einem Neustart. Wird nur fortgeschrieben, wenn wirklich einer startet.
    last_auto_plan_on: Mapped[date | None] = mapped_column(Date)
    # Altlast: Die Blocklänge der Automatik kommt aus `ai_export.PLAN_DAYS_DEFAULT`.
    # Die Spalte steht hier, weil sie in bestehenden Datenbanken NOT NULL ist —
    # aus dem Modell entfernt, ohne die Spalte zu löschen, schlüge das Anlegen
    # einer Einstellungszeile fehl.
    plan_days: Mapped[int] = mapped_column(Integer, default=7)

    status: Mapped[str] = mapped_column(String(24), default="ready")
    # ready | error | token_expired | rate_limited
    status_message: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="ki_settings")


class KiJob(Base):
    """Ein Planungslauf mit seinem Fortschritt.

    Warum ein Job und keine lange HTTP-Antwort: Ein Lauf mit `--effort max`
    dauert gemessen anderthalb Minuten. Hinter dem Home-Assistant-Ingress ist
    eine minutenlange Antwort ein Risiko, und der Nutzer säße vor einem Balken
    ohne Rückmeldung. Die Zustandsnamen sind dieselben wie bei `GarminSyncJob`,
    damit die Abfrageschleife im Frontend für beide gilt.
    """

    __tablename__ = "ai_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # manual | einheit | ernaehrung — „auto" steht nur noch an Läufen aus der
    # Zeit vor dem Wegfall der Automatik.
    kind: Mapped[str] = mapped_column(String(16), default="manual")
    state: Mapped[str] = mapped_column(String(16), default="queued")
    # queued | running | done | failed | cancelled | interrupted

    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    request_id: Mapped[int | None] = mapped_column(Integer)
    start_date: Mapped[date | None] = mapped_column(Date)
    days: Mapped[int] = mapped_column(Integer, default=7)

    # Nur bei `kind == "einheit"` belegt: welche Einheit angepasst wurde und
    # mit welchem Wunsch. Der Wortlaut steht auch hier, nicht nur an der
    # Einheit — ein gescheiterter Lauf hat nichts geschrieben, und ohne den
    # Wunsch am Job wüsste niemand mehr, woran er gescheitert ist.
    plan_session_id: Mapped[int | None] = mapped_column(Integer)
    wunsch: Mapped[str | None] = mapped_column(Text)

    plan_id: Mapped[int | None] = mapped_column(Integer)
    # Nur bei `kind == "ernaehrung"` belegt: der entstandene Ernährungsplan.
    # Eine eigene Spalte und nicht `plan_id`: Das Frontend springt nach einem
    # geglückten Lauf auf `/plan/{plan_id}`, und dort läge dann die Kennung
    # eines Ernährungsplans — ein Trainingsblock, den es nicht gibt.
    ernaehrungsplan_id: Mapped[int | None] = mapped_column(Integer)
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)

    # Welches Modell tatsächlich geantwortet hat. Steht hier, weil kein stiller
    # Rückfall eingebaut ist: Ein Block, den ein schwächeres Modell geschrieben
    # hat, sähe sonst aus wie einer von Opus.
    model_used: Mapped[str | None] = mapped_column(String(64))
    # Listenpreis-Äquivalent des Laufs. Auf dem Abo wird nichts berechnet, aber
    # es ist der einzige greifbare Anhaltspunkt für den Kontingentverbrauch.
    cost_usd: Mapped[float | None] = mapped_column(Float)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    message: Mapped[str | None] = mapped_column(Text)  # deutscher Klartext
    error: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------------
# Ernährung
#
# Zweistufig wie `Plan`/`PlanSession`, aus demselben Grund: Die Ansicht zeigt
# Tage nebeneinander und darin, was wann gegessen wird. Ein JSON-Klumpen am
# Plan wäre schneller geschrieben und ließe sich weder sortieren noch je Tag
# nachschlagen.
# --------------------------------------------------------------------------


class Ernaehrungsplan(Base):
    """Ein Ernährungsblock über dieselben Tage, die der Trainingsblock abdeckt.

    Es gibt je Nutzer **höchstens einen**. Ein neuer übernimmt die Tage seines
    Vorgängers, die vor seinem eigenen Beginn liegen, und löscht ihn danach —
    dieselbe Überlegung wie beim Trainingsblock (`uebernimm_vergangenheit`):
    Wer morgen neu plant, soll heute nicht verlieren. Damit braucht die Ansicht
    keine Liste früherer Pläne, und ein `is_active` gäbe es nichts zu
    unterscheiden.
    """

    __tablename__ = "ernaehrungsplaene"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    # Der Trainingsblock, aus dem er entstanden ist — ohne Fremdschlüssel, wie
    # `KiJob.plan_id`: Der Block darf gelöscht werden, ohne den Ernährungsplan
    # mitzunehmen. Was er beschreibt, steht in seinen eigenen Tagen.
    plan_id: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)

    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    begruendung: Mapped[str | None] = mapped_column(Text)

    # Die ursprüngliche KI-Antwort, wie bei `Plan.raw_json`.
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)

    tage: Mapped[list["ErnaehrungsTag"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="ErnaehrungsTag.date",
    )
    supplemente: Mapped[list["ErnaehrungsSupplement"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="ErnaehrungsSupplement.order_index",
    )


class ErnaehrungsTag(Base):
    """Ein Tag des Ernährungsblocks: Tagessummen und was daran ansteht."""

    __tablename__ = "ernaehrungs_tage"

    id: Mapped[int] = mapped_column(primary_key=True)
    ernaehrungsplan_id: Mapped[int] = mapped_column(
        ForeignKey("ernaehrungsplaene.id"), index=True
    )
    date: Mapped[date] = mapped_column(Date, index=True)

    # Wofür der Tag gedeckt wird, in einem Satz („Schlüsseleinheit: 90 min Rad
    # Z4"). Steht hier und nicht nur im Trainingsplan, damit die Ansicht ohne
    # eine zweite Abfrage erklärt, warum an dem Tag mehr auf dem Teller liegt.
    trainingshinweis: Mapped[str | None] = mapped_column(Text)

    kalorien_kcal: Mapped[int | None] = mapped_column(Integer)
    kohlenhydrate_g: Mapped[int | None] = mapped_column(Integer)
    protein_g: Mapped[int | None] = mapped_column(Integer)
    fett_g: Mapped[int | None] = mapped_column(Integer)
    fluessigkeit_ml: Mapped[int | None] = mapped_column(Integer)

    notiz: Mapped[str | None] = mapped_column(Text)

    plan: Mapped[Ernaehrungsplan] = relationship(back_populates="tage")
    mahlzeiten: Mapped[list["ErnaehrungsMahlzeit"]] = relationship(
        back_populates="tag",
        cascade="all, delete-orphan",
        order_by="ErnaehrungsMahlzeit.order_in_day",
    )


class ErnaehrungsMahlzeit(Base):
    """Eine Mahlzeit: wann, was und wofür."""

    __tablename__ = "ernaehrungs_mahlzeiten"

    id: Mapped[int] = mapped_column(primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("ernaehrungs_tage.id"), index=True)
    order_in_day: Mapped[int] = mapped_column(Integer, default=0)

    # Als Text und nicht als Uhrzeit: Die Hälfte der Angaben ist relativ zur
    # Einheit („90 min vor dem Start"), und eine feste Uhrzeit dafür wäre
    # erfunden — die Einheit hat selbst keine.
    zeitpunkt: Mapped[str] = mapped_column(String(48), default="")
    name: Mapped[str] = mapped_column(String(120), default="")
    beschreibung: Mapped[str | None] = mapped_column(Text)

    # vor | waehrend | nach — der Bezug zur Trainingseinheit des Tages, sofern
    # es einen gibt. Ein Frühstück an einem Ruhetag hat keinen.
    bezug: Mapped[str | None] = mapped_column(String(16))

    kalorien_kcal: Mapped[int | None] = mapped_column(Integer)
    kohlenhydrate_g: Mapped[int | None] = mapped_column(Integer)
    protein_g: Mapped[int | None] = mapped_column(Integer)
    fett_g: Mapped[int | None] = mapped_column(Integer)

    tag: Mapped[ErnaehrungsTag] = relationship(back_populates="mahlzeiten")


class ErnaehrungsSupplement(Base):
    """Ein Nahrungsergänzungsmittel mit Dosierung, Zeitpunkt und Begründung.

    Am Plan und nicht am Tag: Das meiste läuft durchgehend (Kreatin, Vitamin D);
    was an einen Tag gebunden ist, sagt `zeitpunkt` im Wortlaut.
    """

    __tablename__ = "ernaehrungs_supplemente"

    id: Mapped[int] = mapped_column(primary_key=True)
    ernaehrungsplan_id: Mapped[int] = mapped_column(
        ForeignKey("ernaehrungsplaene.id"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    name: Mapped[str] = mapped_column(String(120))
    dosierung: Mapped[str | None] = mapped_column(String(120))
    zeitpunkt: Mapped[str | None] = mapped_column(String(160))
    begruendung: Mapped[str | None] = mapped_column(Text)

    plan: Mapped[Ernaehrungsplan] = relationship(back_populates="supplemente")


class ErnaehrungsProfil(Base):
    """Was den Athleten dauerhaft einschränkt — eine Zeile je Nutzer.

    Eigene Tabelle und keine Spalte an `AthleteProfile`: Der Text überlebt jeden
    Plan und gehört der Ernährungsseite. Am Profil liefe er durch dessen
    Teil-Update-Pfad (`exclude_unset`), den das Profilformular bedient, ohne das
    Feld zu kennen. Dieselbe Trennung wie bei `KiSettings`.

    Und er überlebt ausdrücklich auch das **Löschen** eines Ernährungsplans:
    Eine Laktoseintoleranz endet nicht, weil ein Block weg ist.
    """

    __tablename__ = "ernaehrungs_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)

    hinweise: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
