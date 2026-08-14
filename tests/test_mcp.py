import json
from dataclasses import asdict

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.fastmcp.exceptions import ToolError
from types import SimpleNamespace

from castle_benchmark.api import create_app
from castle_benchmark.mcp_server import build_mcp_server
from castle_benchmark.service import GameService


@pytest.mark.asyncio
async def test_mcp_exposes_versioned_benchmark_tools() -> None:
    """Catches MCP surface drift that would break model clients."""
    server = build_mcp_server(GameService(), orchestrator_token="test-orchestrator")

    tools = await server.list_tools()

    assert {tool.name for tool in tools} >= {
        "benchmark.list_scenarios",
        "benchmark.create_match",
        "benchmark.create_session",
        "benchmark.create_pairing",
        "benchmark.claim_slot",
        "benchmark.heartbeat",
        "benchmark.start_match",
        "benchmark.replace_controller",
        "benchmark.lobby_status",
        "benchmark.join_match",
        "benchmark.observe",
        "benchmark.submit_actions",
        "benchmark.match_status",
        "benchmark.record_usage",
        "benchmark.run_report",
    }


@pytest.mark.asyncio
async def test_streamable_http_does_not_register_local_capability_recovery_tools() -> None:
    """Catches remote MCP exposing the legacy admin-to-controller secret bridge."""
    remote = build_mcp_server(
        GameService(), orchestrator_token="o" * 32, transport="streamable-http"
    )

    names = {tool.name for tool in await remote.list_tools()}

    assert "benchmark.create_match" not in names
    assert "benchmark.join_match" not in names
    assert {
        "benchmark.create_session",
        "benchmark.create_pairing",
        "benchmark.claim_slot",
        "benchmark.observe",
        "benchmark.submit_actions",
    } <= names
    with pytest.raises(ToolError):
        await remote.call_tool(
            "benchmark.create_match",
            {"orchestrator_token": "o" * 32, "colony_count": 1},
        )


def test_stdio_server_cannot_be_reused_as_streamable_http() -> None:
    """Catches a caller bypassing transport-specific registration after construction."""
    local = build_mcp_server(GameService(), orchestrator_token="o" * 32)

    with pytest.raises(ValueError, match="transport"):
        local.streamable_http_app()


@pytest.mark.asyncio
async def test_mcp_create_and_observe_use_same_service_contract() -> None:
    """Catches MCP returning a different observation contract than HTTP/direct use."""
    server = build_mcp_server(GameService(), orchestrator_token="test-orchestrator")

    created_content = await server.call_tool(
        "benchmark.create_match",
        {"orchestrator_token": "test-orchestrator", "scenario_id": "basic-survival-v1", "seed": 97, "colony_count": 1},
    )
    created = json.loads(created_content[0][0].text)
    joined_content = await server.call_tool(
        "benchmark.join_match", {"admin_token": created["admin_token"], "colony_id": "c1"}
    )
    joined = json.loads(joined_content[0][0].text)
    observed_content = await server.call_tool(
        "benchmark.observe", {"controller_token": joined["controller_token"]}
    )
    observed = json.loads(observed_content[0][0].text)

    assert observed["scenario_id"] == "basic-survival-v1"
    assert observed["colony_id"] == "c1"
    assert "resources" in observed["colony"]

    admin_report = json.loads(
        (await server.call_tool("benchmark.run_report", {"admin_token": created["admin_token"]}))[0][0].text
    )
    assert admin_report["metrics"]["cost"]["c1"]["mcp_calls"] == 1


async def call(server: object, name: str, arguments: dict[str, object]) -> dict[str, object]:
    content = await server.call_tool(name, arguments)  # type: ignore[attr-defined]
    return json.loads(content[0][0].text)


