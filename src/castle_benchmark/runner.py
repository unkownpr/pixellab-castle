from __future__ import annotations

import json
import sqlite3
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .actions import WaitAction
from .agents import AGENT_TYPES, Controller
from .engine import SimCore
from .events import state_hash
from .metrics import MetricCollector
from .observation import project_observation
from .persistence import ArtifactWriter, batch_from_dict, scenario_from_dict
from .scenarios import Scenario

# t-critical values for 95% confidence interval, indexed by degrees of freedom.
# Source: standard t-distribution table for alpha=0.05 (two-tailed).
# df → t_critical(0.05): values for common sample sizes used in suite runs.
T_CRITICAL_VALUES = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    15: 2.131,
    20: 2.086,
    25: 2.060,
    30: 2.042,
    40: 2.021,
    50: 2.009,
    60: 2.000,
    120: 1.980,
}


@dataclass(frozen=True, slots=True)
class RunConfig:
    scenario: Scenario
    seed: int
    colony_count: int
    output_dir: Path
    controller_kinds: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RunReport:
    run_dir: Path
    report_path: Path
    termination_reason: str
    metrics: dict[str, object]


@dataclass(frozen=True, slots=True)
class ReplayVerification:
    ok: bool
    expected_hashes: tuple[str, ...]
    actual_hashes: tuple[str, ...]
    first_mismatch_turn: int | None = None


def _controllers(config: RunConfig) -> dict[str, Controller]:
    if len(config.controller_kinds) != config.colony_count:
        raise ValueError("one controller kind is required per colony")
    result: dict[str, Controller] = {}
    for index, kind in enumerate(config.controller_kinds, start=1):
        try:
            factory = AGENT_TYPES[kind]
        except KeyError as exc:
            raise ValueError(f"unknown controller kind: {kind}") from exc
        result[f"c{index}"] = factory(seed=config.seed + index)
    return result


def run_match(config: RunConfig) -> RunReport:
    controllers = _controllers(config)
    sim = SimCore.create(config.scenario, config.seed, config.colony_count)
    run_name = f"{config.scenario.id}-seed-{config.seed}"
    run_dir = config.output_dir / run_name
    suffix = 1
    while run_dir.exists():
        run_dir = config.output_dir / f"{run_name}-{suffix}"
        suffix += 1
    writer = ArtifactWriter.create(
        run_dir,
        config.scenario,
        config.seed,
        config.colony_count,
        {colony_id: controller.name for colony_id, controller in controllers.items()},
    )
    metrics = MetricCollector.create(sim.state)
    while not sim.state.terminal:
        # Capture pre-resolution state for opportunity_waits tracking
        pre_state_colonies = {cid: colony for cid, colony in sim.state.colonies.items()}

        batches = tuple(
            controllers[colony_id].decide(project_observation(sim.state, colony_id))
            for colony_id in sorted(controllers)
        )
        result = sim.resolve(batches)

        # Track opportunity_waits: only wait actions submitted + had labour + had resources
        for batch in batches:
            colony_id = batch.colony_id
            pre_colony = pre_state_colonies.get(colony_id)
            if pre_colony is None:
                continue
            # Check if all actions in batch were wait actions
            all_waits = all(isinstance(action, WaitAction) for action in batch.actions) if batch.actions else True
            # Check if colony had available labour and non-empty resources
            has_labour = pre_colony.available_population > 0
            has_resources = any(getattr(pre_colony.resources, name, 0) > 0
                               for name in ["food", "water", "wood", "stone", "ore", "tools", "influence"])
            if all_waits and has_labour and has_resources:
                metrics.opportunity_waits[colony_id] = metrics.opportunity_waits.get(colony_id, 0) + 1

        metrics.record(result)
        writer.write_turn(batches, result)
    metric_report = metrics.report(sim.state)
    writer.finish(sim.state, metric_report)
    return RunReport(
        run_dir=writer.run_dir,
        report_path=writer.report_path,
        termination_reason=sim.state.termination_reason or "unknown",
        metrics=metric_report,
    )


