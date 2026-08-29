"""Die Grenze zu Claude Code: Aufrufform und Auswertung der JSON-Hülle.

Hier liegt die einzige Stelle, an der die App ein fremdes Programm aufruft.
Alles darunter ist gegen eine Nachbildung geprüft, nicht gegen die CLI — aber
die Hüllen in diesen Tests sind echte Ausgaben aus dem Versuch mit dem
tatsächlichen Programm (Version 2.1.233), nicht ausgedacht.
"""

import json
import subprocess

import pytest

from app.ki import client as ki_client
from app.ki.errors import (
    KiAbgelehnt,
    KiAntwortUnbrauchbar,
    KiCliFehlt,
    KiFehler,
    KiKontingentErschoepft,
    KiTokenUngueltig,
    KiZeitueberschreitung,
)

# Aus dem echten Lauf abgenommen: Das Hilfsmodell verbraucht mehr *Eingabe*
# als das eigentliche, taugt zur Unterscheidung also nicht — der Preis schon.
MODEL_USAGE = {
    "claude-haiku-4-5-20251001": {"inputTokens": 21584, "outputTokens": 31, "costUSD": 0.0217},
    "claude-opus-5": {"inputTokens": 2, "outputTokens": 6241, "costUSD": 0.4087},
}


def huelle(**abweichungen) -> str:
    daten = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "stop_reason": "end_turn",
        "api_error_status": None,
        "result": '{"plan": {}}',
        "total_cost_usd": 0.430414,
        "duration_ms": 85262,
        "modelUsage": MODEL_USAGE,
    }
    daten.update(abweichungen)
    return json.dumps(daten)


class FakeProzess:
    """Ein Unterprozess, der eine vorgegebene Ausgabe liefert."""

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0, *, timeout: bool = False):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._timeout = timeout
        self.getoetet = False

    def communicate(self, eingabe=None, timeout=None):
        if self._timeout:
            self._timeout = False  # der zweite Aufruf nach dem kill() kommt durch
            raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout or 0)
        return self._stdout, self._stderr

    def kill(self):
        self.getoetet = True


@pytest.fixture
def prozess(monkeypatch):
    """Stellt den Unterprozess und merkt sich, womit er aufgerufen wurde."""
    notiz = {}

    def _stelle(stand: FakeProzess):
        def _popen(argv, **kwargs):
            notiz["argv"] = argv
            notiz["kwargs"] = kwargs
            return stand

        monkeypatch.setattr(subprocess, "Popen", _popen)
        return notiz

    return _stelle


def test_erfolg_liefert_text_modell_und_kosten(prozess):
    prozess(FakeProzess(stdout=huelle()))
    antwort = ki_client.rufe_claude("Plane bitte.")

    assert antwort.text == '{"plan": {}}'
    # Der Preis entscheidet, nicht die Tokenzahl — sonst gälte das Hilfsmodell
    # als Urheber des Plans.
    assert antwort.modell == "claude-opus-5"
    assert antwort.kosten_usd == pytest.approx(0.430414)
    assert antwort.dauer_ms == 85262


def test_der_aufruf_haelt_den_agenten_kurz(prozess):
    notiz = prozess(FakeProzess(stdout=huelle()))
    ki_client.rufe_claude("Plane bitte.", modell="opus", effort="max")
    argv = notiz["argv"]

    # Diese vier tragen die Isolierung. Fällt eine weg, antwortet wieder ein
    # Programmieragent mit Werkzeugen — und zwar unbemerkt.
    assert "--safe-mode" in argv
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--system-prompt") + 1] == ki_client.SYSTEMPROMPT
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--model") + 1] == "opus"
    assert argv[argv.index("--effort") + 1] == "max"
    # `--bare` wäre die Falle: Es liest OAuth nie und verlangt einen Schlüssel.
    assert "--bare" not in argv
    # Gearbeitet wird in einem leeren Verzeichnis, nicht im Projekt.
    assert notiz["kwargs"]["cwd"] != ""


SCHEMA = {
    "type": "object",
    "$defs": {"schritt": {"type": "object", "properties": {"kind": {"type": "string"}}}},
    "properties": {"plan": {"type": "object"}},
    "required": ["plan"],
}


