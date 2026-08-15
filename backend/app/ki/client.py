"""Der Aufruf von Claude Code — die einzige Stelle, die den Unterprozess kennt.

Warum die CLI als Unterprozess und nicht die API mit Schlüssel: Der Haushalt hat
ein Claude-Abo, und das trägt diesen einen Aufruf am Tag ohne Abrechnung nach
Token. Warum kein `claude-agent-sdk`: Es umhüllt dieselbe CLI; ein Prompt hinein,
ein Text heraus braucht keine zweite Abhängigkeit.

Vier Vorkehrungen, damit hier ein Trainingsplaner antwortet und kein
Programmieragent — alle am echten Programm geprüft (Version 2.1.233):

* `--tools ""` schaltet **alle** Werkzeuge ab. Hier soll nichts gelesen,
  geschrieben oder gesucht werden.
* `--safe-mode` nimmt CLAUDE.md, Skills, Plugins, Hooks, MCP-Server und eigene
  Kommandos aus dem Spiel — **und lässt die Anmeldung unberührt**. Das
  naheliegende `--bare` wäre falsch: Es liest OAuth ausdrücklich *nie* und
  verlangt einen API-Schlüssel, den es hier nicht gibt.
* Der Systemprompt wird **ersetzt**, nicht ergänzt: Der Standardtext beschreibt
  einen Programmieragenten und kostete im Versuch allein 3049 Token.
* Gearbeitet wird in einem leeren Verzeichnis, damit nichts aus dem Projekt
  mitwandert.

Die Antwort kommt als JSON-Hülle (`--output-format json`) und wird ausgewertet,
*bevor* `result` weitergereicht wird — sonst landete eine Fehlermeldung im
Planparser und käme als „unlesbares JSON" heraus.
"""

import json
import logging
import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass

from ..config import (
    CLAUDE_OAUTH_TOKEN,
    KI_CLI,
    KI_EFFORT,
    KI_MODELL,
    KI_TIMEOUT_S,
)
from .errors import (
    KiAbgelehnt,
    KiAntwortUnbrauchbar,
    KiCliFehlt,
    KiFehler,
    KiKontingentErschoepft,
    KiTokenUngueltig,
    KiZeitueberschreitung,
)

logger = logging.getLogger(__name__)

SYSTEMPROMPT = (
    "Du bist ein erfahrener Trainingsplaner für Ausdauersport. "
    "Antworte ausschließlich mit dem angeforderten JSON-Objekt, "
    "ohne Begleittext und ohne Codefence."
)

# Textbausteine, an denen sich ein Fehlschlag einordnen lässt. Die CLI hat kein
# maschinenlesbares Fehlerfeld für diese Fälle — `api_error_status` bleibt bei
# einem Anmeldeproblem leer, weil die Anfrage gar nicht erst hinausging.
_TOKEN_HINWEISE = (
    "oauth",
    "unauthorized",
    "authentication",
    "not logged in",
    "please run /login",
    "invalid api key",
    "credentials",
)
_KONTINGENT_HINWEISE = (
    "usage limit",
    "rate limit",
    "quota",
    "too many requests",
    "limit reached",
)

# Wie lange die Auskunft „angemeldet" gilt, bevor erneut nachgesehen wird. Der
# Aufruf kostet nur Millisekunden, aber die Statusseite fragt bei jedem Laden.
_ANMELDUNG_CACHE_S = 60
_anmeldung_cache: tuple[float, bool] = (0.0, False)


@dataclass(slots=True)
class Antwort:
    """Was ein Lauf hergibt — der Text und was er gekostet hat."""

    text: str
    modell: str | None = None
    kosten_usd: float | None = None
    dauer_ms: int | None = None


def _umgebung() -> dict[str, str]:
    """Die Umgebung des Unterprozesses — bewusst zusammengestellt, nicht geerbt.

    Der Grund ist am eigenen Rechner aufgefallen: Wer die App aus einer
    laufenden Claude-Code-Sitzung heraus startet, hat ein Dutzend
    `CLAUDE_CODE_*`-Variablen in der Umgebung — darunter die Kennung der
    Sitzung und der Pfad zu ihrem Meldungssocket. Vererbt hängt sich der
    Unterprozess daran und kehrt nicht zurück; der Lauf lief in die
    Zeitüberschreitung statt in eine Antwort. Im Add-on gäbe es das nicht, in
    der Entwicklung ist es der Normalfall.

    Weitergereicht wird deshalb nur, was ein Programm zum Arbeiten und für eine
    HTTPS-Verbindung braucht. Der Token wird nur gesetzt, wenn es ihn gibt:
    Ohne ihn — also bei der lokalen Entwicklung — soll die CLI ihre eigene
    Anmeldung benutzen dürfen, und ein leer gesetzter Wert verdeckte die.
    """
    durchgereicht = (
        "PATH",
        "HOME",
        # `USER` ist keine Kosmetik: Ohne die Variable findet die CLI auf macOS
        # ihre im Schlüsselbund abgelegte Anmeldung nicht und meldet „Not logged
        # in" — auch dann, wenn der Nutzer angemeldet ist. Betrifft nur die
        # lokale Entwicklung; im Add-on kommt der Zugang als Token.
        "USER",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "TZ",
        # Wer hinter einem Firmenproxy oder mit eigenem Wurzelzertifikat
        # arbeitet, käme sonst nicht hinaus.
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "NODE_EXTRA_CA_CERTS",
        # Ausdrücklich gesetzt heißt: so gewollt.
        "CLAUDE_CONFIG_DIR",
    )
    env = {
        name: wert
        for name in durchgereicht
        if (wert := os.environ.get(name)) is not None
    }
    if CLAUDE_OAUTH_TOKEN:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = CLAUDE_OAUTH_TOKEN
    return env


