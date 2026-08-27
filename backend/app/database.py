import sqlite3
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
        # Bleibt für alle bestehenden Einheiten leer: Das Befinden steht im
        # Aktivitätsdetail, und das wird für zurückliegende Einheiten nicht
        # noch einmal geholt (`sync.BEWERTUNGSFENSTER_TAGE`).
        "garmin_feel": "FLOAT",
        # Wie die Einheit ausgeführt wurde. Alle fünf bleiben an bestehenden
        # Einheiten leer: Die Zonenzeiten stehen zwar in der Listenantwort, die
        # übrigen im Aktivitätsdetail bzw. hinter einer eigenen Anfrage — und
        # nichts davon wird für zurückliegende Tage noch einmal geholt
        # (`sync.AKTUALISIERUNGSFENSTER_TAGE` = 5). Wer sie für die Historie
        # will, stößt einen Rückblick an.
        "hr_zone_seconds": "JSON",
        "garmin_abschnitte": "JSON",
        "garmin_uebungen": "JSON",
        "garmin_compliance": "INTEGER",
        "garmin_workout_id": "VARCHAR(32)",
        # Bestehende Zuordnungen gelten als nicht angefasst — die Marke setzt
        # erst, wer eine Verknüpfung von Hand löst.
        "zuordnung_manuell": "BOOLEAN NOT NULL DEFAULT 0",
        # Sechs Messgrößen aus Antworten, die der Abgleich ohnehin holt. Sie
        # bleiben an bestehenden Einheiten leer, aus demselben Grund wie die
        # fünf Ausführungsspalten darüber: Für zurückliegende Tage wird nichts
        # noch einmal geholt (`sync.AKTUALISIERUNGSFENSTER_TAGE` = 5). Wer sie
        # für die Historie will, stößt einen Rückblick an.
        "netto_dauer_min": "INTEGER",
        "gap_pace": "VARCHAR(16)",
        "normalisierte_leistung": "INTEGER",
        "swolf": "INTEGER",
        "zuege": "INTEGER",
        "temperatur_c": "FLOAT",
    },
    "athlete_profiles": {
        "garmin_personal_bests": "JSON",
        # Garmins gemessene Schwellenpace neben der Handeingabe. Bleibt leer,
        # bis der nächste Abgleich `get_lactate_threshold` liest — die
        # Handeingabe rührt sie nie an.
        "garmin_threshold_pace_run": "VARCHAR(16)",
    },
    # Bleibt an bestehenden Blöcken leer; `Plan.beginn` fällt dort auf
    # `start_date` zurück — was vor der Übernahme der Vergangenheit dasselbe war.
    "plans": {
        "geplant_ab": "DATE",
    },
    # Umbenennung von `recovery_time_h`: Garmin liefert Minuten, der alte Name
    # behauptete Stunden. Die Werte zieht `_uebertrage_spalten()` herüber.
    "wellness_days": {
        "recovery_time_min": "INTEGER",
        # Garmins optimales Lastfenster. Bleibt an bestehenden Tagen leer — die
        # Grenzen kommen mit dem nächsten Abgleich, rückwirkend nur, soweit er
        # reicht.
        "garmin_load_min": "FLOAT",
        "garmin_load_max": "FLOAT",
    },
    # Bis wann Daten geholt wurden. Ohne den Wert holt der erste Abgleich nach
    # dem Update einmal das volle Jahr — richtig so: Was vorher gedeckt war,
    # weiß die bestehende Datenbank nicht.
    "garmin_accounts": {
        "synced_through": "DATE",
        # Bestehende Verbindungen bekommen die Automatik eingeschaltet — genau
        # wie ein neu verbundenes Konto.
        "auto_push_enabled": "BOOLEAN NOT NULL DEFAULT 1",
        # Die Abgleichstunde stand einmal als Konstante in `config.py` und war
        # damit nicht einstellbar. Bestehende Konten bekommen die neue Vorgabe
        # 10 statt der bisherigen 9 — ändern lässt sie sich danach in den
        # Einstellungen.
        "sync_hour": "INTEGER NOT NULL DEFAULT 10",
        # Dazu die Minute, seit die Schleife minütlich aufwacht. Bestehende
        # Konten bleiben auf ihrer vollen Stunde — 0 ist genau das, was sie
        # bisher getan haben.
        "sync_minute": "INTEGER NOT NULL DEFAULT 0",
    },
    # Zählwerke für die Gegenrichtung: geplante Einheiten nach Garmin schieben.
    "garmin_sync_jobs": {
        "workouts_pushed": "INTEGER NOT NULL DEFAULT 0",
        "workouts_removed": "INTEGER NOT NULL DEFAULT 0",
    },
    # Die Zuordnung ist während der ersten Übertragung nach dem Update noch
    # leer. Dort werden bestehende Garmin-Kennungen in den Pool übernommen.
    "garmin_workout_links": {
        "pool_slot_id": "INTEGER REFERENCES garmin_workout_pool_slots(id)",
    },
    # Eine einzelne Einheit nachträglich anpassen. Beide Spalten bleiben an
    # bestehenden Einheiten leer — das heißt korrekt „unverändert seit der
    # Planung des Blocks".
    "plan_sessions": {
        "angepasst_am": "DATETIME",
        "anpassungswunsch": "TEXT",
        # Becken oder Freiwasser. Bleibt an bestehenden Einheiten leer; die
        # werden wie bisher als Beckentraining behandelt, sofern nicht der
        # Rückfall in `workouts.schwimmort()` etwas anderes erkennt.
        "swim_location": "VARCHAR(16)",
        # Rolle oder Straße. Bleibt an bestehenden Einheiten leer; dann
        # entscheidet der Rückfall in `workouts.radort()` anhand des Titels,
        # und ohne Hinweis gilt „draußen".
        "bike_location": "VARCHAR(16)",
        # Der Bauplan der KI. Bleibt an bestehenden Einheiten leer — die
        # werden weiter aus ihrem Fließtext zerlegt.
        "steps_json": "JSON",
        # Als welches Workout die Einheit auf der Uhr lag. Bestehende Einheiten
        # bleiben leer und bekommen damit keine Zuordnung mehr — ihre Trainings
        # sind längst importiert und behalten die, die sie schon haben.
        "garmin_workout_id": "VARCHAR(32)",
        "garmin_pushed_at": "DATETIME",
    },
    # Dieselbe Anpassung als Lauf: welche Einheit, mit welchem Wunsch.
    "ai_jobs": {
        "plan_session_id": "INTEGER",
        "wunsch": "TEXT",
        # Der Ernährungsplan, den ein Lauf erzeugt hat. Eigene Spalte statt
        # `plan_id`, weil das Frontend darauf einen Trainingsblock erwartet.
        "ernaehrungsplan_id": "INTEGER",
    },
    # Der Claude-Zugang je Nutzer, verschlüsselt. Vorher gab es ihn nur als
    # Add-on-Option in der Umgebung; bestehende Datenbanken haben die Spalte
    # nicht. Leer heißt weiterhin „nimm den aus der Umgebung".
    "ki_settings": {
        "token_encrypted": "TEXT",
        # Wann die Automatik plant. Bestehende Einstellungen bekommen die
        # Vorgabe Sonntag 09:00 — vorher lief sie täglich nach dem Abgleich und
        # hatte gar keine eigene Zeit.
        "auto_plan_weekday": "INTEGER NOT NULL DEFAULT 6",
        "auto_plan_hour": "INTEGER NOT NULL DEFAULT 9",
        "auto_plan_minute": "INTEGER NOT NULL DEFAULT 0",
    },
    # Wann die Zutaten eines Tages auf die Bring-Liste gingen. Bestehende Tage
    # bleiben leer und gelten damit als nicht übertragen — richtig so: Sie
    # haben ohnehin keine Zutaten, die Tabelle dafür ist neu.
    "ernaehrungs_tage": {
        "bring_uebertragen_am": "DATETIME",
    },
}