def test_das_schema_geht_als_flag_mit(prozess):
    """Die Struktur wird erzwungen, nicht erbeten.

    Die CLI setzt `--json-schema` intern als Tool-Use um: Pflichtfelder sind
    dann wirklich Pflicht, und ein Komma zu viel entsteht gar nicht erst.
    """
    notiz = prozess(FakeProzess(stdout=huelle()))
    ki_client.rufe_claude("Plane bitte.", json_schema=SCHEMA)

    argv = notiz["argv"]
    assert json.loads(argv[argv.index("--json-schema") + 1]) == SCHEMA


def test_ohne_schema_kein_flag(prozess):
    """Der Weg ohne Schema bleibt Wort für Wort der alte."""
    notiz = prozess(FakeProzess(stdout=huelle()))
    ki_client.rufe_claude("Plane bitte.")
    assert "--json-schema" not in notiz["argv"]


def test_die_geparste_antwort_wird_mitgeliefert(prozess):
    """`structured_output` erspart das Suchen nach Klammern im Text."""
    prozess(FakeProzess(stdout=huelle(
        stop_reason="tool_use",
        structured_output={"plan": {"title": "Block"}},
    )))
    antwort = ki_client.rufe_claude("Plane bitte.", json_schema=SCHEMA)

    assert antwort.struktur == {"plan": {"title": "Block"}}
    # `stop_reason` ist mit erzwungenem Schema immer „tool_use" — nur ein
    # `refusal` ist ein Fehler, und der bleibt einer.
    assert antwort.text == '{"plan": {}}'


def test_ohne_schema_bleibt_die_struktur_leer(prozess):
    prozess(FakeProzess(stdout=huelle()))
    assert ki_client.rufe_claude("x").struktur is None


def test_ein_abgelehntes_schema_kostet_nicht_den_ganzen_lauf(monkeypatch):
    """Scheitert der Lauf am Schema, wird er einmal ohne wiederholt.

    Der Textweg ist getestet und funktioniert seit jeher. Ein Block ist zu
    teuer, um ihn an einer Gegenstelle zu verlieren, die das Schema aus einem
    Grund nicht mag, den hier niemand kennt.
    """
    laeufe = []

    def _popen(argv, **kwargs):
        laeufe.append(argv)
        if "--json-schema" in argv:
            return FakeProzess(stderr="unsupported schema", returncode=1)
        return FakeProzess(stdout=huelle())

    monkeypatch.setattr(subprocess, "Popen", _popen)
    antwort = ki_client.rufe_claude("Plane bitte.", json_schema=SCHEMA)

    assert antwort.text == '{"plan": {}}'
    assert len(laeufe) == 2
    assert "--json-schema" not in laeufe[1]


@pytest.mark.parametrize(
    "fehlerausgabe",
    ["invalid api key", "usage limit reached"],
)
def test_am_zugang_scheitert_auch_der_zweite_lauf(monkeypatch, fehlerausgabe):
    """Kein zweiter Versuch, wo er nichts ändern kann.

    Token und Kontingent haben mit dem Schema nichts zu tun — ein
    Wiederholungslauf verdoppelte nur die Wartezeit vor derselben Meldung.
    """
    laeufe = []

    def _popen(argv, **kwargs):
        laeufe.append(argv)
        return FakeProzess(stderr=fehlerausgabe, returncode=1)

    monkeypatch.setattr(subprocess, "Popen", _popen)
    with pytest.raises((KiTokenUngueltig, KiKontingentErschoepft)):
        ki_client.rufe_claude("Plane bitte.", json_schema=SCHEMA)

    assert len(laeufe) == 1


