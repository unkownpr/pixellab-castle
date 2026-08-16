from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .runner import T_CRITICAL_VALUES


# Number of pairs whose variance is typical; enough to meaningfully estimate
# the population variance (minimum degrees of freedom for applying the t-table).
# Fewer pairs risk underestimating spread; larger samples get better precision.
MINIMUM_PAIRS_FOR_INFERENCE = 2


# Half-width of acceptable confidence interval, in composite points, for calling
# a comparison "decided". Smaller margins require more samples. The user supplies
# this via --target-margin; the tool reports if current sample size is insufficient
# and prints how many additional pairs would be needed.
DEFAULT_TARGET_MARGIN = 5


@dataclass(frozen=True, slots=True)
class RunMetadata:
    """Extracted from metadata.json for run identification and pairing."""

    scenario_id: str
    seed: int
    seat_rotation: int
    controller_names: dict[str, str]


@dataclass(frozen=True, slots=True)
class RunMetrics:
    """Extracted from report.json for statistical comparison."""

    composites: dict[str, int]
    axes: dict[str, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class RunInfo:
    """Complete run information for matching and comparison."""

    run_dir: Path
    metadata: RunMetadata
    metrics: RunMetrics


def _load_run(run_dir: Path) -> RunInfo | None:
    """Load a single run's metadata and metrics. Return None if files are missing."""
    metadata_path = run_dir / "metadata.json"
    report_path = run_dir / "report.json"

    if not metadata_path.exists() or not report_path.exists():
        return None

    try:
        metadata_dict = json.loads(metadata_path.read_text())
        report_dict = json.loads(report_path.read_text())

        metadata = RunMetadata(
            scenario_id=str(metadata_dict["scenario"]["id"]),
            seed=int(metadata_dict["seed"]),
            seat_rotation=int(metadata_dict.get("seat_rotation", 0)),
            controller_names=dict(metadata_dict["controllers"]),
        )

        metrics = RunMetrics(
            composites=dict(report_dict["metrics"].get("composites", {})),
            axes={
                k: v
                for k, v in report_dict["metrics"].items()
                if k not in {"composites", "tenure_metrics"}
            },
        )

        return RunInfo(run_dir=run_dir, metadata=metadata, metrics=metrics)
    except (KeyError, ValueError, json.JSONDecodeError):
        return None


def _collect_runs(directory: Path) -> list[RunInfo]:
    """Recursively collect all runs from a directory tree."""
    runs: list[RunInfo] = []

    # Look for run directories: those containing metadata.json and report.json
    for item in sorted(directory.rglob("metadata.json")):
        run_dir = item.parent
        run_info = _load_run(run_dir)
        if run_info:
            runs.append(run_info)

    return runs


def _pair_runs(
    runs_a: list[RunInfo], runs_b: list[RunInfo]
) -> tuple[list[tuple[RunInfo, RunInfo]], list[RunInfo], list[RunInfo]]:
    """Match runs by (scenario_id, seed, seat_rotation, colony_seat).

    Returns: (paired_runs, unpaired_a, unpaired_b)
    """
    # Build index by pairing key: (scenario_id, seed, seat_rotation, colony_id) -> run
    index_a: dict[tuple[str, int, int, str], RunInfo] = {}
    index_b: dict[tuple[str, int, int, str], RunInfo] = {}

    # For runs with only one colony per seat, we pair by the seat name (c1, c2, etc.)
    # The controller_names dict has colony_id as key.
    for run in runs_a:
        for colony_id in sorted(run.metrics.composites.keys()):
            key = (
                run.metadata.scenario_id,
                run.metadata.seed,
                run.metadata.seat_rotation,
                colony_id,
            )
            index_a[key] = run

    for run in runs_b:
        for colony_id in sorted(run.metrics.composites.keys()):
            key = (
                run.metadata.scenario_id,
                run.metadata.seed,
                run.metadata.seat_rotation,
                colony_id,
            )
            index_b[key] = run

    # Pair by finding matching keys
    paired: list[tuple[RunInfo, RunInfo]] = []
    used_a: set[tuple[str, int, int, str]] = set()
    used_b: set[tuple[str, int, int, str]] = set()

    for key, run_a in sorted(index_a.items()):
        if key in index_b:
            run_b = index_b[key]
            paired.append((run_a, run_b))
            used_a.add(key)
            used_b.add(key)

    # Collect unpaired runs
    unpaired_a = [index_a[key] for key in sorted(index_a.keys()) if key not in used_a]
    unpaired_b = [index_b[key] for key in sorted(index_b.keys()) if key not in used_b]

    # Deduplicate: a single run may have multiple colonies, so collect unique run dirs
    unpaired_a_dirs = {run.run_dir for run in unpaired_a}
    unpaired_b_dirs = {run.run_dir for run in unpaired_b}
    unpaired_a = [run for run in runs_a if run.run_dir in unpaired_a_dirs]
    unpaired_b = [run for run in runs_b if run.run_dir in unpaired_b_dirs]

    return paired, unpaired_a, unpaired_b


def _get_t_critical(df: int) -> float:
    """Get t-critical value for 95% CI from lookup table, with fallback."""
    if df in T_CRITICAL_VALUES:
        return T_CRITICAL_VALUES[df]
    # Find closest value if exact match not in table
    closest_df = min(T_CRITICAL_VALUES.keys(), key=lambda x: abs(x - df))
    return T_CRITICAL_VALUES[closest_df]


def _calculate_ci_half_width(stdev: float, n: int) -> float:
    """Calculate half-width of 95% confidence interval."""
    if n < 1:
        return 0.0
    df = n - 1
    t_crit = _get_t_critical(df)
    return t_crit * stdev / (n**0.5)


def _samples_needed_for_target_margin(stdev: float, target_margin: float) -> int:
    """Estimate number of samples needed to reach target confidence interval half-width.

    Uses df=n-1 and t_crit from table, iterating to find the minimum n where
    the half-width equals or undercuts the target.
    """
    if stdev <= 0 or target_margin <= 0:
        return 0

    # Binary search for minimum n
    low, high = 1, 10000
    while low < high:
        mid = (low + high) // 2
        half_width = _calculate_ci_half_width(stdev, mid)
        if half_width <= target_margin:
            high = mid
        else:
            low = mid + 1
    return low


def _extract_numeric_leaves(
    key: str, value: object, target: dict[str, float]
) -> None:
    """Recursively extract numeric leaves from metrics structure."""
    if isinstance(value, (int, float)):
        target[f"{key}"] = float(value)
    elif isinstance(value, dict):
        for subkey, subvalue in value.items():
            nested_key = f"{key}_{subkey}"
            _extract_numeric_leaves(nested_key, subvalue, target)


def _extract_metrics_for_colony(
    run_metrics: RunMetrics, colony_id: str
) -> dict[str, float]:
    """Extract all numeric metrics for a specific colony."""
    metrics: dict[str, float] = {}

    # Composite
    if colony_id in run_metrics.composites:
        metrics["composite"] = float(run_metrics.composites[colony_id])

    # Per-axis metrics: each axis is keyed by colony_id
    for axis_name, axis_data in run_metrics.axes.items():
        if not isinstance(axis_data, dict):
            continue
        if colony_id not in axis_data:
            continue

        own = axis_data[colony_id]
        if isinstance(own, dict):
            for metric_key, metric_value in own.items():
                _extract_numeric_leaves(f"{axis_name}_{metric_key}", metric_value, metrics)
        else:
            metrics[f"{axis_name}"] = float(own)

    return metrics


def compare_runs(
    dir_a: Path,
    dir_b: Path,
    label_a: str = "A",
    label_b: str = "B",
    target_margin: float = DEFAULT_TARGET_MARGIN,
) -> dict[str, Any]:
    """Compare two directories of run results with paired statistics.

    Returns a dict with:
    - "n_pairs": number of matched pairs
    - "unpaired_a": count of unpaired runs from dir_a
    - "unpaired_b": count of unpaired runs from dir_b
    - "metrics": dict[metric_name] -> comparison statistics
    """
    runs_a = _collect_runs(dir_a)
    runs_b = _collect_runs(dir_b)

    paired, unpaired_a, unpaired_b = _pair_runs(runs_a, runs_b)

    if not paired:
        return {
            "n_pairs": 0,
            "unpaired_a": len(unpaired_a),
            "unpaired_b": len(unpaired_b),
            "metrics": {},
        }

    # Extract all metric names across pairs
    all_metrics: set[str] = set()
    for run_a, run_b in paired:
        for cid_a in run_a.metrics.composites:
            metrics_a = _extract_metrics_for_colony(run_a.metrics, cid_a)
            all_metrics.update(metrics_a.keys())
        for cid_b in run_b.metrics.composites:
            metrics_b = _extract_metrics_for_colony(run_b.metrics, cid_b)
            all_metrics.update(metrics_b.keys())

    # Compute statistics for each metric
    metric_stats: dict[str, Any] = {}

    for metric_name in sorted(all_metrics):
        differences: list[float] = []
        values_a: list[float] = []
        values_b: list[float] = []
        wins_a = 0
        wins_b = 0
        ties = 0

        for run_a, run_b in paired:
            # Assume single colony per run for now
            cid_a = list(run_a.metrics.composites.keys())[0]
            cid_b = list(run_b.metrics.composites.keys())[0]

            metrics_a = _extract_metrics_for_colony(run_a.metrics, cid_a)
            metrics_b = _extract_metrics_for_colony(run_b.metrics, cid_b)

            val_a = metrics_a.get(metric_name)
            val_b = metrics_b.get(metric_name)

            if val_a is None or val_b is None:
                continue

            values_a.append(val_a)
            values_b.append(val_b)
            diff = val_b - val_a
            differences.append(diff)

            if val_b > val_a:
                wins_b += 1
            elif val_a > val_b:
                wins_a += 1
            else:
                ties += 1

        if not differences:
            continue

        n = len(differences)
        mean_a = statistics.mean(values_a) if values_a else 0.0
        mean_b = statistics.mean(values_b) if values_b else 0.0
        mean_diff = statistics.mean(differences)
        stdev_diff = statistics.stdev(differences) if n > 1 else 0.0

        # 95% confidence interval for the mean difference
        df = n - 1
        t_crit = _get_t_critical(df)
        margin = t_crit * stdev_diff / (n**0.5) if n > 0 else 0.0
        ci_lower = round(mean_diff - margin, 4)
        ci_upper = round(mean_diff + margin, 4)

        # Determine if difference is distinguishable (CI excludes zero)
        distinguishable = (ci_lower > 0 or ci_upper < 0)

        # Estimate samples needed for target margin (if not distinguishable)
        additional_samples_needed = 0
        if not distinguishable and target_margin > 0:
            required_n = _samples_needed_for_target_margin(stdev_diff, target_margin)
            additional_samples_needed = max(0, required_n - n)

        metric_stats[metric_name] = {
            "n": n,
            f"mean_{label_a}": round(mean_a, 4),
            f"mean_{label_b}": round(mean_b, 4),
            "mean_difference": round(mean_diff, 4),
            "stdev_difference": round(stdev_diff, 4),
            "ci_95": [ci_lower, ci_upper],
            f"win_rate_{label_b}": wins_b,
            f"win_rate_{label_a}": wins_a,
            "ties": ties,
            "distinguishable": distinguishable,
            "additional_samples_needed": additional_samples_needed,
        }

    return {
        "n_pairs": len(paired),
        "unpaired_a": len(unpaired_a),
        "unpaired_b": len(unpaired_b),
        "metrics": metric_stats,
    }


def within_controller_stats(
    directory: Path,
    target_margin: float = DEFAULT_TARGET_MARGIN,
) -> dict[str, Any]:
    """Compute statistics for a single controller across all seeds.

    Returns:
    - "n_samples": number of samples
    - "metrics": dict[metric_name] -> stats (mean, stdev, ci_95, etc.)
    """
    runs = _collect_runs(directory)

    if not runs:
        return {"n_samples": 0, "metrics": {}}

    # Collect all metrics across runs
    all_metrics: set[str] = set()
    for run in runs:
        for cid in run.metrics.composites:
            metrics = _extract_metrics_for_colony(run.metrics, cid)
            all_metrics.update(metrics.keys())

    # Compute statistics for each metric
    metric_stats: dict[str, Any] = {}

    for metric_name in sorted(all_metrics):
        values: list[float] = []

        for run in runs:
            for cid in run.metrics.composites:
                metrics = _extract_metrics_for_colony(run.metrics, cid)
                val = metrics.get(metric_name)
                if val is not None:
                    values.append(val)

        if not values:
            continue

        n = len(values)
        mean = statistics.mean(values)
        stdev = statistics.stdev(values) if n > 1 else 0.0

        # 95% confidence interval
        df = n - 1
        t_crit = _get_t_critical(df)
        margin = t_crit * stdev / (n**0.5) if n > 0 else 0.0
        ci_lower = round(mean - margin, 4)
        ci_upper = round(mean + margin, 4)

        # Half-width of CI (what it would take to tell this apart from anything)
        half_width = round(margin, 4)

        # Estimate samples needed for target margin
        additional_samples_needed = 0
        if target_margin > 0:
            required_n = _samples_needed_for_target_margin(stdev, target_margin)
            additional_samples_needed = max(0, required_n - n)

        metric_stats[metric_name] = {
            "n": n,
            "mean": round(mean, 4),
            "stdev": round(stdev, 4),
            "ci_95": [ci_lower, ci_upper],
            "ci_half_width": half_width,
            "additional_samples_needed": additional_samples_needed,
        }

    return {
        "n_samples": len(runs),
        "metrics": metric_stats,
    }


def format_comparison_table(
    result: dict[str, Any],
    label_a: str = "A",
    label_b: str = "B",
) -> str:
    """Format comparison results as a human-readable table."""
    lines: list[str] = []

    n_pairs = result.get("n_pairs", 0)
    unpaired_a = result.get("unpaired_a", 0)
    unpaired_b = result.get("unpaired_b", 0)

    lines.append(f"Paired Comparison: {n_pairs} pairs")
    if unpaired_a > 0:
        lines.append(f"⚠️  {unpaired_a} unpaired run(s) from {label_a}")
    if unpaired_b > 0:
        lines.append(f"⚠️  {unpaired_b} unpaired run(s) from {label_b}")
    lines.append("")

    metrics = result.get("metrics", {})
    if not metrics:
        lines.append("No paired metrics found.")
        return "\n".join(lines)

    # Header
    lines.append(
        f"{'Metric':<40} {'n':>3} {label_a:>10} {label_b:>10} {'Diff':>10} {'Std':>8} {'95% CI':<20} {'Status':<20}"
    )
    lines.append("-" * 130)

    for metric_name in sorted(metrics.keys()):
        stats = metrics[metric_name]
        n = stats["n"]
        mean_a = stats[f"mean_{label_a}"]
        mean_b = stats[f"mean_{label_b}"]
        mean_diff = stats["mean_difference"]
        stdev_diff = stats["stdev_difference"]
        ci_95 = stats["ci_95"]
        distinguishable = stats["distinguishable"]
        additional = stats["additional_samples_needed"]

        ci_str = f"[{ci_95[0]:.4f}, {ci_95[1]:.4f}]"

        if distinguishable:
            status = "✓ Distinguishable"
        elif mean_a == 0 and mean_b == 0 and stdev_diff == 0:
            # Neither side ever did this, so there is nothing to be inconclusive about.
            # Calling an untouched axis "inconclusive" reads as a close contest and sends
            # people off to run more seeds that would measure the same nothing.
            status = "neither played it"
        elif mean_diff == 0 and stdev_diff == 0:
            status = "identical"
        elif additional > 0:
            status = f"+{additional} more needed"
        else:
            status = "Inconclusive"

        lines.append(
            f"{metric_name:<40} {n:>3} {mean_a:>10.4f} {mean_b:>10.4f} {mean_diff:>10.4f} {stdev_diff:>8.4f} {ci_str:<20} {status:<20}"
        )

    return "\n".join(lines)


def format_within_table(result: dict[str, Any]) -> str:
    """Format within-controller statistics as a human-readable table."""
    lines: list[str] = []

    n_samples = result.get("n_samples", 0)
    lines.append(f"Controller Statistics: {n_samples} sample(s)")
    lines.append("")

    metrics = result.get("metrics", {})
    if not metrics:
        lines.append("No metrics found.")
        return "\n".join(lines)

    # Header
    lines.append(
        f"{'Metric':<40} {'n':>3} {'Mean':>12} {'Std':>10} {'95% CI Half-Width':>20} {'+Samples for 5pt margin':<20}"
    )
    lines.append("-" * 100)

    for metric_name in sorted(metrics.keys()):
        stats = metrics[metric_name]
        n = stats["n"]
        mean = stats["mean"]
        stdev = stats["stdev"]
        half_width = stats["ci_half_width"]
        additional = stats["additional_samples_needed"]

        additional_str = f"+{additional}" if additional > 0 else "—"

        lines.append(
            f"{metric_name:<40} {n:>3} {mean:>12.4f} {stdev:>10.4f} {half_width:>20.4f} {additional_str:<20}"
        )

    return "\n".join(lines)
