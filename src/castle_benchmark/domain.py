from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Mapping


@dataclass(frozen=True, slots=True, order=True)
class Position:
    x: int
    y: int

    def __post_init__(self) -> None:
        if not isinstance(self.x, int) or not isinstance(self.y, int):
            raise TypeError("authoritative coordinates must be integers")


@dataclass(frozen=True, slots=True)
class ResourceStock:
    food: int = 0
    water: int = 0
    wood: int = 0
    stone: int = 0
    ore: int = 0
    tools: int = 0
    influence: int = 0

    def __post_init__(self) -> None:
        if any(getattr(self, field.name) < 0 for field in fields(self)):
            raise ValueError("resource quantities must be non-negative")

    def apply(self, delta: Mapping[str, int]) -> ResourceStock:
        known = {field.name for field in fields(self)}
        unknown = set(delta) - known
        if unknown:
            raise KeyError(f"unknown resources: {sorted(unknown)}")
        values = {name: getattr(self, name) + delta.get(name, 0) for name in known}
        return replace(self, **values)

    def as_dict(self) -> dict[str, int]:
        return {field.name: getattr(self, field.name) for field in fields(self)}

