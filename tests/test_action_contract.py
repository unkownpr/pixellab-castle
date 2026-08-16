"""An action means exactly what it says, or it is refused.

Found by watching a real model play: it submitted
``{"kind": "gather", "resource": "wood", "x": 0, "y": 2}``, believing it had asked for
wood specifically. The parser read the coordinates and dropped ``resource`` on the floor,
so the agent was scored on a plan the simulation never saw. Silence is the wrong answer
to a field nobody implemented.
"""

import pytest

from castle_benchmark.actions import GatherAction, VALID_ACTION_KINDS
from castle_benchmark.persistence import ACTION_FIELDS, action_from_dict


def test_a_known_action_still_parses() -> None:
    action = action_from_dict({"kind": "gather", "x": 3, "y": 4})

    assert isinstance(action, GatherAction)
    assert (action.position.x, action.position.y) == (3, 4)


def test_an_unknown_field_is_refused_and_names_itself() -> None:
    with pytest.raises(ValueError) as error:
        action_from_dict({"kind": "gather", "x": 0, "y": 2, "resource": "wood"})

    assert "resource" in str(error.value)


def test_several_unknown_fields_are_all_reported() -> None:
    with pytest.raises(ValueError) as error:
        action_from_dict({"kind": "wait", "turns": 3, "reason": "thinking"})

    message = str(error.value)
    assert "reason" in message and "turns" in message


def test_optional_fields_are_still_optional() -> None:
    """A diplomacy action without its note is not an action with an unknown field."""
    action = action_from_dict({"kind": "diplomacy", "target_colony_id": "c2", "operation": "contact"})

    assert action.message == ""


def test_every_published_action_kind_declares_its_fields() -> None:
    """A kind added to the contract without an entry here would accept anything."""
    assert set(ACTION_FIELDS) == set(VALID_ACTION_KINDS)
