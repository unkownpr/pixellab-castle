from __future__ import annotations

from typing import Mapping

from .domain import ResourceStock, Structure, StructureKind, StructureStatus


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

# Perishable storage capacity. Only food and water spoil: wood, stone, ore, tools
# and influence can be stockpiled without bound. A colony's base ceiling for each
# perishable is PERISHABLE_BASE_CAPACITY; every OPERATIONAL warehouse raises it by
# WAREHOUSE_CAPACITY_BONUS (damaged, burning, ruined and under-construction
# warehouses raise nothing, matching every other structure effect). The base sits
# above the 60 food / 60 water a colony starts with, so nothing begins the scenario
# already capped, and below the ~200 food an unmanaged colony actually hoards, so
# accumulation stops being free. The bonus makes one warehouse hold ten extra turns
# of consumption for a 21-population colony, repaying its 18-unit build cost well
# inside the eighty-turn horizon.
PERISHABLES = ("food", "water")
PERISHABLE_BASE_CAPACITY = 100
WAREHOUSE_CAPACITY_BONUS = 50

HOUSING_BY_STRUCTURE = {
    StructureKind.HEADQUARTERS: 8,
    StructureKind.HOUSE: 6,
}

# Per-turn yields granted by each OPERATIONAL structure. Production is applied in
# the "production" phase, before needs are consumed, so a farm or well feeding the
# colony the same turn it is built is intentional.
PRODUCTION_YIELDS: dict[StructureKind, dict[str, int]] = {
    StructureKind.FARM: {"food": 2},
    StructureKind.WELL: {"water": 2},
    StructureKind.LUMBER_CAMP: {"wood": 2},
    StructureKind.QUARRY: {"stone": 2},
    StructureKind.MINE: {"ore": 2},
    StructureKind.MARKET: {"influence": 2},
}

# A WORKSHOP turns ore into tools; each workshop converts WORKSHOP_ORE_PER_TOOL ore
# into WORKSHOP_TOOLS_PER_TURN tools per turn, and only while ore is available.
WORKSHOP_ORE_PER_TOOL = 2
WORKSHOP_TOOLS_PER_TURN = 1

# A CLINIC heals this many sick (then injured) colonists per turn.
CLINIC_HEALS_PER_TURN = 1

# Sickness is the consequence of a colony failing to meet its needs. Every turn a
# colony consumes food and water; when it falls short, SICKENED_PER_SHORTFALL_TURN
# healthy colonists fall sick. Starvation death still follows the cumulative
# shortfall counter, but now claims a sick colonist first, so sickness is the stage
# between deprivation and death rather than a separate, parallel drain. Meeting
# needs reverses it: NATURAL_RECOVERY_PER_TURN sick colonists recover each turn a
# colony is fully fed and watered, making the clinic an accelerator rather than the
# only way back to health.
SICKENED_PER_SHORTFALL_TURN = 1
NATURAL_RECOVERY_PER_TURN = 1

# Raid effects and their mitigations. BARRACKS cuts the food a raid can carry away;
# WALL absorbs part of the condition damage raids deal to structures.
RAID_FOOD_LOOT = 3
RAID_STRUCTURE_DAMAGE = 20
RAID_INJURIES = 1
BARRACKS_RAID_LOOT_REDUCTION = 2
WALL_RAID_DAMAGE_REDUCTION = 10

# Trade ratios as (received, paid) fractions, applied to what a side collects.
# Trading without a MARKET loses part of the consignment in transit; a MARKET
# removes that friction. Both ratios are <= 1 on purpose: a trade may destroy
# resources but must never create them, otherwise two colonies with markets can
# mint value by passing goods back and forth every turn.
TRADE_RATIO_BASE = (4, 5)
TRADE_RATIO_MARKET = (1, 1)


def can_afford(stock: ResourceStock, cost: dict[str, int]) -> bool:
    values = stock.as_dict()
    return all(values[name] >= amount for name, amount in cost.items())


def store_overflow(
    stock: ResourceStock, delta: Mapping[str, int], capacity: Mapping[str, int]
) -> set[str]:
    """Perishables whose positive ``delta`` would push ``stock`` past ``capacity``.

    Non-perishable names in ``delta`` never overflow: only food and water are
    capped. Returns the set of perishable names that would exceed the ceiling, so a
    caller can reject the whole action rather than silently truncate it.
    """
    values = stock.as_dict()
    return {
        name
        for name in PERISHABLES
        if name in delta
        and delta[name] > 0
        and capacity.get(name) is not None
        and values[name] + delta[name] > capacity[name]
    }


def within_capacity(stock: ResourceStock, capacity: Mapping[str, int]) -> bool:
    """Whether a colony's perishable stock is at or below its storage ceiling."""
    values = stock.as_dict()
    return all(
        values[name] <= capacity[name] for name in PERISHABLES if name in capacity
    )


def cap_production_delta(
    stock: ResourceStock, delta: Mapping[str, int], capacity: Mapping[str, int]
) -> dict[str, int]:
    """Truncate a production delta so perishable yields stop at the storage ceiling.

    Structure production is allowed to stop at the cap rather than be rejected: a
    perishable with no room left is dropped from the delta and a partially-filling
    one is reduced to the remaining space, so the caller reports what was actually
    produced rather than the nominal yield.
    """
    capped = dict(delta)
    values = stock.as_dict()
    for name in PERISHABLES:
        produced = capped.get(name, 0)
        if produced <= 0:
            continue
        room = max(0, capacity[name] - values[name])
        if room <= 0:
            del capped[name]
        elif room < produced:
            capped[name] = room
    return capped