@pytest.mark.asyncio
async def test_mcp_session_pairing_claim_and_gameplay_contract() -> None:
    """Catches MCP lifecycle drift and any claim response capability overexposure."""
    now = 900.0
    service = GameService()
    server = build_mcp_server(
        service, orchestrator_token="o" * 32, clock=lambda: now
    )

    created = await call(
        server,
        "benchmark.create_session",
        {
            "orchestrator_token": "o" * 32,
            "scenario_id": "basic-survival-v1",
            "seed": 109,
            "colony_count": 1,
        },
    )
    pairing = await call(
        server,
        "benchmark.create_pairing",
        {"admin_token": created["admin_token"], "colony_id": "c1"},
    )
    claimed = await call(
        server,
        "benchmark.claim_slot",
        {
            "pairing_code": pairing["pairing_code"],
            "identity": {
                "display_name": "MCP controller",
                "provider": "openai",
                "model": "gpt-5",
            },
        },
    )
    assert set(claimed) == {
        "schema_version",
        "match_id",
        "controller_id",
        "colony_id",
        "controller_token",
    }
    assert claimed["match_id"] == created["match_id"]

    heartbeat = await call(
        server,
        "benchmark.heartbeat",
        {"controller_token": claimed["controller_token"], "turn": 0, "status": "connected"},
    )
    started = await call(
        server, "benchmark.start_match", {"admin_token": created["admin_token"]}
    )
    observed = await call(
        server, "benchmark.observe", {"controller_token": claimed["controller_token"]}
    )
    direct_before_submit = asdict(service.observe(str(claimed["controller_token"])))
    submitted = await call(
        server,
        "benchmark.submit_actions",
        {
            "controller_token": claimed["controller_token"],
            "turn": 0,
            "actions": [{"kind": "wait"}],
        },
    )
    lobby = await call(
        server, "benchmark.lobby_status", {"admin_token": created["admin_token"]}
    )

    assert heartbeat["status"] == "connected"
    assert started["status"] == "running"
    assert observed["colony_id"] == "c1"
    direct_observed = direct_before_submit
    direct_observed.pop("schema_version")
    normalized_mcp = dict(observed)
    normalized_mcp.pop("schema_version")
    assert normalized_mcp == json.loads(json.dumps(direct_observed))
    assert submitted["status"] == "resolved"
    assert lobby["match_id"] == created["match_id"]
    assert "controller_token" not in json.dumps(lobby)
    assert "admin_token" not in json.dumps(lobby)


@pytest.mark.asyncio
async def test_mcp_counts_each_controller_wrapper_before_service_and_keeps_usage_reported() -> None:
    """Catches MCP call counts being inferred from optional adapter usage reports."""
    now = 1_000.0
    service = GameService()
    server = build_mcp_server(service, orchestrator_token="o" * 32, clock=lambda: now)
    created = await call(
        server,
        "benchmark.create_session",
        {
            "orchestrator_token": "o" * 32,
            "scenario_id": "basic-survival-v1",
            "seed": 113,
            "colony_count": 1,
        },
    )
    pairing = await call(
        server,
        "benchmark.create_pairing",
        {"admin_token": created["admin_token"], "colony_id": "c1"},
    )
    claimed = await call(
        server,
        "benchmark.claim_slot",
        {
            "pairing_code": pairing["pairing_code"],
            "identity": {"display_name": "Metered", "provider": "p", "model": "m"},
        },
    )
    token = claimed["controller_token"]

    await call(
        server,
        "benchmark.heartbeat",
        {"controller_token": token, "turn": 0, "status": "connected"},
    )
    await call(server, "benchmark.start_match", {"admin_token": created["admin_token"]})
    await call(server, "benchmark.observe", {"controller_token": token})
    await call(
        server,
        "benchmark.record_usage",
        {"controller_token": token, "input_tokens": 10, "output_tokens": 3, "latency_ms": 25},
    )
    await call(
        server,
        "benchmark.submit_actions",
        {"controller_token": token, "turn": 0, "actions": [{"kind": "wait"}]},
    )
    report = await call(
        server, "benchmark.run_report", {"admin_token": created["admin_token"]}
    )

    assert report["metrics"]["server_measured"]["mcp_calls"]["c1"] == 4
    assert report["metrics"]["adapter_reported_model_usage"]["c1"] == {
        "model_calls": 1,
        "input_tokens": 10,
        "output_tokens": 3,
        "latency_ms": 25,
    }


