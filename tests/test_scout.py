from dataclasses import replace

from castle_benchmark.actions import (
    ActionBatch,
    BuildAction,
    ScoutAction,
    WaitAction,
)
from castle_benchmark.domain import Position, StructureKind, StructureStatus
from castle_benchmark.engine import SCOUT_FOOD_COST, SimCore
from castle_benchmark.observation import project_observation
from castle_benchmark.persistence import ArtifactWriter
from castle_benchmark.runner import verify_replay
from castle_benchmark.scenarios import BASIC_SURVIVAL


def batch(sim: SimCore, colony_id: str, *actions: object) -> ActionBatch:
    return ActionBatch(turn=sim.state.turn, colony_id=colony_id, actions=actions)  # type: ignore[arg-type]


def all_wait(sim: SimCore) -> tuple[ActionBatch, ...]:
    return tuple(batch(sim, colony_id, WaitAction()) for colony_id in sim.state.colonies)


def test_scout_reveals_previously_unseen_cells_as_it_travels() -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    colony = sim.state.colonies["c1"]
    target = Position(16, 16)
    assert target not in colony.known_cells
    initial = len(colony.known_cells)

    result = sim.resolve((batch(sim, "c1", ScoutAction(target)),))

    assert any(event.kind == "scout_dispatched" for event in result.events)
    assert sim.state.colonies["c1"].scouting == 1

    revealed_events = []
    arrival_events = []
    for _ in range(20):
        resolved = sim.resolve(all_wait(sim))
        revealed_events.extend(event for event in resolved.events if event.kind == "scout_revealed")
        arrival_events.extend(event for event in resolved.events if event.kind == "scout_arrived")

    assert target in sim.state.colonies["c1"].known_cells
    assert len(sim.state.colonies["c1"].known_cells) > initial
    assert revealed_events
    assert arrival_events
    assert not sim.state.scouts


def test_terrain_and_structures_persist_but_live_resource_data_does_not() -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=23, colony_count=1)
    target = Position(15, 15)
    sim.resolve((batch(sim, "c1", ScoutAction(target)),))
    while sim.state.scouts:
        sim.resolve(all_wait(sim))

    colony = sim.state.colonies["c1"]
    observation = project_observation(sim.state, "c1")

    revealed_outside_sight = [
        position for position in colony.known_cells if position not in colony.visible_now
    ]
    assert revealed_outside_sight

    cell_map = {Position(int(cell["x"]), int(cell["y"])): cell for cell in observation.visible_cells}
    for position in revealed_outside_sight:
        cell = cell_map[position]
        authoritative = sim.state.world.cells[position]  # type: ignore[attr-defined]
        assert cell["biome"] == authoritative.biome
        assert cell["water"] == authoritative.water
        assert cell["movement_cost"] == authoritative.movement_cost
        if authoritative.resource_amount > 0:
            assert cell["resource_amount"] == 0


def test_observation_never_contains_unexplored_cells() -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=29, colony_count=2)
    sim.resolve((batch(sim, "c1", ScoutAction(Position(16, 3))), batch(sim, "c2", WaitAction())))
    for _ in range(12):
        sim.resolve(all_wait(sim))

    observation = project_observation(sim.state, "c1")
    known = sim.state.colonies["c1"].known_cells
    observed_cells = {Position(int(cell["x"]), int(cell["y"])) for cell in observation.visible_cells}
    assert observed_cells == set(known)
    observed_structures = {
        Position(int(structure["x"]), int(structure["y"]))
        for structure in observation.visible_structures
    }
    assert observed_structures <= set(known)


def test_scout_costs_food_and_occupies_population_until_return() -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=31, colony_count=1)
    control = SimCore.create(BASIC_SURVIVAL, seed=31, colony_count=1)
    target = Position(10, 3)

    sim.resolve((batch(sim, "c1", ScoutAction(target)),))
    control.resolve((batch(control, "c1", WaitAction()),))

    colony = sim.state.colonies["c1"]
    assert colony.scouting == 1
    assert colony.available_population == colony.population - 1
    assert (
        colony.resources.food
        == control.state.colonies["c1"].resources.food - SCOUT_FOOD_COST
    )

    while sim.state.colonies["c1"].scouting:
        sim.resolve(all_wait(sim))

    assert sim.state.colonies["c1"].scouting == 0
    assert sim.state.colonies["c1"].available_population == sim.state.colonies["c1"].population


def test_operational_watchtower_widens_sight_ruined_does_not() -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=37, colony_count=1)
    colony = sim.state.colonies["c1"]
    base_visible = len(colony.visible_now)
    spawn = colony.spawn
    spot = next(
        position
        for position in sim.state.world.cells  # type: ignore[attr-defined]
        if sim.state.world.cells[position].buildable  # type: ignore[attr-defined]
        and abs(position.x - spawn.x) + abs(position.y - spawn.y) == 1
    )

    sim.resolve((batch(sim, "c1", BuildAction(StructureKind.WATCHTOWER, spot)),))
    for _ in range(3):
        sim.resolve(all_wait(sim))
    tower = next(s for s in sim.state.structures.values() if s.kind == StructureKind.WATCHTOWER)
    assert tower.status == StructureStatus.OPERATIONAL

    widened = len(sim.state.colonies["c1"].visible_now)
    assert widened > base_visible

    sim.state = replace(
        sim.state,
        structures={**sim.state.structures, tower.id: replace(tower, status=StructureStatus.RUINED)},
    )
    sim.resolve(all_wait(sim))

    assert len(sim.state.colonies["c1"].visible_now) == base_visible


def test_match_with_scouting_round_trips_replay(tmp_path) -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=41, colony_count=1)
    writer = ArtifactWriter.create(
        tmp_path / "run",
        scenario=BASIC_SURVIVAL,
        seed=41,
        colony_count=1,
        controller_names={"c1": "wait"},
    )
    dispatched = False
    while not sim.state.terminal:
        action = ScoutAction(Position(14, 3)) if not dispatched else WaitAction()
        dispatched = True
        batches = (batch(sim, "c1", action),)
        result = sim.resolve(batches)
        writer.write_turn(batches, result)
    writer.finish(sim.state, metrics={})

    verification = verify_replay(writer.run_dir)

    assert verification.ok
    assert verification.actual_hashes == verification.expected_hashes
