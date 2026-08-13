from __future__ import annotations

from dataclasses import dataclass, field

from .domain import MatchState
from .engine import TurnResult


@dataclass(slots=True)
class MetricCollector:
    initial_population: dict[str, int]
    invalid_actions: dict[str, int] = field(default_factory=dict)
    raids: dict[str, int] = field(default_factory=dict)
    trades: dict[str, int] = field(default_factory=dict)
    peak_population: dict[str, int] = field(default_factory=dict)
    timeouts: dict[str, int] = field(default_factory=dict)
    reconnects: dict[str, int] = field(default_factory=dict)

    @classmethod
    def create(cls, state: MatchState) -> MetricCollector:
        populations = {colony_id: colony.population for colony_id, colony in state.colonies.items()}
        return cls(populations, peak_population=dict(populations))

    def record(self, result: TurnResult) -> None:
        for item in result.action_results:
            if item.status == "rejected":
                self.invalid_actions[item.colony_id] = self.invalid_actions.get(item.colony_id, 0) + 1
        for event in result.events:
            if event.colony_id is None:
                continue
            if event.kind in {"raid", "surprise_raid"}:
                self.raids[event.colony_id] = self.raids.get(event.colony_id, 0) + 1
            if event.kind == "trade_completed":
                self.trades[event.colony_id] = self.trades.get(event.colony_id, 0) + 1
        for colony_id, colony in result.state.colonies.items():
            self.peak_population[colony_id] = max(
                self.peak_population.get(colony_id, 0), colony.population
            )

    def record_timeout(self, colony_id: str) -> None:
        self.timeouts[colony_id] = self.timeouts.get(colony_id, 0) + 1

    def record_reconnect(self, colony_id: str) -> None:
        self.reconnects[colony_id] = self.reconnects.get(colony_id, 0) + 1

    def report(self, state: MatchState) -> dict[str, object]:
        colony_ids = sorted(state.colonies)
        return {
            "survival": {
                colony_id: {"turns": state.turn, "population": state.colonies[colony_id].population}
                for colony_id in colony_ids
            },
            "growth": {
                colony_id: {
                    "initial_population": self.initial_population[colony_id],
                    "peak_population": self.peak_population[colony_id],
                    "housing": state.colonies[colony_id].housing,
                }
                for colony_id in colony_ids
            },
            "prosperity": {
                colony_id: {"resources": state.colonies[colony_id].resources.as_dict()}
                for colony_id in colony_ids
            },
            "trade": {colony_id: self.trades.get(colony_id, 0) for colony_id in colony_ids},
            "aggression": {colony_id: self.raids.get(colony_id, 0) for colony_id in colony_ids},
            "decision_quality": {
                colony_id: {"invalid_actions": self.invalid_actions.get(colony_id, 0)}
                for colony_id in colony_ids
            },
            "cost": {
                colony_id: {"model_calls": 0, "mcp_calls": 0, "input_tokens": 0, "output_tokens": 0}
                for colony_id in colony_ids
            },
        }