@pytest.mark.asyncio
async def test_deprecated_create_match_alias_never_returns_controller_tokens() -> None:
    """Catches the compatibility alias handing every controller secret to one caller."""
    server = build_mcp_server(GameService(), orchestrator_token="o" * 32)

    created = await call(
        server,
        "benchmark.create_match",
        {
            "orchestrator_token": "o" * 32,
            "scenario_id": "basic-survival-v1",
            "seed": 127,
            "colony_count": 2,
        },
    )

    assert "controller_tokens" not in created
    assert "controller_token" not in created


@pytest.mark.asyncio
async def test_mcp_rejects_oversized_heartbeat_payload_before_authorization() -> None:
    """Catches MCP wrappers other than claim/submit bypassing the protocol payload limit."""
    server = build_mcp_server(GameService(), orchestrator_token="o" * 32)

    response = await call(
        server,
        "benchmark.heartbeat",
        {"controller_token": "x" * (16 * 1024 + 1), "turn": 0, "status": "ready"},
    )

    assert response == {
        "error": {
            "code": "payload_too_large",
            "message": "request payload exceeds 16 KiB",
        }
    }


@pytest.mark.asyncio
async def test_mcp_unknown_pairing_codes_share_bounded_attempt_policy() -> None:
    """Catches MCP claim bypassing the pairing-code abuse limit enforced by HTTP."""
    server = build_mcp_server(
        GameService(), orchestrator_token="o" * 32, clock=lambda: 10.0
    )
    arguments = {
        "pairing_code": "unknown-code",
        "identity": {"display_name": "Agent", "provider": "p", "model": "m"},
    }

    for _ in range(5):
        assert (await call(server, "benchmark.claim_slot", arguments))["error"][
            "code"
        ] == "unauthorized"
    blocked = await call(server, "benchmark.claim_slot", arguments)

    assert blocked["error"]["code"] == "pairing_attempt_limit"


def test_mcp_peer_budget_survives_session_reconnect_and_trusts_only_configured_proxy() -> None:
    """Catches Streamable HTTP reconnects or spoofed forwarding headers resetting peer limits."""
    from castle_benchmark.mcp_server import resolve_mcp_peer

    def context(session: object, direct: str, forwarded: str | None = None) -> object:
        headers = {} if forwarded is None else {"x-forwarded-for": forwarded}
        request = SimpleNamespace(client=SimpleNamespace(host=direct), headers=headers)
        return SimpleNamespace(
            session=session,
            request_context=SimpleNamespace(request=request),
        )

    first = context(object(), "10.1.2.3", "203.0.113.7")
    reconnected = context(object(), "10.1.2.3", "203.0.113.7")

    assert resolve_mcp_peer(first, ()) == resolve_mcp_peer(reconnected, ()) == "10.1.2.3"
    assert resolve_mcp_peer(first, ("10.0.0.0/8",)) == "203.0.113.7"


