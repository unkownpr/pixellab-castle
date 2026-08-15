from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from castle_benchmark.api import create_app
from castle_benchmark.runner import RunConfig, run_match, verify_replay
from castle_benchmark.scenarios import BASIC_SURVIVAL, OFFICIAL_SCENARIOS
from castle_benchmark.service import GameService


# A match can now end by winning, not only by running out of turns or colonists.
TERMINAL_REASONS = {"turn_limit", "extinction", "monument_victory", "domination_victory"}


def test_http_human_turn_and_complete_replayable_baseline_match(tmp_path: Path) -> None:
    service = GameService()
    client = TestClient(create_app(service, orchestrator_token="o" * 32))
    created = client.post(
        "/api/matches",
        headers={"Authorization": f"Bearer {'o' * 32}"},
        json={"scenario_id": BASIC_SURVIVAL.id, "seed": 17, "colony_count": 4},
    ).json()
    tokens = created["controller_tokens"]

    observation = client.get(
        f"/api/matches/{created['match_id']}/observation?colony_id=c1",
        headers={"Authorization": f"Bearer {tokens['c1']}"},
    ).json()
    occupied = {(item["x"], item["y"]) for item in observation["visible_structures"]}
    target = next(
        cell
        for cell in observation["visible_cells"]
        if cell["buildable"] and (cell["x"], cell["y"]) not in occupied
    )
    human = client.post(
        f"/api/matches/{created['match_id']}/actions",
        headers={"Authorization": f"Bearer {tokens['c1']}"},
        json={
            "turn": 0,
            "actions": [
                {
                    "kind": "build",
                    "structure": "house",
                    "x": target["x"],
                    "y": target["y"],
                }
            ],
        },
    )
    assert human.json()["status"] == "pending"

    resolved = None
    for colony_id in ("c2", "c3", "c4"):
        resolved = client.post(
            f"/api/matches/{created['match_id']}/actions",
            headers={"Authorization": f"Bearer {tokens[colony_id]}"},
            json={"turn": 0, "actions": [{"kind": "wait"}]},
        )
    assert resolved is not None
    assert resolved.json()["status"] == "resolved"
    assert any(event["kind"] == "construction_started" for event in resolved.json()["events"])
    while not service.match_status(created["admin_token"])["terminal"]:
        turn = int(service.match_status(created["admin_token"])["turn"])
        for colony_id in ("c1", "c2", "c3", "c4"):
            service.submit_actions(tokens[colony_id], turn, ({"kind": "wait"},))

    report = service.run_report(created["admin_token"])
    assert report["status"]["terminal"] is True
    assert report["status"]["termination_reason"] in TERMINAL_REASONS


@pytest.mark.parametrize("scenario", OFFICIAL_SCENARIOS, ids=lambda scenario: scenario.id)
def test_four_baselines_finish_every_official_scenario(tmp_path: Path, scenario) -> None:
    run = run_match(
        RunConfig(
            scenario,
            seed=17,
            colony_count=4,
            output_dir=tmp_path,
            controller_kinds=("survivalist", "trader", "expansionist", "militarist"),
        )
    )

    assert run.termination_reason in TERMINAL_REASONS
    assert verify_replay(run.run_dir).ok
