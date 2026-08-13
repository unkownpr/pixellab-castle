from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from .domain import MilitaryPosture, Position, StructureKind


@dataclass(frozen=True, slots=True)
class WaitAction:
    kind: Literal["wait"] = "wait"


@dataclass(frozen=True, slots=True)
class GatherAction:
    position: Position
    kind: Literal["gather"] = "gather"


@dataclass(frozen=True, slots=True)
class BuildAction:
    structure: StructureKind
    position: Position
    kind: Literal["build"] = "build"


@dataclass(frozen=True, slots=True)
class DiplomacyAction:
    target_colony_id: str
    operation: Literal["contact", "neutral", "alliance", "declare_war"]
    message: str = ""
    kind: Literal["diplomacy"] = "diplomacy"


@dataclass(frozen=True, slots=True)
class TradeOfferAction:
    target_colony_id: str
    give: tuple[tuple[str, int], ...]
    receive: tuple[tuple[str, int], ...]
    message: str = ""
    kind: Literal["trade_offer"] = "trade_offer"


@dataclass(frozen=True, slots=True)
class TradeRespondAction:
    offer_id: str
    accept: bool
    kind: Literal["trade_respond"] = "trade_respond"


@dataclass(frozen=True, slots=True)
class RaidAction:
    target_colony_id: str
    kind: Literal["raid"] = "raid"


@dataclass(frozen=True, slots=True)
class SetPolicyAction:
    policy: str
    value: str
    kind: Literal["set_policy"] = "set_policy"


GameAction: TypeAlias = (
    WaitAction
    | GatherAction
    | BuildAction
    | DiplomacyAction
    | TradeOfferAction
    | TradeRespondAction
    | RaidAction
    | SetPolicyAction
)


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