def resource_delta(items: tuple[tuple[str, int], ...], sign: int = 1) -> dict[str, int]:
    delta: dict[str, int] = {}
    for name, amount in items:
        if amount <= 0:
            raise ValueError("resource transfer amounts must be positive")
        delta[name] = delta.get(name, 0) + sign * amount
    return delta


def operational_structure_counts(
    structures: Mapping[str, Structure], colony_id: str
) -> dict[StructureKind, int]:
    """Count a colony's OPERATIONAL structures by kind; nothing else contributes."""
    counts: dict[StructureKind, int] = {}
    for structure in structures.values():
        if structure.colony_id == colony_id and structure.status == StructureStatus.OPERATIONAL:
            counts[structure.kind] = counts.get(structure.kind, 0) + 1
    return counts


def perishable_capacity(
    structures: Mapping[str, Structure], colony_id: str
) -> dict[str, int]:
    """Perishable storage ceilings for a colony, from OPERATIONAL warehouses only.

    Every non-operational warehouse — damaged, burning, ruined or still under
    construction — raises nothing, matching how every other structure effect only
    applies while operational.
    """
    warehouses = operational_structure_counts(structures, colony_id).get(
        StructureKind.WAREHOUSE, 0
    )
    ceiling = PERISHABLE_BASE_CAPACITY + warehouses * WAREHOUSE_CAPACITY_BONUS
    return {name: ceiling for name in PERISHABLES}


# Kinds whose OPERATIONAL structures need a worker each turn to produce. Passive
# structures (housing, walls, barracks, watchtower, gate) are excluded: they work
# without hands, so building them never competes with scouting for labour.
LABOUR_STRUCTURE_KINDS = frozenset(
    {
        StructureKind.FARM,
        StructureKind.WELL,
        StructureKind.LUMBER_CAMP,
        StructureKind.QUARRY,
        StructureKind.MINE,
        StructureKind.MARKET,
        StructureKind.WORKSHOP,
        StructureKind.CLINIC,
    }
)


def staffed_production(
    structures: Mapping[str, Structure], colony_id: str, workers: int
) -> tuple[dict[StructureKind, int], int]:
    """Staff a colony's OPERATIONAL producing structures with its available workers.

    Each producing structure (see LABOUR_STRUCTURE_KINDS) needs one worker per turn.
    When ``workers`` falls short of the number of OPERATIONAL producers, the colony
    staffs structures in stable id order so identical replays choose identical
    structures, and the returned idle count records how many stay unstaffed.
    """
    producers = sorted(
        (
            structure
            for structure in structures.values()
            if structure.colony_id == colony_id
            and structure.status == StructureStatus.OPERATIONAL
            and structure.kind in LABOUR_STRUCTURE_KINDS
        ),
        key=lambda structure: structure.id,
    )
    staffed = producers[:workers]
    counts: dict[StructureKind, int] = {}
    for structure in staffed:
        counts[structure.kind] = counts.get(structure.kind, 0) + 1
    return counts, len(producers) - len(staffed)


def production_delta(
    stock: ResourceStock, counts: Mapping[StructureKind, int]
) -> dict[str, int]:
    """Net resource change a colony earns from its OPERATIONAL structures this turn."""
    delta: dict[str, int] = {}
    for kind, yields in PRODUCTION_YIELDS.items():
        count = counts.get(kind, 0)
        if not count:
            continue
        for name, amount in yields.items():
            delta[name] = delta.get(name, 0) + amount * count
    workshops = counts.get(StructureKind.WORKSHOP, 0)
    if workshops:
        ore = stock.ore + delta.get("ore", 0)
        tools = min(workshops * WORKSHOP_TOOLS_PER_TURN, ore // WORKSHOP_ORE_PER_TOOL)
        if tools:
            delta["tools"] = delta.get("tools", 0) + tools
            delta["ore"] = delta.get("ore", 0) - tools * WORKSHOP_ORE_PER_TOOL
    return delta


def has_operational(
    structures: Mapping[str, Structure], colony_id: str, kind: StructureKind
) -> bool:
    return any(
        structure.colony_id == colony_id
        and structure.kind == kind
        and structure.status == StructureStatus.OPERATIONAL
        for structure in structures.values()
    )


def trade_blocked(structures: Mapping[str, Structure], colony_id: str) -> bool:
    """A colony walled without an OPERATIONAL gate cannot trade."""
    return has_operational(structures, colony_id, StructureKind.WALL) and not has_operational(
        structures, colony_id, StructureKind.GATE
    )


def scaled_amount(amount: int, ratio: tuple[int, int]) -> int:
    """Apply a trade ratio, rounding to the nearest unit and never above what was sent.

    Rounding to nearest rather than down matters at the scale colonies actually
    trade at. Rounding down turns a one-unit consignment into nothing and halves a
    two-unit one, so the friction lands hardest exactly where trades are smallest
    and no counterparty can accept a sensible offer. The cap keeps the invariant
    that a trade may destroy resources but never create them.
    """
    numerator, denominator = ratio
    scaled = (amount * numerator + denominator // 2) // denominator
    return min(amount, scaled)


def scaled_receipt(items: tuple[tuple[str, int], ...], ratio: tuple[int, int]) -> dict[str, int]:
    return {name: scaled_amount(amount, ratio) for name, amount in items}
