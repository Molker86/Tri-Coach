"""Das Datenpaket als Text für den Prompt — Tabellen statt wiederholter Schlüssel.

Eine reine Darstellungsschicht über `ai_export.build_payload()`. Der Payload
selbst bleibt der verschachtelte Dict, den er immer war — er geht als
`ExportOut.payload` ins Frontend und wird dort ausgewertet. Nur der Weg **in
den Prompt** führt hier durch. Was der Athlet zurückkopiert, erkennen die
Importeure seither an `ist_datenpaket()` unten statt an obersten Schlüsseln.

Zwei Kostentreiber, beide reine Mechanik ohne Informationsgehalt:

* **Wiederholte Schlüsselnamen.** In `trainingshistorie.einheiten` stehen rund
  dreißig Datensätze, und jeder wiederholt alle fünfundzwanzig Schlüssel
  (`"garmin_trainingslast"`, `"trainingseffekt_aerob"` …). Als CSV mit einer
  Kopfzeile fällt das weg — gemessen 60 % dieses Blocks, bei
  `fitnessdaten.tage` sogar 74 %.
* **`null`-Felder.** `"leistung_watt":null,"trittfrequenz":null` zieht sich
  durch fast jede Einheit. Ein fehlendes Feld sagt dasselbe; `ai_export`
  begründet an mehreren Stellen sogar, dass ein `null` *schlechter* ist als
  das Fehlen — es ist keine leere Angabe, sondern eine Behauptung. Hier gilt
  dieselbe Regel einmal für das ganze Paket, statt an jedem Block einzeln.

**Verlustfrei, und das ist die Bedingung.** Keine Abkürzung, keine erfundene
Kurzschrift für Messwerte, kein weggelassener Wert — nur die Klammern und die
wiederholten Namen verschwinden. `test_paketformat.py` baut den Text zurück in
den Payload und vergleicht.

Die Tabellenüberschriften **sind** die bisherigen JSON-Pfade
(`### trainingshistorie.einheiten`). Damit bleibt jede Feldreferenz im
Anweisungsteil des Prompts gültig, ohne dass dort eine Zeile zu ändern wäre.
"""

import copy
import csv
import io
import json
from typing import Any

# Semikolon statt Komma: Die Freitexte im Paket (Garmins Aktivitätsnamen, die
# Notiz, der Anpassungswunsch) enthalten Kommas laufend und Semikolons so gut
# wie nie — jedes Komma zwänge sonst Anführungszeichen um die ganze Zelle.
TRENNZEICHEN = ";"


# --------------------------------------------------------------------------
# Bausteine
# --------------------------------------------------------------------------


def _json(wert: Any) -> str:
    return json.dumps(wert, separators=(",", ":"), ensure_ascii=False)


def _ohne_leere(wert: Any) -> Any:
    """`None` und leere Behälter raus — rekursiv, für die JSON-Köpfe.

    In den Tabellen erledigt das die leere Zelle; dort bleiben die Schlüssel
    sogar bewusst stehen, damit die Spaltenreihenfolge nicht davon abhängt,
    welche Zeile zufällig als erste einen Wert trägt.

    `0`, `False` und der leere String bleiben stehen — sie sind Messwerte,
    keine fehlende Angabe. Nur `None`, `{}` und `[]` fallen.
    """
    if isinstance(wert, dict):
        gefiltert = {
            schluessel: _ohne_leere(inhalt)
            for schluessel, inhalt in wert.items()
            if inhalt is not None
        }
        return {
            schluessel: inhalt
            for schluessel, inhalt in gefiltert.items()
            if not (isinstance(inhalt, (dict, list)) and not inhalt)
        }
    if isinstance(wert, list):
        return [_ohne_leere(inhalt) for inhalt in wert if inhalt is not None]
    return wert


def _zelle(wert: Any) -> str:
    """Ein Wert als Tabellenzelle.

    Zeilenumbrüche und Mehrfach-Leerzeichen fallen zusammen: Ein Umbruch im
    Freitext zerrisse die Zeile, und `csv` würde die ganze Zelle in
    Anführungszeichen setzen, um sie zu retten — beides kostet mehr, als der
    Umbruch wert ist.
    """
    if wert is None:
        return ""
    if wert is True:
        return "true"
    if wert is False:
        return "false"
    if isinstance(wert, (dict, list)):
        return _json(wert)
    return " ".join(str(wert).split())


