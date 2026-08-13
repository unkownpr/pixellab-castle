from __future__ import annotations

import json
import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .actions import (
    ActionBatch,
    BuildAction,
    DiplomacyAction,
    GatherAction,
    RaidAction,
    SetPolicyAction,
    TradeOfferAction,
    TradeRespondAction,
    WaitAction,
)
from .domain import MatchState, Position, StructureKind
from .engine import TurnResult
from .events import canonical_snapshot, state_hash
from .scenarios import Scenario


REPOSITORY_ROOT = Path(__file__).parents[2]


def _dependency_lock_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative in ("uv.lock", "frontend/package-lock.json"):
        path = REPOSITORY_ROOT / relative
        if path.exists():
            hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def scenario_to_dict(scenario: Scenario) -> dict[str, object]:
    return {
        "id": scenario.id,
        "name": scenario.name,
        "width": scenario.width,
        "height": scenario.height,
        "max_turns": scenario.max_turns,
        "biome": scenario.biome,
        "spawn_points": [{"x": p.x, "y": p.y} for p in scenario.spawn_points],
        "sight_radius": scenario.sight_radius,
    }


def scenario_from_dict(data: dict[str, object]) -> Scenario:
    spawn_data = data["spawn_points"]
    assert isinstance(spawn_data, list)
    return Scenario(
        id=str(data["id"]),
        name=str(data["name"]),
        width=int(data["width"]),
        height=int(data["height"]),
        max_turns=int(data["max_turns"]),
        biome=str(data["biome"]),
        spawn_points=tuple(Position(int(item["x"]), int(item["y"])) for item in spawn_data),
        sight_radius=int(data["sight_radius"]),
    )


def action_to_dict(action: object) -> dict[str, object]:
    if isinstance(action, WaitAction):
        return {"kind": "wait"}
    if isinstance(action, GatherAction):
        return {"kind": "gather", "x": action.position.x, "y": action.position.y}
    if isinstance(action, BuildAction):
        return {
            "kind": "build",
            "structure": action.structure.value,
            "x": action.position.x,
            "y": action.position.y,
        }
    if isinstance(action, DiplomacyAction):
        return {
            "kind": "diplomacy",
            "target_colony_id": action.target_colony_id,
            "operation": action.operation,
            "message": action.message,
        }
    if isinstance(action, TradeOfferAction):
        return {
            "kind": "trade_offer",
            "target_colony_id": action.target_colony_id,
            "give": list(action.give),
            "receive": list(action.receive),
            "message": action.message,
        }
    if isinstance(action, TradeRespondAction):
        return {"kind": "trade_respond", "offer_id": action.offer_id, "accept": action.accept}
    if isinstance(action, RaidAction):
        return {"kind": "raid", "target_colony_id": action.target_colony_id}
    if isinstance(action, SetPolicyAction):
        return {"kind": "set_policy", "policy": action.policy, "value": action.value}
    raise TypeError(f"unsupported action: {type(action).__name__}")


def action_from_dict(data: dict[str, object]) -> object:
    kind = data["kind"]
    if kind == "wait":
        return WaitAction()
    if kind == "gather":
        return GatherAction(Position(int(data["x"]), int(data["y"])))
    if kind == "build":
        return BuildAction(
            StructureKind(str(data["structure"])), Position(int(data["x"]), int(data["y"]))
        )
    if kind == "diplomacy":
        return DiplomacyAction(
            target_colony_id=str(data["target_colony_id"]),
            operation=str(data["operation"]),  # type: ignore[arg-type]
            message=str(data.get("message", "")),
        )
    if kind == "trade_offer":
        return TradeOfferAction(
            target_colony_id=str(data["target_colony_id"]),
            give=tuple((str(name), int(amount)) for name, amount in data["give"]),  # type: ignore[union-attr]
            receive=tuple((str(name), int(amount)) for name, amount in data["receive"]),  # type: ignore[union-attr]
            message=str(data.get("message", "")),
        )
    if kind == "trade_respond":
        return TradeRespondAction(str(data["offer_id"]), bool(data["accept"]))
    if kind == "raid":
        return RaidAction(str(data["target_colony_id"]))
    if kind == "set_policy":
        return SetPolicyAction(str(data["policy"]), str(data["value"]))
    raise ValueError(f"unknown action kind: {kind}")


