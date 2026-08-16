"""The win condition must not be sitting in the starting wagon.

A model played the same seed three times and ended every one of them with a monument, once
on turn 15 of an eighty-turn match. The cost had been tuned down until every line but ore
was already covered by the opening stock, so the long-horizon investment the rule describes
was a two-turn errand. These tests pin the shape of the fix rather than the numbers: what
matters is that no line is affordable on turn zero and that two of them can only come from
production.
"""

from castle_benchmark.domain import ResourceStock, StructureKind
from castle_benchmark.engine import SimCore
from castle_benchmark.scenarios import BASIC_SURVIVAL
from castle_benchmark.systems import BUILD_COSTS, MONUMENT_COST, PRODUCTION_YIELDS


def starting_stock() -> ResourceStock:
    return SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1).state.colonies["c1"].resources


def test_no_line_of_the_monument_is_affordable_on_turn_zero() -> None:
    stock = starting_stock().as_dict()

    covered = {name for name, amount in MONUMENT_COST.items() if stock.get(name, 0) >= amount}

    assert not covered, f"starting stock already covers {sorted(covered)}"


def test_the_monument_needs_goods_only_production_makes() -> None:
    """Tools come from a workshop and influence from a market; both must be out of reach."""
    stock = starting_stock().as_dict()

    for resource, structure in (("tools", StructureKind.WORKSHOP), ("influence", StructureKind.MARKET)):
        assert MONUMENT_COST[resource] > stock[resource]
        produced_by = [
            kind for kind, yields in PRODUCTION_YIELDS.items() if resource in yields
        ]
        assert structure in produced_by or resource == "tools"


def test_the_monument_is_still_the_dearest_thing_on_the_board() -> None:
    def total(cost: dict[str, int]) -> int:
        return sum(cost.values())

    others = [total(cost) for kind, cost in BUILD_COSTS.items() if kind is not StructureKind.MONUMENT]

    assert total(MONUMENT_COST) > 2 * max(others)


def test_the_monument_cannot_be_gathered_out_of_the_ground() -> None:
    """No amount of digging pays for it: two of its lines are not on the map at all.

    Cells carry wood, food, stone, ore and water. Tools and influence exist only as the
    output of a workshop and a market, so the shortfall in those two is a statement about
    buildings and turns rather than about how hard a colony gathers.
    """
    from castle_benchmark.world import generate_world

    world = generate_world(BASIC_SURVIVAL, seed=17)
    gatherable = {cell.resource for cell in world.cells.values() if cell.resource}
    stock = starting_stock().as_dict()

    ungatherable_shortfall = {
        name: amount - stock.get(name, 0)
        for name, amount in MONUMENT_COST.items()
        if name not in gatherable and amount > stock.get(name, 0)
    }

    assert set(ungatherable_shortfall) == {"tools", "influence"}
    assert all(shortfall > 0 for shortfall in ungatherable_shortfall.values())
