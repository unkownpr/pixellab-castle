from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from enum import StrEnum
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


class StructureKind(StrEnum):
    HEADQUARTERS = "headquarters"
    HOUSE = "house"
    WAREHOUSE = "warehouse"
    WELL = "well"
    FARM = "farm"
    LUMBER_CAMP = "lumber_camp"
    QUARRY = "quarry"
    MINE = "mine"
    MARKET = "market"
    WORKSHOP = "workshop"
    CLINIC = "clinic"
    BARRACKS = "barracks"
    WATCHTOWER = "watchtower"
    WALL = "wall"
    GATE = "gate"
    MONUMENT = "monument"


class StructureStatus(StrEnum):
    PLANNED = "planned"
    FOUNDATION = "foundation"
    BUILDING = "building"
    OPERATIONAL = "operational"
    DAMAGED = "damaged"
    BURNING = "burning"
    RUINED = "ruined"
    REPAIRING = "repairing"


class RelationStatus(StrEnum):
    UNKNOWN = "unknown"
    CONTACTED = "contacted"
    NEUTRAL = "neutral"
    TRADE = "trade_agreement"
    ALLIANCE = "alliance"
    WAR = "war"


class MilitaryPosture(StrEnum):
    PEACEFUL = "peaceful"
    DEFENSIVE = "defensive"
    EXPANSIONIST = "expansionist"


@dataclass(frozen=True, slots=True)
class Structure:
    id: str
    colony_id: str
    kind: StructureKind
    position: Position
    status: StructureStatus
    progress: int
    required_progress: int
    condition: int = 100


@dataclass(frozen=True, slots=True)
class ColonyState:
    id: str
    spawn: Position
    resources: ResourceStock
    population: int = 8
    housing: int = 8
    healthy: int = 8
    injured: int = 0
    sick: int = 0
    hungry: int = 0
    relations: dict[str, RelationStatus] = field(default_factory=dict)
    policies: dict[str, str] = field(default_factory=dict)
    policy_cooldowns: dict[str, int] = field(default_factory=dict)
    known_cells: frozenset[Position] = field(default_factory=frozenset)
    visible_now: frozenset[Position] = field(default_factory=frozenset)
    scouting: int = 0

    @property
    def available_population(self) -> int:
        """Members currently at home, well, and able to gather or produce.

        Colonists away scouting, laid up sick, and those recovering from injuries are
        all unavailable. Injured colonists count as unavailable until healed, making
        damage from raids and fire a meaningful cost: every injury reduces production
        and gathering capacity directly.
        """
        return max(0, self.population - self.scouting - self.sick - self.injured)


@dataclass(frozen=True, slots=True)
class Scout:
    id: str
    colony_id: str
    position: Position
    target: Position


@dataclass(frozen=True, slots=True)
class Message:
    """A message delivered to a colony's inbox.

    Channel identifies the context: diplomacy messages accompany proposals,
    trade messages accompany offers, direct messages are standalone,
    treaty messages accompany treaty events.
    """
    turn: int
    from_colony_id: str
    channel: str  # diplomacy, trade, direct, treaty
    text: str


@dataclass(frozen=True, slots=True)
class DiplomacyProposal:
    """A proposal for alliance or peace, requiring consent to change relations.

    Proposals expire after four turns and are answered by DiplomacyRespondAction.
    Relations change only on acceptance.
    """
    id: str
    source_colony_id: str
    target_colony_id: str
    operation: str  # alliance, peace
    message: str
    expires_turn: int
    status: str = "open"  # open, accepted, rejected


@dataclass(frozen=True, slots=True)
class TradeOffer:
    id: str
    source_colony_id: str
    target_colony_id: str
    give: tuple[tuple[str, int], ...]
    receive: tuple[tuple[str, int], ...]
    expires_turn: int
    status: str = "open"


@dataclass(frozen=True, slots=True)
class MatchState:
    scenario_id: str
    seed: int
    turn: int
    world: object
    colonies: dict[str, ColonyState]
    structures: dict[str, Structure]
    offers: dict[str, TradeOffer] = field(default_factory=dict)
    scouts: dict[str, Scout] = field(default_factory=dict)
    proposals: dict[str, DiplomacyProposal] = field(default_factory=dict)
    inboxes: dict[str, tuple[Message, ...]] = field(default_factory=dict)
    terminal: bool = False
    termination_reason: str | None = None
