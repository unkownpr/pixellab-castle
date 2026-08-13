from dataclasses import asdict
import json

import pytest
from fastapi.testclient import TestClient

from castle_benchmark.api import create_app
from castle_benchmark.lobby import ControllerIdentity
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


def test_http_session_contract_matches_direct_pairing_flow(service: GameService) -> None:
    """Catches HTTP omitting a direct-service lifecycle step or leaking another capability."""
    now = 1_725_000_000.0
    client = TestClient(
        create_app(
            service,
            orchestrator_token="o" * 32,
            allowed_origins=("https://operator.example",),
            clock=lambda: now,
        )
    )

    created_response = client.post(
        "/api/sessions",
        headers={"Authorization": f"Bearer {'o' * 32}"},
        json={"scenario_id": "basic-survival-v1", "seed": 101, "colony_count": 1},
    )
    assert created_response.status_code == 201
    created = created_response.json()
    assert created == {
        "schema_version": "1.1",
        "match_id": created["match_id"],
        "scenario_id": "basic-survival-v1",
        "status": "draft",
        "admin_token": created["admin_token"],
    }

    pairing = client.post(
        f"/api/sessions/{created['match_id']}/slots/c1/pairing",
        headers={"Authorization": f"Bearer {created['admin_token']}"},
    ).json()
    claimed_response = client.post(
        "/api/pairings/claim",
        json={
            "pairing_code": pairing["pairing_code"],
            "identity": {
                "display_name": "HTTP controller",
                "provider": "openai",
                "model": "gpt-5",
            },
        },
    )
    assert claimed_response.status_code == 200
    claimed = claimed_response.json()
    assert set(claimed) == {
        "schema_version",
        "match_id",
        "controller_id",
        "colony_id",
        "controller_token",
    }
    assert claimed["match_id"] == created["match_id"]
    assert claimed["colony_id"] == "c1"

    heartbeat = client.post(
        f"/api/sessions/{created['match_id']}/heartbeat",
        headers={"Authorization": f"Bearer {claimed['controller_token']}"},
        json={"turn": 0, "status": "connected"},
    )
    started = client.post(
        f"/api/sessions/{created['match_id']}/start",
        headers={"Authorization": f"Bearer {created['admin_token']}"},
    )
    observed = client.get(
        f"/api/matches/{created['match_id']}/observation",
        headers={"Authorization": f"Bearer {claimed['controller_token']}"},
    )
    submitted = client.post(
        f"/api/matches/{created['match_id']}/actions",
        headers={"Authorization": f"Bearer {claimed['controller_token']}"},
        json={"turn": 0, "actions": [{"kind": "wait"}]},
    )

    assert heartbeat.json() == {
        "schema_version": "1.1",
        "match_id": created["match_id"],
        "status": "connected",
    }
    assert started.json()["status"] == "running"
    assert started.json()["schema_version"] == "1.1"
    assert observed.json()["schema_version"] == "1.1"
    assert observed.json()["colony_id"] == "c1"
    assert submitted.json()["schema_version"] == "1.1"
    assert submitted.json()["status"] == "resolved"

    direct = GameService()
    session = direct.create_session("direct-orchestrator", "basic-survival-v1", 101, 1)
    grant = direct.create_pairing(session.admin_token, "c1", now)
    direct_claim = direct.claim_slot_contract(
        grant.code or "",
        ControllerIdentity("Direct controller", "openai", "gpt-5"),
        now,
    )
    direct.heartbeat(str(direct_claim["controller_token"]), 0, "connected", now)
    direct.start_match(session.admin_token, now)
    direct_observed = asdict(direct.observe(str(direct_claim["controller_token"])))
    http_observed = observed.json()
    direct_observed.pop("schema_version")
    http_observed.pop("schema_version")
    assert json.loads(json.dumps(direct_observed)) == http_observed
    direct_submission = direct.submit_actions(
        str(direct_claim["controller_token"]), 0, ({"kind": "wait"},)
    )
    assert direct_submission.status == submitted.json()["status"] == "resolved"


