from __future__ import annotations

import json
import logging
import sqlite3
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agents import AGENT_TYPES, Controller
from .engine import SimCore
from .events import state_hash
from .lobby import ControllerType
from .metrics import MetricCollector
from .observation import project_observation
from .persistence import ArtifactWriter, batch_from_dict, scenario_from_dict
from .scenarios import Scenario
from .service import GameService

logger = logging.getLogger("castle_benchmark.runner")

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
class MixedRunConfig:
    """Config for a mixed run with external agents and baselines in the same match.

    External agents connect via pairing codes and submit actions through the session flow.
    Baseline controllers are automatically driven by the service.
    """

    scenario: Scenario
    seed: int
    output_dir: Path
    external_seat_indices: tuple[int, ...]  # 1-indexed seat numbers for external agents
    baseline_kinds: tuple[str, ...] | None = None  # baseline kinds for non-external seats
    external_agent_timeout_seconds: int = 30  # wait for external agents to claim


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
        batches = tuple(
            controllers[colony_id].decide(project_observation(sim.state, colony_id))
            for colony_id in sorted(controllers)
        )
        result = sim.resolve(batches)

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


def run_mixed_match(config: MixedRunConfig) -> RunReport:
    """Run a match with a mix of external agents and baseline controllers.

    External agent seats are configured to wait for connection via pairing codes.
    Baseline seats are automatically driven by the service. For fallback testing
    when no external agents connect, this falls back to manual baseline-only mode.

    Determinism and replay verification are preserved: both controller types use
    the same simulation and no wall-clock time reaches SimCore.
    """
    # Derive colony count and baseline assignments
    external_count = len(config.external_seat_indices)
    baseline_count = len(config.baseline_kinds) if config.baseline_kinds else 0
    colony_count = external_count + baseline_count
    if not colony_count:
        raise ValueError("must have at least one seat (external or baseline)")

    # Prepare baseline kinds: cycle through provided kinds or default to survivalist
    provided_baseline_kinds = config.baseline_kinds or ("survivalist",)
    baseline_kinds_by_seat: dict[int, str] = {}
    baseline_kind_cycle = iter(provided_baseline_kinds)
    for seat_index in range(1, colony_count + 1):
        if seat_index not in config.external_seat_indices:
            baseline_kinds_by_seat[seat_index] = next(baseline_kind_cycle)

    # Determine output directory early
    run_name = f"{config.scenario.id}-seed-{config.seed}"
    run_dir = config.output_dir / run_name
    suffix = 1
    while run_dir.exists():
        run_dir = config.output_dir / f"{run_name}-{suffix}"
        suffix += 1

    # If no external seats, just run a normal baseline match
    if not config.external_seat_indices:
        # Build controller order: apply baseline kinds in order
        controller_kinds = list(provided_baseline_kinds[:colony_count])
        if len(controller_kinds) < colony_count:
            controller_kinds += [provided_baseline_kinds[-1]] * (colony_count - len(controller_kinds))
        return run_match(
            RunConfig(
                config.scenario,
                config.seed,
                colony_count,
                config.output_dir,
                tuple(controller_kinds[:colony_count]),
            )
        )

    # Create session with baselines and external slots configured upfront
    service = GameService()
    orchestrator_token = "orchestrator"

    # Build slot configs for baselines
    slot_configs: list[tuple[str, str, str | None]] = []
    for seat_index, baseline_kind in baseline_kinds_by_seat.items():
        colony_id = f"c{seat_index}"
        slot_configs.append((colony_id, ControllerType.BASELINE.value, baseline_kind))

    session = service.create_session(
        orchestrator_token=orchestrator_token,
        scenario_id=config.scenario.id,
        seed=config.seed,
        colony_count=colony_count,
        deadline_seconds=config.external_agent_timeout_seconds,
        slot_configs=slot_configs,
    )
    admin_token = session.admin_token
    match = service._matches[session.match_id]

    # Print pairing codes for external agents
    print("\n=== Mixed Run: External Agent Pairing ===")
    print(f"Scenario: {config.scenario.id}, Seed: {config.seed}, Colonies: {colony_count}")
    print(f"External seats: {', '.join(str(i) for i in config.external_seat_indices)}")
    print()

    now = time.time()
    for seat_index in config.external_seat_indices:
        colony_id = f"c{seat_index}"
        pairing = service.create_pairing(admin_token, colony_id, now)
        print(f"Seat {seat_index} ({colony_id}): {pairing.code}")

    print()

    # Open lobby to allow external agents to connect
    service.open_lobby(admin_token)

    # Wait for external agents to connect
    deadline_at = time.time() + config.external_agent_timeout_seconds
    claimed_seats: set[int] = set()
    while time.time() < deadline_at:
        session_current = service._lobbies[session.match_id]
        for seat_index in config.external_seat_indices:
            colony_id = f"c{seat_index}"
            slot = next(s for s in session_current.slots if s.colony_id == colony_id)
            if slot.pairing_consumed:
                claimed_seats.add(seat_index)
        if len(claimed_seats) == external_count:
            logger.info("all external agents connected")
            break
        time.sleep(0.05)

    # Log unclaimed external seats
    unclaimed = set(config.external_seat_indices) - claimed_seats
    if unclaimed:
        logger.warning(
            f"external agent connection timeout: {len(claimed_seats)}/{external_count} connected"
        )

    # If no external agents connected, fall back to baseline-only mode
    if not claimed_seats:
        logger.warning("no external agents connected; falling back to baseline-only manual drive")
        # Build all baselines and drive manually
        all_baselines: dict[str, Controller] = {}
        for seat_index in range(1, colony_count + 1):
            colony_id = f"c{seat_index}"
            if seat_index in config.external_seat_indices:
                # Use survivalist for unclaimed external
                kind = "survivalist"
            else:
                kind = baseline_kinds_by_seat[seat_index]
            factory = AGENT_TYPES[kind]
            all_baselines[colony_id] = factory(seed=config.seed + seat_index)

        # Record controller names showing fallback
        controller_names = {}
        for seat_index in range(1, colony_count + 1):
            colony_id = f"c{seat_index}"
            if seat_index in config.external_seat_indices:
                controller_names[colony_id] = "external:fallback-survivalist"
            else:
                controller_names[colony_id] = f"baseline:{baseline_kinds_by_seat[seat_index]}"

        # Manual drive (use the match's sim directly)
        metrics = MetricCollector.create(match.sim.state)
        writer = ArtifactWriter.create(
            run_dir,
            config.scenario,
            config.seed,
            colony_count,
            controller_names,
        )
        while not match.sim.state.terminal:
            batches = tuple(
                all_baselines[colony_id].decide(project_observation(match.sim.state, colony_id))
                for colony_id in sorted(all_baselines)
            )
            result = match.sim.resolve(batches)
            metrics.record(result)
            writer.write_turn(batches, result)

        metrics_report = metrics.report(match.sim.state)
        writer.finish(match.sim.state, metrics_report)

        return RunReport(
            run_dir=writer.run_dir,
            report_path=writer.report_path,
            termination_reason=match.sim.state.termination_reason or "unknown",
            metrics=metrics_report,
        )

    # At least one external agent connected: proceed with session-based matching
    service.start_match(admin_token, now)

    # Wait for match to complete
    # Service drives baselines automatically; external agents submit via session
    max_wait = 3600.0
    while not match.sim.state.terminal and time.time() - now < max_wait:
        time.sleep(0.1)

    # Record controller names showing which were real external vs baseline
    controller_names = {}
    session_current = service._lobbies[session.match_id]
    for seat_index in range(1, colony_count + 1):
        colony_id = f"c{seat_index}"
        if seat_index in config.external_seat_indices:
            slot = next(s for s in session_current.slots if s.colony_id == colony_id)
            if slot.pairing_consumed and slot.identity:
                controller_names[colony_id] = f"{slot.identity.model} ({slot.identity.provider})"
            else:
                controller_names[colony_id] = "external:fallback-survivalist"
        else:
            controller_names[colony_id] = f"baseline:{baseline_kinds_by_seat[seat_index]}"

    # Export via service
    writer = ArtifactWriter.create(
        run_dir,
        config.scenario,
        config.seed,
        colony_count,
        controller_names,
    )
    service.write_resolved_turns(admin_token, writer)
    metrics_report = service.run_report(admin_token)["metrics"]
    writer.finish(match.sim.state, metrics_report)

    return RunReport(
        run_dir=writer.run_dir,
        report_path=writer.report_path,
        termination_reason=match.sim.state.termination_reason or "unknown",
        metrics=metrics_report,
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


def _collect_numeric_leaves(
    key: str, value: object, target: dict[str, list[float]]
) -> None:
    """Recursively collect numeric leaves from potentially nested structures.

    Handles flat integers, nested dicts (for resources, etc.), and nested metrics.
    Flattens the key path with underscores for hierarchical metrics.
    """
    if isinstance(value, (int, float)):
        if key not in target:
            target[key] = []
        target[key].append(float(value))
    elif isinstance(value, dict):
        # Recurse into nested dicts
        for subkey, subvalue in value.items():
            nested_key = f"{key}_{subkey}"
            _collect_numeric_leaves(nested_key, subvalue, target)


def _aggregate_controller_stats(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate statistics for a single controller kind across all runs.

    Extracts composites and per-axis metrics for the specific colony_id that
    this controller occupied in each run. Handles axes with different structures:
    - Nested per-colony (dict[colony_id][metric_name]): exploration, labour, etc.
    - Flat integers (dict[metric_name]): trade, aggression counts
    - Complex nested (dict[metric_name][sub_metric]): survival, growth, prosperity
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

        # Extract per-axis metrics: iterate over all axes, not hardcoded list
        # Skip known non-axis fields
        skip_keys = {"composites", "tenure_metrics"}
        for axis_name, axis_data in metrics.items():
            if axis_name in skip_keys or not isinstance(axis_data, dict):
                continue

            if axis_name not in axis_values:
                axis_values[axis_name] = {}

            # Every axis is keyed by colony, whether its value is a nested dict of
            # sub-metrics (exploration, survival) or a bare number (trade, aggression).
            # Only this controller's own colony may be read: rotation moves controllers
            # between seats on purpose, so keeping the colony id would average a
            # controller's turn-11 seat with a rival's turn-17 seat and call it a result.
            if colony_id not in axis_data:
                continue
            own = axis_data[colony_id]
            if isinstance(own, dict):
                for metric_key, metric_value in own.items():
                    _collect_numeric_leaves(metric_key, metric_value, axis_values[axis_name])
            else:
                _collect_numeric_leaves("value", own, axis_values[axis_name])

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
