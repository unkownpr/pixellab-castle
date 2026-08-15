from __future__ import annotations

from fastapi.testclient import TestClient

from castle_benchmark.api import create_app
from castle_benchmark.lobby import ControllerIdentity
from castle_benchmark.scenarios import get_scenario
from castle_benchmark.service import GameService


def _session_two_humans(service: GameService) -> tuple[object, str, str]:
    session = service.create_session("direct", "basic-survival-v1", 47, 2)
    service.configure_slot(session.admin_token, "c1", "human")
    service.configure_slot(session.admin_token, "c2", "human")
    service.start_match(session.admin_token, now=1.0)
    c1 = service.human_controller_token(session.admin_token, "c1")
    c2 = service.human_controller_token(session.admin_token, "c2")
    return session, c1, c2


def test_spectator_view_returns_the_whole_world_for_a_valid_admin_token() -> None:
    """Catches the operator's world view being anything less than the full authoritative grid."""
    service = GameService()
    created = service.create_match("basic-survival-v1", seed=41, colony_count=2)
    client = TestClient(create_app(service))

    response = client.get(
        f"/api/matches/{created.match_id}/spectator",
        headers={"Authorization": f"Bearer {created.admin_token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    world_size = get_scenario("basic-survival-v1").width * get_scenario("basic-survival-v1").height
    assert payload["schema_version"] == "1.1"
    assert payload["turn"] == 0
    assert len(payload["visible_cells"]) == world_size
    assert set(payload["colonies"]) == {"c1", "c2"}
    assert {structure["colony_id"] for structure in payload["visible_structures"]} == {"c1", "c2"}
    controller_view = service.observe(created.controller_tokens["c1"])
    assert len(controller_view.visible_cells) < len(payload["visible_cells"])


def test_spectator_view_rejects_a_controller_token_and_anonymous_requests() -> None:
    """Catches the fog of war being bypassable with a controller capability or no capability at all."""
    service = GameService()
    created = service.create_match("basic-survival-v1", seed=43, colony_count=2)
    client = TestClient(create_app(service))

    denied = client.get(
        f"/api/matches/{created.match_id}/spectator",
        headers={"Authorization": f"Bearer {created.controller_tokens['c1']}"},
    )
    anonymous = client.get(f"/api/matches/{created.match_id}/spectator")

    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "forbidden"
    assert anonymous.status_code == 401
    assert anonymous.json()["detail"]["code"] == "unauthorized"


def test_spectator_view_does_not_weaken_fog_limited_observe() -> None:
    """Catches the spectator projection leaking into the controller observation path."""
    service = GameService()
    created = service.create_match("basic-survival-v1", seed=45, colony_count=2)

    observation = service.observe(created.controller_tokens["c1"])
    world_size = get_scenario("basic-survival-v1").width * get_scenario("basic-survival-v1").height

    assert len(observation.visible_cells) < world_size


def test_decision_feed_reports_each_colony_in_order_with_rejections_and_reasons() -> None:
    """Catches the decision feed dropping actions, ordering, or rejection reasons."""
    service = GameService()
    session, c1, c2 = _session_two_humans(service)

    assert service.submit_actions(c1, 0, ({"kind": "wait"},)).status == "pending"
    service.submit_actions(c2, 0, ({"kind": "gather", "x": 0, "y": 0},))

    snapshot = service.operations_snapshot(session.admin_token, now=2.0)
    resolved = [event for event in snapshot["events"] if event["kind"] == "turn_resolved"]
    assert len(resolved) == 1

    decisions = resolved[0]["data"]["decisions"]
    assert [entry["colony_id"] for entry in decisions] == ["c1", "c2"]
    assert decisions[0]["actions"] == [{"kind": "wait"}]
    assert decisions[0]["results"] == [{"kind": "wait", "status": "accepted", "code": "ok"}]
    assert decisions[1]["actions"][0]["kind"] == "gather"
    assert decisions[1]["results"] == [
        {"kind": "gather", "status": "rejected", "code": "cell_not_visible"}
    ]


def test_decision_feed_is_secret_free_across_http_and_websocket() -> None:
    """Catches capability material or pairing codes leaking through the spectator view or the feed."""
    service = GameService()
    client = TestClient(
        create_app(service, orchestrator_token="o" * 32, clock=lambda: 500.0)
    )
    created = client.post(
        "/api/sessions",
        headers={"Authorization": f"Bearer {'o' * 32}"},
        json={"scenario_id": "basic-survival-v1", "seed": 103, "colony_count": 2},
    ).json()
    admin_headers = {"Authorization": f"Bearer {created['admin_token']}"}
    for colony_id in ("c1", "c2"):
        pairing = client.post(
            f"/api/sessions/{created['match_id']}/slots/{colony_id}/pairing",
            headers=admin_headers,
        ).json()
        claimed = client.post(
            "/api/pairings/claim",
            json={
                "pairing_code": pairing["pairing_code"],
                "identity": {"display_name": f"Agent {colony_id}", "provider": "p", "model": "m"},
            },
        ).json()
        client.post(
            f"/api/sessions/{created['match_id']}/heartbeat",
            headers={"Authorization": f"Bearer {claimed['controller_token']}"},
            json={"turn": 0, "status": "connected"},
        )
    client.post(
        f"/api/sessions/{created['match_id']}/start", headers=admin_headers
    )

    spectator = client.get(
        f"/api/matches/{created['match_id']}/spectator", headers=admin_headers
    ).json()
    operations = client.get(
        f"/api/matches/{created['match_id']}/operations", headers=admin_headers
    ).json()

    def assert_secret_free(value: object) -> None:
        serialized = str(value)
        assert created["admin_token"] not in serialized
        assert "controller_token" not in serialized
        assert "pairing_code" not in serialized
        assert "digest" not in serialized.lower()

    assert_secret_free(spectator)
    assert_secret_free(operations)

    with client.websocket_connect(
        f"/api/matches/{created['match_id']}/operations/ws", headers=admin_headers
    ) as websocket:
        message = websocket.receive_json()
    assert message["type"] == "lobby.snapshot"
    assert_secret_free(message)


def test_operations_websocket_publishes_resolved_decisions() -> None:
    """Catches the decision feed never being pushed to the live operations channel."""
    service = GameService()
    session, c1, c2 = _session_two_humans(service)
    client = TestClient(create_app(service, clock=lambda: 5.0))

    with client.websocket_connect(
        f"/api/matches/{session.match_id}/operations/ws",
        headers={"Authorization": f"Bearer {session.admin_token}"},
    ) as websocket:
        assert websocket.receive_json()["type"] == "lobby.snapshot"
        service.submit_actions(c1, 0, ({"kind": "wait"},))
        service.submit_actions(c2, 0, ({"kind": "gather", "x": 0, "y": 0},))
        messages: list[dict[str, object]] = []
        while not any(message["type"] == "turn.resolved" for message in messages):
            messages.append(websocket.receive_json())

    resolved = next(
        message for message in messages if message["type"] == "turn.resolved"
    )
    decisions = resolved["payload"]["data"]["decisions"]  # type: ignore[index]
    assert [entry["colony_id"] for entry in decisions] == ["c1", "c2"]
