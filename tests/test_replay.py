import json

from castle_benchmark.actions import ActionBatch, WaitAction
from castle_benchmark.engine import SimCore
from castle_benchmark.events import state_hash
from castle_benchmark.persistence import ArtifactWriter
from castle_benchmark.runner import verify_replay
from castle_benchmark.scenarios import BASIC_SURVIVAL


def test_equivalent_states_have_same_canonical_hash() -> None:
    """Catches object identity or dictionary insertion order affecting run hashes."""
    first = SimCore.create(BASIC_SURVIVAL, seed=47, colony_count=2)
    second = SimCore.create(BASIC_SURVIVAL, seed=47, colony_count=2)

    assert state_hash(first.state) == state_hash(second.state)


def test_replay_reproduces_hash_sequence(tmp_path) -> None:
    """Catches persisted action streams that cannot reproduce the original match."""
    sim = SimCore.create(BASIC_SURVIVAL, seed=53, colony_count=2)
    writer = ArtifactWriter.create(
        tmp_path / "run",
        scenario=BASIC_SURVIVAL,
        seed=53,
        colony_count=2,
        controller_names={"c1": "wait", "c2": "wait"},
    )
    while not sim.state.terminal:
        batches = tuple(
            ActionBatch(sim.state.turn, colony_id, (WaitAction(),))
            for colony_id in sim.state.colonies
        )
        result = sim.resolve(batches)
        writer.write_turn(batches, result)
    writer.finish(sim.state, metrics={})

    verification = verify_replay(writer.run_dir)

    assert verification.ok
    assert verification.actual_hashes == verification.expected_hashes
    metadata = json.loads(writer.metadata_path.read_text())
    assert set(metadata["dependency_lock_hashes"]) == {"uv.lock", "frontend/package-lock.json"}
    assert all(len(value) == 64 for value in metadata["dependency_lock_hashes"].values())


def test_replay_fails_closed_when_hash_is_corrupted(tmp_path) -> None:
    """Catches a replay verifier accepting altered benchmark artifacts."""
    sim = SimCore.create(BASIC_SURVIVAL, seed=59, colony_count=1)
    writer = ArtifactWriter.create(
        tmp_path / "run",
        scenario=BASIC_SURVIVAL,
        seed=59,
        colony_count=1,
        controller_names={"c1": "wait"},
    )
    batch = ActionBatch(sim.state.turn, "c1", (WaitAction(),))
    result = sim.resolve((batch,))
    writer.write_turn((batch,), result)
    writer.finish(sim.state, metrics={})
    lines = writer.events_path.read_text().splitlines()
    record = json.loads(lines[0])
    record["state_hash"] = "0" * 64
    writer.events_path.write_text(json.dumps(record) + "\n")

    verification = verify_replay(writer.run_dir)

    assert not verification.ok
    assert verification.first_mismatch_turn == 0


def test_replay_fails_closed_when_turn_log_is_truncated(tmp_path) -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=60, colony_count=1)
    writer = ArtifactWriter.create(tmp_path / "run", BASIC_SURVIVAL, 60, 1, {"c1": "wait"})
    while not sim.state.terminal:
        batch = ActionBatch(sim.state.turn, "c1", (WaitAction(),))
        result = sim.resolve((batch,))
        writer.write_turn((batch,), result)
    writer.finish(sim.state, metrics={})
    writer.events_path.write_text(writer.events_path.read_text().splitlines()[0] + "\n")

    assert not verify_replay(writer.run_dir).ok


def test_tenure_and_action_attribution_are_artifact_metadata_not_replay_inputs(tmp_path) -> None:
    """Catches controller telemetry either leaking into replay input or being omitted from artifacts."""
    sim = SimCore.create(BASIC_SURVIVAL, seed=61, colony_count=1)
    writer = ArtifactWriter.create(
        tmp_path / "run",
        BASIC_SURVIVAL,
        61,
        1,
        {"c1": "external"},
        controller_tenures=[
            {
                "colony_id": "c1",
                "controller_id": "controller-a",
                "controller_type": "external",
                "started_at": 1_000.0,
                "ended_at": None,
            }
        ],
    )
    while not sim.state.terminal:
        batch = ActionBatch(sim.state.turn, "c1", (WaitAction(),))
        result = sim.resolve((batch,))
        writer.write_turn((batch,), result, action_controller_ids={"c1": "controller-a"})
    writer.finish(sim.state, metrics={})

    metadata = json.loads(writer.metadata_path.read_text())
    turn_record = json.loads(writer.events_path.read_text().splitlines()[0])

    assert metadata["controller_tenures"][0]["controller_id"] == "controller-a"
    assert turn_record["action_controller_ids"] == {"c1": "controller-a"}
    assert verify_replay(writer.run_dir).ok
