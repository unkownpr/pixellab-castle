import json

import pytest

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
