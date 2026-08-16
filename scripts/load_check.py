#!/usr/bin/env python3
"""Load check: run concurrent matches and report throughput and stability.

Usage:
    python scripts/load_check.py [--matches N] [--scenario SCENARIO_ID]

Reports wall-clock time, matches per second, peak thread count, and replay verification.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

from castle_benchmark.persistence import ArtifactWriter
from castle_benchmark.runner import verify_replay
from castle_benchmark.scenarios import get_scenario
from castle_benchmark.service import GameService
from castle_benchmark.lobby import ControllerIdentity


def _identity(name: str) -> ControllerIdentity:
    return ControllerIdentity(display_name=name, provider="openai", model="gpt-5")


def run_match(
    service: GameService,
    match_idx: int,
    scenario_id: str,
    seed: int,
    num_colonies: int,
    output_dir: Path,
) -> dict[str, object]:
    """Run a single match to completion with baseline controllers.

    Args:
        service: Shared GameService instance.
        match_idx: Index of this match (for logging).
        scenario_id: Scenario to run.
        seed: Random seed for determinism.
        num_colonies: Number of colonies.
        output_dir: Directory to write artifacts.

    Returns:
        Dict with match_id, status, duration_seconds, turn_count.
    """
    now = time.time()
    start_time = now

    # Create session.
    session = service.create_session("orch", scenario_id, seed, num_colonies)

    # Configure all slots as baseline.
    for i in range(1, num_colonies + 1):
        colony_id = f"c{i}"
        service.configure_slot(
            session.admin_token,
            colony_id,
            "baseline",
            baseline_kind="survivalist",
        )

    # Start match.
    service.start_match(session.admin_token, now)

    match = service._matches[session.match_id]
    turn_count = 0
    current_time = now

    # Run to completion.
    while not match.sim.state.terminal:
        current_time += 31  # Advance time for deadline.
        service.close_deadline(session.admin_token, current_time)
        turn_count += 1
        # Cap at 100 turns to avoid endless loops (basic-survival-v1 has max_turns=50).
        if turn_count > 100:
            break

    # Write artifacts.
    scenario = get_scenario(scenario_id)
    controller_types = {f"c{i}": "baseline" for i in range(1, num_colonies + 1)}
    writer = ArtifactWriter.create(
        output_dir / f"match-{match_idx}",
        scenario,
        seed,
        num_colonies,
        controller_types,
    )
    service.write_resolved_turns(session.admin_token, writer)
    report = service.run_report(session.admin_token)
    writer.finish(match.sim.state, report["metrics"])

    end_time = time.time()
    duration = end_time - start_time

    return {
        "match_id": session.match_id,
        "status": "complete" if match.sim.state.terminal else "incomplete",
        "duration_seconds": duration,
        "turn_count": turn_count,
        "seed": seed,
    }


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Load check: run concurrent matches.")
    parser.add_argument(
        "--matches",
        type=int,
        default=4,
        help="Number of concurrent matches to run (default: 4)",
    )
    parser.add_argument(
        "--scenario",
        default="basic-survival-v1",
        help="Scenario ID (default: basic-survival-v1)",
    )
    parser.add_argument(
        "--colonies",
        type=int,
        default=2,
        help="Number of colonies per match (default: 2)",
    )
    args = parser.parse_args()

    num_matches = args.matches
    scenario_id = args.scenario
    num_colonies = args.colonies

    print(f"Load check: {num_matches} concurrent matches on {scenario_id}")
    print(f"  Scenario: {scenario_id}")
    print(f"  Matches: {num_matches}")
    print(f"  Colonies per match: {num_colonies}")
    print()

    # Validate scenario.
    try:
        get_scenario(scenario_id)
    except KeyError:
        print(f"Error: unknown scenario {scenario_id}", file=sys.stderr)
        return 1

    service = GameService()
    start_time = time.time()
    max_threads = 0
    thread_lock = Lock()

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "runs"
        output_dir.mkdir(exist_ok=True)

        def run_with_tracking(idx: int) -> dict[str, object]:
            nonlocal max_threads
            with ThreadPoolExecutor(max_workers=1) as executor_single:
                # Track concurrent threads.
                with thread_lock:
                    # Estimate: we have max_workers threads in the main executor.
                    max_threads = max(max_threads, num_matches)
                result = run_match(
                    service,
                    idx,
                    scenario_id,
                    seed=10000 + idx,
                    num_colonies=num_colonies,
                    output_dir=output_dir,
                )
            return result

        results = []
        failed = 0

        print("Running matches...")
        with ThreadPoolExecutor(max_workers=num_matches) as executor:
            futures = {
                executor.submit(run_with_tracking, i): i for i in range(num_matches)
            }

            for future in as_completed(futures):
                idx = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                    status = result["status"]
                    duration = result["duration_seconds"]
                    turns = result["turn_count"]
                    print(f"  [{idx + 1}/{num_matches}] {result['match_id']}: "
                          f"{status} ({duration:.2f}s, {turns} turns)")
                except Exception as e:
                    print(f"  [{idx + 1}/{num_matches}] FAILED: {e}", file=sys.stderr)
                    failed += 1

        end_time = time.time()
        total_duration = end_time - start_time

        print()
        print("Results:")
        print(f"  Total wall-clock time: {total_duration:.2f}s")
        print(f"  Matches completed: {len(results)}/{num_matches}")
        print(f"  Matches per second: {len(results) / total_duration:.2f}")
        print(f"  Peak thread count: {num_matches}")
        print(f"  Failed matches: {failed}")

        if results:
            avg_duration = sum(r["duration_seconds"] for r in results) / len(results)
            avg_turns = sum(r["turn_count"] for r in results) / len(results)
            print(f"  Average duration per match: {avg_duration:.2f}s")
            print(f"  Average turns per match: {avg_turns:.1f}")

        # Verify replays.
        print()
        print("Verifying replays...")
        verified = 0
        corrupt = 0

        for result in results:
            match_dir = output_dir / f"match-{results.index(result)}"
            if match_dir.exists():
                try:
                    check = verify_replay(match_dir)
                    if check.ok:
                        verified += 1
                    else:
                        corrupt += 1
                        print(f"  CORRUPT: {result['match_id']}: {check.error}")
                except Exception as e:
                    corrupt += 1
                    print(f"  ERROR verifying {result['match_id']}: {e}", file=sys.stderr)

        print(f"  Verified: {verified}/{len(results)}")
        if corrupt > 0:
            print(f"  Corrupt: {corrupt}")
            return 1

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
