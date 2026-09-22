"""Das Format einer Animation — als Rezept (mit Kontakten) und als Bewegung.

Zwei Stufen, weil zwei verschiedene Leute schreiben und lesen:

* Das **Rezept** schreibt, wer eine Übung beschreibt — die kuratierte
  Bibliothek (`bibliothek/rezepte.json`) oder die KI. Es nennt ungefähre
  Gelenkwinkel und dazu, was aufliegt, was stehen bleibt und was der Löser
  zurechtrücken darf.
* Die **Bewegung** liest die App. Sie enthält nur fertig gelöste Posen, dazu
  Kamera, hervorgehobene Muskeln und Requisiten. Rechnen muss die App nichts
  außer Vorwärtskinematik und Zeichnen.

Beide Modelle prüfen streng: Ein unbekanntes Gelenk, ein Winkel außerhalb des
Möglichen oder eine erfundene Muskelgruppe lassen die Antwort durchfallen,
statt still ignoriert zu werden — genau wie beim Trainingsplan
(`schemas.AISessionIn`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .koerper import BEREICHE, KONTAKT, MUSKELGRUPPEN, SEITEN


def _pruefe_pose(pose: dict[str, float]) -> dict[str, float]:
    for k, v in pose.items():
        if k not in BEREICHE:
            raise ValueError(f"Unbekannter Posenparameter „{k}“")
        lo, hi = BEREICHE[k]
        if not lo <= v <= hi:
            raise ValueError(f"„{k}“ = {v} liegt außerhalb von {lo} … {hi}")
    return pose


def _pruefe_muskeln(gruppen: list[str]) -> list[str]:
    erlaubt = MUSKELGRUPPEN | {f"{g}_{s}" for g in MUSKELGRUPPEN for s in SEITEN}
    for g in gruppen:
        if g not in erlaubt:
            raise ValueError(f"Unbekannte Muskelgruppe „{g}“")
    return gruppen


class Ansicht(BaseModel):
    """Woher die Kamera schaut: `gieren` 0 = von vorn, 90 = von links der Figur."""

    model_config = ConfigDict(extra="forbid")
    gieren: float = Field(70.0, ge=-360, le=360)
    neigen: float = Field(15.0, ge=-10, le=89)


class Requisit(BaseModel):
    """Eine Stufe/ein Kasten oder eine Wand. Maße in Metern, Boden bei y = 0."""

    model_config = ConfigDict(extra="forbid")
    art: Literal["kasten", "wand"]
    x: float = Field(0.0, ge=-3, le=3)
    z: float = Field(0.0, ge=-3, le=3)
    breite: float | None = Field(None, gt=0, le=3)
    tiefe: float | None = Field(None, gt=0, le=3)
    hoehe: float | None = Field(None, gt=0, le=2)

    @model_validator(mode="after")
    def _masse(self) -> "Requisit":
        if self.art == "kasten" and None in (self.breite, self.tiefe, self.hoehe):
            raise ValueError("Ein Kasten braucht breite, tiefe und hoehe")
        return self


class _Gemeinsam(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schluessel: str = Field(..., min_length=1, max_length=80, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    name: str = Field(..., min_length=1, max_length=120)
    aliase: list[str] = Field(default_factory=list, max_length=20)
    ansicht: Ansicht = Field(default_factory=Ansicht)
    betont: list[str] = Field(default_factory=list, max_length=12)
    unterlage: Literal["matte", "boden"] = "matte"
    requisiten: list[Requisit] = Field(default_factory=list, max_length=4)

    _betont = field_validator("betont")(classmethod(lambda cls, v: _pruefe_muskeln(v)))


# --------------------------------------------------------------------------
# Bewegung — das, was die App abspielt
# --------------------------------------------------------------------------


class Schluesselbild(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pose: dict[str, float]
    halten_s: float = Field(0.4, ge=0, le=10)
    uebergang_s: float = Field(1.0, ge=0.1, le=10)
    # Gelöste Zwischenposen auf dem Weg zum nächsten Bild — siehe
    # `loeser._zwischenbilder`, warum es sie gibt.
    zwischen: list[dict[str, float]] = Field(default_factory=list, max_length=4)

    _pose = field_validator("pose")(classmethod(lambda cls, v: _pruefe_pose(v)))

    @field_validator("zwischen")
    @classmethod
    def _zwischen(cls, v: list[dict[str, float]]) -> list[dict[str, float]]:
        return [_pruefe_pose(p) for p in v]


class Bewegung(_Gemeinsam):
    ablauf: list[Schluesselbild] = Field(..., min_length=1, max_length=12)


# --------------------------------------------------------------------------
# Rezept — das, was eine Übung beschreibt
# --------------------------------------------------------------------------


class Auflage(BaseModel):
    """Ein Gelenk liegt auf einer Fläche in `hoehe` Metern (0 = Boden)."""

    model_config = ConfigDict(extra="forbid")
    gelenk: str
    hoehe: float = Field(0.0, ge=0, le=2)


class Ziel(BaseModel):
    """Ein Gelenk an einer festen Stelle (`x`/`y`/`z`) oder an einem anderen (`an` + `versatz`)."""

    model_config = ConfigDict(extra="forbid")
    gelenk: str
    x: float | None = None
    y: float | None = None
    z: float | None = None
    an: str | None = None
    versatz: list[float] | None = Field(None, min_length=3, max_length=3)


class RezeptBild(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pose: dict[str, float] = Field(default_factory=dict)
    halten_s: float = Field(0.4, ge=0, le=10)
    uebergang_s: float = Field(1.0, ge=0.1, le=10)
    aus_vorherigem: bool = False
    boden: list[str | Auflage] = Field(default_factory=list)
    halten: list[str] = Field(default_factory=list)
    ziele: list[Ziel] = Field(default_factory=list)
    frei: list[str] = Field(default_factory=list)

    _pose = field_validator("pose")(classmethod(lambda cls, v: _pruefe_pose(v)))

    @model_validator(mode="after")
    def _gelenke(self) -> "RezeptBild":
        genannt = [b if isinstance(b, str) else b.gelenk for b in self.boden]
        genannt += self.halten
        genannt += [z.gelenk for z in self.ziele] + [z.an for z in self.ziele if z.an]
        for g in genannt:
            if g not in KONTAKT:
                raise ValueError(f"Unbekanntes Gelenk „{g}“")
        for f in self.frei:
            if f not in BEREICHE and not (f.endswith("_") and f"{f}l" in BEREICHE):
                raise ValueError(f"Unbekannter freier Parameter „{f}“")
        return self


class Rezept(_Gemeinsam):
    ablauf: list[RezeptBild] = Field(..., min_length=1, max_length=12)

    def als_dict(self) -> dict:
        """Für den Löser: Pydantic-Objekte zurück in schlichte Dicts."""
        return self.model_dump(exclude_none=True)