def test_admin_http_read_models_and_websocket_are_secret_free(service: GameService) -> None:
    """Catches capability material escaping through lobby, operations, report, or live events."""
    client = TestClient(
        create_app(service, orchestrator_token="o" * 32, clock=lambda: 500.0)
    )
    created = client.post(
        "/api/sessions",
        headers={"Authorization": f"Bearer {'o' * 32}"},
        json={"scenario_id": "basic-survival-v1", "seed": 103, "colony_count": 1},
    ).json()
    pairing = client.post(
        f"/api/sessions/{created['match_id']}/slots/c1/pairing",
        headers={"Authorization": f"Bearer {created['admin_token']}"},
    ).json()
    claimed = client.post(
        "/api/pairings/claim",
        json={
            "pairing_code": pairing["pairing_code"],
            "identity": {"display_name": "Safe", "provider": "p", "model": "m"},
        },
    ).json()

    def assert_secret_free(value: object) -> None:
        serialized = str(value)
        assert created["admin_token"] not in serialized
        assert pairing["pairing_code"] not in serialized
        assert claimed["controller_token"] not in serialized
        assert "digest" not in serialized.lower()
        assert "controller_token" not in serialized
        assert "admin_token" not in serialized

    admin_headers = {"Authorization": f"Bearer {created['admin_token']}"}
    lobby = client.get(
        f"/api/sessions/{created['match_id']}/lobby", headers=admin_headers
    ).json()
    operations = client.get(
        f"/api/matches/{created['match_id']}/operations", headers=admin_headers
    ).json()
    report_response = client.get(
        f"/api/matches/{created['match_id']}/report", headers=admin_headers
    )
    assert report_response.status_code == 200
    report = report_response.json()
    assert "input_tokens" in report["metrics"]["cost"]["c1"]
    assert_secret_free(lobby)
    assert_secret_free(operations)
    assert_secret_free(report)

    with client.websocket_connect(
        f"/api/matches/{created['match_id']}/operations/ws",
        headers=admin_headers,
    ) as websocket:
        message = websocket.receive_json()
    assert message["type"] == "lobby.snapshot"
    assert message["schema_version"] == "1.1"
    assert_secret_free(message)


def test_http_can_configure_a_draft_baseline_slot_before_start(
    service: GameService,
) -> None:
    """Catches the browser-facing session contract being unable to configure mixed slots."""
    client = TestClient(
        create_app(service, orchestrator_token="o" * 32, clock=lambda: 300.0)
    )
    created = client.post(
        "/api/sessions",
        headers={"Authorization": f"Bearer {'o' * 32}"},
        json={"scenario_id": "basic-survival-v1", "seed": 167, "colony_count": 1},
    ).json()
    configured = client.post(
        f"/api/sessions/{created['match_id']}/slots/c1",
        headers={"Authorization": f"Bearer {created['admin_token']}"},
        json={"controller_type": "baseline", "baseline_kind": "survivalist"},
    )
    started = client.post(
        f"/api/sessions/{created['match_id']}/start",
        headers={"Authorization": f"Bearer {created['admin_token']}"},
    )

    assert configured.status_code == 200
    assert configured.json() == {
        "schema_version": "1.1",
        "match_id": created["match_id"],
        "colony_id": "c1",
        "controller_type": "baseline",
        "presence": "ready",
    }
    assert started.status_code == 200
    assert started.json()["status"] == "running"


def test_http_create_session_applies_slot_and_deadline_configuration_atomically() -> None:
    """Catches session creation ignoring the published controller/deadline configuration."""
    client = TestClient(
        create_app(GameService(), orchestrator_token="o" * 32, clock=lambda: 300.0)
    )
    created = client.post(
        "/api/sessions",
        headers={"Authorization": f"Bearer {'o' * 32}"},
        json={
            "scenario_id": "basic-survival-v1",
            "seed": 211,
            "colony_count": 1,
            "deadline_seconds": 12,
            "slots": [
                {
                    "colony_id": "c1",
                    "controller_type": "baseline",
                    "baseline_kind": "trader",
                }
            ],
        },
    ).json()
    admin_headers = {"Authorization": f"Bearer {created['admin_token']}"}
    started = client.post(
        f"/api/sessions/{created['match_id']}/start", headers=admin_headers
    )
    operations = client.get(
        f"/api/matches/{created['match_id']}/operations", headers=admin_headers
    ).json()

    assert started.status_code == 200
    assert operations["deadline_seconds"] == 12
    assert operations["deadline_at"] == 312.0
    assert operations["slots"][0]["controller_type"] == "baseline"
    assert operations["slots"][0]["baseline_kind"] == "trader"


