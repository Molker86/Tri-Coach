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
    hashed_password: Mapped[str] = mapped_column(String(255))
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
    experience_years: Mapped[float | None] = mapped_column(Float)
    current_weekly_hours: Mapped[float | None] = mapped_column(Float)
    sleep_hours: Mapped[float | None] = mapped_column(Float)
    stress_level: Mapped[int | None] = mapped_column(Integer)  # 1-5 (Beruf/Alltag)
    injuries: Mapped[str | None] = mapped_column(Text)
    personal_bests: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

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

    user: Mapped[User] = relationship(back_populates="logs")
    plan_session: Mapped["PlanSession | None"] = relationship(back_populates="log")
