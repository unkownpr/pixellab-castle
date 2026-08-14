from castle_benchmark.actions import (
    ActionBatch,
    DiplomacyAction,
    RaidAction,
    SetPolicyAction,
    TradeOfferAction,
    TradeRespondAction,
    WaitAction,
)
from dataclasses import replace

import pytest

from castle_benchmark.domain import (
    MilitaryPosture,
    Position,
    RelationStatus,
    Structure,
    StructureKind,
    StructureStatus,
)
from castle_benchmark.engine import SimCore
from castle_benchmark.scenarios import BASIC_SURVIVAL, SNOW_RECOVERY


def batch(sim: SimCore, colony_id: str, *actions: object) -> ActionBatch:
    return ActionBatch(turn=sim.state.turn, colony_id=colony_id, actions=actions)  # type: ignore[arg-type]


def all_wait(sim: SimCore) -> tuple[ActionBatch, ...]:
    return tuple(batch(sim, colony_id, WaitAction()) for colony_id in sim.state.colonies)


def add_structure(
    sim: SimCore,
    colony_id: str,
    kind: StructureKind,
    status: StructureStatus = StructureStatus.OPERATIONAL,
) -> str:
    """Seed a structure directly onto the colony without spending a build action."""
    structures = dict(sim.state.structures)
    structure_id = f"s{len(structures) + 1}"
    spawn = sim.state.colonies[colony_id].spawn
    if status in (StructureStatus.FOUNDATION, StructureStatus.BUILDING):
        progress = 0 if status == StructureStatus.FOUNDATION else 1
        required_progress = 3
    else:
        progress = 1
        required_progress = 1
    structures[structure_id] = Structure(
        id=structure_id,
        colony_id=colony_id,
        kind=kind,
        position=Position(spawn.x + 1, spawn.y),
        status=status,
        progress=progress,
        required_progress=required_progress,
    )
    sim.state = replace(sim.state, structures=structures)
    return structure_id


def test_trade_offer_reserves_then_transfers_less_friction() -> None:
    """Catches double-spending or resource creation in accepted trades."""
    sim = SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=2)
    sim.resolve(
        (
            batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),
            batch(sim, "c2", DiplomacyAction(target_colony_id="c1", operation="contact")),
        )
    )
    before_c1_wood = sim.state.colonies["c1"].resources.wood
    before_c1_food = sim.state.colonies["c1"].resources.food
    before_c2_wood = sim.state.colonies["c2"].resources.wood
    before_c2_food = sim.state.colonies["c2"].resources.food

    offered = sim.resolve(
        (
            batch(
                sim,
                "c1",
                TradeOfferAction(target_colony_id="c2", give=(("wood", 10),), receive=(("food", 5),)),
            ),
        )
    )
    offer_id = next(event.data["offer_id"] for event in offered.events if event.kind == "trade_offered")

    assert offered.state.colonies["c1"].resources.wood == before_c1_wood - 10

    accepted = sim.resolve((batch(sim, "c2", TradeRespondAction(offer_id=offer_id, accept=True)),))

    # The payer is debited in full, but neither side owns a MARKET, so only
    # floor(amount * 4/5) of each consignment survives the journey.
    # Both colonies also consume two food on each resolved turn: offer and accept.
    assert accepted.state.colonies["c1"].resources.food == before_c1_food + 4 - 4
    assert accepted.state.colonies["c2"].resources.food == before_c2_food - 5 - 4
    assert accepted.state.colonies["c2"].resources.wood == before_c2_wood + 8
    assert (
        accepted.state.colonies["c1"].resources.wood
        + accepted.state.colonies["c2"].resources.wood
        < before_c1_wood + before_c2_wood
    )


def test_peaceful_colonies_do_not_auto_attack() -> None:
    """Catches proximity triggering combat without an explicit hostile action."""
    sim = SimCore.create(BASIC_SURVIVAL, seed=23, colony_count=2)

    result = sim.resolve(all_wait(sim))

    assert not [event for event in result.events if event.kind == "combat_damage"]


