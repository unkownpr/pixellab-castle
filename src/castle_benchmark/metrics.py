from __future__ import annotations

import math
from dataclasses import dataclass, field

from .actions import VALID_ACTION_KINDS
from .domain import MatchState, StructureKind, StructureStatus
from .engine import TurnResult

# Composite score weights (economic reasoning in comments)
# Design target (AM-19): no single term should exceed others by more than roughly 2x in realistic terminal state.
# Realistic terminal: ~60 from population, ~22 peak, ~20 structures, ~10–20 explored, ~20 resources.
# Population is the foundation: alive colonists enable all work and are direct victory condition.
POPULATION_ALIVE_WEIGHT = 3  # AM-19: reduced from 5x (was 5–10x dominance); 3x balances at ~60
# Peak population records the highest point reached, rewarding growth investment.
PEAK_POPULATION_WEIGHT = 1
# Operational structures are productivity multipliers, but only the ones that make,
# shelter, heal or hold something. The first model to play this benchmark found the hole
# in counting them all: an eight-stone wall took one action and paid the same two points
# as a mine, so it built five of them and said so in its own summary. Defence is scored
# by what it prevents — the raids it survives and the population it keeps — not by
# standing there, so walls, gates, barracks and watchtowers no longer score directly.
OPERATIONAL_STRUCTURES_WEIGHT = 2
SCORING_STRUCTURE_KINDS = frozenset(
    {
        StructureKind.HEADQUARTERS,
        StructureKind.HOUSE,
        StructureKind.WAREHOUSE,
        StructureKind.WELL,
        StructureKind.FARM,
        StructureKind.LUMBER_CAMP,
        StructureKind.QUARRY,
        StructureKind.MINE,
        StructureKind.MARKET,
        StructureKind.WORKSHOP,
        StructureKind.CLINIC,
        StructureKind.MONUMENT,
    }
)
# Exploration scales down by 10 because individual cells have low marginal value; the insight
# is incremental and the known_cells count would dominate the score otherwise.
EXPLORATION_DIVISOR = 10
# Trades and successful raids are outcome metrics: they represent completing plans under pressure.
TRADES_WEIGHT = 2
SUCCESSFUL_RAIDS_WEIGHT = 2
# Resources scale down by 25 (not 10) because uncapped hoarding of wood/stone/ore/tools
# would dominate all other metrics combined, making idle accumulation optimal (AM-11).
# Food and water are excluded: they are consumed, not banked as terminal assets.
RESOURCE_VALUE_DIVISOR = 25
# Resource weights for the value calculation: exclude food/water (consumed), include tools (rarest).
RESOURCE_WEIGHT_WOOD = 2
RESOURCE_WEIGHT_STONE = 2
RESOURCE_WEIGHT_ORE = 3
RESOURCE_WEIGHT_TOOLS = 5
RESOURCE_WEIGHT_INFLUENCE = 1
# Invalid actions and starvation are direct measure of poor play; one-to-one penalty.
INVALID_ACTIONS_PENALTY = -1
STARVATION_TURNS_PENALTY = -1
# Monument victory is worth roughly two thirds of a whole population's survival (AM-19).
MONUMENT_VICTORY_BONUS = 40  # AM-19: raised from 25; makes winning strategic, not accidental


