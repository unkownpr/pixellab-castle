from dataclasses import replace

from castle_benchmark.actions import TradeRespondAction
from castle_benchmark.agents import SurvivalistAgent, TraderAgent
from castle_benchmark.runner import RunConfig, run_match, verify_replay
from castle_benchmark.scenarios import Scenario
from castle_benchmark.domain import Position


SMOKE = Scenario(
    id="runner-smoke-v1",
    name="Runner Smoke",
    width=12,
    height=12,
    max_turns=12,
    biome="grassland",
    spawn_points=(Position(2, 2), Position(9, 9)),
    sight_radius=4,
)


def test_survivalist_is_deterministic_for_same_observation() -> None:
    """Catches baseline behavior depending on process-global random state."""
    from castle_benchmark.engine import SimCore
    from castle_benchmark.observation import project_observation

    sim = SimCore.create(SMOKE, seed=61, colony_count=2)
    observation = project_observation(sim.state, "c1")

    assert SurvivalistAgent(seed=7).decide(observation) == SurvivalistAgent(seed=7).decide(observation)


def test_full_baseline_match_is_replayable(tmp_path) -> None:
    """Catches orchestration that cannot finish and report a complete match."""
    report = run_match(
        RunConfig(
            scenario=SMOKE,
            seed=67,
            colony_count=2,
            output_dir=tmp_path,
            controller_kinds=("survivalist", "trader"),
        )
    )

    assert report.termination_reason == "turn_limit"
    assert verify_replay(report.run_dir).ok
    assert set(report.metrics) >= {"survival", "growth", "prosperity", "aggression", "decision_quality"}
    assert report.report_path.exists()


def test_trader_accepts_affordable_incoming_offer() -> None:
    from castle_benchmark.engine import SimCore
    from castle_benchmark.observation import project_observation

    sim = SimCore.create(SMOKE, seed=69, colony_count=2)
    observation = replace(
        project_observation(sim.state, "c2"),
        active_offers=(
            {
                "id": "o1",
                "source_colony_id": "c1",
                "target_colony_id": "c2",
                "give": {"wood": 2},
                "receive": {"food": 2},
                "expires_turn": 4,
            },
        ),
    )

    decision = TraderAgent(seed=7).decide(observation)

    assert decision.actions == (TradeRespondAction("o1", True),)
