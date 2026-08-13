import pytest

from castle_benchmark.actions import ActionBatch, WaitAction
from castle_benchmark.domain import Position, ResourceStock


def test_resource_stock_rejects_negative_values() -> None:
    """Catches any mutation that permits impossible negative resources."""
    with pytest.raises(ValueError, match="non-negative"):
        ResourceStock(food=-1)


def test_resource_stock_applies_delta_without_mutating_original() -> None:
    """Catches accidental mutable stock updates or incorrect resource arithmetic."""
    original = ResourceStock(food=10, wood=4)
    updated = original.apply({"food": -3, "wood": 2})

    assert original.food == 10
    assert updated.food == 7
    assert updated.wood == 6


def test_position_uses_integer_authoritative_coordinates() -> None:
    """Catches accepting floating point positions in the authoritative model."""
    with pytest.raises(TypeError, match="integers"):
        Position(1.5, 2)  # type: ignore[arg-type]


def test_action_batch_is_bound_to_turn_and_colony() -> None:
    """Catches loss of the anti-stale turn or controller ownership binding."""
    batch = ActionBatch(turn=3, colony_id="c1", actions=(WaitAction(),))

    assert batch.turn == 3
    assert batch.colony_id == "c1"
    assert batch.actions[0].kind == "wait"


def test_action_batch_rejects_empty_colony_id() -> None:
    """Catches anonymous action batches entering the turn barrier."""
    with pytest.raises(ValueError, match="colony_id"):
        ActionBatch(turn=0, colony_id="", actions=(WaitAction(),))
