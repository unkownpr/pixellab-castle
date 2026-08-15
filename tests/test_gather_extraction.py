from dataclasses import replace

import pytest

from castle_benchmark.actions import ActionBatch, GatherAction
from castle_benchmark.domain import Position, Structure, StructureKind, StructureStatus
from castle_benchmark.engine import (
    GATHER_PENALTY_DIVISOR,
    GATHER_RADIUS,
    GATHER_YIELD_PER_ACTION,
    SimCore,
)
from castle_benchmark.scenarios import BASIC_SURVIVAL


def make_sim() -> SimCore:
    return SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)


def batch(sim: SimCore, colony_id: str, *actions: object) -> ActionBatch:
    return ActionBatch(turn=sim.state.turn, colony_id=colony_id, actions=actions)  # type: ignore[arg-type]


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


def set_scouting(sim: SimCore, colony_id: str, scouting: int) -> None:
    colonies = dict(sim.state.colonies)
    colonies[colony_id] = replace(colonies[colony_id], scouting=scouting)
    sim.state = replace(sim.state, colonies=colonies)


def set_cell_resource(sim: SimCore, colony_id: str, resource: str, amount: int = 100) -> Position:
    colony = sim.state.colonies[colony_id]
    world = sim.state.world
    spawn = colony.spawn
    # Find the first known cell within GATHER_RADIUS of the spawn (HQ location)
    position = next(
        iter(sorted(
            (p for p in colony.known_cells
             if abs(p.x - spawn.x) + abs(p.y - spawn.y) <= GATHER_RADIUS),
            key=lambda p: (p.y, p.x)
        ))
    )
    cells = dict(world.cells)
    cells[position] = replace(world.cells[position], resource=resource, resource_amount=amount)
    sim.state = replace(sim.state, world=replace(world, cells=cells))
    return position


def gathered_amount(sim: SimCore, position: Position, resource: str) -> int:
    """The yield the gather action reports, isolated from production and needs."""
    result = sim.resolve((batch(sim, "c1", GatherAction(position)),))
    event = next(event for event in result.events if event.kind == "resource_gathered")
    assert event.data is not None
    assert event.data["resource"] == resource
    return int(event.data["amount"])


@pytest.mark.parametrize(
    ("resource", "kind"),
    [
        ("wood", StructureKind.LUMBER_CAMP),
        ("stone", StructureKind.QUARRY),
        ("ore", StructureKind.MINE),
    ],
)
def test_extraction_structure_restores_full_gather_yield(resource, kind) -> None:
    """Gathering without the matching structure yields half; with it, full."""
    bare = make_sim()
    position = set_cell_resource(bare, "c1", resource)
    assert gathered_amount(bare, position, resource) == GATHER_YIELD_PER_ACTION // GATHER_PENALTY_DIVISOR

    equipped = make_sim()
    position = set_cell_resource(equipped, "c1", resource)
    add_structure(equipped, "c1", kind)
    assert gathered_amount(equipped, position, resource) == GATHER_YIELD_PER_ACTION


@pytest.mark.parametrize(
    "status",
    [
        StructureStatus.RUINED,
        StructureStatus.FOUNDATION,
        StructureStatus.BUILDING,
        StructureStatus.DAMAGED,
        StructureStatus.BURNING,
    ],
)
def test_non_operational_camp_restores_nothing(status) -> None:
    """Only an OPERATIONAL structure counts; every other status yields half."""
    sim = make_sim()
    position = set_cell_resource(sim, "c1", "wood")
    add_structure(sim, "c1", StructureKind.LUMBER_CAMP, status=status)

    assert gathered_amount(sim, position, "wood") == GATHER_YIELD_PER_ACTION // GATHER_PENALTY_DIVISOR


@pytest.mark.parametrize("resource", ["food", "water"])
def test_food_and_water_are_unaffected(resource) -> None:
    """Resources with no extraction building keep their full yield."""
    sim = make_sim()
    position = set_cell_resource(sim, "c1", resource)

    assert gathered_amount(sim, position, resource) == GATHER_YIELD_PER_ACTION


def test_penalty_composes_with_labour_scaling_in_chosen_order() -> None:
    """Labour scaling runs first, then the halving; a positive gather never hits zero."""

    def wood_gain(scouting: int, camp: bool) -> int:
        sim = make_sim()
        if camp:
            add_structure(sim, "c1", StructureKind.LUMBER_CAMP)
        set_scouting(sim, "c1", scouting)
        position = set_cell_resource(sim, "c1", "wood")
        return gathered_amount(sim, position, "wood")

    # Labour scaling (4 * available // population) runs first, halving second.
    assert wood_gain(0, camp=True) == 4  # 8/8 hands, full yield
    assert wood_gain(0, camp=False) == 2  # 8/8 hands, halved
    assert wood_gain(2, camp=True) == 3  # 6/8 hands
    assert wood_gain(2, camp=False) == 1  # 6/8 hands, halved: floor(3 / 2)
    assert wood_gain(6, camp=True) == 1  # 2/8 hands
    assert wood_gain(6, camp=False) == 1  # 2/8 hands, halved: floor(1 / 2) floored at one

    # Both problems together must be worse than either alone...
    assert wood_gain(2, camp=False) < wood_gain(2, camp=True)
    assert wood_gain(2, camp=False) < wood_gain(0, camp=False)
    # ...and a legitimate 2-hands-home gather never rounds to zero.
    assert wood_gain(6, camp=False) > 0