def test_surprise_raid_changes_relation_and_costs_influence() -> None:
    """Catches undeclared aggression without the benchmark's diplomatic cost."""
    sim = SimCore.create(BASIC_SURVIVAL, seed=29, colony_count=2)
    influence_before = sim.state.colonies["c1"].resources.influence

    sim.resolve((batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),))
    result = sim.resolve((batch(sim, "c1", RaidAction(target_colony_id="c2")),))

    assert result.state.colonies["c1"].relations["c2"] == RelationStatus.WAR
    assert result.state.colonies["c1"].resources.influence < influence_before
    assert any(event.kind == "surprise_raid" for event in result.events)
    damaged = [
        structure
        for structure in result.state.structures.values()
        if structure.colony_id == "c2" and structure.status == StructureStatus.DAMAGED
    ]
    assert damaged
    assert any(event.kind == "combat_damage" for event in result.events)


def test_unknown_colony_cannot_be_raided_at_unlimited_range() -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=4)

    result = sim.resolve((batch(sim, "c1", RaidAction(target_colony_id="c4")),))

    assert result.action_results[0].code == "target_not_contacted"


def test_policy_change_has_cooldown() -> None:
    """Catches crisis policies being switched repeatedly without measurable commitment."""
    sim = SimCore.create(BASIC_SURVIVAL, seed=31, colony_count=1)

    first = sim.resolve(
        (batch(sim, "c1", SetPolicyAction(policy="military_posture", value=MilitaryPosture.DEFENSIVE.value)),)
    )
    second = sim.resolve(
        (batch(sim, "c1", SetPolicyAction(policy="military_posture", value=MilitaryPosture.EXPANSIONIST.value)),)
    )

    assert any(item.status == "accepted" for item in first.action_results)
    assert any(item.code == "policy_cooldown" for item in second.action_results)


def test_seeded_snow_scenario_emits_weather_hazard() -> None:
    """Catches disaster schedules depending on wall-clock timing or controller identity."""
    sim = SimCore.create(SNOW_RECOVERY, seed=37, colony_count=1)
    hazard_events = []

    for _ in range(15):
        result = sim.resolve(all_wait(sim))
        hazard_events.extend(event for event in result.events if event.kind == "weather_hazard")

    assert hazard_events
    assert {event.data["biome"] for event in hazard_events} == {"snow"}


def test_seeded_hazard_starts_a_visible_structure_fire() -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=37, colony_count=1)
    hazard_turn = (-sim.state.seed) % 11
    sim.state = replace(sim.state, turn=hazard_turn)

    result = sim.resolve(all_wait(sim))

    burning = [s for s in result.state.structures.values() if s.status == StructureStatus.BURNING]
    assert len(burning) == 1
    event = next(event for event in result.events if event.kind == "fire_started")
    assert event.data == {
        "structure_id": burning[0].id,
        "x": burning[0].position.x,
        "y": burning[0].position.y,
    }


def test_burning_structure_damages_and_spreads_on_next_hazard() -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=37, colony_count=1)
    structures = dict(sim.state.structures)
    headquarters = structures["s1"]
    structures["s1"] = replace(headquarters, status=StructureStatus.BURNING)
    structures["s2"] = Structure(
        id="s2",
        colony_id="c1",
        kind=StructureKind.HOUSE,
        position=Position(headquarters.position.x + 1, headquarters.position.y),
        status=StructureStatus.OPERATIONAL,
        progress=3,
        required_progress=3,
    )
    sim.state = replace(sim.state, structures=structures, turn=(-sim.state.seed) % 11)

    result = sim.resolve(all_wait(sim))

    assert result.state.structures["s1"].status == StructureStatus.DAMAGED
    assert result.state.structures["s1"].condition < 100
    assert result.state.structures["s2"].status == StructureStatus.BURNING
    assert any(event.kind == "fire_damage" for event in result.events)
    assert any(event.kind == "fire_spread" for event in result.events)


