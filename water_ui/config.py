from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Pot:
    id: str
    content: list[str]
    offset_cm: int
    water_hours: list[int]
    duration_s: float | None = None


@dataclass(frozen=True)
class Config:
    default_duration_s: float
    pots: list[Pot]

    def pot_by_id(self, pot_id: str) -> Pot | None:
        for pot in self.pots:
            if pot.id == pot_id:
                return pot
        return None

    def duration_for_pot(self, pot: Pot) -> float:
        if pot.duration_s is not None:
            return pot.duration_s
        return self.default_duration_s


def pot_label(pot: Pot) -> str:
    return ", ".join(pot.content)


def pot_offset_mm(pot: Pot) -> int:
    return pot.offset_cm * 10


def _parse_pot(raw: dict, index: int) -> Pot:
    pot_id = raw.get("id")
    if not pot_id or not str(pot_id).strip():
        raise ValueError(f"Pot at index {index} is missing required 'id'")

    try:
        uuid.UUID(str(pot_id))
    except ValueError as exc:
        raise ValueError(f"Pot at index {index} has invalid UUID '{pot_id}'") from exc

    if "content" not in raw:
        raise ValueError(f"Pot '{pot_id}' is missing required 'content'")

    if "offset_cm" in raw:
        offset_cm = raw["offset_cm"]
    elif "offset" in raw:
        offset_cm = raw["offset"]
    else:
        raise ValueError(f"Pot '{pot_id}' is missing required 'offset_cm'")

    if "water_hours" not in raw:
        raise ValueError(f"Pot '{pot_id}' is missing required 'water_hours'")

    duration_s = raw.get("duration_s")
    if duration_s is not None:
        duration_s = float(duration_s)

    return Pot(
        id=str(pot_id),
        content=list(raw["content"]),
        offset_cm=int(offset_cm),
        water_hours=[int(hour) for hour in raw["water_hours"]],
        duration_s=duration_s,
    )


def load_config(path: str | Path) -> Config:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    if "pots" not in data:
        raise ValueError("Config is missing required 'pots' list")

    default_duration_s = float(data.get("default_duration_s", 5))
    pots = [_parse_pot(raw, index) for index, raw in enumerate(data["pots"])]

    return Config(default_duration_s=default_duration_s, pots=pots)
