from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, replace
from typing import Iterable

from .domain import Position
from .scenarios import Scenario
from .systems import GATHER_RADIUS

# River cells carry water as a gatherable resource. The amount (10,000) does not deplete
# inside a 100-turn match (max drawable is well under 1,000 with starting well production
# or constructed wells). This makes rivers matter for the first time: a colony must either
# build a well or put an OPERATIONAL structure within GATHER_RADIUS of the river.
RIVER_WATER_AMOUNT = 10_000


@dataclass(frozen=True, slots=True)
class WorldCell:
    position: Position
    biome: str
    water: bool
    buildable: bool
    movement_cost: int
    resource: str | None = None
    resource_amount: int = 0


@dataclass(frozen=True, slots=True)
class WorldState:
    width: int
    height: int
    seed: int
    biome: str
    cells: dict[Position, WorldCell]
    spawn_points: tuple[Position, ...]


def derive_seed(seed: int, stream: str) -> int:
    digest = hashlib.sha256(f"{seed}:{stream}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def rotated_spawns(
    scenario: Scenario, rotation: int, colony_count: int
) -> tuple[Position, ...]:
    if not 1 <= colony_count <= len(scenario.spawn_points):
        raise ValueError("colony_count exceeds scenario spawn capacity")
    selected = scenario.spawn_points[:colony_count]
    shift = rotation % colony_count
    return selected[shift:] + selected[:shift]


def _river_columns(scenario: Scenario, seed: int) -> dict[int, int]:
    rng = random.Random(derive_seed(seed, "river"))
    center = scenario.width / 2 + rng.uniform(-1.5, 1.5)
    phase = rng.uniform(0, math.tau)
    amplitude = max(1.0, scenario.width * 0.12)
    columns: dict[int, int] = {}
    for y in range(scenario.height):
        wave = math.sin(y * 0.42 + phase) * amplitude
        jitter = rng.choice((-1, 0, 0, 0, 1))
        columns[y] = max(1, min(scenario.width - 2, round(center + wave + jitter)))
    return columns


def generate_world(scenario: Scenario, seed: int) -> WorldState:
    """Generate a world from the scenario and seed.

    Note: Hashes for existing seeds change with two changes:
    - River cells now carry water as a gatherable resource (non-depleting amount)
    - AM-14 guarantees every spawn has food and wood within GATHER_RADIUS by converting
      the nearest buildable, non-water, resource-free cell if needed.
    """
    river = _river_columns(scenario, seed)
    resource_rng = random.Random(derive_seed(seed, "resources"))
    choices = {
        "grassland": ("wood", "food", "stone", "ore"),
        "desert": ("stone", "ore", "ore", "food"),
        "snow": ("wood", "stone", "ore", "wood"),
    }.get(scenario.biome, ("wood", "food", "stone", "ore"))
    cells: dict[Position, WorldCell] = {}

    for y in range(scenario.height):
        for x in range(scenario.width):
            position = Position(x, y)
            water = abs(x - river[y]) <= 1
            resource = None
            amount = 0
            if water:
                resource = "water"
                amount = RIVER_WATER_AMOUNT
            elif resource_rng.random() < 0.18:
                resource = resource_rng.choice(choices)
                amount = resource_rng.randint(24, 80)
            cells[position] = WorldCell(
                position=position,
                biome=scenario.biome,
                water=water,
                buildable=not water,
                movement_cost=3 if water else (2 if scenario.biome == "snow" else 1),
                resource=resource,
                resource_amount=amount,
            )

    # Guarantee every spawn has food AND wood within GATHER_RADIUS (AM-14).
    # Evaluated independently: if no food-bearing cell in range, convert the nearest
    # buildable non-water resource-free cell to food; then do the same for wood.
    for spawn in scenario.spawn_points:
        for required_resource in ("food", "wood"):
            has_resource_nearby = any(
                cells[pos].resource == required_resource
                for pos in cells
                if abs(pos.x - spawn.x) + abs(pos.y - spawn.y) <= GATHER_RADIUS
                and pos in cells
            )
            if not has_resource_nearby:
                # Find the nearest buildable, non-water, resource-free cell (by manhattan, y, x)
                candidates = sorted(
                    (
                        pos for pos in cells
                        if cells[pos].buildable
                        and not cells[pos].water
                        and cells[pos].resource is None
                    ),
                    key=lambda p: (abs(p.x - spawn.x) + abs(p.y - spawn.y), p.y, p.x),
                )
                if candidates:
                    nearest = candidates[0]
                    cells[nearest] = replace(cells[nearest], resource=required_resource, resource_amount=40)

    return WorldState(
        width=scenario.width,
        height=scenario.height,
        seed=seed,
        biome=scenario.biome,
        cells=cells,
        spawn_points=scenario.spawn_points,
    )


def visible_cells(
    world: WorldState, origins: Iterable[Position], radius: int
) -> frozenset[Position]:
    visible: set[Position] = set()
    for origin in origins:
        for dy in range(-radius, radius + 1):
            remaining = radius - abs(dy)
            for dx in range(-remaining, remaining + 1):
                position = Position(origin.x + dx, origin.y + dy)
                if position in world.cells:
                    visible.add(position)
    return frozenset(visible)


def canonical_world(world: WorldState) -> dict[str, object]:
    cells = [
        {
            "x": position.x,
            "y": position.y,
            "biome": cell.biome,
            "water": cell.water,
            "buildable": cell.buildable,
            "movement_cost": cell.movement_cost,
            "resource": cell.resource,
            "resource_amount": cell.resource_amount,
        }
        for position, cell in sorted(world.cells.items(), key=lambda item: (item[0].y, item[0].x))
    ]
    return {
        "width": world.width,
        "height": world.height,
        "seed": world.seed,
        "biome": world.biome,
        "spawn_points": [{"x": p.x, "y": p.y} for p in world.spawn_points],
        "cells": cells,
    }