# --- Structure economy -----------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "resource", "expected_yield"),
    [
        (StructureKind.FARM, "food", 2),
        (StructureKind.WELL, "water", 2),
        (StructureKind.LUMBER_CAMP, "wood", 2),
        (StructureKind.QUARRY, "stone", 2),
        (StructureKind.MINE, "ore", 2),
    ],
)
def test_producer_yields_resource_while_operational(kind, resource, expected_yield) -> None:
    """Catches resource producers that charge BUILD_COSTS but return nothing."""
    producer = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    control = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    add_structure(producer, "c1", kind)

    producer.resolve(all_wait(producer))
    control.resolve(all_wait(control))

    produced = getattr(producer.state.colonies["c1"].resources, resource)
    baseline = getattr(control.state.colonies["c1"].resources, resource)
    assert produced - baseline == expected_yield


def test_workshop_converts_ore_into_tools() -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    add_structure(sim, "c1", StructureKind.WORKSHOP)
    before_ore = sim.state.colonies["c1"].resources.ore
    before_tools = sim.state.colonies["c1"].resources.tools

    sim.resolve(all_wait(sim))

    assert sim.state.colonies["c1"].resources.ore == before_ore - 2
    assert sim.state.colonies["c1"].resources.tools == before_tools + 1


def test_workshop_stops_when_ore_runs_out() -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    colonies = dict(sim.state.colonies)
    colonies["c1"] = replace(colonies["c1"], resources=replace(colonies["c1"].resources, ore=1))
    sim.state = replace(sim.state, colonies=colonies)
    add_structure(sim, "c1", StructureKind.WORKSHOP)

    sim.resolve(all_wait(sim))

    assert sim.state.colonies["c1"].resources.ore == 1
    assert sim.state.colonies["c1"].resources.tools == 6


def test_clinic_heals_sick_then_injured() -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    colonies = dict(sim.state.colonies)
    colonies["c1"] = replace(colonies["c1"], sick=1, injured=1)
    sim.state = replace(sim.state, colonies=colonies)
    add_structure(sim, "c1", StructureKind.CLINIC)

    sim.resolve(all_wait(sim))
    assert sim.state.colonies["c1"].sick == 0
    assert sim.state.colonies["c1"].injured == 1

    sim.resolve(all_wait(sim))
    assert sim.state.colonies["c1"].injured == 0


def test_market_grants_influence() -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    add_structure(sim, "c1", StructureKind.MARKET)
    before = sim.state.colonies["c1"].resources.influence

    sim.resolve(all_wait(sim))

    assert sim.state.colonies["c1"].resources.influence == before + 2


def test_market_improves_trade_ratio_for_its_owner() -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=2)
    sim.resolve(
        (
            batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),
            batch(sim, "c2", DiplomacyAction(target_colony_id="c1", operation="contact")),
        )
    )
    add_structure(sim, "c2", StructureKind.MARKET)
    before_c2_wood = sim.state.colonies["c2"].resources.wood

    offered = sim.resolve(
        (
            batch(
                sim,
                "c1",
                TradeOfferAction(target_colony_id="c2", give=(("wood", 4),), receive=(("food", 2),)),
            ),
        )
    )
    offer_id = next(event.data["offer_id"] for event in offered.events if event.kind == "trade_offered")
    accepted = sim.resolve((batch(sim, "c2", TradeRespondAction(offer_id=offer_id, accept=True)),))

    # c2 owns a MARKET, so the consignment arrives intact: all 4 wood, not the
    # floor(4 * 4/5) = 3 that a colony without a market would have collected.
    assert accepted.state.colonies["c2"].resources.wood == before_c2_wood + 4


