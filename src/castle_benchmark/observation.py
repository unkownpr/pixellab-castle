from __future__ import annotations

from dataclasses import dataclass

from .actions import VALID_ACTION_KINDS
from .domain import MatchState
from .world import WorldState


SPECTATOR_COLONY_ID = "spectator"


@dataclass(frozen=True, slots=True)
class Observation:
    schema_version: str
    scenario_id: str
    turn: int
    colony_id: str
    colony: dict[str, object]
    visible_cells: tuple[dict[str, object], ...]
    visible_structures: tuple[dict[str, object], ...]
    scouts: tuple[dict[str, object], ...]
    known_colonies: dict[str, dict[str, object]]
    active_offers: tuple[dict[str, object], ...]
    inbox: tuple[dict[str, object], ...]
    open_proposals: tuple[dict[str, object], ...]
    valid_action_kinds: tuple[str, ...]


def project_observation(state: MatchState, colony_id: str) -> Observation:
    if colony_id not in state.colonies:
        raise KeyError(f"unknown colony: {colony_id}")
    colony = state.colonies[colony_id]
    world = state.world
    assert isinstance(world, WorldState)
    cells = tuple(
        {
            "x": position.x,
            "y": position.y,
            "biome": cell.biome,
            "water": cell.water,
            "buildable": cell.buildable,
            "movement_cost": cell.movement_cost,
            "resource": cell.resource,
            "resource_amount": cell.resource_amount if position in colony.visible_now else 0,
        }
        for position in sorted(colony.known_cells, key=lambda item: (item.y, item.x))
        if (cell := world.cells.get(position)) is not None
    )
    structures = tuple(
        {
            "id": structure.id,
            "colony_id": structure.colony_id,
            "kind": structure.kind.value,
            "status": structure.status.value,
            "progress": structure.progress,
            "required_progress": structure.required_progress,
            "condition": structure.condition,
            "x": structure.position.x,
            "y": structure.position.y,
        }
        for structure in sorted(state.structures.values(), key=lambda item: item.id)
        if structure.position in colony.known_cells
    )
    scouts = tuple(
        {
            "id": scout.id,
            "colony_id": scout.colony_id,
            "x": scout.position.x,
            "y": scout.position.y,
            "target_x": scout.target.x,
            "target_y": scout.target.y,
        }
        for scout in sorted(state.scouts.values(), key=lambda item: item.id)
        if scout.colony_id == colony_id or scout.position in colony.visible_now
    )
    known_colonies = {
        other_id: {
            "id": other_id,
            "relation": colony.relations[other_id].value,
            "contacted": colony.relations[other_id].value != "unknown",
        }
        for other_id in sorted(colony.relations)
    }
    offers = tuple(
        {
            "id": offer.id,
            "source_colony_id": offer.source_colony_id,
            "target_colony_id": offer.target_colony_id,
            "give": dict(offer.give),
            "receive": dict(offer.receive),
            "expires_turn": offer.expires_turn,
        }
        for offer in sorted(state.offers.values(), key=lambda item: item.id)
        if offer.status == "open" and colony_id in {offer.source_colony_id, offer.target_colony_id}
    )
    messages = tuple(
        {
            "turn": msg.turn,
            "from_colony_id": msg.from_colony_id,
            "channel": msg.channel,
            "text": msg.text,
        }
        for msg in state.inboxes.get(colony_id, ())
    )
    proposals = tuple(
        {
            "id": proposal.id,
            "source_colony_id": proposal.source_colony_id,
            "target_colony_id": proposal.target_colony_id,
            "operation": proposal.operation,
            "message": proposal.message,
            "expires_turn": proposal.expires_turn,
            "status": proposal.status,
        }
        for proposal in sorted(state.proposals.values(), key=lambda item: item.id)
        if proposal.status == "open" and colony_id in {proposal.source_colony_id, proposal.target_colony_id}
    )
    return Observation(
        schema_version="1.0",
        scenario_id=state.scenario_id,
        turn=state.turn,
        colony_id=colony_id,
        colony={
            "id": colony.id,
            "population": colony.population,
            "housing": colony.housing,
            "health": {
                "healthy": colony.healthy,
                "injured": colony.injured,
                "sick": colony.sick,
                "hungry": colony.hungry,
            },
            "resources": colony.resources.as_dict(),
            "policies": dict(sorted(colony.policies.items())),
        },
        visible_cells=cells,
        visible_structures=structures,
        scouts=scouts,
        known_colonies=known_colonies,
        active_offers=offers,
        inbox=messages,
        open_proposals=proposals,
        valid_action_kinds=VALID_ACTION_KINDS,
    )


def project_spectator_view(state: MatchState) -> dict[str, object]:
    """Project the whole authoritative world with no fog of war.

    This is deliberately separate from ``project_observation``: the fog of war is
    the benchmark's central fairness property, so a fog-free projection must never
    be reachable from the controller-facing observation path. It exists only for
    the operator (admin) view and is gated by ``GameService.spectator_view``.
    """
    world = state.world
    assert isinstance(world, WorldState)
    cells = tuple(
        {
            "x": position.x,
            "y": position.y,
            "biome": cell.biome,
            "water": cell.water,
            "buildable": cell.buildable,
            "movement_cost": cell.movement_cost,
            "resource": cell.resource,
            "resource_amount": cell.resource_amount,
        }
        for position in sorted(world.cells, key=lambda item: (item.y, item.x))
        if (cell := world.cells.get(position)) is not None
    )
    structures = tuple(
        {
            "id": structure.id,
            "colony_id": structure.colony_id,
            "kind": structure.kind.value,
            "status": structure.status.value,
            "progress": structure.progress,
            "required_progress": structure.required_progress,
            "condition": structure.condition,
            "x": structure.position.x,
            "y": structure.position.y,
        }
        for structure in sorted(state.structures.values(), key=lambda item: item.id)
    )
    scouts = tuple(
        {
            "id": scout.id,
            "colony_id": scout.colony_id,
            "x": scout.position.x,
            "y": scout.position.y,
            "target_x": scout.target.x,
            "target_y": scout.target.y,
        }
        for scout in sorted(state.scouts.values(), key=lambda item: item.id)
    )
    colonies = {
        colony_id: {
            "id": colony.id,
            "population": colony.population,
            "housing": colony.housing,
            "healthy": colony.healthy,
            "injured": colony.injured,
            "sick": colony.sick,
            "hungry": colony.hungry,
            "resources": colony.resources.as_dict(),
        }
        for colony_id, colony in sorted(state.colonies.items())
    }
    offers = tuple(
        {
            "id": offer.id,
            "source_colony_id": offer.source_colony_id,
            "target_colony_id": offer.target_colony_id,
            "give": dict(offer.give),
            "receive": dict(offer.receive),
            "expires_turn": offer.expires_turn,
        }
        for offer in sorted(state.offers.values(), key=lambda item: item.id)
    )
    return {
        "scenario_id": state.scenario_id,
        "turn": state.turn,
        "colony_id": SPECTATOR_COLONY_ID,
        "colonies": colonies,
        "visible_cells": cells,
        "visible_structures": structures,
        "scouts": scouts,
        "active_offers": offers,
        "valid_action_kinds": (),
    }
