from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol

from .actions import (
    ActionBatch,
    BuildAction,
    DiplomacyAction,
    GatherAction,
    RaidAction,
    ScoutAction,
    TradeOfferAction,
    TradeRespondAction,
    WaitAction,
)
from .domain import Position, StructureKind
from .engine import SCOUT_FOOD_COST
from .observation import Observation
from .scenarios import get_scenario
from .systems import BUILD_COSTS
from .world import derive_seed


class Controller(Protocol):
    name: str

    def decide(self, observation: Observation) -> ActionBatch: ...


def _resource_cell(observation: Observation, preferred: tuple[str, ...]) -> Position | None:
    for resource in preferred:
        cells = [cell for cell in observation.visible_cells if cell["resource"] == resource and cell["resource_amount"]]
        if cells:
            selected = min(cells, key=lambda item: (int(item["y"]), int(item["x"])))
            return Position(int(selected["x"]), int(selected["y"]))
    return None


def _buildable_cell(observation: Observation) -> Position | None:
    occupied = {(int(item["x"]), int(item["y"])) for item in observation.visible_structures}
    candidates = [
        cell
        for cell in observation.visible_cells
        if cell["buildable"] and (int(cell["x"]), int(cell["y"])) not in occupied
    ]
    if not candidates:
        return None
    selected = min(candidates, key=lambda item: (int(item["y"]), int(item["x"])))
    return Position(int(selected["x"]), int(selected["y"]))


def _resources(observation: Observation) -> dict[str, int]:
    resources = observation.colony["resources"]
    assert isinstance(resources, dict)
    return resources


def _kind_counts(observation: Observation) -> dict[str, int]:
    """Count this colony's non-ruined structures by kind; ruins free their slot for a rebuild."""
    counts: dict[str, int] = {}
    for structure in observation.visible_structures:
        if structure["colony_id"] != observation.colony_id or structure["status"] == "ruined":
            continue
        counts[structure["kind"]] = counts.get(structure["kind"], 0) + 1
    return counts


def _can_afford(resources: dict[str, int], kind: StructureKind) -> bool:
    return all(int(resources.get(name, 0)) >= amount for name, amount in BUILD_COSTS[kind].items())


def _incoming_offers(observation: Observation) -> list[dict[str, object]]:
    return [
        offer
        for offer in observation.active_offers
        if offer["target_colony_id"] == observation.colony_id
    ]


def _offer_would_help(
    observation: Observation,
    offer: dict[str, object],
    wanted: frozenset[str],
    reserve: dict[str, int] | None = None,
) -> bool:
    """Whether accepting ``offer`` helps this colony.

    An offer helps only when the colony can pay its side without dipping a reserved
    resource below its floor and at least one of the goods on offer is something it
    actually wants. The ``wanted`` set ranks how willing a baseline is to trade; the
    ``reserve`` floor stops a cautious colony selling the food it needs to survive.
    """
    resources = _resources(observation)
    requested = offer["receive"]
    assert isinstance(requested, dict)
    for name, amount in requested.items():
        available = int(resources.get(name, 0))
        floor = int(reserve.get(name, 0)) if reserve else 0
        if available - int(amount) < floor:
            return False
    give = offer["give"]
    assert isinstance(give, dict)
    return any(name in wanted for name in give)


def _consider_offers(
    observation: Observation,
    wanted: frozenset[str],
    reserve: dict[str, int] | None = None,
) -> ActionBatch | None:
    """Answer the first incoming offer, or ``None`` when there is nothing to answer."""
    offers = _incoming_offers(observation)
    if not offers:
        return None
    offer = offers[0]
    accept = _offer_would_help(observation, offer, wanted, reserve)
    return ActionBatch(
        observation.turn,
        observation.colony_id,
        (TradeRespondAction(str(offer["id"]), accept),),
    )


def _gather_batch(observation: Observation, preferred: tuple[str, ...]) -> ActionBatch:
    position = _resource_cell(observation, preferred)
    if position is None:
        return ActionBatch(observation.turn, observation.colony_id, (WaitAction(),))
    return ActionBatch(observation.turn, observation.colony_id, (GatherAction(position),))


def _build_batch(observation: Observation, kind: StructureKind) -> ActionBatch | None:
    position = _buildable_cell(observation)
    if position is None:
        return None
    return ActionBatch(observation.turn, observation.colony_id, (BuildAction(kind, position),))