def batch_to_dict(batch: ActionBatch) -> dict[str, object]:
    return {
        "turn": batch.turn,
        "colony_id": batch.colony_id,
        "actions": [action_to_dict(action) for action in batch.actions],
    }


def batch_from_dict(data: dict[str, object]) -> ActionBatch:
    actions = data["actions"]
    assert isinstance(actions, list)
    return ActionBatch(
        turn=int(data["turn"]),
        colony_id=str(data["colony_id"]),
        actions=tuple(action_from_dict(item) for item in actions),  # type: ignore[arg-type]
    )


@dataclass(slots=True)
class ArtifactWriter:
    run_dir: Path
    events_path: Path
    snapshots_path: Path
    metadata_path: Path
    report_path: Path

    @classmethod
    def create(
        cls,
        run_dir: Path,
        scenario: Scenario,
        seed: int,
        colony_count: int,
        controller_names: dict[str, str],
        controller_tenures: list[dict[str, object]] | None = None,
    ) -> ArtifactWriter:
        run_dir.mkdir(parents=True, exist_ok=False)
        writer = cls(
            run_dir=run_dir,
            events_path=run_dir / "turns.jsonl",
            snapshots_path=run_dir / "snapshots.jsonl",
            metadata_path=run_dir / "metadata.json",
            report_path=run_dir / "report.json",
        )
        metadata = {
            "artifact_version": "1.0",
            "ruleset_version": "0.1.0",
            "scenario": scenario_to_dict(scenario),
            "seed": seed,
            "colony_count": colony_count,
            "controllers": controller_names,
            "controller_tenures": controller_tenures or [],
            "dependency_lock_hashes": _dependency_lock_hashes(),
            "seat_rotation": 0,
        }
        writer.metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        return writer

    def write_turn(
        self,
        batches: Iterable[ActionBatch],
        result: TurnResult,
        action_controller_ids: dict[str, str | None] | None = None,
    ) -> None:
        record = {
            "turn": result.state.turn - 1,
            "batches": [batch_to_dict(batch) for batch in batches],
            "action_controller_ids": action_controller_ids or {},
            "events": [
                {
                    "turn": event.turn,
                    "kind": event.kind,
                    "colony_id": event.colony_id,
                    "data": event.data,
                }
                for event in result.events
            ],
            "action_results": [
                {
                    "colony_id": item.colony_id,
                    "action_kind": item.action_kind,
                    "status": item.status,
                    "code": item.code,
                }
                for item in result.action_results
            ],
            "state_hash": state_hash(result.state),
            "completed": True,
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        with self.snapshots_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(canonical_snapshot(result.state), sort_keys=True) + "\n")

    def finish(self, state: MatchState, metrics: dict[str, object]) -> None:
        report = {
            "scenario_id": state.scenario_id,
            "seed": state.seed,
            "turns": state.turn,
            "termination_reason": state.termination_reason,
            "final_state_hash": state_hash(state),
            "metrics": metrics,
        }
        self.report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        database = sqlite3.connect(self.run_dir / "summary.sqlite3")
        try:
            database.execute(
                "CREATE TABLE IF NOT EXISTS run_summary (scenario_id TEXT, seed INTEGER, turns INTEGER, termination_reason TEXT, state_hash TEXT)"
            )
            database.execute(
                "INSERT INTO run_summary VALUES (?, ?, ?, ?, ?)",
                (state.scenario_id, state.seed, state.turn, state.termination_reason, state_hash(state)),
            )
            database.commit()
        finally:
            database.close()
