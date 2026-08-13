from __future__ import annotations

from dataclasses import dataclass

from .domain import Position


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    name: str
    width: int
    height: int
    max_turns: int
    biome: str
    spawn_points: tuple[Position, ...]
    sight_radius: int = 5

    def __post_init__(self) -> None:
        if not self.id or not self.name:
            raise ValueError("scenario id and name are required")
        if self.width < 5 or self.height < 5:
            raise ValueError("scenario dimensions must be at least 5x5")
        if not 1 <= len(self.spawn_points) <= 8:
            raise ValueError("scenarios require one to eight spawn points")
        if len(set(self.spawn_points)) != len(self.spawn_points):
            raise ValueError("spawn points must be unique")


BASIC_SURVIVAL = Scenario(
    id="basic-survival-v1",
    name="Basic Survival",
    width=18,
    height=18,
    max_turns=80,
    biome="grassland",
    spawn_points=(
        Position(3, 3),
        Position(14, 3),
        Position(14, 14),
        Position(3, 14),
    ),
)

DESERT_SCARCITY = Scenario(
    id="desert-scarcity-v1",
    name="Desert Scarcity and Trade",
    width=20,
    height=20,
    max_turns=100,
    biome="desert",
    spawn_points=(Position(3, 3), Position(16, 3), Position(16, 16), Position(3, 16)),
)

SNOW_RECOVERY = Scenario(
    id="snow-recovery-v1",
    name="Snow Disaster Recovery",
    width=20,
    height=20,
    max_turns=100,
    biome="snow",
    spawn_points=(Position(3, 3), Position(16, 3), Position(16, 16), Position(3, 16)),
)

OFFICIAL_SCENARIOS = (BASIC_SURVIVAL, DESERT_SCARCITY, SNOW_RECOVERY)


def get_scenario(scenario_id: str) -> Scenario:
    for scenario in OFFICIAL_SCENARIOS:
        if scenario.id == scenario_id:
            return scenario
    raise KeyError(f"unknown scenario: {scenario_id}")