def _spalten(zeilen: list[dict[str, Any]]) -> list[str]:
    """Spalten in der Reihenfolge ihres ersten Auftretens.

    Nicht sortiert: Die Kernfelder einer Einheit stehen im Payload in einer
    gewachsenen, sachlich sinnvollen Reihenfolge (Datum, Sportart, Dauer …),
    und die optionalen Messgrößen hängen hinten dran. Alphabetisch stünde
    `befinden_0_10` vor `datum`.
    """
    spalten: list[str] = []
    for zeile in zeilen:
        for name in zeile:
            if name not in spalten:
                spalten.append(name)
    return spalten


def _leerspalten_streichen(
    zeilen: list[dict[str, Any]], spalten: list[str]
) -> list[str]:
    """Spalten, die in **keiner** Zeile einen Wert tragen, ganz weglassen.

    Verlustfrei: Eine durchgängig leere Spalte sagt nichts, was ihr Fehlen
    nicht auch sagte. `_konstanten_abtrennen` fängt sie nicht ab — es
    überspringt Spalten mit `None` ausdrücklich, weil ein `feld=` in der
    Überschrift eine Behauptung wäre.

    Spürbar wird das an den Einheiten: `leistung_watt` steht an jeder Zeile im
    Payload, ist aber bei einem Athleten ohne Leistungsmesser fünfzig Mal leer,
    und `stunden_je_sportart.swim` fehlt bei einem reinen Läufer das ganze Jahr.

    Die erste Spalte bleibt aus demselben Grund wie dort stehen: Sie trägt die
    Kennung der Zeile.
    """
    return [
        name
        for i, name in enumerate(spalten)
        if i == 0 or any(zeile.get(name) is not None for zeile in zeilen)
    ]


def _konstanten_abtrennen(
    zeilen: list[dict[str, Any]], spalten: list[str]
) -> tuple[dict[str, Any], list[str]]:
    """Spalten, die in allen Zeilen denselben Wert tragen, aus der Tabelle lösen.

    Am deutlichsten bei den Zonenblöcken (`basis`, `estimated_max_hr`,
    `einheit` galten für alle fünf Zeilen und standen fünfmal da), aber
    genauso bei `status=completed` und `quelle=garmin` über dreißig Einheiten.
    Verlustfrei: Die Legende sagt, dass die Klammer für alle Zeilen gilt.

    Nur ab zwei Zeilen — bei einer einzigen wäre *jede* Spalte konstant. Und nie
    die erste: Sie trägt die Kennung der Zeile (`zone`, `datum`, `nr`), und eine
    Tabelle ohne Spalten wäre keine mehr.
    """
    if len(zeilen) < 2:
        return {}, spalten

    fest: dict[str, Any] = {}
    for name in spalten[1:]:
        werte = [zeile.get(name) for zeile in zeilen]
        if isinstance(werte[0], (dict, list)) or werte[0] is None:
            continue
        if all(wert == werte[0] for wert in werte):
            fest[name] = werte[0]

    return fest, [name for name in spalten if name not in fest]


def _tabelle(zeilen: list[dict[str, Any]], spalten: list[str]) -> str:
    puffer = io.StringIO()
    schreiber = csv.writer(
        puffer,
        delimiter=TRENNZEICHEN,
        lineterminator="\n",
        quoting=csv.QUOTE_MINIMAL,
    )
    schreiber.writerow(spalten)
    for zeile in zeilen:
        schreiber.writerow([_zelle(zeile.get(name)) for name in spalten])
    return puffer.getvalue().rstrip("\n")


