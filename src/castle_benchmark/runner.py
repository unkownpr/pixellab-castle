from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .agents import AGENT_TYPES, Controller
from .engine import SimCore
from .events import state_hash
from .metrics import MetricCollector
from .observation import project_observation
from .persistence import ArtifactWriter, batch_from_dict, scenario_from_dict
from .scenarios import Scenario


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
        expected.append(str(record["state_hash"]))
        batches = tuple(batch_from_dict(batch) for batch in record["batches"])
        sim.resolve(batches)
        actual.append(state_hash(sim.state))
        if mismatch is None and expected[-1] != actual[-1]:
            mismatch = index
    return ReplayVerification(mismatch is None, tuple(expected), tuple(actual), mismatch)