def test_http_hands_one_human_slot_capability_to_its_admin() -> None:
    """Catches configured browser-human slots having no secure gameplay handoff."""
    client = TestClient(
        create_app(GameService(), orchestrator_token="o" * 32, clock=lambda: 350.0)
    )
    created = client.post(
        "/api/sessions",
        headers={"Authorization": f"Bearer {'o' * 32}"},
        json={"scenario_id": "basic-survival-v1", "seed": 179, "colony_count": 1},
    ).json()
    admin_headers = {"Authorization": f"Bearer {created['admin_token']}"}
    client.post(
        f"/api/sessions/{created['match_id']}/slots/c1",
        headers=admin_headers,
        json={"controller_type": "human"},
    )
    client.post(
        f"/api/sessions/{created['match_id']}/start", headers=admin_headers
    )

    handoff = client.post(
        f"/api/sessions/{created['match_id']}/slots/c1/human-capability",
        headers=admin_headers,
    )

    assert handoff.status_code == 200
    assert set(handoff.json()) == {
        "schema_version",
        "match_id",
        "colony_id",
        "controller_token",
    }
    submitted = client.post(
        f"/api/matches/{created['match_id']}/actions",
        headers={"Authorization": f"Bearer {handoff.json()['controller_token']}"},
        json={"turn": 0, "actions": [{"kind": "wait"}]},
    )
    assert submitted.json()["status"] == "resolved"


def test_http_running_replacement_preserves_selected_baseline_kind() -> None:
    """Catches fallback replacement silently discarding the operator's baseline choice."""
    service = GameService()
    session = service.create_session("direct", "basic-survival-v1", 181, 1)
    service.configure_slot(session.admin_token, "c1", "human")
    service.start_match(session.admin_token, now=1.0)
    client = TestClient(create_app(service, orchestrator_token="o" * 32, clock=lambda: 2.0))

    response = client.post(
        f"/api/sessions/{session.match_id}/slots/c1/replace",
        headers={"Authorization": f"Bearer {session.admin_token}"},
        json={"replacement": "baseline", "baseline_kind": "trader"},
    )

    assert response.status_code == 200
    snapshot = service.lobby_status(session.admin_token, now=2.0)
    assert snapshot["slots"][0]["baseline_kind"] == "trader"


def test_operations_projection_retains_ordered_fast_turn_events() -> None:
    """Catches snapshot polling losing submit/resolve transitions between two polls."""
    service = GameService()
    session = service.create_session("direct", "basic-survival-v1", 191, 1)
    service.configure_slot(session.admin_token, "c1", "human")
    service.start_match(session.admin_token, now=1.0)
    token = service.human_controller_token(session.admin_token, "c1")
    service.submit_actions(token, 0, ({"kind": "wait"},))

    events = service.operations_snapshot(session.admin_token, now=2.0)["events"]
    kinds = [event["kind"] for event in events]
    assert kinds.index("turn_opened") < kinds.index("controller_submitted")
    assert kinds.index("controller_submitted") < kinds.index("turn_resolved")
    assert "metric_updated" in kinds
    resolved = next(event for event in events if event["kind"] == "turn_resolved")
    assert resolved["turn"] == 0


def test_operations_projection_bounds_retained_events_without_resetting_sequence() -> None:
    """Catches audit/event abuse growing memory without bound or replaying sequence IDs."""
    service = GameService()
    session = service.create_session("direct", "basic-survival-v1", 239, 1)
    service.configure_slot(session.admin_token, "c1", "human")
    service.start_match(session.admin_token, now=1.0)
    token = service.human_controller_token(session.admin_token, "c1")
    for _ in range(2_100):
        service.record_usage(token, input_tokens=0, output_tokens=0, latency_ms=0)

    events = service.operations_snapshot(session.admin_token, now=2.0)["events"]
    sequences = [event["sequence"] for event in events]
    assert len(events) == 2_048
    assert sequences == list(range(sequences[0], sequences[0] + 2_048))