# Das Gegenstück: Spalten, die aus dem Modell verschwunden sind. Sie einfach
# stehen zu lassen wäre der bequeme Weg — SQLAlchemy stört sich nicht an einer
# Spalte, die es nicht kennt. Es sind hier aber Gesundheitsdaten, und
# `/data/tricoach.db` wandert in jedes Home-Assistant-Backup und von dort auf
# NAS oder USB-Stick. Was niemand mehr liest und niemand mehr füllen kann, hat
# dort nichts verloren.
#
# `DROP COLUMN` beherrscht SQLite seit 3.35 (2021) und nur, solange die Spalte
# in keinem Index und in keiner Bedingung steht — beides trifft hier zu. Auf
# einem älteren SQLite bleiben die Spalten liegen, statt den Start scheitern zu
# lassen: Sie stören dort, aber sie brechen nichts.
_ENTFALLENE_SPALTEN: dict[str, tuple[str, ...]] = {
    # Die subjektiven Marker aus dem Erfassungsformular. Mit ihm haben sie keine
    # Quelle mehr: Garmin liefert nichts davon, und eintragen kann sie niemand.
    "session_logs": (
        "feeling",
        "soreness",
        "sleep_hours",
        "sleep_quality",
        "morning_hr",
        "morning_hrv",
        "conditions",
    ),
    # Der alte Name behauptete Stunden, gespeichert waren Garmins Minuten.
    # Inhalt geht über `_UMZUZIEHENDE_SPALTEN` nach `recovery_time_min`.
    "wellness_days": ("recovery_time_h",),
}

