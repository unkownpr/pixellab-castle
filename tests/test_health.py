import json
from dataclasses import replace

from castle_benchmark.actions import ActionBatch, WaitAction
from castle_benchmark.domain import Position, Structure, StructureKind, StructureStatus
from castle_benchmark.engine import SimCore
from castle_benchmark.persistence import ArtifactWriter
from castle_benchmark.runner import verify_replay
from castle_benchmark.scenarios import BASIC_SURVIVAL


def make_sim(colony_count: int = 1) -> SimCore:
    return SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=colony_count)


def batch(sim: SimCore, colony_id: str, *actions: object) -> ActionBatch:
    return ActionBatch(turn=sim.state.turn, colony_id=colony_id, actions=actions)  # type: ignore[arg-type]


def all_wait(sim: SimCore) -> tuple[ActionBatch, ...]:
    return tuple(batch(sim, colony_id, WaitAction()) for colony_id in sim.state.colonies)


def set_sick(sim: SimCore, colony_id: str, sick: int) -> None:
    colonies = dict(sim.state.colonies)
    colonies[colony_id] = replace(colonies[colony_id], sick=sick)
    sim.state = replace(sim.state, colonies=colonies)


def starve(sim: SimCore, colony_id: str) -> None:
    colonies = dict(sim.state.colonies)
    colonies[colony_id] = replace(
        colonies[colony_id],
        resources=replace(colonies[colony_id].resources, food=0, water=0),
    )
    sim.state = replace(sim.state, colonies=colonies)


def add_clinic(sim: SimCore, colony_id: str, status: StructureStatus) -> None:
    structures = dict(sim.state.structures)
    structure_id = f"s{len(structures) + 1}"
    spawn = sim.state.colonies[colony_id].spawn
    structures[structure_id] = Structure(
        id=structure_id,
        colony_id=colony_id,
        kind=StructureKind.CLINIC,
        position=Position(spawn.x + 1, spawn.y),
        status=status,
        progress=1,
        required_progress=1,
    )
    sim.state = replace(sim.state, structures=structures)


def test_unmet_needs_accumulate_sick_deterministically() -> None:
    """A colony that cannot meet its needs falls sick, identically every run."""

    def sick_after_two_turns() -> int:
        sim = make_sim()
        starve(sim, "c1")
        sim.resolve(all_wait(sim))
        sim.resolve(all_wait(sim))
        return sim.state.colonies["c1"].sick

    assert sick_after_two_turns() == 2
    assert sick_after_two_turns() == 2


def test_starvation_death_claims_a_sick_colonist() -> None:
    """Starvation kills the sick first instead of skipping straight past them."""
    sim = make_sim()
    starve(sim, "c1")
    sim.resolve(all_wait(sim))
    sim.resolve(all_wait(sim))
    # Third shortfall turn triggers a death; the freshly-sickened colonist is the one lost.
    result = sim.resolve(all_wait(sim))

    assert any(event.kind == "population_died" for event in result.events)
    colony = result.state.colonies["c1"]
    assert colony.population == 7
    assert colony.sick + colony.injured <= colony.population


def test_operational_clinic_heals_sick_faster_than_nature() -> None:
    def sick_after_one_turn(with_clinic: bool) -> int:
        sim = make_sim()
        set_sick(sim, "c1", 4)
        if with_clinic:
            add_clinic(sim, "c1", StructureStatus.OPERATIONAL)
        sim.resolve(all_wait(sim))
        return sim.state.colonies["c1"].sick

    # Natural recovery alone heals one per turn; a clinic heals a second one.
    assert sick_after_one_turn(False) == 3
    assert sick_after_one_turn(True) == 2


def test_ruined_clinic_heals_nothing() -> None:
    def sick_after_one_turn(status: StructureStatus) -> int:
        sim = make_sim()
        set_sick(sim, "c1", 4)
        add_clinic(sim, "c1", status)
        sim.resolve(all_wait(sim))
        return sim.state.colonies["c1"].sick

    assert sick_after_one_turn(StructureStatus.RUINED) == 3
    assert sick_after_one_turn(StructureStatus.OPERATIONAL) == 2


def test_fixing_supply_recovers_sick_without_clinic() -> None:
    sim = make_sim()
    set_sick(sim, "c1", 3)

    sim.resolve(all_wait(sim))
    assert sim.state.colonies["c1"].sick == 2
    sim.resolve(all_wait(sim))
    assert sim.state.colonies["c1"].sick == 1
    sim.resolve(all_wait(sim))
    assert sim.state.colonies["c1"].sick == 0


def test_sickness_path_round_trips_replay(tmp_path) -> None:
    """A match that starves a colony reproduces its hashes, sickness included."""
    sim = make_sim()
    writer = ArtifactWriter.create(
        tmp_path / "run",
        scenario=BASIC_SURVIVAL,
        seed=17,
        colony_count=1,
        controller_names={"c1": "wait"},
    )
    while not sim.state.terminal:
        batches = (batch(sim, "c1", WaitAction()),)
        result = sim.resolve(batches)
        writer.write_turn(batches, result)
    writer.finish(sim.state, metrics={})

    records = [json.loads(line) for line in writer.events_path.read_text().splitlines()]
    sick_events = [
        event
        for record in records
        for event in record["events"]
        if event["kind"] == "colonist_sickened"
    ]
    assert sick_events

    verification = verify_replay(writer.run_dir)
    assert verification.ok
    assert verification.actual_hashes == verification.expected_hashes
