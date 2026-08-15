from dataclasses import replace

import pytest

from castle_benchmark.actions import (
    DiplomacyAction,
    RaidAction,
    SetPolicyAction,
    TradeRespondAction,
)
from castle_benchmark.agents import (
    AGENT_TYPES,
    ExpansionistAgent,
    MilitaristAgent,
    SurvivalistAgent,
    TraderAgent,
)
from castle_benchmark.domain import (
    MilitaryPosture,
    Position,
    RelationStatus,
    Structure,
    StructureKind,
    StructureStatus,
)
from castle_benchmark.engine import SimCore
from castle_benchmark.observation import project_observation
from castle_benchmark.scenarios import BASIC_SURVIVAL

BASELINE_KINDS = ("survivalist", "trader", "expansionist", "militarist")


def _offer(give=None, receive=None) -> dict[str, object]:
    return {
        "id": "o1",
        "source_colony_id": "c2",
        "target_colony_id": "c1",
        "give": give if give is not None else {"wood": 2},
        "receive": receive if receive is not None else {"food": 2},
        "expires_turn": 4,
    }


def _observation(resources=None, offers=()) -> object:
    """A single-colony observation with tweakable stocks and a crafted offer set."""
    sim = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=1)
    obs = project_observation(sim.state, "c1")
    if resources is not None:
        colony = dict(obs.colony)
        colony["resources"] = {**colony["resources"], **resources}
        obs = replace(obs, colony=colony)
    if offers:
        obs = replace(obs, active_offers=offers)
    return obs


def _militarist_observation(
    relations: dict[str, RelationStatus],
    turn: int = 8,
    *,
    posture: str = MilitaryPosture.EXPANSIONIST.value,
    armed: bool = True,
) -> object:
    """The militarist's view of a four-colony match with the given outward relations.

    The militarist will not raid from a peaceful posture or without a barracks, so a
    test that wants to see a raid has to grant it both; the defaults do, and the tests
    that exercise those two gates pass ``posture`` or ``armed`` explicitly.
    """
    sim = SimCore.create(BASIC_SURVIVAL, seed=17, colony_count=4)
    c4 = sim.state.colonies["c4"]
    colonies = dict(sim.state.colonies)
    policies = dict(c4.policies)
    policies["military_posture"] = posture
    colonies["c4"] = replace(c4, relations=relations, policies=policies)
    structures = dict(sim.state.structures)
    if armed:
        structures["s_barracks_c4"] = Structure(
            id="s_barracks_c4",
            colony_id="c4",
            kind=StructureKind.BARRACKS,
            position=Position(c4.spawn.x + 1, c4.spawn.y),
            status=StructureStatus.OPERATIONAL,
            progress=1,
            required_progress=1,
        )
    sim.state = replace(sim.state, colonies=colonies, structures=structures, turn=turn)
    return project_observation(sim.state, "c4")


def _run_full(seed: int) -> tuple[SimCore, list[object]]:
    sim = SimCore.create(BASIC_SURVIVAL, seed, 4)
    controllers = {
        f"c{index + 1}": AGENT_TYPES[kind](seed=seed + index + 1)
        for index, kind in enumerate(BASELINE_KINDS)
    }
    events = []
    while not sim.state.terminal:
        batches = tuple(
            controllers[colony_id].decide(project_observation(sim.state, colony_id))
            for colony_id in sorted(controllers)
        )
        events.extend(sim.resolve(batches).events)
    return sim, events


def test_full_match_produces_an_accepted_trade_and_a_raid() -> None:
    _, events = _run_full(17)

    kinds = {event.kind for event in events}
    assert "trade_completed" in kinds
    assert "raid" in kinds or "surprise_raid" in kinds


@pytest.mark.parametrize(
    ("agent", "accepts_wood"),
    [
        (TraderAgent(), True),
        (SurvivalistAgent(), True),
        (ExpansionistAgent(), True),
        (MilitaristAgent(), False),
    ],
)
def test_each_baseline_answers_a_wood_offer_by_character(agent, accepts_wood) -> None:
    observation = _observation(resources={"food": 80, "wood": 10}, offers=(_offer(),))

    decision = agent.decide(observation)

    assert decision.actions == (TradeRespondAction("o1", accepts_wood),)


