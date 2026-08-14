from dataclasses import replace

from castle_benchmark.actions import (
    ActionBatch,
    BuildAction,
    GatherAction,
    ScoutAction,
    WaitAction,
)
from castle_benchmark.domain import Position, Structure, StructureKind, StructureStatus
from castle_benchmark.engine import GATHER_YIELD_PER_ACTION, SimCore
from castle_benchmark.events import state_hash
from castle_benchmark.persistence import ArtifactWriter
from castle_benchmark.runner import verify_replay
from castle_benchmark.scenarios import BASIC_SURVIVAL


def make_sim(colony_count: int = 1) -> SimCore:
    return SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=colony_count)


def batch(sim: SimCore, colony_id: str, *actions: object) -> ActionBatch:
    return ActionBatch(turn=sim.state.turn, colony_id=colony_id, actions=actions)  # type: ignore[arg-type]


def all_wait(sim: SimCore) -> tuple[ActionBatch, ...]:
    return tuple(batch(sim, colony_id, WaitAction()) for colony_id in sim.state.colonies)


def set_scouting(sim: SimCore, colony_id: str, scouting: int) -> None:
    colonies = dict(sim.state.colonies)
    colonies[colony_id] = replace(colonies[colony_id], scouting=scouting)
    sim.state = replace(sim.state, colonies=colonies)


def add_structure(sim: SimCore, colony_id: str, kind: StructureKind, position: Position) -> str:
    structures = dict(sim.state.structures)
    structure_id = f"s{len(structures) + 1}"
    structures[structure_id] = Structure(
        id=structure_id,
        colony_id=colony_id,
        kind=kind,
        position=position,
        status=StructureStatus.OPERATIONAL,
        progress=1,
        required_progress=1,
    )
    sim.state = replace(sim.state, structures=structures)
    return structure_id


def wood_cell(sim: SimCore, colony_id: str, min_amount: int = 1) -> Position:
    for position in sorted(sim.state.world.cells, key=lambda p: (p.y, p.x)):  # type: ignore[attr-defined]
        cell = sim.state.world.cells[position]  # type: ignore[attr-defined]
        if (
            cell.resource == "wood"
            and cell.resource_amount >= min_amount
            and position in sim.state.colonies[colony_id].known_cells
        ):
            return position
    raise AssertionError("no suitable wood cell")


def any_resource_cell(sim: SimCore, colony_id: str) -> Position | None:
    for position in sorted(sim.state.world.cells, key=lambda p: (p.y, p.x)):  # type: ignore[attr-defined]
        cell = sim.state.world.cells[position]  # type: ignore[attr-defined]
        if (
            cell.resource is not None
            and cell.resource_amount > 0
            and position in sim.state.colonies[colony_id].known_cells
        ):
            return position
    return None


def test_gather_yields_less_while_scouting_and_recovers() -> None:
    """Labour scaling: short-handed gathering recovers once scouts return home."""
    sim = make_sim()
    assert sim.state.colonies["c1"].available_population == 8

    first = wood_cell(sim, "c1", min_amount=GATHER_YIELD_PER_ACTION)
    before = sim.state.colonies["c1"].resources.wood
    sim.resolve((batch(sim, "c1", GatherAction(first)),))
    assert sim.state.colonies["c1"].resources.wood == before + GATHER_YIELD_PER_ACTION

    # Yield is proportional, so it drops from the very first colonist sent away
    # rather than only once the colony is nearly empty: six of eight at home.
    set_scouting(sim, "c1", 2)
    assert sim.state.colonies["c1"].available_population == 6
    partial = wood_cell(sim, "c1", min_amount=GATHER_YIELD_PER_ACTION)
    before = sim.state.colonies["c1"].resources.wood
    sim.resolve((batch(sim, "c1", GatherAction(partial)),))
    assert sim.state.colonies["c1"].resources.wood == before + 3

    set_scouting(sim, "c1", 6)
    assert sim.state.colonies["c1"].available_population == 2
    second = wood_cell(sim, "c1", min_amount=GATHER_YIELD_PER_ACTION)
    before = sim.state.colonies["c1"].resources.wood
    sim.resolve((batch(sim, "c1", GatherAction(second)),))
    assert sim.state.colonies["c1"].resources.wood == before + 1

    set_scouting(sim, "c1", 0)
    assert sim.state.colonies["c1"].available_population == 8
    third = wood_cell(sim, "c1", min_amount=GATHER_YIELD_PER_ACTION)
    before = sim.state.colonies["c1"].resources.wood
    sim.resolve((batch(sim, "c1", GatherAction(third)),))
    assert sim.state.colonies["c1"].resources.wood == before + GATHER_YIELD_PER_ACTION