@pytest.mark.asyncio
async def test_streamable_http_runner_disables_uvicorn_proxy_header_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches Uvicorn rewriting the direct peer before explicit proxy trust is applied."""
    import uvicorn

    captured: dict[str, object] = {}

    class FakeConfig:
        def __init__(self, _app: object, **kwargs: object) -> None:
            captured.update(kwargs)

    class FakeServer:
        def __init__(self, _config: object) -> None:
            pass

        async def serve(self) -> None:
            return None

    monkeypatch.setattr(uvicorn, "Config", FakeConfig)
    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    server = build_mcp_server(
        GameService(),
        orchestrator_token="o" * 32,
        transport="streamable-http",
    )

    await server.run_streamable_http_async()

    assert captured["proxy_headers"] is False


@pytest.mark.asyncio
async def test_mcp_counts_rejected_valid_controller_invocation_before_execution() -> None:
    """Catches wrapper telemetry omitting a valid call rejected by the payload boundary."""
    now = 20.0
    service = GameService()
    server = build_mcp_server(service, orchestrator_token="o" * 32, clock=lambda: now)
    created = await call(
        server,
        "benchmark.create_session",
        {
            "orchestrator_token": "o" * 32,
            "scenario_id": "basic-survival-v1",
            "seed": 227,
            "colony_count": 1,
        },
    )
    pairing = await call(
        server,
        "benchmark.create_pairing",
        {"admin_token": created["admin_token"], "colony_id": "c1"},
    )
    claimed = await call(
        server,
        "benchmark.claim_slot",
        {
            "pairing_code": pairing["pairing_code"],
            "identity": {"display_name": "Meter", "provider": "p", "model": "m"},
        },
    )
    token = claimed["controller_token"]

    rejected = await call(
        server,
        "benchmark.submit_actions",
        {
            "controller_token": token,
            "turn": 0,
            "actions": [{"kind": "wait", "message": "x" * (16 * 1024)}],
        },
    )
    report = await call(
        server, "benchmark.run_report", {"admin_token": created["admin_token"]}
    )

    assert rejected["error"]["code"] == "payload_too_large"
    assert report["metrics"]["server_measured"]["mcp_calls"]["c1"] == 1


@pytest.mark.asyncio
async def test_mcp_heartbeat_receipt_survives_immediate_controller_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a committed heartbeat being reported as unauthorized after revocation."""
    from castle_benchmark.lobby import ControllerIdentity

    now = 30.0
    service = GameService()
    session = service.create_session("o" * 32, "basic-survival-v1", 229, 1)
    service.open_lobby(session.admin_token)
    pairing = service.create_pairing(session.admin_token, "c1", now)
    claim = service.claim_slot_contract(
        str(pairing.code),
        ControllerIdentity(display_name="race", provider="p", model="m"),
        now,
    )
    original = service.heartbeat

    def heartbeat_then_replace(*args: object, **kwargs: object) -> object:
        receipt = original(*args, **kwargs)
        service.replace_controller(session.admin_token, "c1", "human", now + 1)
        return receipt

    monkeypatch.setattr(service, "heartbeat", heartbeat_then_replace)
    server = build_mcp_server(service, orchestrator_token="o" * 32, clock=lambda: now)

    response = await call(
        server,
        "benchmark.heartbeat",
        {
            "controller_token": claim["controller_token"],
            "turn": 0,
            "status": "connected",
        },
    )

    assert response == {
        "schema_version": "1.1",
        "match_id": session.match_id,
        "turn": 0,
        "status": "connected",
    }


@pytest.mark.asyncio
async def test_mcp_submit_receipt_survives_immediate_controller_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a committed action batch being reported as unauthorized after revocation."""
    now = 40.0
    service = GameService()
    session = service.create_session(
        "o" * 32,
        "basic-survival-v1",
        233,
        1,
        slot_configs=(("c1", "human", None),),
    )
    service.start_match(session.admin_token, now)
    token = service.human_controller_token(session.admin_token, "c1")
    original = service.submit_actions

    def submit_then_replace(*args: object, **kwargs: object) -> object:
        receipt = original(*args, **kwargs)
        service.replace_controller(session.admin_token, "c1", "human", now + 1)
        return receipt

    monkeypatch.setattr(service, "submit_actions", submit_then_replace)
    server = build_mcp_server(service, orchestrator_token="o" * 32, clock=lambda: now)

    response = await call(
        server,
        "benchmark.submit_actions",
        {"controller_token": token, "turn": 0, "actions": [{"kind": "wait"}]},
    )

    assert response["status"] == "resolved"
    assert response["turn"] == 1
    assert response["events"]


@pytest.mark.asyncio
async def test_mcp_status_projection_preserves_scope_and_rejects_secret_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches raw status dictionaries silently leaking newly added capability fields."""
    service = GameService()
    created = service.create_match("basic-survival-v1", 239, 1)
    token = created.controller_tokens["c1"]
    server = build_mcp_server(service, orchestrator_token="o" * 32)

    status = await call(server, "benchmark.match_status", {"controller_token": token})
    assert status["scope"] == "c1"

    original = service.match_status

    def poisoned_status(capability: str) -> dict[str, object]:
        return {**original(capability), "controller_token": "must-not-escape"}

    monkeypatch.setattr(service, "match_status", poisoned_status)
    rejected = await call(server, "benchmark.match_status", {"controller_token": token})

    assert rejected["error"]["code"] == "invalid_request"
    assert "must-not-escape" not in json.dumps(rejected)


