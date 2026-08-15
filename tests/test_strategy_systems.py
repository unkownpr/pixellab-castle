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


def quiet_hazards(sim: SimCore) -> SimCore:
    """Push the hazard schedule out of reach so a test measures only what it set up.

    Fire ignites per colony on its own clock, and with the headquarters exempt a colony
    holding exactly one other structure — which is what most of these tests build — sees
    that structure catch fire the moment its clock comes round. Tests about trade ratios
    or raid damage should fail when trade or raiding breaks, not when the weather turns.
    """
    sim.scenario = replace(sim.scenario, hazard_cadence=10**6)
    return sim


def arm(sim: SimCore, colony_id: str) -> SimCore:
    """Put a colony on an expansionist footing without spending its turn on the policy.

    Raiding from the default peaceful posture is refused, which is the point of the
    posture — but a test about what a raid does should not have to spend a turn and a
    policy cooldown establishing that the raider means it.
    """
    colonies = dict(sim.state.colonies)
    colony = colonies[colony_id]
    policies = dict(colony.policies)
    policies["military_posture"] = MilitaryPosture.EXPANSIONIST.value
    colonies[colony_id] = replace(colony, policies=policies)
    sim.state = replace(sim.state, colonies=colonies)
    return sim


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
    sim = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=2))
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
    sim = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=29, colony_count=2))
    influence_before = sim.state.colonies["c1"].resources.influence

    sim.resolve((batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),))
    # Set military posture to allow raiding
    sim.resolve((batch(sim, "c1", SetPolicyAction(policy="military_posture", value="expansionist")),))
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
    # Add a house so fire has something to burn (HQ is exempt from fire per AM-1)
    add_structure(sim, "c1", StructureKind.HOUSE)
    # With per-colony fire using derive_seed, fire cadence is hazard_cadence + 4 (AM-15).
    # Grassland: 11 + 4 = 15. Fire for c1 triggers at turns 11, 26, 41, ...
    # (fire_seed % 15 = 4, so turn = (15 - 4) % 15 = 11 + 15*k)
    sim.state = replace(sim.state, turn=11)

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
    # Fire hazard every turn for burning (damage/spread); using turn 0 to test damage immediately
    sim.state = replace(sim.state, structures=structures, turn=0)

    result = sim.resolve(all_wait(sim))

    assert result.state.structures["s1"].status == StructureStatus.BURNING
    assert result.state.structures["s1"].condition < 100
    assert result.state.structures["s2"].status == StructureStatus.BURNING
    assert any(event.kind == "fire_damage" for event in result.events)
    assert any(event.kind == "fire_spread" for event in result.events)


def test_burning_structure_keeps_burning_until_ruined() -> None:
    """A fire persists across consecutive turns until condition reaches zero."""
    sim = SimCore.create(BASIC_SURVIVAL, seed=37, colony_count=1)
    structures = dict(sim.state.structures)
    headquarters = structures["s1"]
    structures["s1"] = replace(headquarters, status=StructureStatus.BURNING)
    sim.state = replace(sim.state, structures=structures, turn=0)

    conditions = []
    for i in range(3):
        # Fire damage (40 per turn) reduces condition every turn: 100 -> 60 -> 20 -> 0/ruined
        sim.state = replace(sim.state, turn=i)
        result = sim.resolve(all_wait(sim))
        structure = result.state.structures["s1"]
        conditions.append((structure.status, structure.condition))

    assert conditions == [
        (StructureStatus.BURNING, 60),
        (StructureStatus.BURNING, 20),
        (StructureStatus.RUINED, 0),
    ]


def test_fire_ruining_emits_events_and_stops() -> None:
    """Ruining a structure emits fire_damage with the ruined status and ignites nothing new."""
    sim = SimCore.create(BASIC_SURVIVAL, seed=37, colony_count=1)
    structures = dict(sim.state.structures)
    headquarters = structures["s1"]
    structures["s1"] = replace(headquarters, status=StructureStatus.BURNING)
    sim.state = replace(sim.state, structures=structures, turn=0)

    damage_events = []
    for i in range(3):
        sim.state = replace(sim.state, turn=i)
        result = sim.resolve(all_wait(sim))
        damage_events.extend(event for event in result.events if event.kind == "fire_damage")

    assert [event.data["status"] for event in damage_events] == [
        StructureStatus.BURNING.value,
        StructureStatus.BURNING.value,
        StructureStatus.RUINED.value,
    ]
    assert damage_events[-1].data["condition"] == 0
    assert result.state.structures["s1"].status == StructureStatus.RUINED

    # Once ruined the fire is out: the next turn ignites nothing new.
    sim.state = replace(sim.state, turn=3)
    final = sim.resolve(all_wait(sim))
    assert not any(event.kind == "fire_started" for event in final.events)
    assert final.state.structures["s1"].status == StructureStatus.RUINED


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
    """The clinic spends its one heal on the sick before it touches the injured.

    Rest mends an injured colonist on its own every second well-supplied turn, so the
    test starts on an odd turn: on that turn the only healing available is the clinic's,
    which is what the ordering claim is about.
    """
    sim = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    colonies = dict(sim.state.colonies)
    colonies["c1"] = replace(colonies["c1"], sick=1, injured=1)
    sim.state = replace(sim.state, colonies=colonies, turn=1)
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
    sim = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=2))
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
        sim = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=2))
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
        arm(sim, "c1")
        sim.resolve((batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),))
        if barracks:
            add_structure(sim, "c2", StructureKind.BARRACKS)
        result = sim.resolve((batch(sim, "c1", RaidAction(target_colony_id="c2")),))
        return next(event.data["stolen_food"] for event in result.events if event.kind in ("raid", "surprise_raid"))

    # AM-5 rebalanced power: defender gets 2 base + 2 per barracks, attacker gets 3 base.
    # Without barracks: attacker 3 > defender 2, raid succeeds, loot 14.
    # With barracks: attacker 3 < defender 4, raid fails, loot 0.
    # (Note: barracks still reduces successful loot, but the raid itself fails here.)
    assert stolen_food(False) == 14
    assert stolen_food(True) == 0