# Umbenennungen: (Tabelle, alt, neu). SQLite kann `ALTER TABLE ... RENAME
# COLUMN`, aber das liefe nur einmal und wäre bei einer frisch angelegten
# Datenbank ein Fehler. Kopieren, was noch leer ist, und die alte Spalte
# anschließend über `_ENTFALLENE_SPALTEN` löschen lassen, ist idempotent: Nach
# dem ersten Start gibt es die Quellspalte nicht mehr und der Schritt entfällt.
_UMZUZIEHENDE_SPALTEN: tuple[tuple[str, str, str], ...] = (
    ("wellness_days", "recovery_time_h", "recovery_time_min"),
)

# Altwerte, die beim Nachrüsten einer Spalte zurückzusetzen sind:
# `(Tabelle, Auslöserspalte, UPDATE)`. Läuft genau einmal — nämlich in dem Lauf,
# der die Auslöserspalte tatsächlich ergänzt hat.
#
# Der eine Fall dahinter: `ki_settings.auto_plan_enabled` gab es schon einmal,
# für eine automatische Planung, die später wieder entfernt wurde. Die Spalte
# blieb als Altlast stehen — samt der Zustimmung von damals. Jetzt, wo sie
# wieder gelesen wird, spränge die Planung bei genau den Nutzern von selbst an,
# die sie vor Monaten einmal eingeschaltet hatten: ein Opus-Lauf am Tag aus
# ihrem Abo-Kontingent, den niemand bestellt hat. Eingeschaltet wird sie
# deshalb neu, in den Einstellungen.
#
# Der Auslöser ist `token_encrypted`, weil dessen Fehlen genau die Datenbanken
# kennzeichnet, die vor dieser Änderung entstanden sind.
_ZURUECKZUSETZENDE_ALTWERTE: tuple[tuple[str, str, str], ...] = (
    (
        "ki_settings",
        "token_encrypted",
        "UPDATE ki_settings SET auto_plan_enabled = 0, last_auto_plan_on = NULL",
    ),
)

_KANN_SPALTEN_LOESCHEN = sqlite3.sqlite_version_info >= (3, 35)

# Eine Spalte in beiden Listen liefe bei jedem Start hin und her: erst ergänzt,
# dann gelöscht, und beim nächsten Mal wieder von vorn.
for _tabelle, _spalten in _ENTFALLENE_SPALTEN.items():
    _doppelt = set(_spalten) & set(_NACHGEREICHTE_SPALTEN.get(_tabelle, {}))
    if _doppelt:
        raise RuntimeError(
            f"{_tabelle}: {sorted(_doppelt)} steht in _NACHGEREICHTE_SPALTEN "
            "und in _ENTFALLENE_SPALTEN"
        )

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

