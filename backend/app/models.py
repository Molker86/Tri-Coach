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
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)  # KI-Antwort im Original

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

    # Subjektive Marker — für die Steuerung mindestens so wichtig wie die Messwerte
    rpe: Mapped[int | None] = mapped_column(Integer)  # 1-10 (Borg CR10)
    feeling: Mapped[int | None] = mapped_column(Integer)  # 1-5
    soreness: Mapped[int | None] = mapped_column(Integer)  # 1-5
    sleep_hours: Mapped[float | None] = mapped_column(Float)
    sleep_quality: Mapped[int | None] = mapped_column(Integer)  # 1-5
    morning_hr: Mapped[int | None] = mapped_column(Integer)
    morning_hrv: Mapped[float | None] = mapped_column(Float)

    conditions: Mapped[str | None] = mapped_column(String(255))  # Wetter/Terrain
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
    # Woher `rpe` stammt. Garmin liefert kein RPE; ohne Schätzung fielen sRPE,
    # ACWR und die Abstandsregel für intensive Einheiten aus. Die Quelle wird
    # mitgeschrieben, damit ein selbst eingetragener Wert beim nächsten Sync
    # nicht überschrieben wird und die KI die Belastbarkeit der Zahl kennt.
    rpe_source: Mapped[str] = mapped_column(String(20), default="manual")
    # manual | hf_zonen | trainingseffekt | hf_schnitt

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
    backfill_from: Mapped[date | None] = mapped_column(Date)
    # Nach einem 429 gesetzt. Garmin sperrt bis zu 48 Stunden, und jeder weitere
    # Versuch verlängert die Sperre — deshalb wird sie hier festgehalten, statt
    # es einfach nochmal zu probieren.
    rate_limited_until: Mapped[datetime | None] = mapped_column(DateTime)

    auto_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    profile_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

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
    recovery_time_h: Mapped[int | None] = mapped_column(Integer)
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
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_session_id: Mapped[int] = mapped_column(
        ForeignKey("plan_sessions.id", ondelete="CASCADE"), index=True
    )

    garmin_workout_id: Mapped[str] = mapped_column(String(32))
    garmin_schedule_id: Mapped[str | None] = mapped_column(String(32))
    scheduled_date: Mapped[date] = mapped_column(Date, index=True)

    title: Mapped[str] = mapped_column(String(255), default="")
    fingerabdruck: Mapped[str] = mapped_column(String(64), default="")

    pushed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    last_error: Mapped[str | None] = mapped_column(Text)