@pytest.mark.asyncio
async def test_mcp_lobby_and_report_projections_reject_nested_secret_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches typed open event data or lobby growth bypassing recursive secret checks."""
    service = GameService()
    session = service.create_session("o" * 32, "basic-survival-v1", 243, 1)
    server = build_mcp_server(service, orchestrator_token="o" * 32)
    original_lobby = service.lobby_status

    def poisoned_lobby(capability: str, now: float) -> dict[str, object]:
        return {**original_lobby(capability, now), "admin_token": "lobby-secret"}

    monkeypatch.setattr(service, "lobby_status", poisoned_lobby)
    lobby = await call(
        server, "benchmark.lobby_status", {"admin_token": session.admin_token}
    )
    assert lobby["error"]["code"] == "invalid_request"
    assert "lobby-secret" not in json.dumps(lobby)

    monkeypatch.setattr(service, "lobby_status", original_lobby)
    original_report = service.run_report

    def poisoned_report(capability: str) -> dict[str, object]:
        payload = original_report(capability)
        return {
            **payload,
            "latest_events": (
                {"turn": 0, "kind": "poison", "data": {"controller_token": "event-secret"}},
            ),
        }

    monkeypatch.setattr(service, "run_report", poisoned_report)
    report = await call(
        server, "benchmark.run_report", {"admin_token": session.admin_token}
    )
    assert report["error"]["code"] == "invalid_request"
    assert "event-secret" not in json.dumps(report)


@pytest.mark.asyncio
async def test_mcp_invocation_telemetry_counts_all_tools_before_validation() -> None:
    """Catches server telemetry depending only on valid colony-scoped wrapper bodies."""
    service = GameService()
    server = build_mcp_server(service, orchestrator_token="o" * 32)
    await call(server, "benchmark.list_scenarios", {})
    created = await call(
        server,
        "benchmark.create_session",
        {"orchestrator_token": "o" * 32, "colony_count": 1},
    )
    pairing = await call(
        server,
        "benchmark.create_pairing",
        {"admin_token": created["admin_token"], "colony_id": "c1"},
    )
    claimed = await call(
        server,
        "benchmark.claim_slot",
        {
            "pairing_code": pairing["pairing_code"],
            "identity": {"display_name": "meter", "provider": "p", "model": "m"},
        },
    )
    await call(
        server,
        "benchmark.lobby_status",
        {"admin_token": created["admin_token"]},
    )
    with pytest.raises(ToolError):
        await server.call_tool(
            "benchmark.heartbeat",
            {"controller_token": claimed["controller_token"], "turn": "bad", "status": "ready"},
        )
    report = await call(
        server,
        "benchmark.run_report",
        {"admin_token": created["admin_token"]},
    )
    telemetry = await call(
        server,
        "benchmark.server_telemetry",
        {"orchestrator_token": "o" * 32},
    )

    measured = report["metrics"]["server_measured"]
    assert telemetry["invocations_total"] == 8
    assert telemetry["invocations_by_tool"] == {
        "benchmark.claim_slot": 1,
        "benchmark.create_pairing": 1,
        "benchmark.create_session": 1,
        "benchmark.heartbeat": 1,
        "benchmark.list_scenarios": 1,
        "benchmark.lobby_status": 1,
        "benchmark.run_report": 1,
        "benchmark.server_telemetry": 1,
    }
    assert measured["mcp_calls"] == {"c1": 1}


@pytest.mark.asyncio
async def test_match_invocation_telemetry_isolated_and_http_mcp_reports_agree() -> None:
    """Catches one session admin seeing process-global MCP activity from another match."""
    from castle_benchmark.api import create_app
    from fastapi.testclient import TestClient

    service = GameService()
    server = build_mcp_server(service, orchestrator_token="o" * 32)
    first = await call(
        server,
        "benchmark.create_session",
        {"orchestrator_token": "o" * 32, "seed": 257, "colony_count": 1},
    )
    second = await call(
        server,
        "benchmark.create_session",
        {"orchestrator_token": "o" * 32, "seed": 263, "colony_count": 1},
    )
    await call(
        server,
        "benchmark.lobby_status",
        {"admin_token": second["admin_token"]},
    )

    mcp_report = await call(
        server,
        "benchmark.run_report",
        {"admin_token": first["admin_token"]},
    )
    http_report = TestClient(create_app(service)).get(
        f"/api/matches/{first['match_id']}/report",
        headers={"Authorization": f"Bearer {first['admin_token']}"},
    ).json()

    expected = {
        "mcp_calls": {"c1": 0},
        "invocations_total": 2,
        "invocations_by_tool": {
            "benchmark.create_session": 1,
            "benchmark.run_report": 1,
        },
    }
    assert mcp_report["metrics"]["server_measured"] == expected
    assert http_report["metrics"]["server_measured"] == expected


@pytest.mark.asyncio
async def test_mcp_replace_response_is_frozen_at_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a later replacement mutating an earlier MCP response projection."""
    service = GameService()
    session = service.create_session("o" * 32, "basic-survival-v1", 269, 1)
    service.open_lobby(session.admin_token)
    original = service.replace_controller
    first_controller_id: str | None = None

    def replace_twice(*args: object, **kwargs: object) -> object:
        nonlocal first_controller_id
        receipt = original(*args, **kwargs)
        first_controller_id = receipt.controller_id
        original(session.admin_token, "c1", "baseline", 51.0, "survivalist")
        return receipt

    monkeypatch.setattr(service, "replace_controller", replace_twice)
    server = build_mcp_server(service, orchestrator_token="o" * 32, clock=lambda: 50.0)

    response = await call(
        server,
        "benchmark.replace_controller",
        {
            "admin_token": session.admin_token,
            "colony_id": "c1",
            "replacement": "human",
        },
    )

    assert response["controller_id"] == first_controller_id