def test_market_owner_collects_more_than_a_colony_without_one() -> None:
    """The market's value is avoided friction, not created value."""

    def collected(with_market: bool) -> int:
        sim = SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=2)
        sim.resolve(
            (
                batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),
                batch(sim, "c2", DiplomacyAction(target_colony_id="c1", operation="contact")),
            )
        )
        if with_market:
            add_structure(sim, "c2", StructureKind.MARKET)
        before = sim.state.colonies["c2"].resources.wood
        offered = sim.resolve(
            (
                batch(
                    sim,
                    "c1",
                    TradeOfferAction(target_colony_id="c2", give=(("wood", 4),), receive=(("food", 2),)),
                ),
            )
        )
        offer_id = next(
            event.data["offer_id"] for event in offered.events if event.kind == "trade_offered"
        )
        accepted = sim.resolve((batch(sim, "c2", TradeRespondAction(offer_id=offer_id, accept=True)),))
        return accepted.state.colonies["c2"].resources.wood - before

    assert collected(with_market=False) == 3
    assert collected(with_market=True) == 4


def test_trade_never_creates_resources() -> None:
    """Two colonies with markets must not be able to mint value by trading in circles.

    Trading is allowed to lose resources to friction, never to invent them. Without
    this, an agent that spams offers back and forth beats one that plays the scenario.
    """
    tracked = ("wood", "stone")

    sim = SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=2)
    sim.resolve(
        (
            batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),
            batch(sim, "c2", DiplomacyAction(target_colony_id="c1", operation="contact")),
        )
    )
    add_structure(sim, "c1", StructureKind.MARKET)
    add_structure(sim, "c2", StructureKind.MARKET)

    def held() -> int:
        return sum(
            colony.resources.as_dict()[name]
            for colony in sim.state.colonies.values()
            for name in tracked
        )

    for _ in range(10):
        start = held()
        offered = sim.resolve(
            (
                batch(
                    sim,
                    "c1",
                    TradeOfferAction(target_colony_id="c2", give=(("wood", 4),), receive=(("stone", 4),)),
                ),
            )
        )
        offer_id = next(
            event.data["offer_id"] for event in offered.events if event.kind == "trade_offered"
        )
        sim.resolve((batch(sim, "c2", TradeRespondAction(offer_id=offer_id, accept=True)),))
        assert held() <= start


def test_barracks_reduces_food_lost_to_raid() -> None:
    def stolen_food(barracks: bool) -> int:
        sim = SimCore.create(BASIC_SURVIVAL, seed=29, colony_count=2)
        sim.resolve((batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),))
        if barracks:
            add_structure(sim, "c2", StructureKind.BARRACKS)
        result = sim.resolve((batch(sim, "c1", RaidAction(target_colony_id="c2")),))
        return next(event.data["stolen_food"] for event in result.events if event.kind in ("raid", "surprise_raid"))

    assert stolen_food(False) == 3
    assert stolen_food(True) == 1


def test_wall_reduces_structure_damage_from_raid() -> None:
    def hq_condition(walled: bool) -> int:
        sim = SimCore.create(BASIC_SURVIVAL, seed=29, colony_count=2)
        sim.resolve((batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),))
        if walled:
            add_structure(sim, "c2", StructureKind.WALL)
        sim.resolve((batch(sim, "c1", RaidAction(target_colony_id="c2")),))
        hq = next(
            structure
            for structure in sim.state.structures.values()
            if structure.colony_id == "c2" and structure.kind == StructureKind.HEADQUARTERS
        )
        return hq.condition

    assert hq_condition(False) == 80
    assert hq_condition(True) == 90


def test_gate_permits_trade_while_walled() -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=2)
    sim.resolve(
        (
            batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),
            batch(sim, "c2", DiplomacyAction(target_colony_id="c1", operation="contact")),
        )
    )
    add_structure(sim, "c2", StructureKind.WALL)

    offered = sim.resolve(
        (
            batch(
                sim,
                "c1",
                TradeOfferAction(target_colony_id="c2", give=(("wood", 2),), receive=(("food", 2),)),
            ),
        )
    )
    offer_id = next(event.data["offer_id"] for event in offered.events if event.kind == "trade_offered")
    blocked = sim.resolve((batch(sim, "c2", TradeRespondAction(offer_id=offer_id, accept=True)),))
    assert any(result.code == "walled" for result in blocked.action_results)

    add_structure(sim, "c2", StructureKind.GATE)
    offered_again = sim.resolve(
        (
            batch(
                sim,
                "c1",
                TradeOfferAction(target_colony_id="c2", give=(("wood", 2),), receive=(("food", 2),)),
            ),
        )
    )
    offer_id_again = next(event.data["offer_id"] for event in offered_again.events if event.kind == "trade_offered")
    accepted = sim.resolve((batch(sim, "c2", TradeRespondAction(offer_id=offer_id_again, accept=True)),))
    assert any(event.kind == "trade_completed" for event in accepted.events)