def test_trader_is_the_most_willing() -> None:
    observation = _observation(resources={"food": 10, "wood": 10}, offers=(_offer(),))

    assert TraderAgent().decide(observation).actions == (TradeRespondAction("o1", True),)
    assert ExpansionistAgent().decide(observation).actions == (TradeRespondAction("o1", False),)


def test_survivalist_keeps_a_food_reserve() -> None:
    rich = _observation(resources={"food": 80, "wood": 10}, offers=(_offer(),))
    poor = _observation(resources={"food": 30, "wood": 10}, offers=(_offer(),))

    assert SurvivalistAgent().decide(rich).actions == (TradeRespondAction("o1", True),)
    assert SurvivalistAgent().decide(poor).actions == (TradeRespondAction("o1", False),)


def test_militarist_trades_only_for_essentials() -> None:
    wood = _observation(resources={"food": 80, "wood": 10}, offers=(_offer(),))
    food = _observation(
        resources={"food": 5, "wood": 60},
        offers=(_offer(give={"food": 2}, receive={"wood": 2}),),
    )

    assert MilitaristAgent().decide(wood).actions == (TradeRespondAction("o1", False),)
    assert MilitaristAgent().decide(food).actions == (TradeRespondAction("o1", True),)


def test_militarist_contacts_before_it_can_raid() -> None:
    observation = _militarist_observation(
        {other: RelationStatus.UNKNOWN for other in ("c1", "c2", "c3")}
    )

    decision = MilitaristAgent().decide(observation)

    assert not any(isinstance(action, RaidAction) for action in decision.actions)
    assert any(
        isinstance(action, DiplomacyAction) and action.operation == "contact"
        for action in decision.actions
    )


def test_militarist_declares_war_before_it_raids() -> None:
    observation = _militarist_observation(
        {other: RelationStatus.CONTACTED for other in ("c1", "c2", "c3")}
    )

    decision = MilitaristAgent().decide(observation)

    assert not any(isinstance(action, RaidAction) for action in decision.actions)
    assert any(
        isinstance(action, DiplomacyAction) and action.operation == "declare_war"
        for action in decision.actions
    )


def test_militarist_raids_only_when_at_war() -> None:
    observation = _militarist_observation(
        {other: RelationStatus.WAR for other in ("c1", "c2", "c3")}
    )

    decision = MilitaristAgent().decide(observation)

    assert any(isinstance(action, RaidAction) for action in decision.actions)


def test_militarist_adopts_an_expansionist_posture_before_it_fights() -> None:
    """A peaceful colony cannot raid at all, so the posture is the militarist's first move."""
    observation = _militarist_observation(
        {other: RelationStatus.WAR for other in ("c1", "c2", "c3")},
        posture=MilitaryPosture.PEACEFUL.value,
    )

    decision = MilitaristAgent().decide(observation)

    assert not any(isinstance(action, RaidAction) for action in decision.actions)
    assert any(
        isinstance(action, SetPolicyAction)
        and action.policy == "military_posture"
        and action.value == MilitaryPosture.EXPANSIONIST.value
        for action in decision.actions
    )


def test_militarist_will_not_raid_without_a_barracks() -> None:
    """An unarmed raid party comes home with three injured colonists and nothing else."""
    observation = _militarist_observation(
        {other: RelationStatus.WAR for other in ("c1", "c2", "c3")},
        armed=False,
    )

    decision = MilitaristAgent().decide(observation)

    assert not any(isinstance(action, RaidAction) for action in decision.actions)


@pytest.mark.parametrize("seed", [17, 23, 91])
def test_colonies_survive_the_scenario(seed) -> None:
    sim, _ = _run_full(seed)

    assert sim.state.termination_reason == "turn_limit"
    assert all(colony.population > 0 for colony in sim.state.colonies.values())
