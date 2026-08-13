from hypothesis import given, settings, strategies as st

from castle_benchmark.actions import ActionBatch, GatherAction, WaitAction
from castle_benchmark.domain import ResourceStock
from castle_benchmark.engine import SimCore
from castle_benchmark.scenarios import BASIC_SURVIVAL


RESOURCE_NAMES = ("food", "water", "wood", "stone", "ore", "tools", "influence")


@given(
    st.dictionaries(
        st.sampled_from(RESOURCE_NAMES),
        st.integers(min_value=0, max_value=100),
    )
)
@settings(max_examples=100)
def test_non_negative_stock_accepts_any_non_negative_resource_vector(values: dict[str, int]) -> None:
    """Catches resource validation rejecting valid benchmark states."""
    stock = ResourceStock(**values)
    assert all(value >= 0 for value in stock.as_dict().values())


@given(st.lists(st.booleans(), min_size=1, max_size=40))
@settings(max_examples=100)
def test_valid_wait_and_gather_sequences_preserve_core_invariants(gather_flags: list[bool]) -> None:
    """Catches long action sequences producing negative stock or over-cap population."""
    sim = SimCore.create(BASIC_SURVIVAL, seed=71, colony_count=1)
    resource_positions = [
        position
        for position, cell in sim.state.world.cells.items()  # type: ignore[attr-defined]
        if cell.resource and cell.resource_amount > 0
    ]
    for flag in gather_flags:
        if sim.state.terminal:
            break
        action = GatherAction(resource_positions[0]) if flag and resource_positions else WaitAction()
        sim.resolve((ActionBatch(sim.state.turn, "c1", (action,)),))
        colony = sim.state.colonies["c1"]
        assert all(value >= 0 for value in colony.resources.as_dict().values())
        assert 0 <= colony.population <= colony.housing