def test_damaged_raid_mitigations_do_not_apply() -> None:
    def stolen_food(status: StructureStatus) -> int:
        sim = SimCore.create(BASIC_SURVIVAL, seed=29, colony_count=2)
        sim.resolve((batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),))
        add_structure(sim, "c2", StructureKind.BARRACKS, status=status)
        result = sim.resolve((batch(sim, "c1", RaidAction(target_colony_id="c2")),))
        return next(event.data["stolen_food"] for event in result.events if event.kind in ("raid", "surprise_raid"))

    assert stolen_food(StructureStatus.OPERATIONAL) == 1
    assert stolen_food(StructureStatus.DAMAGED) == 3


def test_damaged_wall_does_not_reduce_raid_damage() -> None:
    def hq_condition(status: StructureStatus) -> int:
        sim = SimCore.create(BASIC_SURVIVAL, seed=29, colony_count=2)
        sim.resolve((batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),))
        add_structure(sim, "c2", StructureKind.WALL, status=status)
        sim.resolve((batch(sim, "c1", RaidAction(target_colony_id="c2")),))
        hq = next(
            structure
            for structure in sim.state.structures.values()
            if structure.colony_id == "c2" and structure.kind == StructureKind.HEADQUARTERS
        )
        return hq.condition

    assert hq_condition(StructureStatus.OPERATIONAL) == 90
    assert hq_condition(StructureStatus.DAMAGED) == 80


@pytest.mark.parametrize(
    "status",
    [
        StructureStatus.DAMAGED,
        StructureStatus.BURNING,
        StructureStatus.RUINED,
        StructureStatus.FOUNDATION,
        StructureStatus.BUILDING,
    ],
)
def test_non_operational_producer_yields_nothing(status) -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    control = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    add_structure(sim, "c1", StructureKind.FARM, status=status)

    sim.resolve(all_wait(sim))
    control.resolve(all_wait(control))

    assert sim.state.colonies["c1"].resources.food == control.state.colonies["c1"].resources.food


def test_damaged_structure_of_every_producing_kind_yields_nothing() -> None:
    producing_kinds = (
        StructureKind.FARM,
        StructureKind.WELL,
        StructureKind.LUMBER_CAMP,
        StructureKind.QUARRY,
        StructureKind.MINE,
        StructureKind.WORKSHOP,
        StructureKind.CLINIC,
        StructureKind.MARKET,
    )
    for kind in producing_kinds:
        sim = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
        control = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
        add_structure(sim, "c1", kind, status=StructureStatus.DAMAGED)

        sim.resolve(all_wait(sim))
        control.resolve(all_wait(control))

        assert sim.state.colonies["c1"].resources == control.state.colonies["c1"].resources
        assert sim.state.colonies["c1"].sick == control.state.colonies["c1"].sick
        assert sim.state.colonies["c1"].injured == control.state.colonies["c1"].injured


def test_farm_colony_outperforms_do_nothing_colony_over_full_scenario() -> None:
    producer = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    idler = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    add_structure(producer, "c1", StructureKind.FARM)

    for _ in range(BASIC_SURVIVAL.max_turns):
        if producer.state.terminal and idler.state.terminal:
            break
        if not producer.state.terminal:
            producer.resolve(all_wait(producer))
        if not idler.state.terminal:
            idler.resolve(all_wait(idler))

    assert producer.state.colonies["c1"].resources.food > idler.state.colonies["c1"].resources.food
