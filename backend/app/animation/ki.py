"""Prompt und Antwortformat für Animationen, die die KI erzeugt.

Die KI schreibt **Rezepte** (`format.Rezept`), keine fertigen Bewegungen:
ungefähre Gelenkwinkel plus Kontakte. Die Genauigkeit liefert der Löser —
Gelenkwinkel so zu wählen, dass eine Ferse auf den Zentimeter aufliegt, kann
ein Sprachmodell nicht, und muss es auch nicht.

Die Faustregeln unter „Worauf es ankommt“ sind keine Theorie: Jede steht dort,
weil die kuratierte Bibliothek genau an dieser Stelle einmal falsch war
(`docs/animationen.md`, „Was beim Schreiben der Bibliothek schiefging“).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .bibliothek_datei import REZEPTE
from .koerper import BEREICHE, KONTAKT, MUSKELGRUPPEN

SYSTEMPROMPT = (
    "Du bist Bewegungsdesigner für Trainingsanimationen. Du beschreibst Kraft- "
    "und Mobilityübungen so, dass ein vereinfachtes 3D-Körpermodell sie "
    "anatomisch korrekt vorführt. Du arbeitest präzise, hältst dich exakt an "
    "das beschriebene Format und erfindest keine Gelenke oder Felder. Lieber "
    "eine schlichte, eindeutig richtige Bewegung als eine aufwendige, die "
    "falsch aussieht — der Athlet macht nach, was er sieht."
)

# Wie viele Übungen ein Lauf höchstens beschreibt. Mehr machen die Antwort lang
# und fehleranfällig; was übrig bleibt, holt der nächste Lauf.
MAX_JE_LAUF = 6

# Beispiele aus der kuratierten Bibliothek — je eine Rücken-, Vierfüßler- und
# Standübung, damit die typischen Grundhaltungen einmal vorkommen.
_BEISPIELE = ("glute-bridge", "bird-dog", "standing-quad-stretch")


@dataclass(frozen=True)
class Auftrag:
    schluessel: str
    name_en: str
    zeilen: tuple[str, ...]  # wie die Übung im Plan steht (deutsch, mit Umfang)
    sport: str
    rueckmeldung: str | None = None  # warum eine frühere Fassung verworfen wurde


def _beispiele() -> str:
    alle = {r["schluessel"]: r for r in json.loads(REZEPTE.read_text(encoding="utf-8"))["rezepte"]}
    return "\n\n".join(
        json.dumps(alle[k], ensure_ascii=False, separators=(",", ":")) for k in _BEISPIELE if k in alle
    )


def _parameterliste() -> str:
    zeilen = []
    for k, (lo, hi) in BEREICHE.items():
        if k.endswith("_r"):
            continue
        name = k[:-2] + "_l/_r" if k.endswith("_l") else k
        zeilen.append(f"- `{name}`: {lo:g} … {hi:g}")
    return "\n".join(zeilen)


PROMPT_VORLAGE = """\
# Aufgabe

Beschreibe für jede der unten genannten Übungen eine kurze, in sich
geschlossene Bewegungsschleife als **Rezept**. Ein Programm löst daraus die
exakten Posen und spielt sie in der Trainings-App als Animation ab.

# Das Körpermodell

Ein Erwachsener, 1,75 m. Koordinaten in Metern: x nach **links der Figur**,
y nach oben, z nach vorn; Boden bei y = 0. In der Ruhehaltung (alle Werte 0)
steht die Figur aufrecht, Arme hängend, Blick nach +z, Becken auf y = 0,973.

**Wurzel (Becken):** `x`, `y`, `z` und die Lage
- `nicken` (um x): -90 = Rückenlage (Kopf nach -z, Gesicht oben),
  +90 = Bauch-/Vierfüßlerlage (Kopf nach +z, Gesicht unten),
- `rollen` (um z): 90 = Seitenlage auf der rechten Seite (Kopf nach -x,
  Gesicht nach +z), -90 = auf der linken,
- `gieren` (um die Senkrechte), `drehen` (um die eigene Längsachse — rollt
  einen liegenden Körper zur Seite).

**Gelenke** (Grad; positiv = anatomisch übliche Richtung, für links und rechts
gleich — die Spiegelung macht das Modell):
- `rumpf_beugen` (vorbeugen/Buckel +, Hohlkreuz −), `rumpf_seit` (zur linken
  Seite +), `rumpf_drehen`, `kopf_beugen` (Kinn zur Brust +),
- `schulter_beugen` (Arm nach vorn/oben +; 180 = über Kopf),
  `schulter_abspreizen` (seitlich weg +; negativ = vor dem Körper quer),
  `schulter_drehen`, `ellbogen` (0 = gestreckt), `handgelenk` (Handrücken
  zum Unterarm +; ~85 = Handfläche flach im Stütz),
- `huefte_beugen` (Oberschenkel nach vorn/oben +, nach hinten −),
  `huefte_abspreizen` (seitlich weg +), `huefte_drehen` (außen +),
  `knie` (0 = gestreckt), `fuss` (Zehen hoch +, Spitze strecken −).
- `atmen` (0 … 1) weitet den Bauch — nur für Atemübungen.

Zulässige Bereiche:
{parameterliste}

**Gelenkpunkte** für Kontakte: {gelenke}.

**Muskelgruppen** für `betont` (hervorgehoben dargestellt), mit `_l`/`_r` nur
eine Seite: {muskeln}.

# Das Rezept

