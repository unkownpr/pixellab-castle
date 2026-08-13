from __future__ import annotations

import json
from pathlib import Path

import pytest

from castle_benchmark.mcp_server import build_mcp_server
from castle_benchmark.persistence import ArtifactWriter
from castle_benchmark.runner import verify_replay
from castle_benchmark.scenarios import get_scenario
from castle_benchmark.service import GameService

OFFICIAL_BIOMES = ("basic-survival-v1", "desert-scarcity-v1", "snow-recovery-v1")


async def _call(server: object, name: str, arguments: dict[str, object]) -> dict[str, object]:
    content = await server.call_tool(name, arguments)  # type: ignore[attr-defined]
    return json.loads(content[0][0].text)


async def _claim_external_agents(
    server: object, admin_token: str, colonies: tuple[str, ...]
) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for index, colony_id in enumerate(colonies, start=1):
        pairing = await _call(
            server,
            "benchmark.create_pairing",
            {"admin_token": admin_token, "colony_id": colony_id},
        )
        claimed = await _call(
            server,
            "benchmark.claim_slot",
            {
                "pairing_code": pairing["pairing_code"],
                "identity": {
                    "display_name": f"Remote agent {index}",
                    "provider": "openai",
                    "model": "gpt-5",
                },
            },
        )
        await _call(
            server,
            "benchmark.heartbeat",
            {"controller_token": claimed["controller_token"], "turn": 0, "status": "connected"},
        )
        tokens[colony_id] = str(claimed["controller_token"])
    return tokens


async def _drive_to_terminal(server: object, tokens: dict[str, str]) -> None:
    probe = next(iter(tokens.values()))
    while True:
        status = await _call(
            server, "benchmark.match_status", {"controller_token": probe}
        )
        if status["terminal"]:
            return
        turn = int(status["turn"])
        for token in tokens.values():
            await _call(
                server,
                "benchmark.submit_actions",
                {"controller_token": token, "turn": turn, "actions": [{"kind": "wait"}]},
            )


def _export_and_verify_replay(
    service: GameService,
    admin_token: str,
    match_id: str,
    scenario_id: str,
    seed: int,
    colony_count: int,
    metrics: dict[str, object],
    run_dir: Path,
) -> None:
    scenario = get_scenario(scenario_id)
    writer = ArtifactWriter.create(
        run_dir,
        scenario,
        seed,
        colony_count,
        {f"c{index}": f"Remote agent {index}" for index in range(1, colony_count + 1)},
    )
    service.write_resolved_turns(admin_token, writer)
    match = service._matches[match_id]
    writer.finish(match.sim.state, metrics)
    assert verify_replay(run_dir).ok


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario_id", OFFICIAL_BIOMES)
async def test_four_remote_agents_finish_and_export_replay(
    scenario_id: str, tmp_path: Path
) -> None:
    """Catches the remote agent loop failing to reach terminal or export a replay."""
    service = GameService()
    server = build_mcp_server(
        service, orchestrator_token="orch", transport="streamable-http"
    )
    created = await _call(
        server,
        "benchmark.create_session",
        {
            "orchestrator_token": "orch",
            "scenario_id": scenario_id,
            "seed": 17,
            "colony_count": 4,
        },
    )
    admin_token = str(created["admin_token"])
    tokens = await _claim_external_agents(server, admin_token, ("c1", "c2", "c3", "c4"))
    assert set(tokens) == {"c1", "c2", "c3", "c4"}

    started = await _call(
        server, "benchmark.start_match", {"admin_token": admin_token}
    )
    assert started["status"] == "running"

    await _drive_to_terminal(server, tokens)

    report = await _call(server, "benchmark.run_report", {"admin_token": admin_token})
    assert report["status"]["terminal"] is True
    assert report["status"]["termination_reason"] in {"turn_limit", "extinction"}

    _export_and_verify_replay(
        service,
        admin_token,
        str(created["match_id"]),
        scenario_id,
        17,
        4,
        report["metrics"],
        tmp_path / "run",
    )


@pytest.mark.asyncio
async def test_mid_match_baseline_takeover_preserves_tenure_attribution(
    tmp_path: Path,
) -> None:
    """Catches a takeover rewriting prior controller attribution."""
    service = GameService()
    server = build_mcp_server(
        service, orchestrator_token="orch", transport="streamable-http"
    )
    created = await _call(
        server,
        "benchmark.create_session",
        {
            "orchestrator_token": "orch",
            "scenario_id": "basic-survival-v1",
            "seed": 17,
            "colony_count": 2,
        },
    )
    admin_token = str(created["admin_token"])
    tokens = await _claim_external_agents(server, admin_token, ("c1", "c2"))
    c1, c2 = tokens["c1"], tokens["c2"]

    await _call(server, "benchmark.start_match", {"admin_token": admin_token})

    for _ in range(3):
        turn = int(
            (await _call(server, "benchmark.match_status", {"controller_token": c1}))[
                "turn"
            ]
        )
        for token in (c1, c2):
            await _call(
                server,
                "benchmark.submit_actions",
                {"controller_token": token, "turn": turn, "actions": [{"kind": "wait"}]},
            )

    await _call(
        server,
        "benchmark.heartbeat",
        {"controller_token": c2, "turn": 3, "status": "disconnected"},
    )
    await _call(
        server,
        "benchmark.replace_controller",
        {"admin_token": admin_token, "colony_id": "c2", "replacement": "baseline", "baseline_kind": "survivalist"},
    )

    while True:
        status = await _call(server, "benchmark.match_status", {"controller_token": c1})
        if status["terminal"]:
            break
        await _call(
            server,
            "benchmark.submit_actions",
            {"controller_token": c1, "turn": int(status["turn"]), "actions": [{"kind": "wait"}]},
        )

    report = await _call(server, "benchmark.run_report", {"admin_token": admin_token})
    tenures = report["metrics"]["tenure_metrics"]["c2"]

    assert len(tenures) == 2
    assert tenures[0]["controller_id"] != tenures[1]["controller_id"]
    assert {tenure["controller_type"] for tenure in tenures} == {"external", "baseline"}
    assert tenures[0]["generation"] < tenures[1]["generation"]