def test_die_sitzung_des_aufrufers_wird_nicht_vererbt(prozess, monkeypatch):
    """Sonst hängt sich der Unterprozess an die Sitzung, aus der er gestartet wurde.

    Am eigenen Rechner aufgefallen: Wer die App aus einer laufenden
    Claude-Code-Sitzung startet, vererbt deren Kennung und Meldungssocket. Der
    Lauf kehrte dann nicht zurück, sondern lief in die Zeitüberschreitung.
    """
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "die-sitzung-des-entwicklers")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", "/tmp/socket")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-nicht-benutzen")
    monkeypatch.setenv("PATH", "/usr/bin")

    notiz = prozess(FakeProzess(stdout=huelle()))
    ki_client.rufe_claude("x")
    env = notiz["kwargs"]["env"]

    assert "CLAUDE_CODE_SESSION_ID" not in env
    assert "CLAUDE_CODE_MESSAGING_SOCKET" not in env
    assert "CLAUDECODE" not in env
    # Der Abo-Zugang soll gelten, nicht ein herumliegender API-Schlüssel.
    assert "ANTHROPIC_API_KEY" not in env
    # Ohne PATH fände der Prozess nicht einmal sich selbst.
    assert env["PATH"] == "/usr/bin"


def test_abgelaufener_zugang_wird_erkannt(prozess):
    prozess(FakeProzess(stderr="OAuth token expired, please run /login", returncode=1))
    with pytest.raises(KiTokenUngueltig):
        ki_client.rufe_claude("x")


def test_erschoepftes_kontingent_wird_erkannt(prozess):
    prozess(FakeProzess(stderr="You have reached your usage limit", returncode=1))
    with pytest.raises(KiKontingentErschoepft):
        ki_client.rufe_claude("x")


def test_unbekannter_fehler_nimmt_den_originaltext_mit(prozess):
    prozess(FakeProzess(stderr="Etwas ganz Neues ging schief", returncode=1))
    with pytest.raises(KiFehler) as fehler:
        ki_client.rufe_claude("x")
    # Ohne den Originaltext ließe sich ein unbekannter Fall nie aufklären.
    assert "Etwas ganz Neues" in fehler.value.meldung


def test_fehlerhuelle_wird_nicht_als_plan_weitergereicht(prozess):
    prozess(FakeProzess(stdout=huelle(is_error=True, result="Rate limit exceeded")))
    with pytest.raises(KiKontingentErschoepft):
        ki_client.rufe_claude("x")


def test_api_fehlerstatus_schlaegt_durch(prozess):
    prozess(FakeProzess(stdout=huelle(api_error_status=401, result="unauthorized")))
    with pytest.raises(KiTokenUngueltig):
        ki_client.rufe_claude("x")


def test_ablehnung_bekommt_eine_eigene_meldung(prozess):
    prozess(FakeProzess(stdout=huelle(stop_reason="refusal", result="")))
    with pytest.raises(KiAbgelehnt):
        ki_client.rufe_claude("x")


def test_leere_antwort_ist_unbrauchbar(prozess):
    prozess(FakeProzess(stdout=huelle(result="   ")))
    with pytest.raises(KiAntwortUnbrauchbar):
        ki_client.rufe_claude("x")


def test_keine_json_huelle_ist_unbrauchbar(prozess):
    prozess(FakeProzess(stdout="Kein JSON weit und breit"))
    with pytest.raises(KiAntwortUnbrauchbar):
        ki_client.rufe_claude("x")


def test_fehlende_cli_sagt_das_auch(monkeypatch):
    def _popen(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(subprocess, "Popen", _popen)
    with pytest.raises(KiCliFehlt):
        ki_client.rufe_claude("x")


def test_zeitueberschreitung_toetet_den_prozess(prozess):
    stand = FakeProzess(timeout=True)
    prozess(stand)
    with pytest.raises(KiZeitueberschreitung):
        ki_client.rufe_claude("x", timeout_s=1)
    # `communicate` beendet den Prozess nicht von selbst — ohne das Töten liefe
    # er als Waise weiter.
    assert stand.getoetet


def test_anmeldung_wird_am_programm_geprueft(monkeypatch):
    """Nicht „ist die Variable gesetzt", sondern „hat die CLI einen Zugang"."""

    def _run(argv, **kwargs):
        assert argv[1:] == ["auth", "status"]
        return subprocess.CompletedProcess(
            argv, 0, stdout=json.dumps({"loggedIn": True, "subscriptionType": "pro"}), stderr=""
        )

    monkeypatch.setattr(subprocess, "run", _run)
    assert ki_client.ist_angemeldet(erzwinge=True) is True

    def _run_aus(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="not logged in")

    monkeypatch.setattr(subprocess, "run", _run_aus)
    assert ki_client.ist_angemeldet(erzwinge=True) is False
