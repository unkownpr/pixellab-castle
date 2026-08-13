from __future__ import annotations

from .domain import ResourceStock, StructureKind


BUILD_COSTS: dict[StructureKind, dict[str, int]] = {
    StructureKind.HOUSE: {"wood": 12, "stone": 4},
    StructureKind.WAREHOUSE: {"wood": 10, "stone": 8},
    StructureKind.WELL: {"wood": 4, "stone": 10},
    StructureKind.FARM: {"wood": 6},
    StructureKind.LUMBER_CAMP: {"wood": 8},
    StructureKind.QUARRY: {"wood": 8, "tools": 1},
    StructureKind.MINE: {"wood": 12, "stone": 8, "tools": 2},
    StructureKind.MARKET: {"wood": 14, "stone": 8},
    StructureKind.WORKSHOP: {"wood": 12, "stone": 10, "ore": 4},
    StructureKind.CLINIC: {"wood": 12, "stone": 8, "tools": 1},
    StructureKind.BARRACKS: {"wood": 16, "stone": 12, "tools": 1},
    StructureKind.WATCHTOWER: {"wood": 12, "stone": 6},
    StructureKind.WALL: {"stone": 8},
    StructureKind.GATE: {"wood": 8, "stone": 8},
}

BUILD_TURNS: dict[StructureKind, int] = {kind: 3 for kind in BUILD_COSTS}
BUILD_TURNS[StructureKind.WALL] = 2

HOUSING_BY_STRUCTURE = {
    StructureKind.HEADQUARTERS: 8,
    StructureKind.HOUSE: 6,
}


def can_afford(stock: ResourceStock, cost: dict[str, int]) -> bool:
    values = stock.as_dict()
    return all(values[name] >= amount for name, amount in cost.items())


def resource_delta(items: tuple[tuple[str, int], ...], sign: int = 1) -> dict[str, int]:
    delta: dict[str, int] = {}
    for name, amount in items:
        if amount <= 0:
            raise ValueError("resource transfer amounts must be positive")
        delta[name] = delta.get(name, 0) + sign * amount
    return delta