def ist_angemeldet(erzwinge: bool = False) -> bool:
    """Ob Claude Code einen brauchbaren Zugang hat.

    Bewusst nicht „ist die Umgebungsvariable gesetzt": Im Add-on kommt der
    Zugang als Token, bei der lokalen Entwicklung aus der Anmeldung der CLI
    selbst. Gefragt wird deshalb das Programm, nicht die Umgebung.
    """
    global _anmeldung_cache

    gemessen, wert = _anmeldung_cache
    if not erzwinge and time.monotonic() - gemessen < _ANMELDUNG_CACHE_S:
        return wert

    try:
        lauf = subprocess.run(
            [KI_CLI, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=30,
            env=_umgebung(),
        )
        daten = json.loads(lauf.stdout or "{}")
        wert = bool(daten.get("loggedIn"))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        wert = False

    _anmeldung_cache = (time.monotonic(), wert)
    return wert


def _hauptmodell(model_usage: dict) -> str | None:
    """Welches Modell die Antwort geschrieben hat.

    Die CLI zieht nebenher ein kleines Hilfsmodell heran, das in `modelUsage`
    genauso auftaucht — und dabei durchaus mehr Eingabetoken verbraucht als das
    eigentliche. Verlässlich ist der Preis: Das Modell, das die Antwort
    geschrieben hat, ist in beiden gemessenen Läufen das mit Abstand teuerste.
    """
    if not model_usage:
        return None
    return max(
        model_usage.items(),
        key=lambda eintrag: eintrag[1].get("costUSD") or 0.0,
    )[0]


def _ordne_fehler_ein(text: str) -> KiFehler:
    """Übersetzt einen Fehlschlag in einen eigenen Fehler mit deutscher Meldung."""
    klein = text.lower()
    if any(hinweis in klein for hinweis in _TOKEN_HINWEISE):
        return KiTokenUngueltig()
    if any(hinweis in klein for hinweis in _KONTINGENT_HINWEISE):
        return KiKontingentErschoepft()
    # Alles andere bleibt unübersetzt, aber nicht unerklärt: Der Originaltext ist
    # das Einzige, womit sich ein unbekannter Fall überhaupt aufklären lässt.
    gekuerzt = text.strip().replace("\n", " ")[:300]
    return KiFehler(
        "Der Aufruf der KI ist fehlgeschlagen."
        + (f" Meldung: {gekuerzt}" if gekuerzt else "")
    )


def rufe_claude(
    prompt: str,
    *,
    modell: str | None = None,
    effort: str | None = None,
    timeout_s: int | None = None,
    bei_start: Callable[[subprocess.Popen], None] | None = None,
) -> Antwort:
    """Schickt den Prompt an Claude Code und gibt den Antworttext zurück.

    Der Prompt geht über **stdin**, nicht über die Kommandozeile: Das Datenpaket
    ist gut fünfzig Kilobyte groß.

    `bei_start` bekommt den laufenden Prozess gereicht. Darüber kann der Runner
    ihn abbrechen — anders käme er nicht an ihn heran, und ein Lauf, der
    Minuten dauert, muss abbrechbar sein.
    """
    argv = [
        KI_CLI,
        "-p",
        "--model", modell or KI_MODELL,
        "--effort", effort or KI_EFFORT,
        # Kein Werkzeug, keine Anpassungen, keine Sitzungsdateien auf einem
        # Server — und kein Rückfragen, das den Prozess hängen ließe.
        "--tools", "",
        "--safe-mode",
        "--no-session-persistence",
        "--permission-mode", "dontAsk",
        "--system-prompt", SYSTEMPROMPT,
        "--output-format", "json",
    ]

    # Ein leeres Arbeitsverzeichnis: Claude Code sammelt sonst auf, was es dort
    # findet. `--safe-mode` allein deckt das nicht ab.
    with tempfile.TemporaryDirectory(prefix="tricoach-ki-") as leeres_verzeichnis:
        try:
            prozess = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=leeres_verzeichnis,
                env=_umgebung(),
            )
        except FileNotFoundError as exc:
            raise KiCliFehlt() from exc
        except OSError as exc:
            raise KiFehler(f"Claude Code ließ sich nicht starten: {exc}") from exc

        if bei_start is not None:
            bei_start(prozess)

        try:
            ausgabe, fehlerausgabe = prozess.communicate(
                prompt, timeout=timeout_s or KI_TIMEOUT_S
            )
        except subprocess.TimeoutExpired as exc:
            # `communicate` beendet den Prozess **nicht** von selbst — anders als
            # `subprocess.run`. Ohne das Töten liefe er als Waise weiter.
            prozess.kill()
            prozess.communicate()
            raise KiZeitueberschreitung() from exc

    if prozess.returncode != 0:
        raise _ordne_fehler_ein(fehlerausgabe or ausgabe or "")

    try:
        huelle = json.loads(ausgabe)
    except json.JSONDecodeError as exc:
        raise KiAntwortUnbrauchbar(
            "Claude Code hat keine auswertbare Antwort geliefert."
        ) from exc

    if huelle.get("is_error") or huelle.get("api_error_status"):
        raise _ordne_fehler_ein(
            f"{huelle.get('api_error_status') or ''} "
            f"{huelle.get('subtype') or ''} {huelle.get('result') or ''}"
        )

    if huelle.get("stop_reason") == "refusal":
        raise KiAbgelehnt()

    text = (huelle.get("result") or "").strip()
    if not text:
        raise KiAntwortUnbrauchbar("Die KI hat eine leere Antwort geliefert.")

    return Antwort(
        text=text,
        modell=_hauptmodell(huelle.get("modelUsage") or {}),
        kosten_usd=huelle.get("total_cost_usd"),
        dauer_ms=huelle.get("duration_ms"),
    )
