import json
import statistics
from pathlib import Path

import pytest

from castle_benchmark.compare import (
    compare_runs,
    format_comparison_table,
    format_within_table,
    within_controller_stats,
    _calculate_ci_half_width,
    _extract_numeric_leaves,
    _get_t_critical,
    _load_run,
    _pair_runs,
    _samples_needed_for_target_margin,
)


def create_mock_run(
    run_dir: Path,
    scenario_id: str = "test-scenario",
    seed: int = 42,
    seat_rotation: int = 0,
    controller_names: dict[str, str] | None = None,
    composites: dict[str, int] | None = None,
    axes: dict[str, dict[str, object]] | None = None,
) -> None:
    """Create a mock run with metadata.json and report.json."""
    run_dir.mkdir(parents=True, exist_ok=True)

    if controller_names is None:
        controller_names = {"c1": "controller-a"}
    if composites is None:
        composites = {"c1": 100}
    if axes is None:
        axes = {
            "survival": {"c1": {"population": 10}},
            "trade": {"c1": 5},
        }

    # Create metadata.json
    metadata = {
        "scenario": {"id": scenario_id, "name": "Test"},
        "seed": seed,
        "colony_count": 1,
        "seat_rotation": seat_rotation,
        "controllers": controller_names,
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata, sort_keys=True))

    # Create report.json
    report = {
        "scenario_id": scenario_id,
        "seed": seed,
        "turns": 50,
        "termination_reason": "max_turns",
        "metrics": {
            "composites": composites,
            **axes,
        },
    }
    (run_dir / "report.json").write_text(json.dumps(report, sort_keys=True))


