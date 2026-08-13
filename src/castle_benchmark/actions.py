from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias


@dataclass(frozen=True, slots=True)
class WaitAction:
    kind: Literal["wait"] = "wait"


GameAction: TypeAlias = WaitAction


@dataclass(frozen=True, slots=True)
class ActionBatch:
    turn: int
    colony_id: str
    actions: tuple[GameAction, ...]

    def __post_init__(self) -> None:
        if self.turn < 0:
            raise ValueError("turn must be non-negative")
        if not self.colony_id:
            raise ValueError("colony_id must not be empty")
        if not self.actions:
            raise ValueError("actions must not be empty")
