from castle_benchmark.actions import BuildAction, ScoutAction
from castle_benchmark.agents import (
    AGENT_TYPES,
    ExpansionistAgent,
    MilitaristAgent,
    RandomValidAgent,
    SurvivalistAgent,
    TraderAgent,
)
from castle_benchmark.domain import StructureKind
from castle_benchmark.engine import SimCore
from castle_benchmark.events import state_hash
from castle_benchmark.observation import project_observation
from castle_benchmark.runner import RunConfig, run_match, verify_replay
from castle_benchmark.scenarios import BASIC_SURVIVAL

import pytest


def drive(agent, seed: int = 17):
    """Run a single-colony match to terminal, collecting build intents and scout activity."""
    sim = SimCore.create(BASIC_SURVIVAL, seed, 1)
    built: set[StructureKind] = set()
    scouted = False
    revealed = 0
    while not sim.state.terminal:
        batch = agent.decide(project_observation(sim.state, "c1"))
        for action in batch.actions:
            if isinstance(action, BuildAction):
                built.add(action.structure)
            if isinstance(action, ScoutAction):
                scouted = True
        result = sim.resolve((batch,))
        revealed += sum(1 for event in result.events if event.kind == "scout_revealed")
    return sim, built, scouted, revealed


@pytest.mark.parametrize(
    ("agent", "signature"),
    [
        (
            SurvivalistAgent(),
            {StructureKind.FARM, StructureKind.WELL, StructureKind.LUMBER_CAMP, StructureKind.HOUSE},
        ),
        (TraderAgent(), {StructureKind.MARKET}),
        (
            ExpansionistAgent(),
            {StructureKind.QUARRY, StructureKind.MINE, StructureKind.WORKSHOP},
        ),
        (
            MilitaristAgent(),
            {
                StructureKind.BARRACKS,
                StructureKind.WALL,
                StructureKind.GATE,
                StructureKind.WATCHTOWER,
                StructureKind.CLINIC,
            },
        ),
    ],
)
def test_baseline_builds_its_signature_structures(agent, signature) -> None:
    _, built, _, _ = drive(agent)

    assert signature <= built


def test_expansionist_dispatches_scout_and_reveals_cells() -> None:
    sim = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    agent = ExpansionistAgent()
    initial = len(sim.state.colonies["c1"].known_cells)
    scouted = False
    revealed = 0
    while not sim.state.terminal:
        batch = agent.decide(project_observation(sim.state, "c1"))
        for action in batch.actions:
            if isinstance(action, ScoutAction):
                scouted = True
        result = sim.resolve((batch,))
        revealed += sum(1 for event in result.events if event.kind == "scout_revealed")

    assert scouted
    assert revealed > 0
    assert len(sim.state.colonies["c1"].known_cells) > initial


def test_production_baseline_outsurvives_gather_only_baseline() -> None:
    producer, _, _, _ = drive(SurvivalistAgent())
    gatherer, _, _, _ = drive(RandomValidAgent())

    assert producer.state.termination_reason == "turn_limit"
    assert producer.state.colonies["c1"].population > 0
    assert gatherer.state.termination_reason == "extinction"
    assert gatherer.state.colonies["c1"].population == 0


def test_baselines_are_deterministic() -> None:
    def run_once() -> str:
        sim = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=4)
        kinds = ("survivalist", "trader", "expansionist", "militarist")
        controllers = {
            f"c{index + 1}": AGENT_TYPES[kind](seed=17 + index + 1)
            for index, kind in enumerate(kinds)
        }
        while not sim.state.terminal:
            batches = tuple(
                controllers[colony_id].decide(project_observation(sim.state, colony_id))
                for colony_id in sorted(controllers)
            )
            sim.resolve(batches)
        return state_hash(sim.state)

    assert run_once() == run_once()


def test_full_baseline_match_round_trips_replay(tmp_path) -> None:
    report = run_match(
        RunConfig(
            scenario=BASIC_SURVIVAL,
            seed=17,
            colony_count=4,
            output_dir=tmp_path,
            controller_kinds=("survivalist", "trader", "expansionist", "militarist"),
        )
    )

    assert report.termination_reason in {"turn_limit", "extinction"}
    assert verify_replay(report.run_dir).ok