```
{{"schluessel": "…", "name": "Englischer Name", "aliase": [],
 "ansicht": {{"gieren": 0-360, "neigen": 0-80}},
 "betont": ["…"], "unterlage": "matte" | "boden",
 "requisiten": [{{"art": "kasten", "x": 0, "z": 0.4, "breite": 0.6, "tiefe": 0.4, "hoehe": 0.3}}
                | {{"art": "wand", "z": -0.3}}],
 "ablauf": [ {{"pose": {{…}}, "halten_s": 0.5, "uebergang_s": 1.2,
             "boden": ["ferse_l", {{"gelenk": "zehen_l", "hoehe": 0.3}}],
             "halten": ["ferse_l"], "ziele": [{{"gelenk": "hand_l", "an": "knie_l", "versatz": [0, 0.05, 0]}}],
             "frei": ["y", "z", "nicken", "knie_"], "aus_vorherigem": false}} ]}}
```

- `ablauf`: 2–6 Schlüsselbilder; nach dem letzten geht es zum ersten zurück.
  Halte- und Übergangszeiten wie in echt (Dehnung: lange halten; Kraft:
  ~1 s Übergang).
- `boden`: was aufliegt (mit `hoehe` auf einer Stufe). `halten`: was an der
  Stelle des **vorigen** Bilds bleibt (stehender Fuß, stützende Hand).
  `ziele`: ein Gelenk an einer Stelle — absolut (`x`/`y`/`z`) oder an einem
  anderen Gelenk (`an` + `versatz`), z. B. die Hand am Knöchel.
- `frei`: welche Werte das Programm verändern darf, um die Kontakte zu
  erfüllen. `knie_` steht für beide Knie gemeinsam; für nur eines `knie_l`.
  Nenne immer Beckenlage (`y`, `z`, oft `nicken`) und die Gelenke, die den
  Kontakt herstellen. Alles nicht Genannte bleibt, wie du es angibst.
- `aus_vorherigem: true`: Die Pose baut auf dem **gelösten** vorigen Bild auf;
  `pose` nennt dann nur, was sich ändert.
- `ansicht`: so, dass die Bewegung klar zu sehen ist — meist schräg von der
  Seite (gieren 60–80), seitliche Bewegungen von vorn (gieren 0–20),
  Drehungen am Boden von oben (neigen 40–60).
- `schluessel` übernimmst du **unverändert** aus der Liste unten.

# Worauf es ankommt

1. Im aufrechten **Sitz** braucht ein waagrechter Oberschenkel ~90°
   `huefte_beugen`, nicht 45°.
2. Beugen und Abspreizen **addieren sich** zur Anhebung: Oberschenkel
   waagrecht und 50° zur Seite ist ~ beugen 58 + abspreizen 69, nicht 90 + 50.
3. Hände flach im Stütz (Vierfüßler, Liegestütz): `handgelenk` ~85, und
   `hand_*` **und** `finger_*` unter `boden`.
4. Nach vorn lehnen im Sitz über `rumpf_beugen`, nicht über `nicken` — sonst
   kippen die Beine mit.
5. Vierfüßler: `nicken` 90, Hüften und Knie 90, Schultern 90, Kontakte Hände,
   Finger, Knie und Zehen.
6. Einseitige Übungen zeigst du **eine** Seite (links), außer der Wechsel ist
   die Übung selbst.
7. Lieber zwei klare Schlüsselbilder als fünf unsichere.

# Beispiele aus der geprüften Bibliothek

{beispiele}

# Die Übungen

{uebungen}

Antworte mit `{{"animationen": [ … ]}}` — ein Rezept je Übung, in dieser
Reihenfolge.
"""


def prompt(auftraege: list[Auftrag]) -> str:
    teile = []
    for a in auftraege:
        zeilen = "\n".join(f"  - im Plan: „{z}“" for z in a.zeilen)
        teil = f"- `{a.schluessel}` — {a.name_en} ({'Kraft' if a.sport == 'strength' else 'Mobility'})\n{zeilen}"
        if a.rueckmeldung:
            teil += f"\n  - Eine frühere Fassung wurde verworfen: „{a.rueckmeldung}“"
        teile.append(teil)
    return PROMPT_VORLAGE.format(
        parameterliste=_parameterliste(),
        gelenke=", ".join(f"`{g}`" for g in sorted(KONTAKT)),
        muskeln=", ".join(f"`{g}`" for g in sorted(MUSKELGRUPPEN)),
        beispiele=_beispiele(),
        uebungen="\n".join(teile),
    )


_ZAHL = {"type": "number"}
_GELENK = {"type": "string", "enum": sorted(KONTAKT)}

# Bewusst locker — wie beim Trainingsplan (`ai_export._einheit_strukturschema`):
# Das Schema erzwingt die Form, geprüft wird danach von `format.Rezept`.
JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "animationen": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "schluessel": {"type": "string"},
                    "name": {"type": "string"},
                    "aliase": {"type": "array", "items": {"type": "string"}},
                    "ansicht": {"type": "object", "properties": {"gieren": _ZAHL, "neigen": _ZAHL}},
                    "betont": {"type": "array", "items": {"type": "string"}},
                    "unterlage": {"type": "string", "enum": ["matte", "boden"]},
                    "requisiten": {"type": "array", "items": {"type": "object"}},
                    "ablauf": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "pose": {"type": "object", "additionalProperties": _ZAHL},
                                "halten_s": _ZAHL,
                                "uebergang_s": _ZAHL,
                                "aus_vorherigem": {"type": "boolean"},
                                "boden": {"type": "array"},
                                "halten": {"type": "array", "items": _GELENK},
                                "ziele": {"type": "array", "items": {"type": "object"}},
                                "frei": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["pose"],
                        },
                    },
                },
                "required": ["schluessel", "name", "ablauf"],
            },
        },
    },
    "required": ["animationen"],
}