@dataclass(slots=True)
class MetricCollector:
    initial_population: dict[str, int]
    invalid_actions: dict[str, int] = field(default_factory=dict)
    raids: dict[str, int] = field(default_factory=dict)
    trades: dict[str, int] = field(default_factory=dict)
    peak_population: dict[str, int] = field(default_factory=dict)
    min_population: dict[str, int] = field(default_factory=dict)
    timeouts: dict[str, int] = field(default_factory=dict)
    reconnects: dict[str, int] = field(default_factory=dict)
    # Exploration axes
    scouts_dispatched: dict[str, int] = field(default_factory=dict)
    scout_revealed_cells: dict[str, int] = field(default_factory=dict)
    # Labour axes
    idle_producers_sum: dict[str, int] = field(default_factory=dict)
    colonist_turns_sick: dict[str, int] = field(default_factory=dict)
    colonist_turns_injured: dict[str, int] = field(default_factory=dict)
    colonist_turns_scouting: dict[str, int] = field(default_factory=dict)
    # Recovery axes
    structures_repaired: dict[str, int] = field(default_factory=dict)
    structures_extinguished: dict[str, int] = field(default_factory=dict)
    structures_demolished: dict[str, int] = field(default_factory=dict)
    turns_with_damaged_structures: dict[str, int] = field(default_factory=dict)
    # Communication axes
    messages_sent: dict[str, int] = field(default_factory=dict)
    proposals_made: dict[str, int] = field(default_factory=dict)
    proposals_accepted: dict[str, int] = field(default_factory=dict)
    proposals_rejected: dict[str, int] = field(default_factory=dict)
    proposals_expired: dict[str, int] = field(default_factory=dict)
    # Decision quality axes
    starvation_turns: dict[str, int] = field(default_factory=dict)
    store_full_rejections: dict[str, int] = field(default_factory=dict)
    wait_turns: dict[str, int] = field(default_factory=dict)
    opportunity_waits: dict[str, int] = field(default_factory=dict)
    # The state each colony actually decided against: this turn's observation is last
    # turn's result, so judging a wait against the post-resolution state would credit or
    # blame a colony for hands it did not have when it chose.
    decided_against: MatchState | None = None
    action_kinds_used: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def create(cls, state: MatchState) -> MetricCollector:
        populations = {colony_id: colony.population for colony_id, colony in state.colonies.items()}
        return cls(
            populations,
            peak_population=dict(populations),
            min_population=dict(populations),
            action_kinds_used={colony_id: set() for colony_id in populations},
            decided_against=state,
        )

    def record(self, result: TurnResult) -> None:
        submitted: dict[str, list[str]] = {}
        for item in result.action_results:
            colony_id = item.colony_id
            submitted.setdefault(colony_id, []).append(item.action_kind)
            if item.status == "rejected":
                self.invalid_actions[colony_id] = self.invalid_actions.get(colony_id, 0) + 1
                if item.code == "store_full":
                    self.store_full_rejections[colony_id] = self.store_full_rejections.get(colony_id, 0) + 1
            else:
                if colony_id not in self.action_kinds_used:
                    self.action_kinds_used[colony_id] = set()
                self.action_kinds_used[colony_id].add(item.action_kind)
            if item.action_kind == "wait":
                self.wait_turns[colony_id] = self.wait_turns.get(colony_id, 0) + 1

        # A wait is only evidence of passivity when the colony had something to spend it
        # on. Waiting with nobody able to work, or with an empty store, is the only move
        # there is; waiting with hands and materials is a decision, and it is the one
        # thing that separates a careful agent from an idle one.
        for colony_id, kinds in submitted.items():
            source = self.decided_against or result.state
            colony = source.colonies.get(colony_id)
            if colony is None or not kinds or any(kind != "wait" for kind in kinds):
                continue
            if colony.available_population >= 1 and any(colony.resources.as_dict().values()):
                self.opportunity_waits[colony_id] = self.opportunity_waits.get(colony_id, 0) + 1
        self.decided_against = result.state

        for event in result.events:
            if event.colony_id is None:
                continue
            colony_id = event.colony_id
            if event.kind in {"raid", "surprise_raid"}:
                self.raids[colony_id] = self.raids.get(colony_id, 0) + 1
            elif event.kind == "trade_completed":
                # A trade is two colonies agreeing. The event names the one that accepted,
                # so crediting only that side scored the seller at zero no matter how many
                # deals it opened — which is how the scripted trader ended a suite with a
                # trade count of nought.
                self.trades[colony_id] = self.trades.get(colony_id, 0) + 1
                source = str((event.data or {}).get("source_colony_id", ""))
                if source and source != colony_id:
                    self.trades[source] = self.trades.get(source, 0) + 1
            elif event.kind == "scout_dispatched":
                self.scouts_dispatched[colony_id] = self.scouts_dispatched.get(colony_id, 0) + 1
            elif event.kind == "scout_revealed":
                self.scout_revealed_cells[colony_id] = self.scout_revealed_cells.get(colony_id, 0) + 1
            elif event.kind == "repair_completed":
                self.structures_repaired[colony_id] = self.structures_repaired.get(colony_id, 0) + 1
            elif event.kind == "fire_extinguished":
                self.structures_extinguished[colony_id] = self.structures_extinguished.get(colony_id, 0) + 1
            elif event.kind == "structure_demolished":
                self.structures_demolished[colony_id] = self.structures_demolished.get(colony_id, 0) + 1
            elif event.kind == "production":
                # Aggregate idle_producers from production events
                data = event.data or {}
                idle = int(data.get("idle_producers", 0))
                self.idle_producers_sum[colony_id] = self.idle_producers_sum.get(colony_id, 0) + idle
            elif event.kind == "colonist_sickened":
                self.colonist_turns_sick[colony_id] = self.colonist_turns_sick.get(colony_id, 0) + 1
            elif event.kind == "colonist_recovered":
                # We don't double-count; sickened tracks the turns
                pass
            elif event.kind == "starvation":
                self.starvation_turns[colony_id] = self.starvation_turns.get(colony_id, 0) + 1
            elif event.kind == "message_sent":
                self.messages_sent[colony_id] = self.messages_sent.get(colony_id, 0) + 1
            elif event.kind == "proposal_made":
                self.proposals_made[colony_id] = self.proposals_made.get(colony_id, 0) + 1
            elif event.kind == "proposal_accepted":
                # The event carries the answering colony, but a treaty is a thing two
                # colonies did: crediting only the accepter would make a colony that
                # negotiates well look like it never negotiated at all.
                self.proposals_accepted[colony_id] = self.proposals_accepted.get(colony_id, 0) + 1
                source = str((event.data or {}).get("source_colony_id", ""))
                if source:
                    self.proposals_accepted[source] = self.proposals_accepted.get(source, 0) + 1
            elif event.kind == "proposal_rejected":
                self.proposals_rejected[colony_id] = self.proposals_rejected.get(colony_id, 0) + 1
                source = str((event.data or {}).get("source_colony_id", ""))
                if source:
                    self.proposals_rejected[source] = self.proposals_rejected.get(source, 0) + 1
            elif event.kind == "proposal_expired":
                self.proposals_expired[colony_id] = self.proposals_expired.get(colony_id, 0) + 1

        # Track population extrema and health state
        for colony_id, colony in result.state.colonies.items():
            self.peak_population[colony_id] = max(
                self.peak_population.get(colony_id, 0), colony.population
            )
            self.min_population[colony_id] = min(
                self.min_population.get(colony_id, colony.population), colony.population
            )
            # Track colonist-turns in various states
            self.colonist_turns_injured[colony_id] = (
                self.colonist_turns_injured.get(colony_id, 0) + colony.injured
            )
            self.colonist_turns_scouting[colony_id] = (
                self.colonist_turns_scouting.get(colony_id, 0) + colony.scouting
            )

        # Check for structures in damaged/burning/ruined state
        has_damaged = any(
            struct.status in {StructureStatus.DAMAGED, StructureStatus.BURNING, StructureStatus.RUINED}
            for struct in result.state.structures.values()
            if struct.colony_id in result.state.colonies
        )
        if has_damaged:
            for colony_id in result.state.colonies:
                self.turns_with_damaged_structures[colony_id] = (
                    self.turns_with_damaged_structures.get(colony_id, 0) + 1
                )

    def record_timeout(self, colony_id: str) -> None:
        self.timeouts[colony_id] = self.timeouts.get(colony_id, 0) + 1

    def record_reconnect(self, colony_id: str) -> None:
        self.reconnects[colony_id] = self.reconnects.get(colony_id, 0) + 1

    @staticmethod
    def _scoring_structures(state: MatchState, colony_id: str) -> int:
        """Operational structures that count toward the composite (see SCORING_STRUCTURE_KINDS)."""
        return sum(
            1
            for structure in state.structures.values()
            if structure.colony_id == colony_id
            and structure.status == StructureStatus.OPERATIONAL
            and structure.kind in SCORING_STRUCTURE_KINDS
        )

    def _calculate_resource_value(self, resources: object) -> int:
        """Calculate weighted resource value for composite score (AM-11).

        Excludes food and water because they are consumed, not banked as terminal assets.
        Includes only wood, stone, ore, tools, and influence.
        """
        if not hasattr(resources, "as_dict"):
            return 0
        res_dict = resources.as_dict()
        return (
            res_dict.get("wood", 0) * RESOURCE_WEIGHT_WOOD
            + res_dict.get("stone", 0) * RESOURCE_WEIGHT_STONE
            + res_dict.get("ore", 0) * RESOURCE_WEIGHT_ORE
            + res_dict.get("tools", 0) * RESOURCE_WEIGHT_TOOLS
            + res_dict.get("influence", 0) * RESOURCE_WEIGHT_INFLUENCE
        )

    def _calculate_composite(
        self,
        state: MatchState,
        colony_id: str,
    ) -> float:
        """Calculate composite score from terminal state and aggregated counters."""
        colony = state.colonies[colony_id]
        monument_victory = state.termination_reason == "monument_victory"

        operational_structures = self._scoring_structures(state, colony_id)

        # Count explored cells
        known_cells = len(colony.known_cells)

        # Resource value
        resource_value = self._calculate_resource_value(colony.resources)

        # Build composite (all terms are integer; result is integer for ranking stability)
        score = (
            POPULATION_ALIVE_WEIGHT * colony.population
            + PEAK_POPULATION_WEIGHT * self.peak_population.get(colony_id, 0)
            + OPERATIONAL_STRUCTURES_WEIGHT * operational_structures
            + (known_cells // EXPLORATION_DIVISOR)
            + TRADES_WEIGHT * self.trades.get(colony_id, 0)
            + SUCCESSFUL_RAIDS_WEIGHT * self.raids.get(colony_id, 0)
            + (resource_value // RESOURCE_VALUE_DIVISOR)
            + INVALID_ACTIONS_PENALTY * self.invalid_actions.get(colony_id, 0)
            + STARVATION_TURNS_PENALTY * self.starvation_turns.get(colony_id, 0)
            + (MONUMENT_VICTORY_BONUS if monument_victory else 0)
        )
        return int(score)

    def report(self, state: MatchState) -> dict[str, object]:
        colony_ids = sorted(state.colonies)
        colony_count = len(colony_ids)
        total_map_area = state.scenario_id  # This will be used to calculate exploration share

        # Try to get map area from world state
        map_area = 1  # Default fallback
        if hasattr(state, "world") and hasattr(state.world, "width") and hasattr(state.world, "height"):
            map_area = state.world.width * state.world.height

        report: dict[str, object] = {
            "survival": {
                colony_id: {"turns": state.turn, "population": state.colonies[colony_id].population}
                for colony_id in colony_ids
            },
            "growth": {
                colony_id: {
                    "initial_population": self.initial_population[colony_id],
                    "peak_population": self.peak_population[colony_id],
                    "min_population": self.min_population.get(colony_id, self.initial_population[colony_id]),
                    "housing": state.colonies[colony_id].housing,
                }
                for colony_id in colony_ids
            },
            "prosperity": {
                colony_id: {"resources": state.colonies[colony_id].resources.as_dict()}
                for colony_id in colony_ids
            },
            "trade": {colony_id: self.trades.get(colony_id, 0) for colony_id in colony_ids},
            "aggression": {colony_id: self.raids.get(colony_id, 0) for colony_id in colony_ids},
            "exploration": {
                colony_id: {
                    "known_cells": len(state.colonies[colony_id].known_cells),
                    "exploration_share": round(len(state.colonies[colony_id].known_cells) / map_area, 4),
                    "scouts_dispatched": self.scouts_dispatched.get(colony_id, 0),
                    "cells_revealed_by_scouts": self.scout_revealed_cells.get(colony_id, 0),
                }
                for colony_id in colony_ids
            },
            "labour": {
                colony_id: {
                    "idle_producers_sum": self.idle_producers_sum.get(colony_id, 0),
                    "colonist_turns_sick": self.colonist_turns_sick.get(colony_id, 0),
                    "colonist_turns_injured": self.colonist_turns_injured.get(colony_id, 0),
                    "colonist_turns_scouting": self.colonist_turns_scouting.get(colony_id, 0),
                }
                for colony_id in colony_ids
            },
            "recovery": {
                colony_id: {
                    "structures_repaired": self.structures_repaired.get(colony_id, 0),
                    "structures_extinguished": self.structures_extinguished.get(colony_id, 0),
                    "structures_demolished": self.structures_demolished.get(colony_id, 0),
                    "turns_with_damaged_structures": self.turns_with_damaged_structures.get(colony_id, 0),
                    "population_recovery": (
                        state.colonies[colony_id].population
                        - self.min_population.get(colony_id, state.colonies[colony_id].population)
                    ),
                }
                for colony_id in colony_ids
            },
            "communication": {
                colony_id: {
                    "messages_sent": self.messages_sent.get(colony_id, 0),
                    "proposals_made": self.proposals_made.get(colony_id, 0),
                    "proposals_accepted": self.proposals_accepted.get(colony_id, 0),
                    "proposals_rejected": self.proposals_rejected.get(colony_id, 0),
                    "proposals_expired": self.proposals_expired.get(colony_id, 0),
                }
                for colony_id in colony_ids
            },
            "decision_quality": {
                colony_id: {
                    "invalid_actions": self.invalid_actions.get(colony_id, 0),
                    "wait_turns": self.wait_turns.get(colony_id, 0),
                    "opportunity_waits": self.opportunity_waits.get(colony_id, 0),
                    "action_diversity": round(
                        len(self.action_kinds_used.get(colony_id, set())) / len(VALID_ACTION_KINDS),
                        4,
                    ),
                    "starvation_turns": self.starvation_turns.get(colony_id, 0),
                    "store_full_rejections": self.store_full_rejections.get(colony_id, 0),
                }
                for colony_id in colony_ids
            },
            "cost": {
                colony_id: {"model_calls": 0, "mcp_calls": 0, "input_tokens": 0, "output_tokens": 0}
                for colony_id in colony_ids
            },
        }

        # Add composite scores
        composites = {
            colony_id: self._calculate_composite(state, colony_id)
            for colony_id in colony_ids
        }
        report["composites"] = composites

        # Add Pareto front
        report["pareto_front"] = self._calculate_pareto_front(state, colony_ids)

        return report

    def _calculate_pareto_front(self, state: MatchState, colony_ids: list[str]) -> list[str]:
        """Calculate Pareto front based on per-axis values.

        A colony is on the front if it is >= every other colony on all axes and
        strictly > on at least one axis. Return sorted list of colony IDs on front.
        """
        # For simplicity, use a few key axes: population, resources, trades, raids, structures
        def get_point(cid: str) -> tuple[float, ...]:
            colony = state.colonies[cid]
            operational_structures = self._scoring_structures(state, cid)
            resource_value = self._calculate_resource_value(colony.resources)
            return (
                colony.population,
                self.peak_population.get(cid, 0),
                operational_structures,
                len(colony.known_cells),
                self.trades.get(cid, 0),
                self.raids.get(cid, 0),
                resource_value,
            )

        front = []
        for candidate_id in colony_ids:
            candidate_point = get_point(candidate_id)
            is_dominated = False
            for other_id in colony_ids:
                if candidate_id == other_id:
                    continue
                other_point = get_point(other_id)
                # Check if candidate is dominated by other
                if all(other_point[i] >= candidate_point[i] for i in range(len(candidate_point))):
                    if any(other_point[i] > candidate_point[i] for i in range(len(candidate_point))):
                        is_dominated = True
                        break
            if not is_dominated:
                front.append(candidate_id)
        return sorted(front)