class TestLoadRun:
    def test_load_valid_run(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run_seed_42"
        create_mock_run(run_dir, seed=42, composites={"c1": 95})

        run_info = _load_run(run_dir)
        assert run_info is not None
        assert run_info.metadata.seed == 42
        assert run_info.metadata.scenario_id == "test-scenario"
        assert run_info.metrics.composites == {"c1": 95}

    def test_load_run_missing_metadata(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "bad_run"
        run_dir.mkdir()
        (run_dir / "report.json").write_text('{"metrics": {}}')

        assert _load_run(run_dir) is None

    def test_load_run_missing_report(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "bad_run"
        run_dir.mkdir()
        (run_dir / "metadata.json").write_text('{"scenario": {"id": "x"}}')

        assert _load_run(run_dir) is None

    def test_load_run_invalid_json(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "bad_run"
        run_dir.mkdir()
        (run_dir / "metadata.json").write_text("not json")
        (run_dir / "report.json").write_text("{}")

        assert _load_run(run_dir) is None


class TestPairingLogic:
    def test_pairing_exact_match(self, tmp_path: Path) -> None:
        """Runs with same scenario, seed, rotation, colony_id should pair."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        # Create matching runs
        run_a = dir_a / "run_seed_42"
        run_b = dir_b / "run_seed_42"
        create_mock_run(run_a, seed=42, composites={"c1": 100})
        create_mock_run(run_b, seed=42, composites={"c1": 105})

        runs_a = [info for info in [_load_run(run_a)] if info]
        runs_b = [info for info in [_load_run(run_b)] if info]

        paired, unpaired_a, unpaired_b = _pair_runs(runs_a, runs_b)

        assert len(paired) == 1
        assert len(unpaired_a) == 0
        assert len(unpaired_b) == 0

    def test_pairing_no_match(self, tmp_path: Path) -> None:
        """Runs with different seeds should not pair."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        run_a = dir_a / "run_seed_42"
        run_b = dir_b / "run_seed_43"
        create_mock_run(run_a, seed=42)
        create_mock_run(run_b, seed=43)

        runs_a = [_load_run(run_a)]
        runs_b = [_load_run(run_b)]

        paired, unpaired_a, unpaired_b = _pair_runs(runs_a, runs_b)

        assert len(paired) == 0
        assert len(unpaired_a) == 1
        assert len(unpaired_b) == 1

    def test_pairing_respects_seat_rotation(self, tmp_path: Path) -> None:
        """Runs must match on seat_rotation to pair."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        run_a = dir_a / "run_seed_42"
        run_b = dir_b / "run_seed_42"
        create_mock_run(run_a, seed=42, seat_rotation=0)
        create_mock_run(run_b, seed=42, seat_rotation=1)

        runs_a = [_load_run(run_a)]
        runs_b = [_load_run(run_b)]

        paired, unpaired_a, unpaired_b = _pair_runs(runs_a, runs_b)

        assert len(paired) == 0
        assert len(unpaired_a) == 1
        assert len(unpaired_b) == 1

    def test_pairing_unpaired_reported_clearly(self, tmp_path: Path) -> None:
        """Unpaired runs should be reported, not silently averaged."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        # Create two runs in a, one in b
        create_mock_run(dir_a / "run1", seed=42)
        create_mock_run(dir_a / "run2", seed=43)
        create_mock_run(dir_b / "run1", seed=42)

        runs_a = [_load_run(dir_a / "run1"), _load_run(dir_a / "run2")]
        runs_b = [_load_run(dir_b / "run1")]

        paired, unpaired_a, unpaired_b = _pair_runs(runs_a, runs_b)

        assert len(paired) == 1
        assert len(unpaired_a) == 1
        assert len(unpaired_b) == 0


class TestTCritical:
    def test_t_critical_known_values(self) -> None:
        """t-critical values should match standard table."""
        assert _get_t_critical(1) == 12.706
        assert _get_t_critical(5) == 2.571
        assert _get_t_critical(30) == 2.042

    def test_t_critical_fallback_for_unknown_df(self) -> None:
        """Unknown df should fall back to closest known value."""
        # df=100 is not in table, should find closest
        result = _get_t_critical(100)
        assert isinstance(result, float)
        assert result > 0


class TestConfidenceIntervalMath:
    def test_ci_half_width_increases_with_variance(self) -> None:
        """Half-width should increase with standard deviation."""
        small_var = _calculate_ci_half_width(stdev=1.0, n=10)
        large_var = _calculate_ci_half_width(stdev=10.0, n=10)
        assert large_var > small_var

    def test_ci_half_width_decreases_with_sample_size(self) -> None:
        """Half-width should decrease with more samples."""
        small_n = _calculate_ci_half_width(stdev=5.0, n=5)
        large_n = _calculate_ci_half_width(stdev=5.0, n=30)
        assert large_n < small_n

    def test_ci_half_width_hand_computed_example(self) -> None:
        """Verify half-width calculation against hand-computed example."""
        # df=4, stdev=2.0, n=5: t_crit=2.776
        # margin = 2.776 * 2.0 / sqrt(5) = 2.776 * 2.0 / 2.236 ≈ 2.482
        half_width = _calculate_ci_half_width(stdev=2.0, n=5)
        assert abs(half_width - 2.482) < 0.01


class TestSamplesNeeded:
    def test_samples_needed_reaches_target(self) -> None:
        """Increasing samples should eventually reach target margin."""
        target_margin = 1.0
        stdev = 5.0
        needed = _samples_needed_for_target_margin(stdev, target_margin)
        assert needed > 1

        # Verify that this sample size does reach the target
        half_width = _calculate_ci_half_width(stdev, needed)
        assert half_width <= target_margin

    def test_samples_needed_returns_zero_for_zero_stdev(self) -> None:
        """Zero standard deviation should return 0."""
        result = _samples_needed_for_target_margin(stdev=0.0, target_margin=5.0)
        assert result == 0

    def test_samples_needed_returns_zero_for_zero_margin(self) -> None:
        """Zero target margin should return 0."""
        result = _samples_needed_for_target_margin(stdev=5.0, target_margin=0.0)
        assert result == 0


class TestExtractNumericLeaves:
    def test_extract_simple_values(self) -> None:
        target: dict[str, float] = {}
        _extract_numeric_leaves("metric", 42, target)
        assert target == {"metric": 42.0}

    def test_extract_nested_dict(self) -> None:
        target: dict[str, float] = {}
        value = {"sub1": 10, "sub2": 20}
        _extract_numeric_leaves("parent", value, target)
        assert target == {"parent_sub1": 10.0, "parent_sub2": 20.0}

    def test_extract_deeply_nested(self) -> None:
        target: dict[str, float] = {}
        value = {"level1": {"level2": 5}}
        _extract_numeric_leaves("root", value, target)
        assert target == {"root_level1_level2": 5.0}


class TestComparePairedMetrics:
    def test_compare_identical_runs(self, tmp_path: Path) -> None:
        """Comparing identical runs should show zero difference."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        # Create identical runs
        create_mock_run(dir_a / "run", seed=42, composites={"c1": 100})
        create_mock_run(dir_b / "run", seed=42, composites={"c1": 100})

        result = compare_runs(dir_a, dir_b)

        assert result["n_pairs"] == 1
        assert result["unpaired_a"] == 0
        assert result["unpaired_b"] == 0
        assert "composite" in result["metrics"]
        assert result["metrics"]["composite"]["mean_difference"] == 0.0

    def test_compare_distinguishable_difference(self, tmp_path: Path) -> None:
        """Large consistent difference should be distinguishable."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        # Create runs with consistent difference
        for seed in [42, 43, 44]:
            create_mock_run(dir_a / f"run_{seed}", seed=seed, composites={"c1": 100})
            create_mock_run(dir_b / f"run_{seed}", seed=seed, composites={"c1": 110})

        result = compare_runs(dir_a, dir_b, target_margin=5.0)

        assert result["n_pairs"] == 3
        composite_stats = result["metrics"]["composite"]
        # With 3 pairs and 10-point consistent difference, should be distinguishable
        assert composite_stats["distinguishable"]
        assert composite_stats["mean_difference"] == 10.0

    def test_compare_noisy_difference_inconclusive(self, tmp_path: Path) -> None:
        """Noisy difference might not be distinguishable with few samples."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        # Create runs with noisy differences
        diffs = [2, -1, 3]  # Small, inconsistent differences
        for i, diff in enumerate(diffs):
            create_mock_run(dir_a / f"run_{i}", seed=i, composites={"c1": 100})
            create_mock_run(dir_b / f"run_{i}", seed=i, composites={"c1": 100 + diff})

        result = compare_runs(dir_a, dir_b, target_margin=5.0)

        assert result["n_pairs"] == 3
        composite_stats = result["metrics"]["composite"]
        # CI should include zero
        ci_lower, ci_upper = composite_stats["ci_95"]
        assert ci_lower < 0 < ci_upper
        assert not composite_stats["distinguishable"]

    def test_win_rate_and_ties(self, tmp_path: Path) -> None:
        """Win rates should count victories and ties correctly."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        # Create: 1 win for B (105 > 100), 1 win for A (100 > 95), 1 tie (100 = 100)
        create_mock_run(dir_a / "r1", seed=1, composites={"c1": 100})
        create_mock_run(dir_b / "r1", seed=1, composites={"c1": 105})

        create_mock_run(dir_a / "r2", seed=2, composites={"c1": 100})
        create_mock_run(dir_b / "r2", seed=2, composites={"c1": 95})

        create_mock_run(dir_a / "r3", seed=3, composites={"c1": 100})
        create_mock_run(dir_b / "r3", seed=3, composites={"c1": 100})

        result = compare_runs(dir_a, dir_b, label_a="A", label_b="B")

        composite_stats = result["metrics"]["composite"]
        assert composite_stats["win_rate_B"] == 1
        assert composite_stats["win_rate_A"] == 1
        assert composite_stats["ties"] == 1

    def test_compare_multiple_metrics(self, tmp_path: Path) -> None:
        """Comparison should handle multiple metrics."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        axes_a = {
            "survival": {"c1": {"population": 10}},
            "trade": {"c1": 5},
            "aggression": {"c1": 2},
        }
        axes_b = {
            "survival": {"c1": {"population": 12}},
            "trade": {"c1": 6},
            "aggression": {"c1": 2},
        }

        create_mock_run(dir_a / "run", seed=42, composites={"c1": 100}, axes=axes_a)
        create_mock_run(dir_b / "run", seed=42, composites={"c1": 105}, axes=axes_b)

        result = compare_runs(dir_a, dir_b)

        assert "composite" in result["metrics"]
        assert "survival_population" in result["metrics"]
        assert "trade" in result["metrics"]
        assert "aggression" in result["metrics"]


class TestWithinControllerStats:
    def test_within_stats_single_sample(self, tmp_path: Path) -> None:
        """Single sample should still compute statistics."""
        create_mock_run(tmp_path / "run", seed=42, composites={"c1": 100})

        result = within_controller_stats(tmp_path)

        assert result["n_samples"] == 1
        assert "composite" in result["metrics"]
        composite_stats = result["metrics"]["composite"]
        assert composite_stats["n"] == 1
        assert composite_stats["mean"] == 100.0
        assert composite_stats["stdev"] == 0.0

    def test_within_stats_multiple_samples(self, tmp_path: Path) -> None:
        """Multiple samples should show variance and CI."""
        for seed in [42, 43, 44]:
            create_mock_run(tmp_path / f"run_{seed}", seed=seed, composites={"c1": 100 + seed})

        result = within_controller_stats(tmp_path)

        assert result["n_samples"] == 3
        composite_stats = result["metrics"]["composite"]
        assert composite_stats["n"] == 3
        assert composite_stats["stdev"] > 0
        ci_lower, ci_upper = composite_stats["ci_95"]
        assert ci_lower < composite_stats["mean"] < ci_upper

    def test_within_stats_reports_additional_samples_needed(self, tmp_path: Path) -> None:
        """Should report samples needed for target margin."""
        # High variance with few samples
        for seed in [42, 43]:
            create_mock_run(tmp_path / f"run_{seed}", seed=seed, composites={"c1": 100 + 20 * seed})

        result = within_controller_stats(tmp_path, target_margin=5.0)

        composite_stats = result["metrics"]["composite"]
        # With high variance and only 2 samples, should need more
        assert composite_stats["additional_samples_needed"] > 0


class TestFormatting:
    def test_format_comparison_table_with_data(self, tmp_path: Path) -> None:
        """Formatted table should include all key statistics."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        create_mock_run(dir_a / "run", seed=42, composites={"c1": 100})
        create_mock_run(dir_b / "run", seed=42, composites={"c1": 105})

        result = compare_runs(dir_a, dir_b, label_a="ModelA", label_b="ModelB")
        table = format_comparison_table(result, "ModelA", "ModelB")

        assert "Paired Comparison" in table
        assert "1 pairs" in table
        assert "composite" in table
        assert "ModelA" in table
        assert "ModelB" in table

    def test_format_within_table_with_data(self, tmp_path: Path) -> None:
        """Within table should show controller statistics."""
        for seed in [42, 43]:
            create_mock_run(tmp_path / f"run_{seed}", seed=seed, composites={"c1": 100 + seed})

        result = within_controller_stats(tmp_path)
        table = format_within_table(result)

        assert "Controller Statistics" in table
        assert "2 sample" in table
        assert "composite" in table
        assert "Mean" in table


class TestEmptyDirectories:
    def test_compare_empty_directories(self, tmp_path: Path) -> None:
        """Comparing empty directories should return empty result."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        result = compare_runs(dir_a, dir_b)

        assert result["n_pairs"] == 0
        assert result["unpaired_a"] == 0
        assert result["unpaired_b"] == 0
        assert result["metrics"] == {}

    def test_within_empty_directory(self, tmp_path: Path) -> None:
        """Within stats for empty directory should return empty result."""
        result = within_controller_stats(tmp_path)

        assert result["n_samples"] == 0
        assert result["metrics"] == {}


class TestDeterministicOutput:
    def test_json_output_sorted_keys(self, tmp_path: Path) -> None:
        """JSON output should have sorted keys for determinism."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        create_mock_run(dir_a / "run", seed=42, composites={"c1": 100})
        create_mock_run(dir_b / "run", seed=42, composites={"c1": 105})

        result = compare_runs(dir_a, dir_b)
        json_str = json.dumps(result, sort_keys=True)

        # Should be stable across multiple calls
        for _ in range(3):
            result2 = compare_runs(dir_a, dir_b)
            json_str2 = json.dumps(result2, sort_keys=True)
            assert json_str == json_str2

    def test_rounded_floats_deterministic(self, tmp_path: Path) -> None:
        """Float values should be rounded to 4 decimals for determinism."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        create_mock_run(dir_a / "run", seed=42, composites={"c1": 100})
        create_mock_run(dir_b / "run", seed=42, composites={"c1": 105})

        result = compare_runs(dir_a, dir_b)

        composite_stats = result["metrics"]["composite"]
        mean_a = composite_stats["mean_A"]
        mean_b = composite_stats["mean_B"]

        # Check that values are rounded to 4 decimals
        assert len(str(mean_a).split(".")[-1]) <= 4
        assert len(str(mean_b).split(".")[-1]) <= 4
