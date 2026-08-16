"""A submission the parser refuses still says something about the controller.

Found by running two models in one match: one of them attached a field the gather action
does not have, every submission was refused before the engine saw it, and its
decision-quality row stayed spotless. Rejections were only counted once an action reached
the simulation, so the controller that could not form a legal request looked better than
one whose legal requests were turned down.
"""

import pytest

from castle_benchmark.service import GameService, InvalidActionError


def report_for(service: GameService, admin_token: str) -> dict:
    return service.run_report(admin_token)["metrics"]["decision_quality"]


def test_a_refused_submission_is_counted_against_the_colony_that_sent_it() -> None:
    service = GameService()
    match = service.create_match("basic-survival-v1", 17, 2)
    controller = match.controller_tokens["c1"]

    with pytest.raises(InvalidActionError):
        service.submit_actions(controller, 0, [{"kind": "gather", "x": 3, "y": 4, "resource": "wood"}])

    quality = report_for(service, match.admin_token)
    assert quality["c1"]["malformed_submissions"] == 1
    assert quality["c2"]["malformed_submissions"] == 0


def test_a_legal_submission_leaves_the_counter_alone() -> None:
    service = GameService()
    match = service.create_match("basic-survival-v1", 17, 2)

    service.submit_actions(match.controller_tokens["c1"], 0, [{"kind": "wait"}])

    assert report_for(service, match.admin_token)["c1"]["malformed_submissions"] == 0


def test_every_refusal_counts_not_just_the_first() -> None:
    """A controller that never learns the schema should look worse each time it tries."""
    service = GameService()
    match = service.create_match("basic-survival-v1", 17, 2)
    controller = match.controller_tokens["c1"]

    for _ in range(3):
        with pytest.raises(InvalidActionError):
            service.submit_actions(controller, 0, [{"kind": "gather", "x": 1, "y": 1, "nope": True}])

    assert report_for(service, match.admin_token)["c1"]["malformed_submissions"] == 3
