from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Mapping

from .actions import (
    ActionBatch,
    BuildAction,
    DiplomacyAction,
    GameAction,
    GatherAction,
    RaidAction,
    SetPolicyAction,
    TradeOfferAction,
    TradeRespondAction,
    WaitAction,
)
from .domain import (
    ColonyState,
    MatchState,
    MilitaryPosture,
    RelationStatus,
    ResourceStock,
    Structure,
    StructureKind,
    StructureStatus,
    TradeOffer,
)
from .scenarios import Scenario
from .systems import BUILD_COSTS, BUILD_TURNS, HOUSING_BY_STRUCTURE, can_afford, resource_delta
from .world import WorldCell, WorldState, generate_world, rotated_spawns, visible_cells


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

    @classmethod
    def create(cls, scenario: Scenario, seed: int, colony_count: int) -> SimCore:
        world = generate_world(scenario, seed)
        spawns = rotated_spawns(scenario, rotation=0, colony_count=colony_count)
        colonies: dict[str, ColonyState] = {}
        structures: dict[str, Structure] = {}
        ids = tuple(f"c{index + 1}" for index in range(colony_count))
        for index, (colony_id, spawn) in enumerate(zip(ids, spawns, strict=True), start=1):
            relations = {other: RelationStatus.UNKNOWN for other in ids if other != colony_id}
            colonies[colony_id] = ColonyState(
                id=colony_id,
                spawn=spawn,
                resources=ResourceStock(
                    food=60, water=60, wood=50, stone=35, ore=10, tools=6, influence=20
                ),
                relations=relations,
                policies={"military_posture": MilitaryPosture.PEACEFUL.value, "rationing": "normal"},
                known_cells=visible_cells(world, (spawn,), scenario.sight_radius),
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

        for colony_id in sorted(self.state.colonies):
            batch = provided.get(colony_id)
            if batch is None:
                events.append(DomainEvent(self.state.turn, "controller_wait", colony_id))
                continue
            for action in batch.actions:
                result = self._apply_action(colony_id, action, events)
                results.append(result)

        self._progress_construction(events)
        self._expire_offers(events)
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
        return ActionResult(colony_id, "unknown", "rejected", "unknown_action")

    def _update_colony(self, colony_id: str, **changes: object) -> None:
        colonies = dict(self.state.colonies)
        colonies[colony_id] = replace(colonies[colony_id], **changes)
        self.state = replace(self.state, colonies=colonies)

    def _gather(self, colony_id: str, action: GatherAction, events: list[DomainEvent]) -> ActionResult:
        world = self.state.world
        assert isinstance(world, WorldState)
        cell = world.cells.get(action.position)
        if cell is None or cell.resource is None or cell.resource_amount <= 0:
            return ActionResult(colony_id, action.kind, "rejected", "no_resource")
        amount = min(4, cell.resource_amount)
        colony = self.state.colonies[colony_id]
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
        colony = self.state.colonies[colony_id]
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
        structures = dict(self.state.structures)
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
            target_after_payment = target.resources.apply(resource_delta(offer.receive, sign=-1))
            source_after_receipt = source.resources.apply(resource_delta(offer.receive))
            target_after_trade = target_after_payment.apply(resource_delta(offer.give))
        except (ValueError, KeyError):
            return ActionResult(colony_id, action.kind, "rejected", "insufficient_resources")
        self._update_colony(offer.source_colony_id, resources=source_after_receipt)
        self._update_colony(colony_id, resources=target_after_trade)
        offers = dict(self.state.offers)
        offers[action.offer_id] = replace(offer, status="accepted")
        self.state = replace(self.state, offers=offers)
        events.append(DomainEvent(self.state.turn, "trade_completed", colony_id, {"offer_id": offer.id}))
        return ActionResult(colony_id, action.kind, "accepted", "ok")

    def _raid(self, colony_id: str, action: RaidAction, events: list[DomainEvent]) -> ActionResult:
        if action.target_colony_id not in self.state.colonies or action.target_colony_id == colony_id:
            return ActionResult(colony_id, action.kind, "rejected", "invalid_target")
        attacker = self.state.colonies[colony_id]
        surprise = attacker.relations[action.target_colony_id] != RelationStatus.WAR
        if surprise:
            cost = min(5, attacker.resources.influence)
            self._update_colony(colony_id, resources=attacker.resources.apply({"influence": -cost}))
        for source, target in ((colony_id, action.target_colony_id), (action.target_colony_id, colony_id)):
            relations = dict(self.state.colonies[source].relations)
            relations[target] = RelationStatus.WAR
            self._update_colony(source, relations=relations)
        defender = self.state.colonies[action.target_colony_id]
        stolen = min(3, defender.resources.food)
        self._update_colony(
            action.target_colony_id, resources=defender.resources.apply({"food": -stolen})
        )
        current_attacker = self.state.colonies[colony_id]
        self._update_colony(colony_id, resources=current_attacker.resources.apply({"food": stolen}))
        events.append(
            DomainEvent(
                self.state.turn,
                "surprise_raid" if surprise else "raid",
                colony_id,
                {"target": action.target_colony_id, "stolen_food": stolen},
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

    def _progress_construction(self, events: list[DomainEvent]) -> None:
        structures = dict(self.state.structures)
        changed = False
        for structure_id in sorted(structures):
            structure = structures[structure_id]
            if structure.status not in {StructureStatus.FOUNDATION, StructureStatus.BUILDING}:
                continue
            progress = structure.progress + 1
            status = StructureStatus.OPERATIONAL if progress >= structure.required_progress else (
                StructureStatus.BUILDING if progress > 1 else StructureStatus.FOUNDATION
            )
            structures[structure_id] = replace(structure, progress=progress, status=status)
            changed = True
            events.append(DomainEvent(self.state.turn, "construction_progress", structure.colony_id, {"structure_id": structure_id, "progress": progress, "status": status.value}))
            if status == StructureStatus.OPERATIONAL:
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

    def _refresh_colonies(self) -> None:
        for colony_id, colony in tuple(self.state.colonies.items()):
            housing = sum(
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
            known = visible_cells(self.state.world, (colony.spawn,), self.scenario.sight_radius)  # type: ignore[arg-type]
            population = colony.population
            if (
                self.state.turn > 0
                and self.state.turn % 5 == 0
                and population < housing
                and colony.resources.food >= population * 2
                and colony.resources.water >= population * 2
            ):
                population += 1
            self._update_colony(colony_id, housing=housing, population=population, healthy=max(0, population - colony.injured - colony.sick), known_cells=known)

    def _apply_needs(self, events: list[DomainEvent]) -> None:
        for colony_id, colony in tuple(self.state.colonies.items()):
            food_need = max(1, colony.population // 4)
            water_need = max(1, colony.population // 4)
            food = min(food_need, colony.resources.food)
            water = min(water_need, colony.resources.water)
            stock = colony.resources.apply({"food": -food, "water": -water})
            hungry = colony.hungry + int(food < food_need or water < water_need)
            population = colony.population
            if hungry >= 3 and population > 0:
                population -= 1
                hungry = 0
                events.append(DomainEvent(self.state.turn, "population_died", colony_id, {"cause": "needs"}))
            self._update_colony(colony_id, resources=stock, hungry=hungry, population=population)

    def _apply_hazards(self, events: list[DomainEvent]) -> None:
        cadence = {"grassland": 11, "desert": 9, "snow": 7}.get(self.scenario.biome, 13)
        if (self.state.turn + (self.state.seed % cadence)) % cadence != 0:
            return
        events.append(DomainEvent(self.state.turn, "weather_hazard", data={"biome": self.scenario.biome}))
        for colony_id, colony in tuple(self.state.colonies.items()):
            if self.scenario.biome == "snow":
                loss = min(2, colony.resources.wood)
                self._update_colony(colony_id, resources=colony.resources.apply({"wood": -loss}))
            elif self.scenario.biome == "desert":
                loss = min(3, colony.resources.water)
                self._update_colony(colony_id, resources=colony.resources.apply({"water": -loss}))
        self._apply_fire(events)

    def _apply_fire(self, events: list[DomainEvent]) -> None:
        structures = dict(self.state.structures)
        burning = [
            structure
            for structure in sorted(structures.values(), key=lambda item: item.id)
            if structure.status == StructureStatus.BURNING
        ]
        if not burning:
            candidates = [
                structure
                for structure in sorted(structures.values(), key=lambda item: item.id)
                if structure.status in {StructureStatus.OPERATIONAL, StructureStatus.DAMAGED}
            ]
            if not candidates:
                return
            target_index = (self.state.seed + self.state.turn) % len(candidates)
            target = candidates[target_index]
            structures[target.id] = replace(target, status=StructureStatus.BURNING)
            self.state = replace(self.state, structures=structures)
            events.append(
                DomainEvent(
                    self.state.turn,
                    "fire_started",
                    target.colony_id,
                    {
                        "structure_id": target.id,
                        "x": target.position.x,
                        "y": target.position.y,
                    },
                )
            )
            return

        spread_targets: set[str] = set()
        for source in burning:
            neighbours = [
                target
                for target in sorted(structures.values(), key=lambda item: item.id)
                if target.status == StructureStatus.OPERATIONAL
                and target.colony_id == source.colony_id
                and abs(target.position.x - source.position.x)
                + abs(target.position.y - source.position.y)
                == 1
            ]
            if neighbours:
                spread_targets.add(neighbours[0].id)
            condition = max(0, source.condition - 40)
            status = StructureStatus.RUINED if condition == 0 else StructureStatus.DAMAGED
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
