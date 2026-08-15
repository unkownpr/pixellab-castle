from dataclasses import replace

from castle_benchmark.actions import ActionBatch, BuildAction, GatherAction, WaitAction
from castle_benchmark.domain import Position, StructureKind, StructureStatus
from castle_benchmark.engine import SimCore
from castle_benchmark.scenarios import BASIC_SURVIVAL


def make_sim() -> SimCore:
    return SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=2)


def first_buildable_near(sim: SimCore, colony_id: str) -> Position:
    spawn = sim.state.colonies[colony_id].spawn
    occupied = {structure.position for structure in sim.state.structures.values()}
    candidates = sorted(
        sim.state.world.cells,
        key=lambda position: (abs(position.x - spawn.x) + abs(position.y - spawn.y), position.y, position.x),
    )
    return next(
        position
        for position in candidates
        if sim.state.world.cells[position].buildable and position not in occupied
    )


def batch(sim: SimCore, colony_id: str, *actions: object) -> ActionBatch:
    return ActionBatch(turn=sim.state.turn, colony_id=colony_id, actions=actions)  # type: ignore[arg-type]


def waits(sim: SimCore) -> tuple[ActionBatch, ...]:
    return tuple(batch(sim, colony_id, WaitAction()) for colony_id in sim.state.colonies)


def test_house_construction_progresses_before_it_adds_housing() -> None:
    """Catches instant building completion or capacity from unfinished houses."""
    sim = make_sim()
    location = first_buildable_near(sim, "c1")

    started = sim.resolve((batch(sim, "c1", BuildAction(StructureKind.HOUSE, location)),))
    house = next(structure for structure in started.state.structures.values() if structure.kind == StructureKind.HOUSE)

    assert house.status == StructureStatus.FOUNDATION
    assert started.state.colonies["c1"].housing == 8

    sim.resolve(waits(sim))
    completed = sim.resolve(waits(sim))

    assert completed.state.structures[house.id].status == StructureStatus.OPERATIONAL
    assert completed.state.colonies["c1"].housing == 14


def test_house_enables_but_does_not_force_immediate_immigration() -> None:
    """Catches population growth being tied only to placing a house."""
    sim = make_sim()
    location = first_buildable_near(sim, "c1")

    result = sim.resolve((batch(sim, "c1", BuildAction(StructureKind.HOUSE, location)),))

    assert result.state.colonies["c1"].population == 8


def test_two_colonies_cannot_build_on_same_cell() -> None:
    """Catches simultaneous resolution allowing overlapping structures."""
    sim = make_sim()
    location = next(
        position
        for position, cell in sim.state.world.cells.items()
        if cell.buildable and position not in {c.spawn for c in sim.state.colonies.values()}
    )
    colonies = {
        colony_id: replace(colony, known_cells=colony.known_cells | {location})
        for colony_id, colony in sim.state.colonies.items()
    }
    sim.state = replace(sim.state, colonies=colonies)

    result = sim.resolve(
        (
            batch(sim, "c1", BuildAction(StructureKind.HOUSE, location)),
            batch(sim, "c2", BuildAction(StructureKind.HOUSE, location)),
        )
    )

    assert sum(event.kind == "construction_started" for event in result.events) == 1
    rejected = [item for item in result.action_results if item.status == "rejected"]
    assert len(rejected) == 1
    assert rejected[0].code == "cell_occupied"


def test_stale_action_is_measured_as_wait() -> None:
    """Catches stale controller output being applied to a later turn."""
    sim = make_sim()
    stale = ActionBatch(turn=99, colony_id="c1", actions=(WaitAction(),))

    result = sim.resolve((stale,))

    assert any(item.code == "stale_turn" for item in result.action_results)
    assert any(event.kind == "controller_wait" and event.colony_id == "c1" for event in result.events)


def test_gather_depletes_deposit_and_adds_stock() -> None:
    """Catches gathering that creates resources without depleting the map."""
    sim = make_sim()
    position, cell = next(
        (position, cell)
        for position, cell in sim.state.world.cells.items()
        if cell.resource == "wood"
        and cell.resource_amount >= 4
        and position in sim.state.colonies["c1"].known_cells
    )
    before = sim.state.colonies["c1"].resources.wood

    result = sim.resolve((batch(sim, "c1", GatherAction(position)),))

    assert result.state.colonies["c1"].resources.wood == before + 4
    assert result.state.world.cells[position].resource_amount == cell.resource_amount - 4


def test_controller_cannot_gather_or_build_in_hidden_cells() -> None:
    sim = make_sim()
    hidden = next(
        position
        for position, cell in sim.state.world.cells.items()
        if cell.buildable and position not in sim.state.colonies["c1"].known_cells
    )

    result = sim.resolve(
        (batch(sim, "c1", GatherAction(hidden), BuildAction(StructureKind.HOUSE, hidden)),)
    )

    assert [item.code for item in result.action_results] == ["cell_not_visible", "cell_not_visible"]


def test_action_batch_cannot_exceed_per_turn_work_budget() -> None:
    sim = make_sim()
    position = next(
        position
        for position, cell in sim.state.world.cells.items()
        if cell.resource and position in sim.state.colonies["c1"].known_cells
    )

    result = sim.resolve(
        (batch(sim, "c1", GatherAction(position), GatherAction(position), GatherAction(position)),)
    )

    assert [item.code for item in result.action_results] == ["ok", "ok", "action_budget_exceeded"]


def test_scouting_colonists_shrink_the_work_budget() -> None:
    """Catches the work budget ignoring colonists who are away scouting."""
    sim = make_sim()
    colony = sim.state.colonies["c1"]
    sim._update_colony("c1", scouting=colony.population - 1)

    result = sim.resolve((batch(sim, "c1", WaitAction(), WaitAction()),))

    codes = [item.code for item in result.action_results if item.colony_id == "c1"]
    assert codes == ["ok", "action_budget_exceeded"]