_TABELLENABHAENGIGE_INDIZES: dict[str, tuple[str, ...]] = {
    "garmin_workout_links": (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_garmin_workout_pool_slot_link "
        "ON garmin_workout_links (pool_slot_id) "
        "WHERE pool_slot_id IS NOT NULL",
    ),
}


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


def _setze_altwerte_zurueck(connection: Connection, ergaenzt: list[str]) -> list[str]:
    """Räumt Werte auf, die eine nachgerüstete Spalte erst wieder bedeutsam macht.

    Nur im Lauf der Ergänzung: `ergaenzt` nennt die Spalten, die dieser Start
    tatsächlich angelegt hat. Danach greift nichts mehr — die Einstellung des
    Nutzers bliebe sonst bei jedem Neustart wieder stehen.
    """
    zurueckgesetzt: list[str] = []
    for tabelle, ausloeser, anweisung in _ZURUECKZUSETZENDE_ALTWERTE:
        if f"{tabelle}.{ausloeser}" not in ergaenzt:
            continue
        ergebnis = connection.exec_driver_sql(anweisung)
        if ergebnis.rowcount:
            zurueckgesetzt.append(f"{tabelle} ({ergebnis.rowcount})")
    return zurueckgesetzt


def _uebertrage_spalten(connection: Connection) -> list[str]:
    """Zieht Werte einer umbenannten Spalte in ihre Nachfolgerin.

    Läuft zwischen Ergänzen und Löschen und nur, solange beide Spalten
    nebeneinander stehen — danach ist die Quelle weg und der Schritt tut
    nichts mehr. Überschrieben wird nichts: Nur Zeilen, in denen die neue
    Spalte leer ist, bekommen den alten Wert.
    """
    umgezogen: list[str] = []
    for tabelle, alt, neu in _UMZUZIEHENDE_SPALTEN:
        vorhanden = {
            row[1]
            for row in connection.exec_driver_sql(
                f"PRAGMA table_info({tabelle})"
            ).fetchall()
        }
        if alt not in vorhanden or neu not in vorhanden:
            continue
        ergebnis = connection.exec_driver_sql(
            f"UPDATE {tabelle} SET {neu} = {alt} "
            f"WHERE {neu} IS NULL AND {alt} IS NOT NULL"
        )
        if ergebnis.rowcount:
            umgezogen.append(f"{tabelle}.{alt} -> {neu} ({ergebnis.rowcount})")
    return umgezogen


def _entferne_spalten(connection: Connection) -> list[str]:
    """Löscht entfallene Spalten. Idempotent — läuft bei jedem Start mit.

    Gibt die tatsächlich entfernten Spalten zurück (für Protokoll und Test).
    """
    if not _KANN_SPALTEN_LOESCHEN:
        return []

    entfernt: list[str] = []
    for tabelle, spalten in _ENTFALLENE_SPALTEN.items():
        vorhanden = {
            row[1]
            for row in connection.exec_driver_sql(
                f"PRAGMA table_info({tabelle})"
            ).fetchall()
        }
        for name in spalten:
            if name in vorhanden:
                connection.exec_driver_sql(
                    f"ALTER TABLE {tabelle} DROP COLUMN {name}"
                )
                entfernt.append(f"{tabelle}.{name}")
    return entfernt


def _ergaenze_tabellenabhaengige_indizes(connection: Connection) -> None:
    """Legt Indizes nur an, wenn ihre nachgereichte Tabelle vorhanden ist."""
    tabellen = {
        row[0]
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    for tabelle, indizes in _TABELLENABHAENGIGE_INDIZES.items():
        if tabelle not in tabellen:
            continue
        for ddl in indizes:
            connection.exec_driver_sql(ddl)


def init_db() -> None:
    from . import models  # noqa: F401  -- Modelle registrieren

    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        ergaenzt = _ergaenze_spalten(connection)
        _setze_altwerte_zurueck(connection, ergaenzt)
        _uebertrage_spalten(connection)
        _entferne_spalten(connection)
        for ddl in _NACHGEREICHTE_INDIZES:
            connection.exec_driver_sql(ddl)
        _ergaenze_tabellenabhaengige_indizes(connection)