def test_legacy_local_match_report_remains_a_typed_http_contract() -> None:
    """Catches session-only report fields turning the legacy compatibility route into a 500."""
    client = TestClient(create_app(GameService()))
    created = client.post(
        "/api/matches",
        json={"scenario_id": "basic-survival-v1", "seed": 229, "colony_count": 1},
    ).json()

    response = client.get(
        f"/api/matches/{created['match_id']}/report",
        headers={"Authorization": f"Bearer {created['admin_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["schema_version"] == "1.1"
    assert response.json()["metrics"]["cost"]["c1"]["timeouts"] == 0


def test_operations_websocket_pushes_sequence_events_without_refresh() -> None:
    """Catches the admin WebSocket depending on client polling and dropping fast transitions."""
    service = GameService()
    session = service.create_session("direct", "basic-survival-v1", 193, 1)
    service.configure_slot(session.admin_token, "c1", "human")
    client = TestClient(create_app(service, clock=lambda: 5.0))

    with client.websocket_connect(
        f"/api/matches/{session.match_id}/operations/ws",
        headers={"Authorization": f"Bearer {session.admin_token}"},
    ) as websocket:
        assert websocket.receive_json()["type"] == "lobby.snapshot"
        service.start_match(session.admin_token, now=5.0)
        pushed = websocket.receive_json()

    assert pushed["type"] == "turn.opened"
    assert pushed["payload"]["sequence"] == 2
    assert pushed["payload"]["kind"] == "turn_opened"


def test_operations_websocket_emits_presence_and_terminal_turn_sequence() -> None:
    """Catches required typed presence/submission/resolution/metric/completion events going silent."""
    service = GameService()
    session = service.create_session("direct", "basic-survival-v1", 223, 1)
    pairing = service.create_pairing(session.admin_token, "c1", now=1.0)
    claimed = service.claim_slot_contract(
        pairing.code or "", ControllerIdentity("Live", "p", "m"), now=1.0
    )
    token = str(claimed["controller_token"])
    service.heartbeat(token, 0, "connected", now=2.0)
    service.start_match(session.admin_token, now=2.0)
    for turn in range(53):
        service.submit_actions(token, turn, ({"kind": "wait"},))
    client = TestClient(create_app(service, clock=lambda: 50.0))

    with client.websocket_connect(
        f"/api/matches/{session.match_id}/operations/ws",
        headers={"Authorization": f"Bearer {session.admin_token}"},
    ) as websocket:
        assert websocket.receive_json()["type"] == "lobby.snapshot"
        service.heartbeat(token, 53, "disconnected", now=49.0)
        assert websocket.receive_json()["type"] == "controller.presence_changed"
        service.heartbeat(token, 53, "connected", now=49.2)
        assert websocket.receive_json()["type"] == "controller.presence_changed"
        service.submit_actions(token, 53, ({"kind": "wait"},))
        pushed_types: list[str] = []
        while "match.completed" not in pushed_types:
            pushed_types.append(websocket.receive_json()["type"])

    assert pushed_types[0] == "controller.submitted"
    assert "controller.presence_changed" in pushed_types
    assert pushed_types[-3:] == ["turn.resolved", "metric.updated", "match.completed"]


def test_controller_cannot_use_admin_http_mutations(service: GameService) -> None:
    """Catches controller capabilities crossing into session administration."""
    client = TestClient(create_app(service, orchestrator_token="o" * 32, clock=lambda: 50.0))
    created = client.post(
        "/api/sessions",
        headers={"Authorization": f"Bearer {'o' * 32}"},
        json={"scenario_id": "basic-survival-v1", "seed": 107, "colony_count": 1},
    ).json()
    pairing = client.post(
        f"/api/sessions/{created['match_id']}/slots/c1/pairing",
        headers={"Authorization": f"Bearer {created['admin_token']}"},
    ).json()
    claimed = client.post(
        "/api/pairings/claim",
        json={
            "pairing_code": pairing["pairing_code"],
            "identity": {"display_name": "Agent", "provider": "p", "model": "m"},
        },
    ).json()

    denied = client.post(
        f"/api/sessions/{created['match_id']}/slots/c1/pairing",
        headers={"Authorization": f"Bearer {claimed['controller_token']}"},
    )

    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "forbidden"


def test_http_accepts_ready_heartbeat_and_browser_websocket_subprotocol_auth(
    service: GameService,
) -> None:
    """Catches documented readiness or browser-compatible WS authentication regressing."""
    client = TestClient(
        create_app(
            service,
            orchestrator_token="o" * 32,
            allowed_origins=("https://ops.example",),
            clock=lambda: 200.0,
        )
    )
    created = client.post(
        "/api/sessions",
        headers={"Authorization": f"Bearer {'o' * 32}"},
        json={"scenario_id": "basic-survival-v1", "seed": 163, "colony_count": 1},
    ).json()
    pairing = client.post(
        f"/api/sessions/{created['match_id']}/slots/c1/pairing",
        headers={"Authorization": f"Bearer {created['admin_token']}"},
    ).json()
    claimed = client.post(
        "/api/pairings/claim",
        json={
            "pairing_code": pairing["pairing_code"],
            "identity": {"display_name": "Ready", "provider": "p", "model": "m"},
        },
    ).json()

    heartbeat = client.post(
        f"/api/sessions/{created['match_id']}/heartbeat",
        headers={"Authorization": f"Bearer {claimed['controller_token']}"},
        json={"turn": 0, "status": "ready"},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["status"] == "ready"

    ticket = client.post(
        f"/api/matches/{created['match_id']}/operations/ticket",
        headers={"Authorization": f"Bearer {created['admin_token']}"},
    ).json()["websocket_ticket"]
    with client.websocket_connect(
        f"/api/matches/{created['match_id']}/operations/ws",
        subprotocols=["castle.operations", ticket],
        headers={"Origin": "https://ops.example"},
    ) as websocket:
        assert websocket.accepted_subprotocol == "castle.operations"
        message = websocket.receive_json()
    assert message["type"] == "lobby.snapshot"
