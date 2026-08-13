import pytest
from fastapi.testclient import TestClient

from castle_benchmark.api import create_app
from castle_benchmark.service import ForbiddenError, GameService


@pytest.fixture
def service() -> GameService:
    return GameService()


def test_controller_can_only_observe_own_colony(service: GameService) -> None:
    """Catches controller capabilities leaking another colony's private view."""
    created = service.create_match("basic-survival-v1", seed=73, colony_count=2)
    c1_token = created.controller_tokens["c1"]

    assert service.observe(c1_token).colony_id == "c1"
    with pytest.raises(ForbiddenError):
        service.observe(c1_token, requested_colony_id="c2")


def test_http_contract_rejects_cross_colony_observation(service: GameService) -> None:
    """Catches HTTP adapting away the direct-service authorization rule."""
    client = TestClient(create_app(service))
    created = client.post(
        "/api/matches", json={"scenario_id": "basic-survival-v1", "seed": 79, "colony_count": 2}
    )
    assert created.status_code == 201
    payload = created.json()
    token = payload["controller_tokens"]["c1"]

    own = client.get(f"/api/matches/{payload['match_id']}/observation", headers={"Authorization": f"Bearer {token}"})
    forbidden = client.get(
        f"/api/matches/{payload['match_id']}/observation?colony_id=c2",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert own.status_code == 200
    assert own.json()["colony_id"] == "c1"
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "forbidden"


def test_turn_resolves_only_after_all_controllers_submit(service: GameService) -> None:
    """Catches a fast model gaining a timing advantage over another controller."""
    created = service.create_match("basic-survival-v1", seed=83, colony_count=2)

    first = service.submit_actions(
        created.controller_tokens["c1"], turn=0, actions=({"kind": "wait"},)
    )
    second = service.submit_actions(
        created.controller_tokens["c2"], turn=0, actions=({"kind": "wait"},)
    )

    assert first.status == "pending"
    assert first.turn == 0
    assert second.status == "resolved"
    assert second.turn == 1


def test_stale_http_action_has_stable_error_code(service: GameService) -> None:
    """Catches adapter-specific stale-turn behavior or unstable error text."""
    client = TestClient(create_app(service))
    payload = client.post(
        "/api/matches", json={"scenario_id": "basic-survival-v1", "seed": 89, "colony_count": 1}
    ).json()
    token = payload["controller_tokens"]["c1"]

    response = client.post(
        f"/api/matches/{payload['match_id']}/actions",
        headers={"Authorization": f"Bearer {token}"},
        json={"turn": 99, "actions": [{"kind": "wait"}]},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_turn"


def test_live_report_accumulates_model_usage_and_decision_metrics(service: GameService) -> None:
    created = service.create_match("basic-survival-v1", seed=91, colony_count=1)
    token = created.controller_tokens["c1"]

    service.record_usage(token, input_tokens=120, output_tokens=35, latency_ms=480)
    service.record_mcp_call(token)
    service.submit_actions(token, turn=0, actions=({"kind": "wait"},))
    report = service.run_report(created.admin_token)

    assert report["metrics"]["cost"]["c1"] == {
        "model_calls": 1,
        "mcp_calls": 1,
        "input_tokens": 120,
        "output_tokens": 35,
        "latency_ms": 480,
    }
    assert report["metrics"]["decision_quality"]["c1"]["invalid_actions"] == 0
