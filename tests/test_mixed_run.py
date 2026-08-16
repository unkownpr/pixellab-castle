"""Tests for mixed model-vs-baseline runs."""

from pathlib import Path

import pytest

from castle_benchmark.runner import MixedRunConfig, run_mixed_match, verify_replay
from castle_benchmark.scenarios import get_scenario


@pytest.mark.parametrize("scenario_id", ["basic-survival-v1", "desert-scarcity-v1"])
def test_mixed_run_with_fallback_baselines(tmp_path: Path, scenario_id: str) -> None:
    """Verify mixed run falls back to baselines when no external agents connect.

    This tests the core mixed-run flow: external seats configured but no agents
    connecting, so they fall back to local baselines. The resulting artifacts
    should be identical to a baseline-only run and replay should verify.
    """
    report = run_mixed_match(
        MixedRunConfig(
            scenario=get_scenario(scenario_id),
            seed=17,
            output_dir=tmp_path,
            external_seat_indices=(1,),  # Seat 1 is external (will fall back)
            baseline_kinds=("survivalist", "trader", "expansionist"),
            external_agent_timeout_seconds=1,  # Short timeout to test fallback
        )
    )

    # Verify artifacts were created
    assert report.run_dir.exists()
    assert report.report_path.exists()
    assert (report.run_dir / "metadata.json").exists()
    assert (report.run_dir / "turns.jsonl").exists()
    assert (report.run_dir / "summary.sqlite3").exists()

    # Verify replay passes (determinism is preserved)
    verification = verify_replay(report.run_dir)
    assert verification.ok, f"Replay failed at turn {verification.first_mismatch_turn}"

    # Verify the report contains expected structure
    import json

    metadata = json.loads((report.run_dir / "metadata.json").read_text())
    assert metadata["scenario"]["id"] == scenario_id
    assert metadata["seed"] == 17
    assert metadata["colony_count"] == 4  # 1 external + 3 baselines

    # Verify controller names record the types
    assert "c1" in metadata["controllers"]
    assert "c2" in metadata["controllers"]
    assert "c3" in metadata["controllers"]
    assert "c4" in metadata["controllers"]

    # Verify external seat fallback is recorded
    assert "external:fallback" in metadata["controllers"]["c1"]
    assert "baseline:" in metadata["controllers"]["c2"]
    assert "baseline:" in metadata["controllers"]["c3"]
    assert "baseline:" in metadata["controllers"]["c4"]


def test_mixed_run_with_specified_baselines(tmp_path: Path) -> None:
    """Verify mixed run with explicit baseline kinds for non-external seats."""
    report = run_mixed_match(
        MixedRunConfig(
            scenario=get_scenario("basic-survival-v1"),
            seed=23,
            output_dir=tmp_path,
            external_seat_indices=(2, 4),  # Seats 2 and 4 are external
            baseline_kinds=("militarist", "expansionist"),  # Seats 1 and 3
            external_agent_timeout_seconds=1,
        )
    )

    # Verify replay passes
    verification = verify_replay(report.run_dir)
    assert verification.ok, f"Replay failed at turn {verification.first_mismatch_turn}"

    # Verify metadata records the right structure
    import json

    metadata = json.loads((report.run_dir / "metadata.json").read_text())
    assert metadata["colony_count"] == 4

    # Verify baseline kinds are assigned correctly
    assert "baseline:militarist" in metadata["controllers"]["c1"]
    assert "external:fallback" in metadata["controllers"]["c2"]
    assert "baseline:expansionist" in metadata["controllers"]["c3"]
    assert "external:fallback" in metadata["controllers"]["c4"]
