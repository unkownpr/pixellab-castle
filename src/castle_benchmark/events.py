from __future__ import annotations

import hashlib
import json

from .domain import MatchState
from .world import WorldState, canonical_world


def canonical_snapshot(state: MatchState) -> dict[str, object]:
    world = state.world
    assert isinstance(world, WorldState)
    return {
        "scenario_id": state.scenario_id,
        "seed": state.seed,
        "turn": state.turn,
        "terminal": state.terminal,
        "termination_reason": state.termination_reason,
        "world": canonical_world(world),
        "colonies": {
            colony_id: {
                "id": colony.id,
                "spawn": {"x": colony.spawn.x, "y": colony.spawn.y},
                "resources": colony.resources.as_dict(),
                "population": colony.population,
                "housing": colony.housing,
                "healthy": colony.healthy,
                "injured": colony.injured,
                "sick": colony.sick,
                "hungry": colony.hungry,
                "relations": {key: value.value for key, value in sorted(colony.relations.items())},
                "policies": dict(sorted(colony.policies.items())),
                "policy_cooldowns": dict(sorted(colony.policy_cooldowns.items())),
                "known_cells": [
                    {"x": position.x, "y": position.y}
                    for position in sorted(colony.known_cells, key=lambda item: (item.y, item.x))
                ],
            }
            for colony_id, colony in sorted(state.colonies.items())
        },
        "structures": {
            structure_id: {
                "id": structure.id,
                "colony_id": structure.colony_id,
                "kind": structure.kind.value,
                "position": {"x": structure.position.x, "y": structure.position.y},
                "status": structure.status.value,
                "progress": structure.progress,
                "required_progress": structure.required_progress,
                "condition": structure.condition,
            }
            for structure_id, structure in sorted(state.structures.items())
        },
        "offers": {
            offer_id: {
                "id": offer.id,
                "source_colony_id": offer.source_colony_id,
                "target_colony_id": offer.target_colony_id,
                "give": list(offer.give),
                "receive": list(offer.receive),
                "expires_turn": offer.expires_turn,
                "status": offer.status,
            }
            for offer_id, offer in sorted(state.offers.items())
        },
    }


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def state_hash(state: MatchState) -> str:
    return hashlib.sha256(canonical_json(canonical_snapshot(state)).encode("utf-8")).hexdigest()