def test_wall_reduces_structure_damage_from_raid() -> None:
    def raid_target_condition(walled: bool) -> int:
        """AM-5 rebalanced raid power, making defense strong but not absolute.

        Without wall: attacker 3 > defender 2, raid succeeds, HQ takes 20 damage → 80 condition.
        With wall: attacker 3 = defender (2+2 from wall), fails (strict >), no damage → 100 condition.

        The test name is historical; with the new power balance, a wall fully defends
        a bare colony against a default attacker. A committed aggressor needs barracks
        or expansionist posture to overcome the wall.
        """
        sim = SimCore.create(BASIC_SURVIVAL, seed=29, colony_count=2)
        arm(sim, "c1")
        sim.resolve((batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),))
        if walled:
            add_structure(sim, "c2", StructureKind.WALL)
        sim.resolve((batch(sim, "c1", RaidAction(target_colony_id="c2")),))

        if walled:
            # With a wall, raid fails, wall takes no damage
            wall = next(
                structure
                for structure in sim.state.structures.values()
                if structure.colony_id == "c2" and structure.kind == StructureKind.WALL
            )
            return wall.condition
        else:
            # Without a wall, raid succeeds, HQ is the target (only structure)
            hq = next(
                structure
                for structure in sim.state.structures.values()
                if structure.colony_id == "c2" and structure.kind == StructureKind.HEADQUARTERS
            )
            return hq.condition

    assert raid_target_condition(False) == 80
    assert raid_target_condition(True) == 100


def test_gate_permits_trade_while_walled() -> None:
    sim = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=2))
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
        arm(sim, "c1")
        sim.resolve((batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),))
        add_structure(sim, "c2", StructureKind.BARRACKS, status=status)
        result = sim.resolve((batch(sim, "c1", RaidAction(target_colony_id="c2")),))
        return next(event.data["stolen_food"] for event in result.events if event.kind in ("raid", "surprise_raid"))

    # AM-5: Operational barracks add +2 to defender power (cap 3 total). With one operational
    # barracks, defender_power = 2 + 2 = 4, attacker_power = 3, raid fails (0 loot).
    # Damaged barracks don't provide defense (not operational), so defender_power = 2,
    # raid succeeds, loot = 14 (base RAID_FOOD_LOOT, no barracks reduction applies).
    assert stolen_food(StructureStatus.OPERATIONAL) == 0
    assert stolen_food(StructureStatus.DAMAGED) == 14


def test_damaged_wall_does_not_reduce_raid_damage() -> None:
    def target_condition(status: StructureStatus) -> int:
        sim = SimCore.create(BASIC_SURVIVAL, seed=29, colony_count=2)
        arm(sim, "c1")
        sim.resolve((batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),))
        add_structure(sim, "c2", StructureKind.WALL, status=status)
        sim.resolve((batch(sim, "c1", RaidAction(target_colony_id="c2")),))

        if status == StructureStatus.OPERATIONAL:
            # Raid fails, no damage occurs
            hq = next(s for s in sim.state.structures.values()
                     if s.colony_id == "c2" and s.kind == StructureKind.HEADQUARTERS)
            return hq.condition
        else:
            # Raid succeeds, AM-10 excludes HQ when other structures exist,
            # so wall (a damaged structure) is targeted instead
            wall = next(s for s in sim.state.structures.values()
                       if s.colony_id == "c2" and s.kind == StructureKind.WALL)
            return wall.condition

    # Operational wall makes raid fail, so HQ takes no damage = 100.
    # Damaged wall is not operational, so raid succeeds, and by AM-10 the wall
    # (another structure) is targeted, taking full 20 damage = 80.
    assert target_condition(StructureStatus.OPERATIONAL) == 100
    assert target_condition(StructureStatus.DAMAGED) == 80


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
    producer = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1))
    idler = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1))
    add_structure(producer, "c1", StructureKind.FARM)

    for _ in range(BASIC_SURVIVAL.max_turns):
        if producer.state.terminal and idler.state.terminal:
            break
        if not producer.state.terminal:
            producer.resolve(all_wait(producer))
        if not idler.state.terminal:
            idler.resolve(all_wait(idler))

    assert producer.state.colonies["c1"].resources.food > idler.state.colonies["c1"].resources.food


def test_unimplemented_actions_rejected_properly() -> None:
    """MessageAction and DiplomacyRespondAction reject appropriately when conditions aren't met."""
    from castle_benchmark.actions import MessageAction, DiplomacyRespondAction

    sim = SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=2)
    # MessageAction without contact should be rejected
    result = sim.resolve((
        batch(sim, "c1", MessageAction(target_colony_id="c2", text="Hello")),
        batch(sim, "c2", WaitAction()),
    ))
    assert result.action_results[0].code == "target_not_contacted"

    # DiplomacyRespondAction with a non-existent proposal should be rejected
    sim = SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=2)
    result = sim.resolve((
        batch(sim, "c1", DiplomacyRespondAction(proposal_id="p1", accept=True)),
        batch(sim, "c2", WaitAction()),
    ))
    assert result.action_results[0].code == "proposal_unavailable"
