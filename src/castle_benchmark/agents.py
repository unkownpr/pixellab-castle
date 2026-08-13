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
    TradeOfferAction,
    TradeRespondAction,
    WaitAction,
)
from .domain import Position, StructureKind
from .observation import Observation
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


@dataclass(frozen=True, slots=True)
class SurvivalistAgent:
    seed: int = 0
    name: str = "survivalist"

    def decide(self, observation: Observation) -> ActionBatch:
        resources = observation.colony["resources"]
        assert isinstance(resources, dict)
        if int(resources["food"]) < 35:
            position = _resource_cell(observation, ("food", "wood", "stone"))
            if position:
                return ActionBatch(observation.turn, observation.colony_id, (GatherAction(position),))
        if observation.turn == 1 and int(resources["wood"]) >= 12 and int(resources["stone"]) >= 4:
            position = _buildable_cell(observation)
            if position:
                return ActionBatch(
                    observation.turn,
                    observation.colony_id,
                    (BuildAction(StructureKind.HOUSE, position),),
                )
        position = _resource_cell(observation, ("food", "wood", "stone", "ore"))
        return ActionBatch(
            observation.turn,
            observation.colony_id,
            (GatherAction(position),) if position else (WaitAction(),),
        )


@dataclass(frozen=True, slots=True)
class TraderAgent:
    seed: int = 0
    name: str = "trader"

    def decide(self, observation: Observation) -> ActionBatch:
        resources = observation.colony["resources"]
        assert isinstance(resources, dict)
        incoming = [
            offer
            for offer in observation.active_offers
            if offer["target_colony_id"] == observation.colony_id
        ]
        if incoming:
            offer = incoming[0]
            requested = offer["receive"]
            assert isinstance(requested, dict)
            affordable = all(int(resources.get(name, 0)) >= int(amount) for name, amount in requested.items())
            return ActionBatch(
                observation.turn,
                observation.colony_id,
                (TradeRespondAction(str(offer["id"]), affordable),),
            )
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
        return SurvivalistAgent(self.seed).decide(observation)


@dataclass(frozen=True, slots=True)
class ExpansionistAgent:
    seed: int = 0
    name: str = "expansionist"

    def decide(self, observation: Observation) -> ActionBatch:
        position = _buildable_cell(observation)
        resources = observation.colony["resources"]
        assert isinstance(resources, dict)
        if position and int(resources["wood"]) >= 12 and int(resources["stone"]) >= 4:
            return ActionBatch(observation.turn, observation.colony_id, (BuildAction(StructureKind.HOUSE, position),))
        return SurvivalistAgent(self.seed).decide(observation)


@dataclass(frozen=True, slots=True)
class MilitaristAgent:
    seed: int = 0
    name: str = "militarist"

    def decide(self, observation: Observation) -> ActionBatch:
        targets = sorted(observation.known_colonies)
        if targets and observation.turn >= 4 and observation.turn % 4 == 0:
            return ActionBatch(observation.turn, observation.colony_id, (RaidAction(targets[0]),))
        return SurvivalistAgent(self.seed).decide(observation)


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