def _faecherschluessel(zeilen: list[dict[str, Any]], feld: str) -> list[str]:
    """Die Unterschlüssel eines Feldes über **alle** Zeilen, erstes Auftreten zuerst.

    Der Satz muss vor dem Auffächern feststehen, sonst zerreißt die Gruppe:
    `_aufgefaechert` schrieb je Zeile nur die Schlüssel *dieser* Zeile, und
    `_spalten` ordnet nach erstem Auftreten. Trug die erste Einheit nur z1–z4,
    stand `zeit_in_hf_zonen_min.z5` am Ende der Tabelle — hinter `effizienz` und
    `rpe_quelle`, weil es erst in einer späteren Zeile auftauchte. Über fünfzig
    Zeilen ist das genau die Zuordnung, die ein Sprachmodell verlieren soll.

    Erstes Auftreten und **nicht** alphabetisch, dieselbe Regel wie in
    `_spalten` und aus demselben Grund: `intensitaetsverteilung_pct` hat die
    Schlüssel `niedrig`, `mittel`, `hoch`, und alphabetisch stünde `hoch` vorn.
    """
    namen: list[str] = []
    for zeile in zeilen:
        wert = zeile.get(feld)
        if isinstance(wert, dict):
            for name in wert:
                if name not in namen:
                    namen.append(name)
    return namen


def _aufgefaechert(
    zeile: dict[str, Any], faecher: dict[str, list[str]]
) -> dict[str, Any]:
    """Ein Dict-Feld wird zu Spalten `feld.schluessel`.

    Für `zeit_in_hf_zonen_min` und `intensitaetsverteilung_pct`: Die Unterkeys
    sind über alle Zeilen dieselben fünf, als eigene Spalten kosten ihre Namen
    einmal statt dreißigmal — und über die Zeilen hinweg untereinander stehende
    Zahlen sind genau das, was die Verteilung vergleichbar macht.

    `faecher` nennt je Feld den vollständigen Schlüsselsatz aus
    `_faecherschluessel`. Jede Zeile bekommt ihn ganz; was sie nicht trägt, wird
    `None` und damit zur leeren Zelle. Eine Unterspalte, die in *keiner* Zeile
    etwas trägt, streicht `_leerspalten_streichen` gleich danach wieder.
    """
    if not faecher:
        return zeile
    neu: dict[str, Any] = {}
    for name, wert in zeile.items():
        if name in faecher:
            # Auch wo nichts anliegt: Sonst stünde neben den aufgefächerten
            # Spalten noch eine leere Spalte unter dem alten Namen.
            unter = wert if isinstance(wert, dict) else {}
            for unterschluessel in faecher[name]:
                neu[f"{name}.{unterschluessel}"] = unter.get(unterschluessel)
        else:
            neu[name] = wert
    return neu


def _tabellenblock(
    pfad: str,
    zeilen: list[dict[str, Any]],
    *,
    auffaechern: tuple[str, ...] = (),
) -> list[str]:
    if not zeilen:
        return []

    # Erst den Schlüsselsatz je Feld, dann auffächern: Die öffentliche Angabe
    # bleibt die Feldliste, die vollständige Spaltenfolge entsteht hier.
    faecher = {feld: _faecherschluessel(zeilen, feld) for feld in auffaechern}
    zeilen = [_aufgefaechert(zeile, faecher) for zeile in zeilen]
    spalten = _leerspalten_streichen(zeilen, _spalten(zeilen))
    fest, spalten = _konstanten_abtrennen(zeilen, spalten)
    kopf = f"### {pfad}"
    if fest:
        kopf += " (" + ", ".join(f"{k}={_zelle(v)}" for k, v in fest.items()) + ")"
    return [f"{kopf}\n{_tabelle(zeilen, spalten)}"]


def _langformat_liste(
    zeilen: list[dict[str, Any]], feld: str, bezug: str
) -> list[dict[str, Any]]:
    """Ein verschachteltes Listenfeld aus den Zeilen lösen und flach ausrollen.

    `absolvierte_abschnitte` und `absolvierte_uebungen` sind Listen von Dicts
    *innerhalb* einer Einheit — in der Zelle wären sie wieder JSON mit
    wiederholten Schlüsseln, und ihre Anführungszeichen zwängen die Zelle in
    Anführungszeichen. Als eigene Tabelle mit einer Bezugsspalte kostet jeder
    Abschnitt eine Zeile.
    """
    heraus: list[dict[str, Any]] = []
    for zeile in zeilen:
        eintraege = zeile.pop(feld, None)
        if not eintraege:
            continue
        for eintrag in eintraege:
            heraus.append({bezug: zeile.get(bezug), **eintrag})
    return heraus