@pytest.mark.asyncio
async def test_mcp_start_response_is_frozen_at_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches later lifecycle progress rewriting the successful start response."""
    from castle_benchmark.lobby import SessionStatus

    service = GameService()
    session = service.create_session(
        "o" * 32,
        "basic-survival-v1",
        281,
        1,
        slot_configs=(("c1", "human", None),),
    )
    original = service.start_match

    def start_then_complete(*args: object, **kwargs: object) -> object:
        returned = original(*args, **kwargs)
        session.status = SessionStatus.COMPLETED
        return returned

    monkeypatch.setattr(service, "start_match", start_then_complete)
    server = build_mcp_server(service, orchestrator_token="o" * 32)

    response = await call(
        server,
        "benchmark.start_match",
        {"admin_token": session.admin_token},
    )

    assert response["status"] == "running"


@pytest.mark.asyncio
async def test_serve_app_mounts_shared_service_mcp_and_claims_pairing() -> None:
    """Catches the serve gateway not exposing a shared-service MCP endpoint."""
    token = "o" * 32
    app = create_app(GameService(), orchestrator_token=token)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http:
            created = (
                await http.post(
                    "/api/sessions",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"scenario_id": "basic-survival-v1", "seed": 17, "colony_count": 1},
                )
            ).json()
            pairing = (
                await http.post(
                    f"/api/sessions/{created['match_id']}/slots/c1/pairing",
                    headers={"Authorization": f"Bearer {created['admin_token']}"},
                )
            ).json()

        async with streamable_http_client(
            "http://127.0.0.1:8000/mcp",
            http_client=httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000"),
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "benchmark.claim_slot",
                    {
                        "pairing_code": pairing["pairing_code"],
                        "identity": {"display_name": "Claude", "provider": "anthropic", "model": "claude"},
                    },
                )

    payload = json.loads(result.content[0].text)
    assert set(payload) == {
        "schema_version",
        "match_id",
        "controller_id",
        "colony_id",
        "controller_token",
    }
    assert payload["colony_id"] == "c1"