def verify_replay(run_dir: Path) -> ReplayVerification:
    metadata = json.loads((run_dir / "metadata.json").read_text())
    scenario = scenario_from_dict(metadata["scenario"])
    sim = SimCore.create(scenario, int(metadata["seed"]), int(metadata["colony_count"]))
    expected: list[str] = []
    actual: list[str] = []
    mismatch: int | None = None
    events_path = run_dir / "turns.jsonl"
    if not events_path.exists():
        return ReplayVerification(False, (), (), 0)
    for index, line in enumerate(events_path.read_text().splitlines()):
        record = json.loads(line)
        if record.get("completed") is not True:
            mismatch = index
            break
        expected.append(str(record["state_hash"]))
        batches = tuple(batch_from_dict(batch) for batch in record["batches"])
        sim.resolve(batches)
        actual.append(state_hash(sim.state))
        if mismatch is None and expected[-1] != actual[-1]:
            mismatch = index
    report_path = run_dir / "report.json"
    if mismatch is None:
        if not report_path.exists():
            mismatch = len(actual)
        else:
            report = json.loads(report_path.read_text())
            if (
                not sim.state.terminal
                or int(report.get("turns", -1)) != sim.state.turn
                or report.get("final_state_hash") != state_hash(sim.state)
            ):
                mismatch = len(actual)
    return ReplayVerification(mismatch is None, tuple(expected), tuple(actual), mismatch)


def _get_t_critical(df: int) -> float:
    """Get t-critical value for 95% CI from lookup table, with interpolation/fallback."""
    if df in T_CRITICAL_VALUES:
        return T_CRITICAL_VALUES[df]
    # Find closest value if exact match not in table
    closest_df = min(T_CRITICAL_VALUES.keys(), key=lambda x: abs(x - df))
    return T_CRITICAL_VALUES[closest_df]


def _calculate_ci_95(values: list[float]) -> tuple[float, float]:
    """Calculate 95% confidence interval for a list of values."""
    if not values:
        return (0.0, 0.0)
    if len(values) == 1:
        return (values[0], values[0])

    mean = statistics.mean(values)
    stdev = statistics.stdev(values)
    n = len(values)
    df = n - 1
    t_crit = _get_t_critical(df)
    margin = t_crit * stdev / (n**0.5)
    return (round(mean - margin, 4), round(mean + margin, 4))


@dataclass(frozen=True, slots=True)
class SuiteConfig:
    scenario: Scenario | str  # Scenario object or "procedural-v1"
    seeds: tuple[int, ...]
    rotations: str  # "all" or specific rotation count
    colonies: int
    controllers: tuple[str, ...]
    output_dir: Path
    baseline_reference: Path | None = None


def run_suite(config: SuiteConfig) -> dict[str, Any]:
    """Run a suite of matches across seeds and rotations, computing aggregated statistics."""
    from .scenarios import get_scenario, generate_scenario

    output_dir = config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine actual rotations count
    if config.rotations == "all":
        rotations = config.colonies  # Each controller in each seat
    else:
        rotations = int(config.rotations)

    # Collect results by controller kind
    all_results: dict[str, list[dict[str, Any]]] = {}

    # Run each match
    for seed in sorted(config.seeds):
        for rotation in range(rotations):
            # Get scenario
            if isinstance(config.scenario, str) and config.scenario == "procedural-v1":
                scenario = generate_scenario(seed)
            elif isinstance(config.scenario, str):
                scenario = get_scenario(config.scenario)
            else:
                scenario = config.scenario

            # Rotate controllers for this seat configuration
            rotated_controllers = config.controllers[rotation:] + config.controllers[:rotation]

            # Run the match
            report = run_match(
                RunConfig(scenario, seed, config.colonies, output_dir, rotated_controllers)
            )

            # Extract metrics for each controller
            metrics = report.metrics
            for colony_index, controller_kind in enumerate(rotated_controllers, start=1):
                colony_id = f"c{colony_index}"
                if controller_kind not in all_results:
                    all_results[controller_kind] = []

                # Extract composite and per-axis metrics for this controller
                # (metrics dict has composite and per-axis info from MetricCollector.report)
                result_entry = {
                    "seed": seed,
                    "rotation": rotation,
                    "colony_id": colony_id,
                    "metrics": metrics,
                }
                all_results[controller_kind].append(result_entry)

    # Aggregate statistics by controller kind
    suite_stats = {}
    for controller_kind in sorted(all_results.keys()):
        results = all_results[controller_kind]
        suite_stats[controller_kind] = _aggregate_controller_stats(results)

    # Add baseline reference if provided
    baseline_z_scores = None
    if config.baseline_reference and config.baseline_reference.exists():
        baseline_data = json.loads(config.baseline_reference.read_text())
        baseline_z_scores = _compute_z_scores(suite_stats, baseline_data)

    # Write suite.json
    suite_output = {
        "scenario": (
            config.scenario if isinstance(config.scenario, str) else config.scenario.id
        ),
        "seeds": list(config.seeds),
        "rotations": rotations,
        "colonies": config.colonies,
        "controllers": list(config.controllers),
        "statistics": suite_stats,
    }
    if baseline_z_scores:
        suite_output["z_scores"] = baseline_z_scores

    suite_json_path = output_dir / "suite.json"
    suite_json_path.write_text(json.dumps(suite_output, indent=2, sort_keys=True) + "\n")

    # Write suite.sqlite3 for structured queries
    db_path = output_dir / "suite.sqlite3"
    _write_suite_database(db_path, suite_output)

    return suite_output


