from dataclasses import replace

import pytest

from castle_benchmark.actions import (
    ActionBatch,
    DiplomacyAction,
    GatherAction,
    TradeOfferAction,
    TradeRespondAction,
    WaitAction,
)
from castle_benchmark.agents import AGENT_TYPES
from castle_benchmark.domain import Position, Structure, StructureKind, StructureStatus
from castle_benchmark.engine import SimCore
from castle_benchmark.observation import project_observation
from castle_benchmark.scenarios import BASIC_SURVIVAL
from castle_benchmark.systems import (
    PERISHABLE_BASE_CAPACITY,
    WAREHOUSE_CAPACITY_BONUS,
    perishable_capacity,
)


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


def set_resources(sim: SimCore, colony_id: str, **values: int) -> None:
    colonies = dict(sim.state.colonies)
    colonies[colony_id] = replace(
        colonies[colony_id], resources=replace(colonies[colony_id].resources, **values)
    )
    sim.state = replace(sim.state, colonies=colonies)


def food_cell(sim: SimCore, colony_id: str = "c1") -> Position:
    world = sim.state.world
    colony = sim.state.colonies[colony_id]
    for position in sorted(colony.known_cells, key=lambda p: (p.y, p.x)):
        cell = world.cells[position]
        if cell.buildable:
            cells = dict(world.cells)
            cells[position] = replace(cell, resource="food", resource_amount=100)
            sim.state = replace(sim.state, world=replace(world, cells=cells))
            return position
    raise AssertionError("no known buildable cell")


def test_food_and_water_stop_at_cap_while_wood_stone_ore_accumulate() -> None:
    """Perishables are capped by storage; non-perishables keep accumulating."""
    sim = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    for kind in (
        StructureKind.FARM,
        StructureKind.WELL,
        StructureKind.LUMBER_CAMP,
        StructureKind.QUARRY,
        StructureKind.MINE,
    ):
        add_structure(sim, "c1", kind)
    set_resources(
        sim, "c1", food=PERISHABLE_BASE_CAPACITY - 1, water=PERISHABLE_BASE_CAPACITY - 1
    )

    result = sim.resolve(all_wait(sim))

    production = next(event for event in result.events if event.kind == "production")
    assert production.data["resources"] == {
        "food": 1,
        "water": 1,
        "wood": 2,
        "stone": 2,
        "ore": 2,
    }
    assert result.state.colonies["c1"].resources.food <= PERISHABLE_BASE_CAPACITY
    assert result.state.colonies["c1"].resources.water <= PERISHABLE_BASE_CAPACITY


def test_operational_warehouse_raises_capacity() -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    assert perishable_capacity(sim.state.structures, "c1") == {
        "food": PERISHABLE_BASE_CAPACITY,
        "water": PERISHABLE_BASE_CAPACITY,
    }

    add_structure(sim, "c1", StructureKind.WAREHOUSE)

    assert perishable_capacity(sim.state.structures, "c1") == {
        "food": PERISHABLE_BASE_CAPACITY + WAREHOUSE_CAPACITY_BONUS,
        "water": PERISHABLE_BASE_CAPACITY + WAREHOUSE_CAPACITY_BONUS,
    }


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
def test_non_operational_warehouse_raises_nothing(status) -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    add_structure(sim, "c1", StructureKind.WAREHOUSE, status=status)

    assert perishable_capacity(sim.state.structures, "c1") == {
        "food": PERISHABLE_BASE_CAPACITY,
        "water": PERISHABLE_BASE_CAPACITY,
    }


def test_warehouse_raises_the_gather_cap() -> None:
    """An operational warehouse lets a full colony keep gathering perishables."""
    sim = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    position = food_cell(sim)
    set_resources(sim, "c1", food=PERISHABLE_BASE_CAPACITY)

    full = sim.resolve((batch(sim, "c1", GatherAction(position)),))
    assert full.action_results[0].code == "store_full"
    assert full.state.world.cells[position].resource_amount == 100

    add_structure(sim, "c1", StructureKind.WAREHOUSE)
    stored = sim.resolve((batch(sim, "c1", GatherAction(position)),))

    assert stored.action_results[0].code == "ok"
    assert stored.state.world.cells[position].resource_amount == 96


def test_gathering_into_a_full_store_is_rejected_not_dropped() -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    position = food_cell(sim)
    set_resources(sim, "c1", food=PERISHABLE_BASE_CAPACITY)

    result = sim.resolve((batch(sim, "c1", GatherAction(position)),))

    assert result.action_results[0].status == "rejected"
    assert result.action_results[0].code == "store_full"
    assert result.state.world.cells[position].resource_amount == 100
    assert result.state.colonies["c1"].resources.food <= PERISHABLE_BASE_CAPACITY


def test_production_stops_at_cap_and_reports_actual_yield() -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    add_structure(sim, "c1", StructureKind.FARM)
    add_structure(sim, "c1", StructureKind.LUMBER_CAMP)
    set_resources(sim, "c1", food=PERISHABLE_BASE_CAPACITY)

    result = sim.resolve(all_wait(sim))

    production = next(event for event in result.events if event.kind == "production")
    assert production.data["resources"] == {"wood": 2}
    assert result.state.colonies["c1"].resources.food <= PERISHABLE_BASE_CAPACITY


def test_trade_that_would_overfill_a_store_is_refused() -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=2)
    sim.resolve(
        (
            batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),
            batch(sim, "c2", DiplomacyAction(target_colony_id="c1", operation="contact")),
        )
    )
    set_resources(sim, "c2", food=PERISHABLE_BASE_CAPACITY)

    offered = sim.resolve(
        (
            batch(
                sim,
                "c1",
                TradeOfferAction(
                    target_colony_id="c2",
                    give=(("food", 4),),
                    receive=(("wood", 2),),
                ),
            ),
        )
    )
    offer_id = next(event.data["offer_id"] for event in offered.events if event.kind == "trade_offered")

    result = sim.resolve((batch(sim, "c2", TradeRespondAction(offer_id=offer_id, accept=True)),))

    assert result.action_results[0].status == "rejected"
    assert result.action_results[0].code == "store_full"
    assert sim.state.offers[offer_id].status == "open"


@pytest.mark.parametrize("seed", [17, 23, 91])
def test_four_colony_match_finishes_with_every_colony_alive(seed) -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=seed, colony_count=4)
    kinds = ("survivalist", "trader", "expansionist", "militarist")
    controllers = {
        f"c{index + 1}": AGENT_TYPES[kind](seed=seed + index + 1)
        for index, kind in enumerate(kinds)
    }
    while not sim.state.terminal:
        batches = tuple(
            controllers[colony_id].decide(project_observation(sim.state, colony_id))
            for colony_id in sorted(controllers)
        )
        sim.resolve(batches)

    assert sim.state.termination_reason == "turn_limit"
    assert all(colony.population > 0 for colony in sim.state.colonies.values())
