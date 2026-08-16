"""Tests for suite result aggregation across multiple axes shapes."""

from pathlib import Path

import pytest

from castle_benchmark.runner import run_suite
from castle_benchmark.scenarios import get_scenario


def test_suite_aggregates_all_axis_types(tmp_path: Path) -> None:
    """Verify suite aggregation collects axes of all three shapes.

    The metrics dict contains axes with different structures:
    1. Nested per-colony: dict[colony_id][metric_name] = value
    2. Flat integers: dict[metric_name] = value (trade, aggression)
    3. Complex nested: dict[metric_name][sub_metric] = value (survival, growth, prosperity)

    This test verifies that suite aggregation handles all three shapes and
    produces statistics with n, mean, median, stdev, ci_95 for each.
    """
    from castle_benchmark.runner import SuiteConfig

    # Run a minimal suite (2 seeds x 1 rotation for speed)
    suite_output = run_suite(
        SuiteConfig(
            scenario=get_scenario("basic-survival-v1"),
            seeds=(17, 23),
            rotations="1",
            colonies=4,
            controllers=("survivalist", "trader", "expansionist", "militarist"),
            output_dir=tmp_path,
        )
    )

    # Verify composites are present for all controller kinds
    assert "survivalist" in suite_output["statistics"]
    assert "trader" in suite_output["statistics"]
    assert "expansionist" in suite_output["statistics"]
    assert "militarist" in suite_output["statistics"]

    for controller_kind in ["survivalist", "trader", "expansionist", "militarist"]:
        stats = suite_output["statistics"][controller_kind]

        # Verify composite stats
        composite = stats.get("composite", {})
        assert "n" in composite
        assert "mean" in composite
        assert "median" in composite
        assert "stdev" in composite
        assert "ci_95" in composite
        assert composite["n"] == 2  # 2 seeds x 1 rotation

        # Verify axes are present (should have at least multiple axes now)
        axes = stats.get("axes", {})
        assert len(axes) > 0, f"No axes found for {controller_kind}"

        # Collect axis names to check for different shapes
        axis_names = set(axes.keys())

        # Verify that we have axes from different shapes:
        # 1. Nested per-colony axes (e.g., exploration, labour, communication)
        nested_axes = {"exploration", "labour", "recovery", "communication", "decision_quality"}
        found_nested = axis_names & nested_axes
        assert (
            len(found_nested) > 0
        ), f"No nested per-colony axes found. Got: {axis_names}"

        # 2. Flat integer axes (trade, aggression)
        flat_axes = {"trade", "aggression"}
        found_flat = axis_names & flat_axes
        assert (
            len(found_flat) > 0
        ), f"No flat integer axes found. Got: {axis_names}"

        # 3. Complex nested axes (survival, growth, prosperity)
        # These might be decomposed as survival_turns, survival_population, etc.
        complex_axes = {"survival", "growth", "prosperity"}
        found_complex = axis_names & complex_axes
        # Also check for decomposed versions
        found_decomposed = {
            a
            for a in axis_names
            if any(a.startswith(f"{prefix}_") for prefix in ["survival", "growth", "prosperity"])
        }
        assert (
            len(found_complex) > 0 or len(found_decomposed) > 0
        ), f"No complex nested axes found. Got: {axis_names}"

        # Verify that each metric in each axis has the required statistics
        for axis_name, axis_metrics in axes.items():
            assert isinstance(
                axis_metrics, dict
            ), f"Axis {axis_name} should be a dict"
            for metric_name, metric_stats in axis_metrics.items():
                assert isinstance(
                    metric_stats, dict
                ), f"Metric {axis_name}.{metric_name} should be a dict"
                assert "n" in metric_stats, f"{axis_name}.{metric_name} missing n"
                assert "mean" in metric_stats, f"{axis_name}.{metric_name} missing mean"
                assert (
                    "median" in metric_stats
                ), f"{axis_name}.{metric_name} missing median"
                assert (
                    "stdev" in metric_stats
                ), f"{axis_name}.{metric_name} missing stdev"
                assert (
                    "ci_95" in metric_stats
                ), f"{axis_name}.{metric_name} missing ci_95"