def _aggregate_controller_stats(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate statistics for a single controller kind across all runs.

    Extracts composites and per-axis metrics for the specific colony_id that
    this controller occupied in each run, using metadata to ensure correct mapping.
    """
    composites = []
    # Collect per-axis values: dict[axis_name][metric_name] = [values...]
    axis_values: dict[str, dict[str, list[float]]] = {}

    for result in results:
        metrics = result["metrics"]
        colony_id = result["colony_id"]

        # Extract composite for this specific colony
        if "composites" in metrics and colony_id in metrics["composites"]:
            composites.append(int(metrics["composites"][colony_id]))

        # Extract per-axis metrics for this colony
        for axis_name in ["exploration", "labour", "recovery", "communication", "decision_quality"]:
            if axis_name in metrics and colony_id in metrics[axis_name]:
                if axis_name not in axis_values:
                    axis_values[axis_name] = {}
                axis_data = metrics[axis_name][colony_id]
                for metric_key, metric_value in axis_data.items():
                    if isinstance(metric_value, (int, float)):
                        if metric_key not in axis_values[axis_name]:
                            axis_values[axis_name][metric_key] = []
                        axis_values[axis_name][metric_key].append(float(metric_value))

    # Aggregate composites
    composite_stats = {
        "n": len(composites),
        "mean": round(statistics.mean(composites), 4) if composites else 0,
        "median": round(statistics.median(composites), 4) if composites else 0,
        "stdev": round(statistics.stdev(composites), 4) if composites and len(composites) > 1 else 0,
        "ci_95": _calculate_ci_95(composites),
    }

    # Aggregate per-axis metrics
    axes = {}
    for axis_name, metrics_dict in axis_values.items():
        axes[axis_name] = {}
        for metric_key, values in metrics_dict.items():
            if values:
                axes[axis_name][metric_key] = {
                    "n": len(values),
                    "mean": round(statistics.mean(values), 4),
                    "median": round(statistics.median(values), 4),
                    "stdev": round(statistics.stdev(values), 4) if len(values) > 1 else 0,
                    "ci_95": _calculate_ci_95(values),
                }

    return {
        "composite": composite_stats,
        "axes": axes,
    }


def _compute_z_scores(
    current_stats: dict[str, Any], baseline_stats: dict[str, Any]
) -> dict[str, dict[str, float]]:
    """Compute z-scores comparing current results to baseline."""
    z_scores = {}
    for controller_kind in current_stats:
        if controller_kind in baseline_stats:
            current_composite = current_stats[controller_kind].get("composite", {})
            baseline_composite = baseline_stats[controller_kind].get("composite", {})

            baseline_mean = baseline_composite.get("mean", 0)
            baseline_stdev = baseline_composite.get("stdev", 1)

            if baseline_stdev > 0 and "mean" in current_composite:
                z = (current_composite["mean"] - baseline_mean) / baseline_stdev
                z_scores[controller_kind] = {"composite_z_score": round(z, 4)}

    return z_scores


def _write_suite_database(db_path: Path, suite_output: dict[str, Any]) -> None:
    """Write suite results to SQLite database for structured queries."""
    db = sqlite3.connect(db_path)
    cursor = db.cursor()

    # Create table for suite results
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS suite_results (
            scenario TEXT,
            controller TEXT,
            seed INTEGER,
            rotation INTEGER,
            metric_name TEXT,
            metric_value REAL,
            PRIMARY KEY (scenario, controller, seed, rotation, metric_name)
        )
        """
    )

    # Insert aggregated stats
    scenario = suite_output["scenario"]
    for controller_kind, stats in suite_output.get("statistics", {}).items():
        composite = stats.get("composite", {})
        for key, value in composite.items():
            if isinstance(value, (int, float)):
                cursor.execute(
                    "INSERT OR REPLACE INTO suite_results VALUES (?, ?, ?, ?, ?, ?)",
                    (scenario, controller_kind, 0, 0, f"composite_{key}", value),
                )

    db.commit()
    db.close()