def _build_toward(
    observation: Observation,
    resources: dict[str, int],
    order: tuple[StructureKind, ...],
    targets: dict[StructureKind, int],
    preferred: tuple[str, ...],
) -> ActionBatch | None:
    """Build the first kind in ``order`` still below its target count.

    Gathers toward the next build when it is not yet affordable, and returns
    ``None`` once every kind has reached its target.
    """
    counts = _kind_counts(observation)
    for kind in order:
        if counts.get(kind.value, 0) < targets[kind]:
            if _can_afford(resources, kind):
                batch = _build_batch(observation, kind)
                return batch if batch is not None else _gather_batch(observation, preferred)
            return _gather_batch(observation, preferred)
    return None


def _scout_target(observation: Observation) -> Position | None:
    try:
        scenario = get_scenario(observation.scenario_id)
    except KeyError:
        return None
    return Position(scenario.width // 2, scenario.height // 2)


# Trade willingness. Every baseline answers an incoming offer, but what it wants to
# receive and how much of its own stock it will spend differ. The trader is the most
# willing (no reserve, broadest wants), the militarist the least (food and water only,
# and it protects a food floor).
TRADER_WANTED = frozenset({"food", "water", "wood", "stone", "ore", "tools"})
SURVIVALIST_WANTED = frozenset({"food", "water", "wood", "stone"})
EXPANSIONIST_WANTED = frozenset({"food", "water", "wood", "stone", "ore", "tools"})
MILITARIST_WANTED = frozenset({"food", "water"})


SURVIVALIST_ORDER = (
    StructureKind.FARM,
    StructureKind.WELL,
    StructureKind.LUMBER_CAMP,
    StructureKind.HOUSE,
)
SURVIVALIST_TARGETS = {
    StructureKind.FARM: 1,
    StructureKind.WELL: 2,
    StructureKind.LUMBER_CAMP: 1,
    StructureKind.HOUSE: 1,
}


@dataclass(frozen=True, slots=True)
class SurvivalistAgent:
    seed: int = 0
    name: str = "survivalist"

    def decide(self, observation: Observation) -> ActionBatch:
        resources = _resources(observation)
        if int(resources["food"]) < 25:
            return _gather_batch(observation, ("food", "wood", "stone"))
        response = _consider_offers(observation, SURVIVALIST_WANTED, {"food": 50})
        if response is not None:
            return response
        batch = _build_toward(
            observation, resources, SURVIVALIST_ORDER, SURVIVALIST_TARGETS, ("wood", "stone", "food")
        )
        if batch is not None:
            return batch
        return _gather_batch(observation, ("food", "wood", "stone"))


TRADER_ORDER = (
    StructureKind.FARM,
    StructureKind.WELL,
    StructureKind.LUMBER_CAMP,
    StructureKind.MARKET,
    StructureKind.HOUSE,
)
TRADER_TARGETS = {
    StructureKind.FARM: 1,
    StructureKind.WELL: 2,
    StructureKind.LUMBER_CAMP: 1,
    StructureKind.MARKET: 1,
    StructureKind.HOUSE: 1,
}


@dataclass(frozen=True, slots=True)
class TraderAgent:
    seed: int = 0
    name: str = "trader"

    def decide(self, observation: Observation) -> ActionBatch:
        response = _consider_offers(observation, TRADER_WANTED)
        if response is not None:
            return response
        resources = _resources(observation)
        built = _build_toward(
            observation, resources, TRADER_ORDER, TRADER_TARGETS, ("wood", "stone", "food")
        )
        if built is not None:
            return built
        unknown = [item for item in observation.known_colonies.values() if not item["contacted"]]
        if unknown:
            return ActionBatch(
                observation.turn,
                observation.colony_id,
                (DiplomacyAction(str(unknown[0]["id"]), "contact", "Trade brings resilience."),),
            )
        targets = sorted(observation.known_colonies)
        outgoing = [
            offer
            for offer in observation.active_offers
            if offer["source_colony_id"] == observation.colony_id
        ]
        if targets and not outgoing and observation.turn % 6 == 0 and int(resources["wood"]) >= 2:
            return ActionBatch(
                observation.turn,
                observation.colony_id,
                (
                    TradeOfferAction(
                        targets[0],
                        give=(("wood", 2),),
                        receive=(("food", 2),),
                        message="Timber for provisions.",
                    ),
                ),
            )
        return _gather_batch(observation, ("food", "wood", "stone"))


EXPANSIONIST_ORDER = (
    StructureKind.FARM,
    StructureKind.WELL,
    StructureKind.LUMBER_CAMP,
    StructureKind.HOUSE,
    StructureKind.QUARRY,
    StructureKind.MINE,
    StructureKind.WORKSHOP,
)
EXPANSIONIST_TARGETS = {
    StructureKind.FARM: 1,
    StructureKind.WELL: 2,
    StructureKind.LUMBER_CAMP: 1,
    StructureKind.HOUSE: 4,
    StructureKind.QUARRY: 1,
    StructureKind.MINE: 1,
    StructureKind.WORKSHOP: 1,
}


@dataclass(frozen=True, slots=True)
class ExpansionistAgent:
    seed: int = 0
    name: str = "expansionist"

    def decide(self, observation: Observation) -> ActionBatch:
        response = _consider_offers(observation, EXPANSIONIST_WANTED, {"food": 15})
        if response is not None:
            return response
        resources = _resources(observation)
        if (
            observation.turn == 1
            and not observation.scouts
            and int(resources["food"]) >= SCOUT_FOOD_COST
        ):
            target = _scout_target(observation)
            if target is not None:
                return ActionBatch(observation.turn, observation.colony_id, (ScoutAction(target),))
        batch = _build_toward(
            observation, resources, EXPANSIONIST_ORDER, EXPANSIONIST_TARGETS, ("wood", "stone", "food")
        )
        if batch is not None:
            return batch
        return _gather_batch(observation, ("food", "wood", "stone"))


MILITARIST_ORDER = (
    StructureKind.FARM,
    StructureKind.WELL,
    StructureKind.BARRACKS,
    StructureKind.WALL,
    StructureKind.GATE,
    StructureKind.WATCHTOWER,
    StructureKind.CLINIC,
)
MILITARIST_TARGETS = {
    StructureKind.FARM: 1,
    StructureKind.WELL: 2,
    StructureKind.BARRACKS: 1,
    StructureKind.WALL: 1,
    StructureKind.GATE: 1,
    StructureKind.WATCHTOWER: 1,
    StructureKind.CLINIC: 1,
}


@dataclass(frozen=True, slots=True)
class MilitaristAgent:
    seed: int = 0
    name: str = "militarist"

    def decide(self, observation: Observation) -> ActionBatch:
        response = _consider_offers(observation, MILITARIST_WANTED, {"food": 10})
        if response is not None:
            return response
        unknown = [item for item in observation.known_colonies.values() if not item["contacted"]]
        if unknown:
            return ActionBatch(
                observation.turn,
                observation.colony_id,
                (DiplomacyAction(str(unknown[0]["id"]), "contact", "We watch the borders."),),
            )
        targets = sorted(observation.known_colonies)
        at_war = [target for target in targets if observation.known_colonies[target]["relation"] == "war"]
        if targets and not at_war:
            return ActionBatch(
                observation.turn,
                observation.colony_id,
                (DiplomacyAction(targets[0], "declare_war", "The borders are ours."),),
            )
        if at_war and observation.turn % 4 == 0:
            return ActionBatch(observation.turn, observation.colony_id, (RaidAction(at_war[0]),))
        resources = _resources(observation)
        batch = _build_toward(
            observation, resources, MILITARIST_ORDER, MILITARIST_TARGETS, ("wood", "stone", "food")
        )
        if batch is not None:
            return batch
        return _gather_batch(observation, ("food", "wood", "stone"))


@dataclass(frozen=True, slots=True)
class RandomValidAgent:
    seed: int = 0
    name: str = "random_valid"

    def decide(self, observation: Observation) -> ActionBatch:
        rng = random.Random(derive_seed(self.seed, f"{observation.colony_id}:{observation.turn}"))
        position = _resource_cell(observation, ("food", "wood", "stone", "ore"))
        action = GatherAction(position) if position and rng.randrange(2) else WaitAction()
        return ActionBatch(observation.turn, observation.colony_id, (action,))


AGENT_TYPES = {
    "random_valid": RandomValidAgent,
    "survivalist": SurvivalistAgent,
    "trader": TraderAgent,
    "expansionist": ExpansionistAgent,
    "militarist": MilitaristAgent,
}
