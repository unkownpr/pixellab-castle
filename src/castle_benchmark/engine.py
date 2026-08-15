from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Mapping

from .actions import (
    ActionBatch,
    BuildAction,
    DemolishAction,
    DiplomacyAction,
    DiplomacyRespondAction,
    ExtinguishAction,
    GameAction,
    GatherAction,
    MessageAction,
    RaidAction,
    RepairAction,
    ScoutAction,
    SetPolicyAction,
    TradeOfferAction,
    TradeRespondAction,
    WaitAction,
)
from .domain import (
    ColonyState,
    DiplomacyProposal,
    MatchState,
    Message,
    MilitaryPosture,
    Position,
    RelationStatus,
    ResourceStock,
    Scout,
    Structure,
    StructureKind,
    StructureStatus,
    TradeOffer,
)
from .scenarios import Scenario
from .systems import (
    ALLIANCE_UPKEEP_INFLUENCE,
    BARRACKS_RAID_LOOT_REDUCTION,
    BUILD_COSTS,
    BUILD_TURNS,
    CLINIC_HEALS_PER_TURN,
    EXPOSED_SICKENED_PER_TURN,
    EXTINGUISH_WATER_COST,
    EXTINGUISH_WATER_COST_WITH_WELL,
    FIRE_IGNITION_CADENCE_BONUS,
    GATHER_RADIUS,
    HOUSING_BY_STRUCTURE,
    MIN_ABLE_COLONISTS,
    NATURAL_RECOVERY_PER_TURN,
    PERISHABLES,
    RAID_FOOD_LOOT,
    RAID_INFLUENCE_COST_SURPRISE,
    RAID_INJURIES_FAILURE_ATTACKER,
    RAID_INJURIES_FAILURE_DEFENDER,
    RAID_INJURIES_SUCCESS_ATTACKER,
    RAID_INJURIES_SUCCESS_DEFENDER,
    RAID_PARTY_FOOD,
    RAID_PARTY_SIZE,
    RAID_STRUCTURE_DAMAGE,
    RAID_WOOD_LOOT,
    REPAIR_COST_DENOMINATOR,
    REPAIR_COST_NUMERATOR,
    REPAIR_TURNS,
    SICKENED_PER_SHORTFALL_TURN,
    TRADE_RATIO_BASE,
    TRADE_RATIO_MARKET,
    TREATY_BREAK_INFLUENCE,
    WALL_RAID_DAMAGE_REDUCTION,
    can_afford,
    cap_production_delta,
    has_operational,
    perishable_capacity,
    production_delta,
    repair_cost,
    resource_delta,
    scaled_receipt,
    staffed_production,
    store_overflow,
    trade_blocked,
    within_capacity,
)
from .world import WorldCell, WorldState, derive_seed, generate_world, rotated_spawns, visible_cells


# Exploration and sight constants. Kept as named module-level values so the
# scouting trade-off and watchtower benefit stay tunable without touching the
# resolution logic.
SCOUT_SPEED = 3  # cells a scout advances toward its target each turn
SCOUT_REVEAL_RADIUS = 2  # radius around the scout revealed as it travels
SCOUT_FOOD_COST = 12  # provisioning charged when a scout is dispatched
WATCHTOWER_SIGHT_BONUS = 2  # added to active sight radius per operational watchtower

# Labour economy constants. A scout occupies one colonist for its whole journey, so
# available_population (population minus colonists out scouting) is the real cost of
# exploration: every hand sent scouting is a hand that cannot gather, cannot work a
# producing structure, and cannot carry an action that turn. These encode how scarce
# that labour is.
GATHER_YIELD_PER_ACTION = 4  # units one gather action collects at full strength
WORKERS_PER_PRODUCER = 1  # colonists needed to staff one producing structure a turn

# Gathering a resource the colony has no extraction structure for collects at half
# strength. The mapping ties each extractable resource to the OPERATIONAL structure
# that restores full yield; food, water and anything else without an entry keep
# their present yield. GATHER_PENALTY_DIVISOR is the halving factor: the
# labour-scaled yield is divided by it (see ``_gather``) whenever the matching
# structure is not OPERATIONAL.
GATHER_EXTRACTION_STRUCTURES: dict[str, StructureKind] = {
    "wood": StructureKind.LUMBER_CAMP,
    "stone": StructureKind.QUARRY,
    "ore": StructureKind.MINE,
}
GATHER_PENALTY_DIVISOR = 2

# Hazard constants. Fire consumes a fixed amount of structure condition each turn a
# structure keeps burning; a structure reduced to zero condition becomes a ruin.
FIRE_DAMAGE_PER_TURN = 40


@dataclass(frozen=True, slots=True)
class DomainEvent:
    turn: int
    kind: str
    colony_id: str | None = None
    data: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if self.data is None:
            object.__setattr__(self, "data", {})


@dataclass(frozen=True, slots=True)
class ActionResult:
    colony_id: str
    action_kind: str
    status: str
    code: str


@dataclass(frozen=True, slots=True)
class TurnResult:
    state: MatchState
    events: tuple[DomainEvent, ...]
    action_results: tuple[ActionResult, ...]


