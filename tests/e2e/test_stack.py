from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from castle_benchmark.api import create_app
from castle_benchmark.runner import RunConfig, run_match, verify_replay
from castle_benchmark.scenarios import BASIC_SURVIVAL, OFFICIAL_SCENARIOS


def test_http_human_turn_and_complete_replayable_baseline_match(tmp_path: Path) -> None:
    client = TestClient(create_app())
    created = client.post(
        "/api/matches",
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

    run = run_match(
        RunConfig(
            BASIC_SURVIVAL,
            seed=17,
            colony_count=4,
            output_dir=tmp_path,
            controller_kinds=("survivalist", "trader", "expansionist", "militarist"),
        )
    )
    assert run.termination_reason in {"turn_limit", "extinction"}
    assert verify_replay(run.run_dir).ok


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

    assert run.termination_reason in {"turn_limit", "extinction"}
    assert verify_replay(run.run_dir).ok
