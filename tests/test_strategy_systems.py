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


def test_trade_offer_reserves_then_transfers_exact_resources() -> None:
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

    # Both colonies also consume two food on each resolved turn: offer and accept.
    assert accepted.state.colonies["c1"].resources.food == before_c1_food + 5 - 4
    assert accepted.state.colonies["c2"].resources.food == before_c2_food - 5 - 4
    assert accepted.state.colonies["c2"].resources.wood == before_c2_wood + 10
    assert (
        accepted.state.colonies["c1"].resources.wood
        + accepted.state.colonies["c2"].resources.wood
        == before_c1_wood + before_c2_wood
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