def _langformat_dict(
    zeilen: list[dict[str, Any]], feld: str, bezug: str, benennung: str
) -> list[dict[str, Any]]:
    """Dasselbe für ein Dict-Feld: Der Schlüssel wird zur eigenen Spalte.

    Für `by_sport`. Als Spalten je Sportart wären es fünf mal sechs meist leere
    Felder; die Sportart in eine Zeile zu setzen ist die kürzere und die
    lesbarere Form.
    """
    heraus: list[dict[str, Any]] = []
    for zeile in zeilen:
        unter = zeile.pop(feld, None)
        if not unter:
            continue
        for schluessel, werte in unter.items():
            heraus.append({bezug: zeile.get(bezug), benennung: schluessel, **werte})
    return heraus


def _kopf(name: str, block: dict[str, Any]) -> list[str]:
    """Was vom Block nach dem Herauslösen der Tabellen übrig ist — als JSON."""
    rest = _ohne_leere(block)
    return [f"{name}: {_json(rest)}"] if rest else []


# --------------------------------------------------------------------------
# Die einzelnen Blöcke
# --------------------------------------------------------------------------


def _athlet(block: dict[str, Any]) -> list[str]:
    verlauf = block.pop("verlauf", None) or []
    bestzeiten = block.pop("bestzeiten_aus_garmin", None) or []
    teile = _kopf("athlet", block)
    teile += _tabellenblock(
        "athlet.verlauf",
        verlauf,
        # Sonst stünde je Monat ein JSON-Klumpen in der Zelle. Die Sportarten
        # sind über die Zeilen hinweg dieselben — als Spalten kosten ihre Namen
        # einmal statt zwölfmal, und untereinander stehende Zahlen sind genau
        # das, was den Jahresverlauf lesbar macht.
        auffaechern=("stunden_je_sportart", "effizienz_je_sportart"),
    )
    teile += _tabellenblock("athlet.bestzeiten_aus_garmin", bestzeiten)
    return teile


def _historie(block: dict[str, Any]) -> list[str]:
    wochen = block.pop("wochenuebersicht", None) or []
    einheiten = block.pop("einheiten", None) or []

    # Die laufende Nummer als Bezugspunkt der Untertabellen. Datum und Sportart
    # täten es nicht: Zwei Radeinheiten an einem Tag sind keine Seltenheit, und
    # dann wäre nicht mehr zu erkennen, zu welcher ein Abschnitt gehört.
    einheiten = [{"nr": nummer, **zeile} for nummer, zeile in enumerate(einheiten, 1)]

    je_sportart = _langformat_dict(wochen, "by_sport", "week_start", "sportart")
    abschnitte = _langformat_liste(einheiten, "absolvierte_abschnitte", "nr")
    uebungen = _langformat_liste(einheiten, "absolvierte_uebungen", "nr")

    teile = _kopf("trainingshistorie", block)
    teile += _tabellenblock(
        "trainingshistorie.wochenuebersicht",
        wochen,
        auffaechern=("zeit_in_hf_zonen_min", "intensitaetsverteilung_pct"),
    )
    teile += _tabellenblock("trainingshistorie.wochenuebersicht.by_sport", je_sportart)
    teile += _tabellenblock(
        "trainingshistorie.einheiten",
        einheiten,
        auffaechern=("zeit_in_hf_zonen_min",),
    )
    teile += _tabellenblock(
        "trainingshistorie.einheiten.absolvierte_abschnitte", abschnitte
    )
    teile += _tabellenblock(
        "trainingshistorie.einheiten.absolvierte_uebungen", uebungen
    )
    return teile


def _fitness(block: dict[str, Any]) -> list[str]:
    mittelwerte = block.pop("mittelwerte", None) or {}
    tage = block.pop("tage", None) or []
    teile = _kopf("fitnessdaten", block)
    teile += _tabellenblock(
        "fitnessdaten.mittelwerte",
        [{"groesse": name, **werte} for name, werte in mittelwerte.items()],
    )
    teile += _tabellenblock("fitnessdaten.tage", tage)
    return teile


def _blockumfeld(name: str, block: dict[str, Any]) -> list[str]:
    """Ein Trainingsblock als Umfeld — Kopf als JSON, die Tage als Tabelle.

    Betrifft `einheit_anpassen.block` und `ernaehrung.trainingsblock`, beide aus
    `ai_export._planumfeld`. Reiner Kontext und streng gleichförmig, also
    Tabelle. Anders als `einheit_anpassen.bisherige_einheit`, die bewusst JSON
    bleibt: Deren Schlüssel sind die des Antwortformats, damit die KI dieselben
    Felder zurückgibt, die sie sieht.
    """
    tage = block.pop("tage", None) or []
    zeilen = [
        {"datum": tag.get("datum"), "wochentag": tag.get("wochentag"), **einheit}
        for tag in tage
        for einheit in tag.get("einheiten", [])
    ]
    return _kopf(name, block) + _tabellenblock(f"{name}.tage", zeilen)


