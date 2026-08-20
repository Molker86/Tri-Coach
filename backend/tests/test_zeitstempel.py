"""Zeitstempel der API tragen ihre Zeitzone.

Die Spalten stehen ohne Zeitzone in SQLite und meinen UTC (`app/zeit.py`).
Gibt Pydantic sie genauso heraus — `"2026-08-20T04:10:12"` ohne `Z` —, liest
JavaScript sie als **Ortszeit**: Ein gerade gelaufener Abgleich stand deshalb
als „vor 2 Stunden" in der Oberfläche, exakt um den Sommerzeitversatz daneben.
Gefunden wurde das an `last_sync_at`; betroffen war jedes Feld dieser Art.
"""

import inspect
import typing
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel

from app import schemas


def _traegt_zeitstempel(annotation) -> bool:
    """Steckt in dem Typ ein `datetime`?

    Über die Klasse und nicht über den Text des Typs: `date` heißt mit vollem
    Namen `datetime.date` und käme sonst mit — dort ist ein fehlender Versatz
    aber richtig, ein Geburtstag hat keine Uhrzeit.
    """
    if annotation is datetime:
        return True
    if annotation is date:
        return False
    return any(_traegt_zeitstempel(teil) for teil in typing.get_args(annotation))


def _zeitstempelfelder():
    """Jedes Feld aller Schemas, dessen Typ einen Zeitstempel trägt."""
    for name, klasse in vars(schemas).items():
        if not inspect.isclass(klasse) or not issubclass(klasse, BaseModel):
            continue
        for feld, info in klasse.model_fields.items():
            if _traegt_zeitstempel(info.annotation):
                yield f"{name}.{feld}", klasse, feld


def test_zeitstempel_tragen_ihre_zeitzone():
    """Ein blankes `datetime` im Schema ist der Fehler — `UtcDatetime` heilt ihn.

    Geprüft wird über die Schemas statt über eine Liste bekannter Felder: Ein
    neu ergänztes Ausgabefeld fiele sonst still in denselben Fehler zurück.
    """
    naiv = datetime(2026, 8, 20, 4, 10, 12)

    felder = list(_zeitstempelfelder())
    assert felder, "keine Zeitstempelfelder gefunden — der Test greift ins Leere"

    # Über das echte Modell und nicht über den Typ des Felds: Pydantic zieht die
    # Anmerkungen eines Pflichtfelds nach `FieldInfo.metadata` heraus, ein
    # nachgebauter `TypeAdapter` verlöre den Serialisierer also gerade dort.
    ohne_zeitzone = [
        pfad
        for pfad, klasse, feld in felder
        if not klasse.model_construct(**{feld: naiv})
        .model_dump_json(include={feld})
        .endswith('+00:00"}')
    ]
    assert not ohne_zeitzone, (
        "Diese Felder gehen ohne Zeitzone heraus und liegen im Browser um den "
        f"Ortszeitversatz daneben: {', '.join(sorted(ohne_zeitzone))}. "
        "`UtcDatetime` aus `app.zeit` statt `datetime` verwenden."
    )


def test_der_abgleich_meldet_sich_als_gerade_eben(client, verbunden):
    """Der Fall aus der Beschwerde, durch die ganze Kette.

    Nach einem Abgleich muss `last_sync_at` als Zeitpunkt herauskommen, der
    wenige Sekunden zurückliegt — und nicht als einer vor zwei Stunden.
    """
    antwort = client.post("/api/garmin/sync", headers=verbunden)
    assert antwort.status_code == 202, antwort.text

    konto = client.get("/api/garmin/status", headers=verbunden).json()["konto"]
    zeitpunkt = datetime.fromisoformat(konto["last_sync_at"])

    assert zeitpunkt.tzinfo is not None, konto["last_sync_at"]
    abstand = abs(datetime.now(timezone.utc) - zeitpunkt)
    assert abstand < timedelta(minutes=1), f"{abstand} — Zeitzone verrutscht?"
