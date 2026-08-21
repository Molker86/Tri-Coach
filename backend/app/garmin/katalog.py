"""Garmins Übungskatalog holen, prüfen und vorhalten.

Garmin liefert den Katalog, aus dem `uebungen.py` die Kennungen `category` und
`exerciseName` zieht, öffentlich und ohne Anmeldung als zwei JSON-Dateien — je
eine für Kraft und für Mobility. Sie sind der **aktuelle** Stand; die Liste in
`garminconnect.exercises` ist eine statisch erzeugte Kopie und altert mit der
Bibliothek statt mit Garmin.

Geholt wird einmal am Tag im Zuge des Garmin-Abgleichs. Was ankommt, ersetzt
die gespeicherte Datei; schlägt der Abruf fehl, gilt der zuletzt gespeicherte
Stand und der Abgleich meldet es. Eine Versionierung gibt es nicht — je Katalog
eine Datei, die überschrieben wird.

**Zwei Kataloge, nicht einer.** Garmin führt sie getrennt und lässt in Connect
nicht zu, eine Yogapose in ein Krafttraining zu legen; eine unbekannte
Kategorie beantwortet der Dienst mit 400, und zwar für das *ganze* Workout.
`Mobility.json` bringt dafür die Kategorien `POSE` und `MOVE` mit, die im
Kraftkatalog fehlen — die Yogaposen und Dehnungen, die diese App bisher nur
über `WARM_UP` erreichen konnte.

**Die Dateien tragen keine Anzeigenamen**, nur Enum-Schlüssel:

    {"categories": {"PLANK": {"primaryMuscles": [...],
                              "exercises": {"SIDE_PLANK": {...}}}}}

Der Name („Side Plank“, „Banded Ab Twist“) ist Garmins UI-Übersetzung und steht
dort nirgends — die Texterkennung in `uebungen.py` sucht aber über ihn. Deshalb
wird verschmolzen: Die JSON entscheidet, **welche** Paare es gibt (nur die gehen
auf die Uhr), den **Namen** liefert `garminconnect.exercises`, wo das Paar dort
bekannt ist. Für alles Übrige wird er aus dem Schlüssel gebildet
(`DOWNWARD_FACING_DOG` → „Downward Facing Dog“); das reicht, weil die Schlüssel
beschreibend sind und der Name ohnehin nur zum Suchen dient.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import time
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

from garminconnect import exercises as bibliothek

from ..config import KATALOG_DIR, KATALOG_MITGELIEFERT

logger = logging.getLogger(__name__)

# Die beiden Kataloge unter ihrem Kurznamen: Dateiname und Adresse.
QUELLEN: dict[str, tuple[str, str]] = {
    "kraft": (
        "Exercises.json",
        "https://connect.garmin.com/web-data/exercises/Exercises.json",
    ),
    "mobility": (
        "Mobility.json",
        "https://connect.garmin.com/web-data/exercises/Mobility.json",
    ),
}

# Ein Abgleich lässt sich mehrmals am Tag von Hand auslösen; der Katalog ändert
# sich nicht stündlich. Zwanzig Stunden lassen den täglichen Lauf trotzdem
# jedes Mal durch, auch wenn er einmal früher dran ist als am Vortag.
ALTER_MAX_STUNDEN = 20

ZEITLIMIT_S = 15

# Untergrenzen für die Plausibilitätsprüfung. Sie sollen keine echte Änderung
# des Katalogs abweisen, sondern nur das, was gar keiner ist — eine
# Fehlerseite, ein abgeschnittener Rumpf, eine leere Hülle. Gemessen am
# tatsächlichen Umfang (47 Kategorien / 1547 Einträge für Kraft, 15 / 284 für
# Mobility) ist das reichlich Luft nach unten.
MINDEST_KATEGORIEN = 5
MINDEST_EINTRAEGE = 50


class KatalogFehler(Exception):
    """Der Abruf oder die Prüfung ist gescheitert. Trägt einen deutschen Text."""

    def __init__(self, meldung: str) -> None:
        super().__init__(meldung)
        self.meldung = meldung


# --------------------------------------------------------------------------
# Abruf
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _ssl_kontext() -> ssl.SSLContext:
    """Der Vertrauensanker für die TLS-Verbindung.

    `ssl.create_default_context()` allein genügt nicht überall: Auf macOS bringt
    Pythons OpenSSL keinen Zertifikatsspeicher mit, und der Abruf scheitert dort
    mit `CERTIFICATE_VERIFY_FAILED` — in der Entwicklung also immer. `certifi`
    liefert das Bündel, das `requests` ohnehin benutzt; es kommt mit
    `garminconnect` mit und steht deshalb auch im Docker-Abbild.

    Fehlt es wider Erwarten, gilt der Standardkontext: Auf Linux trägt der
    Systemspeicher, und eine Prüfung abzuschalten kommt nicht in Frage.
    """
    try:
        import certifi
    except ImportError:  # pragma: no cover — im Abbild immer vorhanden
        logger.warning("certifi fehlt — Übungskatalog nutzt den Systemspeicher.")
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _hole(adresse: str) -> bytes:
    """Der eigentliche Netzzugriff — in Tests die Stelle zum Ersetzen.

    Bewusst `urllib` aus der Standardbibliothek: Es sind zwei öffentliche
    GET-Anfragen ohne Anmeldung, und `requirements.txt` führt keinen
    HTTP-Client (`httpx` steht nur in `requirements-dev.txt` und fehlt im
    Docker-Abbild). Dafür eine neue Laufzeitabhängigkeit aufzunehmen wäre
    unverhältnismäßig — anders als bei `certifi`, das nur das
    Zertifikatsbündel beisteuert und ohnehin schon mitkommt.
    """
    # Der eigene Name als Kennung. Nicht Kosmetik: Auf Pythons Vorgabe
    # („Python-urllib/3.12“) antwortet Garmin mit **403**, auf so ziemlich
    # jede andere Kennung mit 200 — am echten Dienst nachgemessen. Ein
    # vorgetäuschter Browser wäre dafür nicht nötig.
    anfrage = urllib.request.Request(
        adresse,
        headers={"Accept": "application/json", "User-Agent": "tri-coach"},
    )
    with urllib.request.urlopen(
        anfrage, timeout=ZEITLIMIT_S, context=_ssl_kontext()
    ) as antwort:
        return antwort.read()


def _pruefe(rohdaten: bytes) -> dict[str, Any]:
    """Ist das ein brauchbarer Katalog? Wirft `KatalogFehler`, wenn nicht.

    Geprüft wird **vor** dem Überschreiben. Das ist der einzige Weg, auf dem
    dieser Mechanismus die Zuordnung dauerhaft beschädigen könnte: Eine
    HTML-Fehlerseite oder ein auf halbem Weg abgerissener Rumpf, der eine gute
    Datei ersetzt, nähme jeder Kraft- und Mobility-Einheit ihre Animation — und
    zwar bis jemand es bemerkt.
    """
    try:
        daten = json.loads(rohdaten)
    except (ValueError, UnicodeDecodeError) as exc:
        raise KatalogFehler("Die Antwort war kein lesbares JSON.") from exc

    kategorien = daten.get("categories") if isinstance(daten, dict) else None
    if not isinstance(kategorien, dict) or not kategorien:
        raise KatalogFehler("Die Antwort enthielt keinen Katalog.")

    if len(kategorien) < MINDEST_KATEGORIEN:
        raise KatalogFehler(
            f"Der Katalog wirkt unvollständig ({len(kategorien)} Kategorien)."
        )

    eintraege = sum(
        len(inhalt.get("exercises") or {})
        for inhalt in kategorien.values()
        if isinstance(inhalt, dict)
    )
    if eintraege < MINDEST_EINTRAEGE:
        raise KatalogFehler(
            f"Der Katalog wirkt unvollständig ({eintraege} Übungen)."
        )
    return daten


def _schreibe(ziel: Path, rohdaten: bytes) -> None:
    """Atomar ersetzen: erst daneben schreiben, dann umlegen.

    Ohne das bliebe ein Abbruch mitten im Schreiben als halbe Datei liegen —
    und die wäre beim nächsten Start unlesbar, obwohl vorher eine gute dastand.
    """
    ziel.parent.mkdir(parents=True, exist_ok=True)
    vorlaeufig = ziel.with_name(ziel.name + ".neu")
    vorlaeufig.write_bytes(rohdaten)
    os.replace(vorlaeufig, ziel)


def _ist_frisch(ziel: Path) -> bool:
    if not ziel.exists():
        return False
    return (time.time() - ziel.stat().st_mtime) < ALTER_MAX_STUNDEN * 3600


def aktualisiere(*, erzwinge: bool = False) -> list[str]:
    """Beide Kataloge holen. Gibt deutsche Hinweise zurück und wirft nie.

    Der Aufrufer ist der Garmin-Abgleich, und der darf an einer öffentlichen
    JSON-Datei nicht scheitern: Die Trainingsdaten sind zu diesem Zeitpunkt
    längst geholt, und der gespeicherte Katalog von gestern ist eine völlig
    brauchbare Antwort.
    """
    hinweise: list[str] = []
    geaendert = False

    for welcher, (dateiname, adresse) in QUELLEN.items():
        ziel = KATALOG_DIR / dateiname
        if not erzwinge and _ist_frisch(ziel):
            continue
        try:
            rohdaten = _hole(adresse)
            _pruefe(rohdaten)
            _schreibe(ziel, rohdaten)
            geaendert = True
        except KatalogFehler as exc:
            logger.warning("Übungskatalog '%s': %s", welcher, exc.meldung)
            hinweise.append(f"Übungskatalog ({welcher}): {exc.meldung}")
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            # `URLError` und `ssl.SSLError` sind beide OSError-Abkömmlinge; die
            # breite Klammer fängt zusätzlich, was beim Schreiben schiefgeht.
            logger.warning("Übungskatalog '%s' nicht erreichbar: %s", welcher, exc)
            hinweise.append(f"Übungskatalog ({welcher}) konnte nicht geladen werden.")

    if hinweise:
        hinweise.append("Es gilt der zuletzt gespeicherte Stand.")
    if geaendert:
        leere_zwischenspeicher()
    return hinweise


# --------------------------------------------------------------------------
# Einträge
# --------------------------------------------------------------------------

# Paar aus Kategorie und Übung -> Anzeigename, aus der Bibliothek. Die
# Grundübung einer Kategorie („Plank“ in PLANK) steht dort mit
# `exercise == category`, nie mit einem leeren Feld.
_BIBLIOTHEKSNAMEN: dict[tuple[str, str], str] = {
    (eintrag["category"], eintrag["exercise"]): eintrag["name"]
    for eintrag in bibliothek.EXERCISES
}


def _abgeleiteter_name(schluessel: str) -> str:
    return " ".join(wort.capitalize() for wort in schluessel.split("_"))


def _lies(welcher: str) -> dict[str, Any]:
    """Der gespeicherte Katalog, ersatzweise die mitgelieferte Erstausstattung.

    Eine unlesbare heruntergeladene Datei fällt auf die Erstausstattung zurück,
    statt den Start scheitern zu lassen: Ohne Katalog bekäme *keine* Übung mehr
    eine Animation, und das wäre die schlechtere Antwort auf ein kaputtes Byte.
    """
    dateiname = QUELLEN[welcher][0]
    for pfad in (KATALOG_DIR / dateiname, KATALOG_MITGELIEFERT / dateiname):
        if not pfad.exists():
            # Vor dem ersten Abgleich steht hier nichts. Das ist der Normalfall
            # und keine Meldung wert — die Erstausstattung springt ein.
            continue
        try:
            return _pruefe(pfad.read_bytes())
        except (OSError, KatalogFehler) as exc:
            logger.warning("Übungskatalog '%s' aus %s unbrauchbar: %s", welcher, pfad, exc)
    return {"categories": {}}


def eintraege(welcher: str) -> list[dict[str, str]]:
    """Der Katalog in der Form, die `uebungen.py` erwartet.

    `{"name", "category", "exercise"}` je Eintrag — dieselbe Form wie
    `garminconnect.exercises`, damit der Rest des Moduls unverändert bleibt.

    Die Grundübung einer Kategorie trägt dabei `exercise == category` und
    **nicht** den Leerstring: `workouts.py` schreibt den Wert unverändert als
    `exerciseName` ins Workout, ein leeres Feld ginge also so auf die Uhr. An
    demselben Vergleich hängt außerdem `uebungen._ist_grundform()`.
    """
    kategorien = _lies(welcher).get("categories") or {}
    liste: list[dict[str, str]] = []

    for kategorie, inhalt in kategorien.items():
        if not isinstance(inhalt, dict):
            continue
        # Trägt die Kategorie selbst Muskeln, ist sie zugleich eine Übung —
        # so drückt die JSON aus, was die Bibliothek als `exercise: ""` führt
        # („Plank“ in PLANK, „Calf Raise“ in CALF_RAISE).
        namen = [kategorie] if "primaryMuscles" in inhalt else []
        namen += list(inhalt.get("exercises") or {})
        # Dreißig Kategorien führen ihre Grundübung zusätzlich unter
        # `exercises` auf — derselbe Eintrag, zweimal genannt.
        namen = list(dict.fromkeys(namen))

        for uebungsname in namen:
            liste.append({
                "name": (
                    _BIBLIOTHEKSNAMEN.get((kategorie, uebungsname))
                    or _abgeleiteter_name(uebungsname)
                ),
                "category": kategorie,
                "exercise": uebungsname,
            })
    return liste


def leere_zwischenspeicher() -> None:
    """Nach einem Download: das Verzeichnis in `uebungen.py` neu aufbauen lassen.

    Ohne das gälte der frische Katalog erst nach einem Neustart — der Abgleich
    läuft im laufenden Prozess, und die Verzeichnisse hängen an `lru_cache`.
    """
    from . import uebungen

    uebungen.leere_zwischenspeicher()
