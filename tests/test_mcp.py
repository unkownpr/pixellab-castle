import json

import pytest

from castle_benchmark.mcp_server import build_mcp_server
from castle_benchmark.service import GameService


@pytest.mark.asyncio
async def test_mcp_exposes_versioned_benchmark_tools() -> None:
    """Catches MCP surface drift that would break model clients."""
    server = build_mcp_server(GameService())

    tools = await server.list_tools()

    assert {tool.name for tool in tools} >= {
        "benchmark.list_scenarios",
        "benchmark.create_match",
        "benchmark.observe",
        "benchmark.submit_actions",
        "benchmark.match_status",
    }


@pytest.mark.asyncio
async def test_mcp_create_and_observe_use_same_service_contract() -> None:
    """Catches MCP returning a different observation contract than HTTP/direct use."""
    server = build_mcp_server(GameService())

    created_content = await server.call_tool(
        "benchmark.create_match",
        {"scenario_id": "basic-survival-v1", "seed": 97, "colony_count": 1},
    )
    created = json.loads(created_content[0][0].text)
    observed_content = await server.call_tool(
        "benchmark.observe", {"controller_token": created["controller_tokens"]["c1"]}
    )
    observed = json.loads(observed_content[0][0].text)

    assert observed["scenario_id"] == "basic-survival-v1"
    assert observed["colony_id"] == "c1"
    assert "resources" in observed["colony"]
