from collections.abc import Generator

from sqlalchemy import Connection, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    # `timeout`: Der Garmin-Sync schreibt aus einem Hintergrund-Thread, während
    # Anfragen dieselbe Datei anfassen. Ohne Wartezeit gäbe es "database is
    # locked" statt einer kurzen Verzögerung.
    connect_args={"check_same_thread": False, "timeout": 30},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record) -> None:
    """WAL-Modus: Lesen blockiert nicht mehr, während der Sync schreibt.

    Ohne das wäre ein mehrminütiger Backfill für die Oberfläche als Folge von
    Sperrfehlern spürbar, obwohl er im Hintergrund läuft.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --------------------------------------------------------------------------
# Nachgereichte Schemaänderungen
#
# `create_all()` legt fehlende *Tabellen* an, sieht aber eine neue *Spalte* auf
# einer bestehenden Tabelle nicht. Bisher war "Datenbank löschen" der bewusste
# Weg dafür. Mit der Garmin-Anbindung wird er teuer: Ein neuer Backfill kostet
# Minuten gegen ein fremdes System mit Rate-Limit und verlangt Passwort und
# MFA-Code erneut. Ein paar Zeilen ALTER TABLE sind billiger als Alembic und
# lösen genau diesen Schmerz.
# --------------------------------------------------------------------------

_NACHGEREICHTE_SPALTEN: dict[str, dict[str, str]] = {
    "session_logs": {
        "source": "VARCHAR(16) NOT NULL DEFAULT 'manual'",
        "garmin_activity_id": "VARCHAR(32)",
        "garmin_activity_type": "VARCHAR(48)",
        "garmin_training_load": "FLOAT",
        "garmin_aerobic_te": "FLOAT",
        "garmin_anaerobic_te": "FLOAT",
        "rpe_source": "VARCHAR(20) NOT NULL DEFAULT 'manual'",
    },
    "athlete_profiles": {
        "garmin_personal_bests": "JSON",
    },
    # Bis wann Daten geholt wurden. Ohne den Wert holt der erste Abgleich nach
    # dem Update einmal das volle Jahr — richtig so: Was vorher gedeckt war,
    # weiß die bestehende Datenbank nicht.
    "garmin_accounts": {
        "synced_through": "DATE",
    },
    # Zählwerke für die Gegenrichtung: geplante Einheiten nach Garmin schieben.
    "garmin_sync_jobs": {
        "workouts_pushed": "INTEGER NOT NULL DEFAULT 0",
        "workouts_removed": "INTEGER NOT NULL DEFAULT 0",
    },
}

_NACHGEREICHTE_INDIZES: tuple[str, ...] = (
    # Trägt die Idempotenz des Garmin-Imports. Der Teilindex (WHERE ... NOT
    # NULL) hält ihn klein und macht die Absicht deutlich — SQLite behandelt
    # NULLs in UNIQUE-Indizes ohnehin als verschieden.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_log_garmin_activity "
    "ON session_logs (user_id, garmin_activity_id) "
    "WHERE garmin_activity_id IS NOT NULL",
    # `list_logs`, `weekly_summary` und der Sync filtern genau in dieser
    # Kombination.
    "CREATE INDEX IF NOT EXISTS ix_session_logs_user_date "
    "ON session_logs (user_id, date)",
)


def _ergaenze_spalten(connection: Connection) -> list[str]:
    """Fügt fehlende Spalten hinzu. Idempotent — läuft bei jedem Start mit.

    Gibt die tatsächlich ergänzten Spalten zurück (für Protokoll und Test).
    """
    ergaenzt: list[str] = []
    for tabelle, spalten in _NACHGEREICHTE_SPALTEN.items():
        vorhanden = {
            row[1]
            for row in connection.exec_driver_sql(
                f"PRAGMA table_info({tabelle})"
            ).fetchall()
        }
        if not vorhanden:
            # Tabelle existiert nicht — `create_all()` hat sie gerade frisch
            # und vollständig angelegt.
            continue
        for name, ddl in spalten.items():
            if name not in vorhanden:
                connection.exec_driver_sql(
                    f"ALTER TABLE {tabelle} ADD COLUMN {name} {ddl}"
                )
                ergaenzt.append(f"{tabelle}.{name}")
    return ergaenzt


def init_db() -> None:
    from . import models  # noqa: F401  -- Modelle registrieren

    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        _ergaenze_spalten(connection)
        for ddl in _NACHGEREICHTE_INDIZES:
            connection.exec_driver_sql(ddl)