class SimCore:
    ACTION_BUDGET = 2
    RESOLUTION_ORDER = (
        "policies",
        "reservations",
        "movement",
        "work",
        "construction",
        "production",
        "needs",
        "trade",
        "combat",
        "hazards",
        "visibility",
        "immigration",
        "terminal",
    )

    def __init__(self, scenario: Scenario, state: MatchState):
        self.scenario = scenario
        self.state = state
        self._next_structure = len(state.structures) + 1
        self._next_offer = 1
        self._next_scout = len(state.scouts) + 1

    @classmethod
    def create(cls, scenario: Scenario, seed: int, colony_count: int, rotation: int = 0) -> SimCore:
        world = generate_world(scenario, seed)
        spawns = rotated_spawns(scenario, rotation=rotation, colony_count=colony_count)
        colonies: dict[str, ColonyState] = {}
        structures: dict[str, Structure] = {}
        ids = tuple(f"c{index + 1}" for index in range(colony_count))
        for index, (colony_id, spawn) in enumerate(zip(ids, spawns, strict=True), start=1):
            relations = {other: RelationStatus.UNKNOWN for other in ids if other != colony_id}
            initial_sight = visible_cells(world, (spawn,), scenario.sight_radius)
            colonies[colony_id] = ColonyState(
                id=colony_id,
                spawn=spawn,
                resources=ResourceStock(
                    food=60, water=60, wood=50, stone=35, ore=10, tools=6, influence=20
                ),
                relations=relations,
                policies={"rationing": "normal"},
                known_cells=initial_sight,
                visible_now=initial_sight,
            )
            structure_id = f"s{index}"
            structures[structure_id] = Structure(
                id=structure_id,
                colony_id=colony_id,
                kind=StructureKind.HEADQUARTERS,
                position=spawn,
                status=StructureStatus.OPERATIONAL,
                progress=1,
                required_progress=1,
            )
        return cls(
            scenario,
            MatchState(
                scenario_id=scenario.id,
                seed=seed,
                turn=0,
                world=world,
                colonies=colonies,
                structures=structures,
            ),
        )

    def resolve(self, batches: Iterable[ActionBatch]) -> TurnResult:
        if self.state.terminal:
            raise RuntimeError("match is already terminal")
        events: list[DomainEvent] = []
        results: list[ActionResult] = []
        provided: dict[str, ActionBatch] = {}
        for batch in batches:
            if batch.colony_id not in self.state.colonies:
                results.append(ActionResult(batch.colony_id, "batch", "rejected", "unknown_colony"))
                continue
            if batch.turn != self.state.turn:
                results.append(ActionResult(batch.colony_id, "batch", "rejected", "stale_turn"))
                continue
            if batch.colony_id in provided:
                results.append(ActionResult(batch.colony_id, "batch", "rejected", "duplicate_batch"))
                continue
            provided[batch.colony_id] = batch

        # Determine resolution order for this turn: sorted colony IDs, rotated by a
        # per-turn pseudo-random rotation. This ensures fair initiative distribution
        # across multiple turns while remaining deterministic.
        sorted_ids = sorted(self.state.colonies.keys())
        order_seed = derive_seed(self.state.seed, f"order:{self.state.turn}")
        rotation = order_seed % len(sorted_ids) if sorted_ids else 0
        resolution_order = sorted_ids[rotation:] + sorted_ids[:rotation]

        for colony_id in resolution_order:
            batch = provided.get(colony_id)
            if batch is None:
                events.append(DomainEvent(self.state.turn, "controller_wait", colony_id))
                continue
            # Scouting eats into the turn's work budget: colonists away travelling
            # cannot carry an action. The ceiling itself is unchanged.
            budget = min(
                self.ACTION_BUDGET,
                self.state.colonies[colony_id].available_population,
            )
            for index, action in enumerate(batch.actions):
                if index >= budget:
                    results.append(
                        ActionResult(
                            colony_id,
                            action.kind,
                            "rejected",
                            "action_budget_exceeded",
                        )
                    )
                    continue
                result = self._apply_action(colony_id, action, events)
                results.append(result)

        self._progress_construction(events)
        self._apply_production(events)
        self._expire_offers(events)
        self._advance_scouts(events)
        self._apply_needs(events)
        self._apply_hazards(events)
        self._refresh_colonies()

        next_turn = self.state.turn + 1
        terminal = next_turn >= self.scenario.max_turns or not any(
            colony.population > 0 for colony in self.state.colonies.values()
        )
        reason = None
        if terminal:
            reason = "turn_limit" if next_turn >= self.scenario.max_turns else "extinction"
            events.append(DomainEvent(self.state.turn, "match_ended", data={"reason": reason}))
        self.state = replace(
            self.state,
            turn=next_turn,
            terminal=terminal,
            termination_reason=reason,
        )
        return TurnResult(self.state, tuple(events), tuple(results))

    def _apply_action(
        self, colony_id: str, action: GameAction, events: list[DomainEvent]
    ) -> ActionResult:
        if isinstance(action, WaitAction):
            events.append(DomainEvent(self.state.turn, "controller_wait", colony_id))
            return ActionResult(colony_id, action.kind, "accepted", "ok")
        if isinstance(action, GatherAction):
            return self._gather(colony_id, action, events)
        if isinstance(action, BuildAction):
            return self._build(colony_id, action, events)
        if isinstance(action, DiplomacyAction):
            return self._diplomacy(colony_id, action, events)
        if isinstance(action, TradeOfferAction):
            return self._offer(colony_id, action, events)
        if isinstance(action, TradeRespondAction):
            return self._respond(colony_id, action, events)
        if isinstance(action, RaidAction):
            return self._raid(colony_id, action, events)
        if isinstance(action, SetPolicyAction):
            return self._set_policy(colony_id, action, events)
        if isinstance(action, ScoutAction):
            return self._scout(colony_id, action, events)
        if isinstance(action, RepairAction):
            return self._repair(colony_id, action, events)
        if isinstance(action, ExtinguishAction):
            return self._extinguish(colony_id, action, events)
        if isinstance(action, DemolishAction):
            return self._demolish(colony_id, action, events)
        return ActionResult(colony_id, "unknown", "rejected", "unknown_action")

    def _update_colony(self, colony_id: str, **changes: object) -> None:
        colonies = dict(self.state.colonies)
        colonies[colony_id] = replace(colonies[colony_id], **changes)
        self.state = replace(self.state, colonies=colonies)

    def _gather(self, colony_id: str, action: GatherAction, events: list[DomainEvent]) -> ActionResult:
        colony = self.state.colonies[colony_id]
        if action.position not in colony.known_cells:
            return ActionResult(colony_id, action.kind, "rejected", "cell_not_visible")
        # Check if target is within GATHER_RADIUS of an OPERATIONAL structure (Manhattan distance)
        operational_structures = [
            structure
            for structure in self.state.structures.values()
            if structure.colony_id == colony_id and structure.status == StructureStatus.OPERATIONAL
        ]
        within_radius = any(
            abs(action.position.x - structure.position.x) + abs(action.position.y - structure.position.y) <= GATHER_RADIUS
            for structure in operational_structures
        )
        if not within_radius:
            return ActionResult(colony_id, action.kind, "rejected", "out_of_range")
        world = self.state.world
        assert isinstance(world, WorldState)
        cell = world.cells.get(action.position)
        if cell is None or cell.resource is None or cell.resource_amount <= 0:
            return ActionResult(colony_id, action.kind, "rejected", "no_resource")
        # Yield scales with the share of the colony still at home, so sending people
        # scouting costs production from the first colonist onward rather than only
        # once the colony is nearly wiped out.
        if colony.population <= 0:
            return ActionResult(colony_id, action.kind, "rejected", "no_population")
        staffed_yield = (
            GATHER_YIELD_PER_ACTION * colony.available_population // colony.population
        )
        # Labour scaling comes first: the share of colonists at home scales the base
        # yield, then the missing extraction structure halves what is left. Halving
        # after scaling keeps a colony short-handed AND without a camp strictly worse
        # off than one with only one of those problems, and flooring at one stops a
        # positive gather from rounding away to nothing.
        if (
            staffed_yield > 0
            and cell.resource in GATHER_EXTRACTION_STRUCTURES
            and not has_operational(
                self.state.structures,
                colony_id,
                GATHER_EXTRACTION_STRUCTURES[cell.resource],
            )
        ):
            staffed_yield = max(1, staffed_yield // GATHER_PENALTY_DIVISOR)
        amount = min(staffed_yield, cell.resource_amount)
        if amount <= 0:
            return ActionResult(colony_id, action.kind, "rejected", "no_available_population")
        if cell.resource in PERISHABLES:
            capacity = perishable_capacity(self.state.structures, colony_id)
            if store_overflow(colony.resources, {cell.resource: amount}, capacity):
                return ActionResult(colony_id, action.kind, "rejected", "store_full")
        try:
            stock = colony.resources.apply({cell.resource: amount})
        except KeyError:
            return ActionResult(colony_id, action.kind, "rejected", "unknown_resource")
        cells = dict(world.cells)
        cells[action.position] = replace(cell, resource_amount=cell.resource_amount - amount)
        self.state = replace(self.state, world=replace(world, cells=cells))
        self._update_colony(colony_id, resources=stock)
        events.append(
            DomainEvent(
                self.state.turn,
                "resource_gathered",
                colony_id,
                {"resource": cell.resource, "amount": amount, "x": action.position.x, "y": action.position.y},
            )
        )
        return ActionResult(colony_id, action.kind, "accepted", "ok")

    def _build(self, colony_id: str, action: BuildAction, events: list[DomainEvent]) -> ActionResult:
        colony = self.state.colonies[colony_id]
        if action.position not in colony.known_cells:
            return ActionResult(colony_id, action.kind, "rejected", "cell_not_visible")
        world = self.state.world
        assert isinstance(world, WorldState)
        cell = world.cells.get(action.position)
        occupied = {structure.position for structure in self.state.structures.values() if structure.status != StructureStatus.RUINED}
        if cell is None or not cell.buildable:
            return ActionResult(colony_id, action.kind, "rejected", "cell_not_buildable")
        if action.position in occupied:
            return ActionResult(colony_id, action.kind, "rejected", "cell_occupied")
        cost = BUILD_COSTS.get(action.structure)
        if cost is None:
            return ActionResult(colony_id, action.kind, "rejected", "structure_not_buildable")
        if not can_afford(colony.resources, cost):
            return ActionResult(colony_id, action.kind, "rejected", "insufficient_resources")
        stock = colony.resources.apply({name: -amount for name, amount in cost.items()})
        self._update_colony(colony_id, resources=stock)
        structure_id = f"s{self._next_structure}"
        self._next_structure += 1
        structure = Structure(
            id=structure_id,
            colony_id=colony_id,
            kind=action.structure,
            position=action.position,
            status=StructureStatus.FOUNDATION,
            progress=0,
            required_progress=BUILD_TURNS[action.structure],
        )
        structures = {
            structure_id: existing
            for structure_id, existing in self.state.structures.items()
            if not (
                existing.position == action.position
                and existing.status == StructureStatus.RUINED
            )
        }
        structures[structure_id] = structure
        self.state = replace(self.state, structures=structures)
        events.append(
            DomainEvent(
                self.state.turn,
                "construction_started",
                colony_id,
                {"structure_id": structure_id, "kind": action.structure.value, "x": action.position.x, "y": action.position.y},
            )
        )
        return ActionResult(colony_id, action.kind, "accepted", "ok")

    def _diplomacy(
        self, colony_id: str, action: DiplomacyAction, events: list[DomainEvent]
    ) -> ActionResult:
        if action.target_colony_id not in self.state.colonies or action.target_colony_id == colony_id:
            return ActionResult(colony_id, action.kind, "rejected", "invalid_target")
        transitions = {
            "contact": RelationStatus.CONTACTED,
            "neutral": RelationStatus.NEUTRAL,
            "alliance": RelationStatus.ALLIANCE,
            "declare_war": RelationStatus.WAR,
        }
        relation = transitions[action.operation]
        for source, target in ((colony_id, action.target_colony_id), (action.target_colony_id, colony_id)):
            relations = dict(self.state.colonies[source].relations)
            relations[target] = relation
            self._update_colony(source, relations=relations)
        events.append(
            DomainEvent(
                self.state.turn,
                "diplomacy_changed",
                colony_id,
                {"target": action.target_colony_id, "relation": relation.value, "message": action.message},
            )
        )
        return ActionResult(colony_id, action.kind, "accepted", "ok")

    def _offer(self, colony_id: str, action: TradeOfferAction, events: list[DomainEvent]) -> ActionResult:
        if action.target_colony_id not in self.state.colonies or action.target_colony_id == colony_id:
            return ActionResult(colony_id, action.kind, "rejected", "invalid_target")
        if trade_blocked(self.state.structures, colony_id):
            return ActionResult(colony_id, action.kind, "rejected", "walled")
        try:
            give_delta = resource_delta(action.give, sign=-1)
            resource_delta(action.receive)
            reserved = self.state.colonies[colony_id].resources.apply(give_delta)
        except (ValueError, KeyError):
            return ActionResult(colony_id, action.kind, "rejected", "invalid_trade")
        self._update_colony(colony_id, resources=reserved)
        offer_id = f"o{self._next_offer}"
        self._next_offer += 1
        offer = TradeOffer(
            id=offer_id,
            source_colony_id=colony_id,
            target_colony_id=action.target_colony_id,
            give=action.give,
            receive=action.receive,
            expires_turn=self.state.turn + 4,
        )
        offers = dict(self.state.offers)
        offers[offer_id] = offer
        self.state = replace(self.state, offers=offers)
        events.append(
            DomainEvent(self.state.turn, "trade_offered", colony_id, {"offer_id": offer_id, "target": action.target_colony_id, "message": action.message})
        )
        return ActionResult(colony_id, action.kind, "accepted", "ok")

    def _respond(
        self, colony_id: str, action: TradeRespondAction, events: list[DomainEvent]
    ) -> ActionResult:
        offer = self.state.offers.get(action.offer_id)
        if offer is None or offer.status != "open" or offer.target_colony_id != colony_id:
            return ActionResult(colony_id, action.kind, "rejected", "offer_unavailable")
        source = self.state.colonies[offer.source_colony_id]
        target = self.state.colonies[colony_id]
        if action.accept and trade_blocked(self.state.structures, colony_id):
            return ActionResult(colony_id, action.kind, "rejected", "walled")
        offers = dict(self.state.offers)
        if not action.accept:
            self._update_colony(
                offer.source_colony_id,
                resources=source.resources.apply(resource_delta(offer.give)),
            )
            offers[action.offer_id] = replace(offer, status="rejected")
            self.state = replace(self.state, offers=offers)
            events.append(DomainEvent(self.state.turn, "trade_rejected", colony_id, {"offer_id": offer.id}))
            return ActionResult(colony_id, action.kind, "accepted", "ok")
        try:
            source_ratio = (
                TRADE_RATIO_MARKET
                if has_operational(self.state.structures, offer.source_colony_id, StructureKind.MARKET)
                else TRADE_RATIO_BASE
            )
            target_ratio = (
                TRADE_RATIO_MARKET
                if has_operational(self.state.structures, colony_id, StructureKind.MARKET)
                else TRADE_RATIO_BASE
            )
            target_after_payment = target.resources.apply(resource_delta(offer.receive, sign=-1))
            source_after_receipt = source.resources.apply(scaled_receipt(offer.receive, source_ratio))
            target_after_trade = target_after_payment.apply(scaled_receipt(offer.give, target_ratio))
        except (ValueError, KeyError):
            return ActionResult(colony_id, action.kind, "rejected", "insufficient_resources")
        if not within_capacity(
            source_after_receipt,
            perishable_capacity(self.state.structures, offer.source_colony_id),
        ) or not within_capacity(
            target_after_trade,
            perishable_capacity(self.state.structures, colony_id),
        ):
            return ActionResult(colony_id, action.kind, "rejected", "store_full")
        self._update_colony(offer.source_colony_id, resources=source_after_receipt)
        self._update_colony(colony_id, resources=target_after_trade)
        offers = dict(self.state.offers)
        offers[action.offer_id] = replace(offer, status="accepted")
        self.state = replace(self.state, offers=offers)
        events.append(DomainEvent(self.state.turn, "trade_completed", colony_id, {"offer_id": offer.id}))
        return ActionResult(colony_id, action.kind, "accepted", "ok")

    def _raid(self, colony_id: str, action: RaidAction, events: list[DomainEvent]) -> ActionResult:
        """Execute a raid according to A8 combat mechanics (AM-5, AM-16).

        Attacker and defender each have a power calculated from healthy colonists,
        barracks, and posture bonuses. On success (attacker_power > defender_power),
        the attacker loots resources and takes no casualties; the defender loses
        resources and 2 injured. On failure, both take casualties and no resources
        change. Structure damage targets non-HQ structures when other structures exist.
        Injuries are clamped to available healthy population (AM-4). Peaceful posture
        blocks raiding entirely. Surprise raids (non-WAR targets) cost influence.
        """
        if action.target_colony_id not in self.state.colonies or action.target_colony_id == colony_id:
            return ActionResult(colony_id, action.kind, "rejected", "invalid_target")
        attacker = self.state.colonies[colony_id]
        defender = self.state.colonies[action.target_colony_id]

        # Check peaceful posture: only peaceful explicitly blocks raiding
        attacker_posture = attacker.policies.get("military_posture")
        if attacker_posture == MilitaryPosture.PEACEFUL.value:
            return ActionResult(colony_id, action.kind, "rejected", "pacifist_posture")

        # Check contact
        if attacker.relations.get(action.target_colony_id) == RelationStatus.UNKNOWN:
            return ActionResult(colony_id, action.kind, "rejected", "target_not_contacted")

        # Check alliance - cannot raid allies
        if attacker.relations.get(action.target_colony_id) == RelationStatus.ALLIANCE:
            return ActionResult(colony_id, action.kind, "rejected", "allied_target")

        # Check attacker has healthy colonists
        if attacker.available_population <= 0:
            return ActionResult(colony_id, action.kind, "rejected", "no_healthy_colonists")

        # Check food cost
        if attacker.resources.food < RAID_PARTY_FOOD:
            return ActionResult(colony_id, action.kind, "rejected", "insufficient_resources")

        # Check for surprise raid and influence cost
        surprise = attacker.relations.get(action.target_colony_id) != RelationStatus.WAR
        if surprise:
            if attacker.resources.influence < RAID_INFLUENCE_COST_SURPRISE:
                return ActionResult(colony_id, action.kind, "rejected", "insufficient_resources")

        # Pay food upfront
        attacker = self.state.colonies[colony_id]
        self._update_colony(colony_id, resources=attacker.resources.apply({"food": -RAID_PARTY_FOOD}))

        # Pay surprise raid influence
        if surprise:
            attacker = self.state.colonies[colony_id]
            self._update_colony(colony_id, resources=attacker.resources.apply({"influence": -RAID_INFLUENCE_COST_SURPRISE}))
            # Refresh attacker after update
            attacker = self.state.colonies[colony_id]

        # Set both to war
        for source, target in ((colony_id, action.target_colony_id), (action.target_colony_id, colony_id)):
            relations = dict(self.state.colonies[source].relations)
            relations[target] = RelationStatus.WAR
            self._update_colony(source, relations=relations)

        # Calculate combat power (AM-5)
        attacker = self.state.colonies[colony_id]
        defender = self.state.colonies[action.target_colony_id]

        attacker_barracks = len([s for s in self.state.structures.values()
                                 if s.colony_id == colony_id and s.kind == StructureKind.BARRACKS
                                 and s.status == StructureStatus.OPERATIONAL])
        defender_barracks = len([s for s in self.state.structures.values()
                                 if s.colony_id == action.target_colony_id and s.kind == StructureKind.BARRACKS
                                 and s.status == StructureStatus.OPERATIONAL])
        defender_walls = len([s for s in self.state.structures.values()
                             if s.colony_id == action.target_colony_id and s.kind == StructureKind.WALL
                             and s.status == StructureStatus.OPERATIONAL])

        attacker_posture = attacker.policies.get("military_posture")
        defender_posture = defender.policies.get("military_posture")

        attacker_power = min(attacker.available_population, RAID_PARTY_SIZE) \
                        + min(3, 2 * attacker_barracks) \
                        + (1 if attacker_posture == MilitaryPosture.EXPANSIONIST.value else 0)

        defender_power = min(defender.available_population, 2) \
                        + min(3, 2 * defender_walls + 2 * defender_barracks) \
                        + (1 if defender_posture == MilitaryPosture.DEFENSIVE.value else 0)

        success = attacker_power > defender_power

        # Initialize loot to 0 for failed raids
        food_loot = 0
        wood_loot = 0

        # Apply outcome
        if success:
            # Loot calculation
            food_loot = min(RAID_FOOD_LOOT, defender.resources.food)
            if defender_barracks:
                food_loot = max(0, food_loot - BARRACKS_RAID_LOOT_REDUCTION)
            wood_loot = min(RAID_WOOD_LOOT, defender.resources.wood)

            # Cap by attacker's perishable capacity
            attacker_capacity = perishable_capacity(self.state.structures, colony_id)
            if attacker.resources.food + food_loot > attacker_capacity.get("food", float("inf")):
                food_loot = max(0, attacker_capacity.get("food", 0) - attacker.resources.food)
            if attacker.resources.water + 0 > attacker_capacity.get("water", float("inf")):
                pass  # No water loot

            # Update defender: lose resources, gain injuries
            defender_injuries = min(
                RAID_INJURIES_SUCCESS_DEFENDER,
                max(0, defender.population - defender.injured - defender.sick)
            )
            self._update_colony(
                action.target_colony_id,
                resources=defender.resources.apply({"food": -food_loot, "wood": -wood_loot}),
                injured=defender.injured + defender_injuries,
            )

            # Update attacker: gain resources, 0 injuries
            attacker = self.state.colonies[colony_id]
            self._update_colony(
                colony_id,
                resources=attacker.resources.apply({"food": food_loot, "wood": wood_loot}),
            )

            # Structure damage (excludes HQ if other structures exist - AM-10)
            targets = [
                s for s in sorted(self.state.structures.values(), key=lambda item: item.id)
                if s.colony_id == action.target_colony_id
                and s.status in {StructureStatus.OPERATIONAL, StructureStatus.DAMAGED}
            ]
            # Exclude HQ if other structures exist
            if len(targets) > 1:
                targets = [s for s in targets if s.kind != StructureKind.HEADQUARTERS]

            if targets:
                target = targets[0]
                # Walls reduce raid damage, but the reduction only applies once regardless of wall count
                walled = has_operational(self.state.structures, action.target_colony_id, StructureKind.WALL)
                damage = RAID_STRUCTURE_DAMAGE - (WALL_RAID_DAMAGE_REDUCTION if walled else 0)
                condition = max(0, target.condition - damage)
                status = StructureStatus.RUINED if condition == 0 else StructureStatus.DAMAGED
                structures = dict(self.state.structures)
                structures[target.id] = replace(target, condition=condition, status=status)
                self.state = replace(self.state, structures=structures)
                events.append(
                    DomainEvent(
                        self.state.turn,
                        "combat_damage",
                        colony_id,
                        {
                            "target_colony_id": action.target_colony_id,
                            "structure_id": target.id,
                            "condition": condition,
                            "status": status.value,
                            "x": target.position.x,
                            "y": target.position.y,
                        },
                    )
                )
        else:
            # Failed raid: both sides take casualties, no loot, no structure damage
            attacker_injuries = min(
                RAID_INJURIES_FAILURE_ATTACKER,
                max(0, attacker.population - attacker.injured - attacker.sick)
            )
            defender_injuries = min(
                RAID_INJURIES_FAILURE_DEFENDER,
                max(0, defender.population - defender.injured - defender.sick)
            )
            self._update_colony(colony_id, injured=attacker.injured + attacker_injuries)
            self._update_colony(action.target_colony_id, injured=defender.injured + defender_injuries)

        events.append(
            DomainEvent(
                self.state.turn,
                "surprise_raid" if surprise else "raid",
                colony_id,
                {"target": action.target_colony_id, "stolen_food": food_loot if success else 0},
            )
        )
        return ActionResult(colony_id, action.kind, "accepted", "ok")

    def _set_policy(
        self, colony_id: str, action: SetPolicyAction, events: list[DomainEvent]
    ) -> ActionResult:
        colony = self.state.colonies[colony_id]
        if colony.policy_cooldowns.get(action.policy, -1) > self.state.turn:
            return ActionResult(colony_id, action.kind, "rejected", "policy_cooldown")
        if action.policy == "military_posture" and action.value not in {value.value for value in MilitaryPosture}:
            return ActionResult(colony_id, action.kind, "rejected", "invalid_policy_value")
        policies = dict(colony.policies)
        policies[action.policy] = action.value
        cooldowns = dict(colony.policy_cooldowns)
        cooldowns[action.policy] = self.state.turn + 3
        self._update_colony(colony_id, policies=policies, policy_cooldowns=cooldowns)
        events.append(DomainEvent(self.state.turn, "policy_changed", colony_id, {"policy": action.policy, "value": action.value}))
        return ActionResult(colony_id, action.kind, "accepted", "ok")

    def _scout(
        self, colony_id: str, action: ScoutAction, events: list[DomainEvent]
    ) -> ActionResult:
        colony = self.state.colonies[colony_id]
        world = self.state.world
        assert isinstance(world, WorldState)
        if action.target not in world.cells:
            return ActionResult(colony_id, action.kind, "rejected", "invalid_target")
        if colony.available_population < 1:
            return ActionResult(colony_id, action.kind, "rejected", "insufficient_population")
        if colony.resources.food < SCOUT_FOOD_COST:
            return ActionResult(colony_id, action.kind, "rejected", "insufficient_resources")
        stock = colony.resources.apply({"food": -SCOUT_FOOD_COST})
        scout_id = f"sc{self._next_scout}"
        self._next_scout += 1
        scouts = dict(self.state.scouts)
        scouts[scout_id] = Scout(
            id=scout_id,
            colony_id=colony_id,
            position=colony.spawn,
            target=action.target,
        )
        self.state = replace(self.state, scouts=scouts)
        self._update_colony(colony_id, resources=stock, scouting=colony.scouting + 1)
        events.append(
            DomainEvent(
                self.state.turn,
                "scout_dispatched",
                colony_id,
                {"scout_id": scout_id, "x": action.target.x, "y": action.target.y, "food_cost": SCOUT_FOOD_COST},
            )
        )
        return ActionResult(colony_id, action.kind, "accepted", "ok")

    def _repair(self, colony_id: str, action: RepairAction, events: list[DomainEvent]) -> ActionResult:
        structure = self.state.structures.get(action.structure_id)
        if structure is None:
            return ActionResult(colony_id, action.kind, "rejected", "unknown_structure")
        if structure.colony_id != colony_id:
            return ActionResult(colony_id, action.kind, "rejected", "not_owned")
        if structure.status == StructureStatus.BURNING:
            return ActionResult(colony_id, action.kind, "rejected", "structure_burning")
        if structure.status == StructureStatus.RUINED:
            return ActionResult(colony_id, action.kind, "rejected", "structure_ruined")
        if structure.status != StructureStatus.DAMAGED:
            return ActionResult(colony_id, action.kind, "rejected", "structure_not_damaged")
        # Calculate repair cost from the structure's build cost
        colony = self.state.colonies[colony_id]
        build_cost = BUILD_COSTS.get(structure.kind)
        if build_cost is None:
            return ActionResult(colony_id, action.kind, "rejected", "unknown_structure")
        cost = repair_cost(build_cost)
        if not can_afford(colony.resources, cost):
            return ActionResult(colony_id, action.kind, "rejected", "insufficient_resources")
        # Deduct cost and start repair
        stock = colony.resources.apply({name: -amount for name, amount in cost.items()})
        self._update_colony(colony_id, resources=stock)
        structures = dict(self.state.structures)
        structures[action.structure_id] = replace(
            structure,
            status=StructureStatus.REPAIRING,
            progress=0,
            required_progress=REPAIR_TURNS,
        )
        self.state = replace(self.state, structures=structures)
        events.append(
            DomainEvent(
                self.state.turn,
                "repair_started",
                colony_id,
                {"structure_id": action.structure_id, "x": structure.position.x, "y": structure.position.y},
            )
        )
        return ActionResult(colony_id, action.kind, "accepted", "ok")

    def _extinguish(self, colony_id: str, action: ExtinguishAction, events: list[DomainEvent]) -> ActionResult:
        structure = self.state.structures.get(action.structure_id)
        if structure is None:
            return ActionResult(colony_id, action.kind, "rejected", "unknown_structure")
        if structure.colony_id != colony_id:
            return ActionResult(colony_id, action.kind, "rejected", "not_owned")
        if structure.status != StructureStatus.BURNING:
            return ActionResult(colony_id, action.kind, "rejected", "structure_not_burning")
        colony = self.state.colonies[colony_id]
        # Determine water cost based on whether colony has a well
        has_well = has_operational(self.state.structures, colony_id, StructureKind.WELL)
        water_cost = EXTINGUISH_WATER_COST_WITH_WELL if has_well else EXTINGUISH_WATER_COST
        if colony.resources.water < water_cost:
            return ActionResult(colony_id, action.kind, "rejected", "insufficient_resources")
        # Deduct water cost and extinguish the structure
        stock = colony.resources.apply({"water": -water_cost})
        self._update_colony(colony_id, resources=stock)
        structures = dict(self.state.structures)
        structures[action.structure_id] = replace(structure, status=StructureStatus.DAMAGED)
        self.state = replace(self.state, structures=structures)
        events.append(
            DomainEvent(
                self.state.turn,
                "fire_extinguished",
                colony_id,
                {"structure_id": action.structure_id, "x": structure.position.x, "y": structure.position.y},
            )
        )
        return ActionResult(colony_id, action.kind, "accepted", "ok")

    def _demolish(self, colony_id: str, action: DemolishAction, events: list[DomainEvent]) -> ActionResult:
        structure = self.state.structures.get(action.structure_id)
        if structure is None:
            return ActionResult(colony_id, action.kind, "rejected", "unknown_structure")
        if structure.colony_id != colony_id:
            return ActionResult(colony_id, action.kind, "rejected", "not_owned")
        if structure.kind == StructureKind.HEADQUARTERS:
            return ActionResult(colony_id, action.kind, "rejected", "cannot_demolish_headquarters")
        # Demolish the structure (move it to RUINED status without refunding)
        structures = dict(self.state.structures)
        structures[action.structure_id] = replace(structure, status=StructureStatus.RUINED)
        self.state = replace(self.state, structures=structures)
        events.append(
            DomainEvent(
                self.state.turn,
                "structure_demolished",
                colony_id,
                {"structure_id": action.structure_id, "x": structure.position.x, "y": structure.position.y},
            )
        )
        return ActionResult(colony_id, action.kind, "accepted", "ok")

    def _advance_scouts(self, events: list[DomainEvent]) -> None:
        if not self.state.scouts:
            return
        world = self.state.world
        assert isinstance(world, WorldState)
        scouts = dict(self.state.scouts)
        for scout_id in sorted(scouts):
            scout = scouts[scout_id]
            position = self._step_toward(scout.position, scout.target, SCOUT_SPEED)
            reached = position == scout.target
            revealed = visible_cells(world, (position,), SCOUT_REVEAL_RADIUS)
            colony = self.state.colonies[scout.colony_id]
            newly_seen = revealed - colony.known_cells
            if newly_seen:
                self._update_colony(
                    scout.colony_id,
                    known_cells=colony.known_cells | revealed,
                )
                events.append(
                    DomainEvent(
                        self.state.turn,
                        "scout_revealed",
                        scout.colony_id,
                        {"scout_id": scout.id, "x": position.x, "y": position.y, "revealed": len(newly_seen)},
                    )
                )
            if reached:
                del scouts[scout_id]
                current = self.state.colonies[scout.colony_id]
                self._update_colony(
                    scout.colony_id, scouting=max(0, current.scouting - 1)
                )
                events.append(
                    DomainEvent(
                        self.state.turn,
                        "scout_arrived",
                        scout.colony_id,
                        {"scout_id": scout.id, "x": position.x, "y": position.y},
                    )
                )
            else:
                scouts[scout_id] = replace(scout, position=position)
        self.state = replace(self.state, scouts=scouts)

    def _step_toward(self, position: Position, target: Position, steps: int) -> Position:
        x, y = position.x, position.y
        for _ in range(steps):
            if x == target.x and y == target.y:
                break
            dx = target.x - x
            dy = target.y - y
            if abs(dx) >= abs(dy):
                x += 1 if dx > 0 else -1
            else:
                y += 1 if dy > 0 else -1
        return Position(x, y)

    def _active_sight(
        self, colony: ColonyState
    ) -> frozenset[Position]:
        world = self.state.world
        assert isinstance(world, WorldState)
        towers = [
            structure
            for structure in self.state.structures.values()
            if structure.colony_id == colony.id
            and structure.kind == StructureKind.WATCHTOWER
            and structure.status == StructureStatus.OPERATIONAL
        ]
        radius = self.scenario.sight_radius + WATCHTOWER_SIGHT_BONUS * len(towers)
        origins = (colony.spawn, *(tower.position for tower in towers))
        return visible_cells(world, origins, radius)

    def _progress_construction(self, events: list[DomainEvent]) -> None:
        structures = dict(self.state.structures)
        changed = False
        for structure_id in sorted(structures):
            structure = structures[structure_id]
            if structure.status not in {StructureStatus.FOUNDATION, StructureStatus.BUILDING, StructureStatus.REPAIRING}:
                continue
            progress = structure.progress + 1
            if structure.status == StructureStatus.REPAIRING:
                # Repair targets OPERATIONAL status and keeps the condition
                status = StructureStatus.OPERATIONAL if progress >= structure.required_progress else StructureStatus.REPAIRING
            else:
                # Building progresses from FOUNDATION → BUILDING → OPERATIONAL
                status = StructureStatus.OPERATIONAL if progress >= structure.required_progress else (
                    StructureStatus.BUILDING if progress > 1 else StructureStatus.FOUNDATION
                )
            structures[structure_id] = replace(structure, progress=progress, status=status)
            changed = True
            events.append(DomainEvent(self.state.turn, "construction_progress", structure.colony_id, {"structure_id": structure_id, "progress": progress, "status": status.value}))
            if status == StructureStatus.OPERATIONAL:
                if structure.status == StructureStatus.REPAIRING:
                    events.append(
                        DomainEvent(
                            self.state.turn,
                            "repair_completed",
                            structure.colony_id,
                            {
                                "structure_id": structure_id,
                                "kind": structure.kind.value,
                                "x": structure.position.x,
                                "y": structure.position.y,
                            },
                        )
                    )
                else:
                    events.append(
                        DomainEvent(
                            self.state.turn,
                            "construction_completed",
                            structure.colony_id,
                            {
                                "structure_id": structure_id,
                                "kind": structure.kind.value,
                                "x": structure.position.x,
                                "y": structure.position.y,
                            },
                        )
                    )
        if changed:
            self.state = replace(self.state, structures=structures)

    def _apply_production(self, events: list[DomainEvent]) -> None:
        for colony_id in sorted(self.state.colonies):
            colony = self.state.colonies[colony_id]
            workers = colony.available_population // WORKERS_PER_PRODUCER
            counts, idle_producers = staffed_production(
                self.state.structures, colony_id, workers
            )
            delta = production_delta(colony.resources, counts)
            delta = cap_production_delta(
                colony.resources, delta, perishable_capacity(self.state.structures, colony_id)
            )
            heal_capacity = counts.get(StructureKind.CLINIC, 0) * CLINIC_HEALS_PER_TURN
            healed_sick = min(heal_capacity, colony.sick)
            healed_injured = min(heal_capacity - healed_sick, colony.injured)
            if not delta and not healed_sick and not healed_injured:
                continue
            self._update_colony(
                colony_id,
                resources=colony.resources.apply(delta),
                sick=colony.sick - healed_sick,
                injured=colony.injured - healed_injured,
            )
            events.append(
                DomainEvent(
                    self.state.turn,
                    "production",
                    colony_id,
                    {
                        "resources": delta,
                        "healed_sick": healed_sick,
                        "healed_injured": healed_injured,
                        "idle_producers": idle_producers,
                    },
                )
            )

    def _housing_for(self, colony_id: str) -> int:
        """Housing a colony's structures provide while they can still shelter anyone.

        A structure counts as long as it stands — a burning or damaged house still has
        a roof tonight, so it keeps housing its colonists; only a ruin stops. This is
        the same set ``_refresh_colonies`` and ``_apply_needs`` both read, so the two
        phases agree on how many roofs a colony has.
        """
        return sum(
            HOUSING_BY_STRUCTURE.get(structure.kind, 0)
            for structure in self.state.structures.values()
            if structure.colony_id == colony_id
            and structure.status
            in {
                StructureStatus.OPERATIONAL,
                StructureStatus.DAMAGED,
                StructureStatus.BURNING,
                StructureStatus.REPAIRING,
            }
        )

    def _refresh_colonies(self) -> None:
        for colony_id, colony in tuple(self.state.colonies.items()):
            housing = self._housing_for(colony_id)
            visible_now = self._active_sight(colony)
            known = colony.known_cells | visible_now
            population = colony.population
            if (
                self.state.turn > 0
                and self.state.turn % 5 == 0
                and population < housing
                and colony.resources.food >= population * 2
                and colony.resources.water >= population * 2
            ):
                population += 1
            self._update_colony(colony_id, housing=housing, population=population, healthy=max(0, population - colony.injured - colony.sick), known_cells=known, visible_now=visible_now)

    def _apply_needs(self, events: list[DomainEvent]) -> None:
        for colony_id, colony in tuple(self.state.colonies.items()):
            food_need = max(1, colony.population // 4)
            water_need = max(1, colony.population // 4)
            food = min(food_need, colony.resources.food)
            water = min(water_need, colony.resources.water)
            stock = colony.resources.apply({"food": -food, "water": -water})
            shortfall = food < food_need or water < water_need
            hungry = colony.hungry + int(shortfall)
            population = colony.population
            sick = colony.sick
            if hungry >= 3 and population > 0:
                population -= 1
                hungry = 0
                if sick > 0:
                    sick -= 1
                events.append(DomainEvent(self.state.turn, "population_died", colony_id, {"cause": "needs"}))
            # Colonists without a roof are exposed. They fall sick the way a food or
            # water shortfall sickens colonists, but only up to the number actually
            # exposed — housed colonists are never touched by exposure.
            exposed = max(0, population - self._housing_for(colony_id))
            # Sickness may never take the last able colonist. A colony with nobody able
            # cannot gather, cannot staff its clinic and cannot carry an action, so it can
            # never climb out again: the match stops measuring recovery and starts
            # measuring how long an absorbing state takes to finish. MIN_ABLE_COLONISTS
            # keeps one pair of hands so the way back is hard rather than closed.
            able = max(0, population - colony.scouting - colony.injured - sick)
            sickening_room = max(0, able - MIN_ABLE_COLONISTS) if population > 0 else 0
            if shortfall:
                healthy_available = max(0, population - colony.injured - sick)
                sickened = min(SICKENED_PER_SHORTFALL_TURN, healthy_available, sickening_room)
                if sickened:
                    sick += sickened
                    events.append(
                        DomainEvent(
                            self.state.turn,
                            "colonist_sickened",
                            colony_id,
                            {"count": sickened, "cause": "needs"},
                        )
                    )
            elif exposed > 0:
                healthy_available = max(0, population - colony.injured - sick)
                sickened = min(
                    EXPOSED_SICKENED_PER_TURN,
                    max(0, exposed - sick),
                    healthy_available,
                    sickening_room,
                )
                if sickened:
                    sick += sickened
                    events.append(
                        DomainEvent(
                            self.state.turn,
                            "colonist_sickened",
                            colony_id,
                            {"count": sickened, "cause": "exposure"},
                        )
                    )
            elif sick > 0:
                recovered = min(NATURAL_RECOVERY_PER_TURN, sick)
                if recovered:
                    sick -= recovered
                    events.append(
                        DomainEvent(
                            self.state.turn,
                            "colonist_recovered",
                            colony_id,
                            {"count": recovered, "cause": "supply"},
                        )
                    )
            self._update_colony(
                colony_id, resources=stock, hungry=hungry, population=population, sick=sick
            )

    def _apply_hazards(self, events: list[DomainEvent]) -> None:
        # Use the scenario's hazard cadence (set per-biome, see AM-2)
        cadence = self.scenario.hazard_cadence
        # Weather hazards follow the global schedule
        if (self.state.turn + (self.state.seed % cadence)) % cadence == 0:
            events.append(DomainEvent(self.state.turn, "weather_hazard", data={"biome": self.scenario.biome}))
            for colony_id, colony in tuple(self.state.colonies.items()):
                if self.scenario.biome == "snow":
                    loss = min(2, colony.resources.wood)
                    self._update_colony(colony_id, resources=colony.resources.apply({"wood": -loss}))
                elif self.scenario.biome == "desert":
                    loss = min(3, colony.resources.water)
                    self._update_colony(colony_id, resources=colony.resources.apply({"water": -loss}))
        # Fire happens every turn per-colony (not tied to global hazard schedule)
        self._apply_fire(events)

    def _apply_fire(self, events: list[DomainEvent]) -> None:
        # Use the scenario's hazard cadence (set per-biome, see AM-2)
        # Weather loss uses hazard_cadence; fire ignition uses hazard_cadence + bonus
        # so fire is slower and rarer than weather (AM-15).
        weather_cadence = self.scenario.hazard_cadence
        fire_cadence = self.scenario.hazard_cadence + FIRE_IGNITION_CADENCE_BONUS
        structures = dict(self.state.structures)

        # Process existing burning structures: damage them and spread fire
        spread_targets: set[str] = set()
        burning = [
            structure
            for structure in sorted(structures.values(), key=lambda item: item.id)
            if structure.status == StructureStatus.BURNING
        ]
        for source in burning:
            neighbours = [
                target
                for target in sorted(structures.values(), key=lambda item: item.id)
                if target.status == StructureStatus.OPERATIONAL
                and target.colony_id == source.colony_id
                and target.kind != StructureKind.HEADQUARTERS
                and abs(target.position.x - source.position.x)
                + abs(target.position.y - source.position.y)
                == 1
            ]
            if neighbours:
                spread_targets.add(neighbours[0].id)
            condition = max(0, source.condition - FIRE_DAMAGE_PER_TURN)
            status = StructureStatus.RUINED if condition == 0 else StructureStatus.BURNING
            structures[source.id] = replace(source, condition=condition, status=status)
            events.append(
                DomainEvent(
                    self.state.turn,
                    "fire_damage",
                    source.colony_id,
                    {
                        "structure_id": source.id,
                        "condition": condition,
                        "status": status.value,
                        "x": source.position.x,
                        "y": source.position.y,
                    },
                )
            )

        for target_id in sorted(spread_targets):
            target = structures[target_id]
            structures[target_id] = replace(target, status=StructureStatus.BURNING)
            events.append(
                DomainEvent(
                    self.state.turn,
                    "fire_spread",
                    target.colony_id,
                    {
                        "structure_id": target.id,
                        "x": target.position.x,
                        "y": target.position.y,
                    },
                )
            )

        # Try to ignite a new fire for each colony in sorted order, if that colony
        # has no burning structures and the fire schedule says so
        for colony_id in sorted(self.state.colonies):
            colony_burning = [
                s for s in structures.values()
                if s.colony_id == colony_id and s.status == StructureStatus.BURNING
            ]
            if colony_burning:
                # This colony already has a fire, skip it
                continue

            # Check if this colony gets a fire this turn (using fire_cadence, not weather_cadence)
            fire_seed = derive_seed(self.state.seed, f"fire:{colony_id}")
            if (self.state.turn + fire_seed % fire_cadence) % fire_cadence != 0:
                continue

            # This colony gets a fire. Pick a target from its OPERATIONAL/DAMAGED structures
            # (but not the HQ, which is unrecoverable if burned to ruins)
            candidates = [
                structure
                for structure in sorted(structures.values(), key=lambda item: item.id)
                if structure.colony_id == colony_id
                and structure.kind != StructureKind.HEADQUARTERS
                and structure.status in {StructureStatus.OPERATIONAL, StructureStatus.DAMAGED}
            ]
            if not candidates:
                continue

            target_seed = derive_seed(self.state.seed, f"fire-target:{colony_id}:{self.state.turn}")
            target_index = target_seed % len(candidates)
            target = candidates[target_index]
            structures[target.id] = replace(target, status=StructureStatus.BURNING)
            events.append(
                DomainEvent(
                    self.state.turn,
                    "fire_started",
                    colony_id,
                    {
                        "structure_id": target.id,
                        "x": target.position.x,
                        "y": target.position.y,
                    },
                )
            )

        self.state = replace(self.state, structures=structures)

    def _expire_offers(self, events: list[DomainEvent]) -> None:
        for offer_id, offer in tuple(self.state.offers.items()):
            if offer.status != "open" or offer.expires_turn > self.state.turn:
                continue
            source = self.state.colonies[offer.source_colony_id]
            self._update_colony(
                offer.source_colony_id,
                resources=source.resources.apply(resource_delta(offer.give)),
            )
            offers = dict(self.state.offers)
            offers[offer_id] = replace(offer, status="expired")
            self.state = replace(self.state, offers=offers)
            events.append(DomainEvent(self.state.turn, "trade_expired", offer.source_colony_id, {"offer_id": offer_id}))
