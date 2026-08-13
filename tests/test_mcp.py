import json
from dataclasses import asdict

import pytest
from types import SimpleNamespace

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
    server = build_mcp_server(GameService(), orchestrator_token="o" * 32)

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