def test_short_handed_colony_staffs_producers_in_stable_id_order() -> None:
    """One worker runs one producer; a short-handed colony staffs by id order."""
    producer = make_sim()
    control = make_sim()
    spawn = producer.state.colonies["c1"].spawn
    add_structure(producer, "c1", StructureKind.FARM, Position(spawn.x + 1, spawn.y))
    add_structure(producer, "c1", StructureKind.WELL, Position(spawn.x + 2, spawn.y))
    set_scouting(producer, "c1", 7)
    assert producer.state.colonies["c1"].available_population == 1

    producer.resolve(all_wait(producer))
    control.resolve(all_wait(control))

    # The farm (lower id) is staffed, the well is left idle.
    assert producer.state.colonies["c1"].resources.food == control.state.colonies["c1"].resources.food + 2
    assert producer.state.colonies["c1"].resources.water == control.state.colonies["c1"].resources.water


def test_fully_staffed_colony_runs_every_producer() -> None:
    """With enough hands at home, every OPERATIONAL producer runs."""
    producer = make_sim()
    control = make_sim()
    spawn = producer.state.colonies["c1"].spawn
    add_structure(producer, "c1", StructureKind.FARM, Position(spawn.x + 1, spawn.y))
    add_structure(producer, "c1", StructureKind.WELL, Position(spawn.x + 2, spawn.y))
    assert producer.state.colonies["c1"].available_population == 8

    producer.resolve(all_wait(producer))
    control.resolve(all_wait(control))

    assert producer.state.colonies["c1"].resources.food == control.state.colonies["c1"].resources.food + 2
    assert producer.state.colonies["c1"].resources.water == control.state.colonies["c1"].resources.water + 2


def test_staffing_rule_is_deterministic() -> None:
    """Identical short-handed setups resolve to identical state hashes."""

    def resolve_once() -> str:
        sim = make_sim()
        spawn = sim.state.colonies["c1"].spawn
        add_structure(sim, "c1", StructureKind.FARM, Position(spawn.x + 1, spawn.y))
        add_structure(sim, "c1", StructureKind.WELL, Position(spawn.x + 2, spawn.y))
        set_scouting(sim, "c1", 7)
        sim.resolve(all_wait(sim))
        return state_hash(sim.state)

    assert resolve_once() == resolve_once()


def test_action_budget_shrinks_while_scouting_and_rejects_surplus() -> None:
    """The work budget stays capped at two, but scouting can pull it below that.

    Seven of eight colonists away leaves one hand at home, so only one action lands
    and the surplus is rejected rather than silently dropped.
    """
    sim = make_sim()
    set_scouting(sim, "c1", 7)
    assert sim.state.colonies["c1"].available_population == 1

    result = sim.resolve((batch(sim, "c1", *(WaitAction(),) * 3),))

    assert [item.code for item in result.action_results] == ["ok"] + ["action_budget_exceeded"] * 2
    assert len(result.action_results) == 3


def test_action_budget_ceiling_is_unchanged_by_a_full_colony() -> None:
    """A colony with everyone home still gets the standing budget, not one per colonist."""
    sim = make_sim()
    assert sim.state.colonies["c1"].available_population == 8

    result = sim.resolve((batch(sim, "c1", *(WaitAction(),) * 4),))

    assert [item.code for item in result.action_results] == ["ok"] * 2 + [
        "action_budget_exceeded"
    ] * 2


def test_labour_constrained_match_round_trips_replay(tmp_path) -> None:
    """A match that builds, scouts and gathers under labour limits reproduces its hashes."""
    sim = make_sim()
    writer = ArtifactWriter.create(
        tmp_path / "run",
        scenario=BASIC_SURVIVAL,
        seed=17,
        colony_count=1,
        controller_names={"c1": "manual"},
    )
    spawn = sim.state.colonies["c1"].spawn
    build_spot = next(
        position
        for position in sorted(sim.state.world.cells, key=lambda p: (p.y, p.x))  # type: ignore[attr-defined]
        if position in sim.state.colonies["c1"].known_cells
        and sim.state.world.cells[position].buildable  # type: ignore[attr-defined]
        and position != spawn
    )
    plan = (
        BuildAction(StructureKind.FARM, build_spot),
        ScoutAction(Position(spawn.x + 8, spawn.y)),
    )
    while not sim.state.terminal:
        if sim.state.turn < len(plan):
            action = plan[sim.state.turn]
        else:
            position = any_resource_cell(sim, "c1")
            action = GatherAction(position) if position else WaitAction()
        batches = (batch(sim, "c1", action),)
        result = sim.resolve(batches)
        writer.write_turn(batches, result)
    writer.finish(sim.state, metrics={})

    verification = verify_replay(writer.run_dir)

    assert verification.ok
    assert verification.actual_hashes == verification.expected_hashes