def _anpassung(block: dict[str, Any]) -> list[str]:
    umfeld = block.pop("block", None) or {}
    return _kopf("einheit_anpassen", block) + _blockumfeld(
        "einheit_anpassen.block", umfeld
    )


def _ernaehrung(block: dict[str, Any]) -> list[str]:
    trainingsblock = block.pop("trainingsblock", None) or {}
    return _kopf("ernaehrung", block) + _blockumfeld(
        "ernaehrung.trainingsblock", trainingsblock
    )


# --------------------------------------------------------------------------
# Das Ganze
# --------------------------------------------------------------------------

_LEGENDE = (
    'Tabellen sind CSV mit Kopfzeile, Trennzeichen "{trenner}", '
    "leere Zelle = keine Angabe.\n"
    "Werte in Klammern hinter einer Überschrift gelten für alle Zeilen der Tabelle."
).format(trenner=TRENNZEICHEN)

_LEGENDE_BEZUG = (
    'Eine Spalte "nr" verweist auf die Zeile gleicher "nr" '
    "in trainingshistorie.einheiten."
)


def ist_datenpaket(text: str) -> bool:
    """Steht in dem eingefügten Text unser eigenes Datenpaket?

    Wer den ganzen Prompt zurückkopiert, soll „das ist das Datenpaket, nicht
    die Antwort" lesen und keine Feldliste. Solange der Datenteil JSON war,
    erkannten die Importeure ihn an seinen obersten Schlüsseln; jetzt ist er
    kein JSON-Objekt mehr, und die Legende ist der Satz, den nur er trägt.
    """
    return _LEGENDE.splitlines()[0] in text


def paket_als_text(payload: dict[str, Any]) -> str:
    """Das Datenpaket als Abschnittsdokument für den Prompt.

    Unregelmäßiges bleibt kompaktes JSON, alles Gleichförmige wird eine
    CSV-Tabelle. Die Reihenfolge der Abschnitte ist die des Payloads — jede
    Tabelle steht direkt hinter dem Block, aus dem sie stammt.
    """
    # Eine eigene Kopie: Die Tabellen lösen ihre verschachtelten Felder aus den
    # Zeilen heraus, und derselbe Payload geht gleich darauf als
    # `ExportOut.payload` ins Frontend.
    daten = copy.deepcopy(payload)

    abschnitte: list[str] = []
    for name, wert in daten.items():
        if name == "athlet":
            abschnitte += _athlet(wert)
        elif name == "trainingshistorie":
            abschnitte += _historie(wert)
        elif name == "fitnessdaten":
            abschnitte += _fitness(wert)
        elif name == "einheit_anpassen":
            abschnitte += _anpassung(wert)
        elif name == "ernaehrung":
            abschnitte += _ernaehrung(wert)
        elif isinstance(wert, dict):
            abschnitte += _kopf(name, wert)
        elif isinstance(wert, list) and all(isinstance(e, dict) for e in wert):
            # Deckt die vier Zonenblöcke ab und jeden künftigen gleichförmigen
            # Block dazu: Wer eine Liste von Dicts ins Paket legt, bekommt die
            # Tabelle, ohne hier etwas eintragen zu müssen.
            abschnitte += _tabellenblock(name, wert)
        elif isinstance(wert, list):
            abschnitte.append(f"{name}: {_json(wert)}")
        else:
            abschnitte.append(f"{name}: {wert}")

    legende = _LEGENDE
    # Der Satz zur Bezugsspalte nur, wo es eine solche Tabelle gibt — eine Regel
    # zu einer Tabelle, die nicht dasteht, ist eine Einladung zum Erfinden.
    if any(zeile.startswith("### trainingshistorie.einheiten.") for zeile in abschnitte):
        legende += "\n" + _LEGENDE_BEZUG

    return legende + "\n\n" + "\n\n".join(abschnitte)
