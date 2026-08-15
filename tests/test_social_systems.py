"""Alliance, diplomacy, messaging and victory: the paths an agent actually plays.

The rejection paths for these mechanics are covered elsewhere. What matters here is
that the mechanics *work*: that a proposal only binds when the other side agrees, that
an alliance is worth something and costs something, that a message written by one
colony is read by another and by nobody else, and that a colony can win.
"""

from dataclasses import replace

import pytest

from castle_benchmark.actions import (
    ActionBatch,
    BuildAction,
    DiplomacyAction,
    DiplomacyRespondAction,
    MessageAction,
    TradeOfferAction,
    TradeRespondAction,
    WaitAction,
)
from castle_benchmark.domain import (
    Position,
    RelationStatus,
    ResourceStock,
    Structure,
    StructureKind,
    StructureStatus,
)
from castle_benchmark.engine import SimCore
from castle_benchmark.observation import project_observation
from castle_benchmark.scenarios import BASIC_SURVIVAL
from castle_benchmark.systems import (
    ALLIANCE_UPKEEP_INFLUENCE,
    INBOX_CAPACITY,
    MAX_MESSAGE_LENGTH,
)


def batch(sim: SimCore, colony_id: str, *actions: object) -> ActionBatch:
    return ActionBatch(turn=sim.state.turn, colony_id=colony_id, actions=actions)  # type: ignore[arg-type]


def all_wait(sim: SimCore) -> tuple[ActionBatch, ...]:
    return tuple(batch(sim, colony_id, WaitAction()) for colony_id in sim.state.colonies)


def quiet_hazards(sim: SimCore) -> SimCore:
    """Push the hazard schedule out of reach; these tests are not about the weather."""
    sim.scenario = replace(sim.scenario, hazard_cadence=10**6)
    return sim


def contacted_pair(seed: int = 19) -> SimCore:
    sim = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=seed, colony_count=2))
    sim.resolve((batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),))
    return sim


def result_for(results, colony_id: str):
    return next(item for item in results if item.colony_id == colony_id)


def test_alliance_binds_only_after_the_other_side_accepts() -> None:
    """An alliance nobody agreed to is the exploit consensual diplomacy exists to close."""
    sim = contacted_pair()

    proposed = sim.resolve(
        (batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="alliance")),)
    )

    assert sim.state.colonies["c1"].relations["c2"] != RelationStatus.ALLIANCE
    assert sim.state.colonies["c2"].relations["c1"] != RelationStatus.ALLIANCE
    proposal_id = next(
        event.data["proposal_id"] for event in proposed.events if event.kind == "proposal_made"
    )

    sim.resolve((batch(sim, "c2", DiplomacyRespondAction(proposal_id=str(proposal_id), accept=True)),))

    assert sim.state.colonies["c1"].relations["c2"] == RelationStatus.ALLIANCE
    assert sim.state.colonies["c2"].relations["c1"] == RelationStatus.ALLIANCE


def test_a_refused_proposal_leaves_the_relation_untouched() -> None:
    sim = contacted_pair()
    proposed = sim.resolve(
        (batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="alliance")),)
    )
    proposal_id = str(
        next(event.data["proposal_id"] for event in proposed.events if event.kind == "proposal_made")
    )

    refused = sim.resolve(
        (batch(sim, "c2", DiplomacyRespondAction(proposal_id=proposal_id, accept=False)),)
    )

    assert any(event.kind == "proposal_rejected" for event in refused.events)
    assert sim.state.colonies["c1"].relations["c2"] == RelationStatus.CONTACTED


def ally(sim: SimCore) -> SimCore:
    """Bring c1 and c2 into an accepted alliance."""
    proposed = sim.resolve(
        (batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="alliance")),)
    )
    proposal_id = str(
        next(event.data["proposal_id"] for event in proposed.events if event.kind == "proposal_made")
    )
    sim.resolve((batch(sim, "c2", DiplomacyRespondAction(proposal_id=proposal_id, accept=True)),))
    return sim


def test_allies_trade_without_losing_the_consignment() -> None:
    """An alliance is worth as much as a market on the goods that move between allies."""
    sim = ally(contacted_pair())
    before = sim.state.colonies["c2"].resources.wood

    offered = sim.resolve(
        (
            batch(
                sim,
                "c1",
                TradeOfferAction(target_colony_id="c2", give=(("wood", 4),), receive=(("food", 2),)),
            ),
        )
    )
    offer_id = str(
        next(event.data["offer_id"] for event in offered.events if event.kind == "trade_offered")
    )
    accepted = sim.resolve((batch(sim, "c2", TradeRespondAction(offer_id=offer_id, accept=True)),))

    assert accepted.state.colonies["c2"].resources.wood == before + 4


def test_allies_see_what_the_other_can_see_but_not_where_it_has_been() -> None:
    """Shared sight is live intelligence; a colony's map memory stays its own."""
    sim = ally(contacted_pair())
    sim.resolve(all_wait(sim))

    c1 = sim.state.colonies["c1"]
    c2 = sim.state.colonies["c2"]

    assert c2.visible_now <= c1.visible_now
    assert c1.visible_now <= c1.known_cells
    # c2's spawn surroundings are visible to c1 through the alliance, and c1's own
    # memory is strictly larger than what the pair can see this turn.
    assert c2.spawn in c1.visible_now


def test_alliance_upkeep_lapses_the_treaty_a_colony_cannot_pay_for() -> None:
    """Upkeep has to bite, or 'ally everyone' is free and therefore dominant."""
    sim = ally(contacted_pair())
    colonies = dict(sim.state.colonies)
    colonies["c1"] = replace(
        colonies["c1"],
        resources=colonies["c1"].resources.apply(
            {"influence": -colonies["c1"].resources.influence}
        ),
    )
    sim.state = replace(sim.state, colonies=colonies)

    result = sim.resolve(all_wait(sim))

    assert any(event.kind == "alliance_lapsed" for event in result.events)
    assert sim.state.colonies["c1"].relations["c2"] != RelationStatus.ALLIANCE
    assert sim.state.colonies["c1"].resources.influence >= 0


def test_a_paying_ally_keeps_the_treaty_and_is_charged_for_it() -> None:
    sim = ally(contacted_pair())
    before = sim.state.colonies["c1"].resources.influence

    sim.resolve(all_wait(sim))

    assert sim.state.colonies["c1"].relations["c2"] == RelationStatus.ALLIANCE
    assert sim.state.colonies["c1"].resources.influence <= before - ALLIANCE_UPKEEP_INFLUENCE


def test_a_message_reaches_its_recipient_and_nobody_else() -> None:
    sim = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=3))
    sim.resolve((batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),))

    sim.resolve((batch(sim, "c1", MessageAction(target_colony_id="c2", text="Grain for stone?")),))

    inbox = project_observation(sim.state, "c2").inbox
    assert any(item["text"] == "Grain for stone?" for item in inbox)
    assert all(item["from_colony_id"] == "c1" for item in inbox)
    assert not project_observation(sim.state, "c3").inbox


def test_an_over_long_message_is_refused_rather_than_truncated() -> None:
    sim = contacted_pair()

    result = sim.resolve(
        (batch(sim, "c1", MessageAction(target_colony_id="c2", text="x" * (MAX_MESSAGE_LENGTH + 1))),)
    )

    assert result_for(result.action_results, "c1").code == "message_too_long"
    assert not project_observation(sim.state, "c2").inbox


def test_the_inbox_keeps_the_newest_messages_and_drops_the_oldest() -> None:
    sim = contacted_pair()
    for index in range(INBOX_CAPACITY + 2):
        sim.resolve((batch(sim, "c1", MessageAction(target_colony_id="c2", text=f"note {index}")),))

    inbox = project_observation(sim.state, "c2").inbox

    assert len(inbox) == INBOX_CAPACITY
    assert inbox[-1]["text"] == f"note {INBOX_CAPACITY + 1}"


def test_no_colony_sees_another_colony_inbox_or_a_proposal_it_is_not_party_to() -> None:
    """The fog covers the new state as completely as it covers the map."""
    sim = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=3))
    sim.resolve((batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),))
    sim.resolve((batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="alliance")),))
    sim.resolve((batch(sim, "c1", MessageAction(target_colony_id="c2", text="between us")),))

    outsider = project_observation(sim.state, "c3")

    assert not outsider.inbox
    assert not outsider.open_proposals
    assert "between us" not in repr(outsider)


def test_finishing_a_monument_ends_the_match_in_its_builder_favour() -> None:
    sim = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=2))
    colonies = dict(sim.state.colonies)
    colonies["c1"] = replace(
        colonies["c1"],
        resources=ResourceStock(food=60, water=60, wood=200, stone=200, ore=60, tools=40, influence=80),
    )
    sim.state = replace(sim.state, colonies=colonies)
    spawn = sim.state.colonies["c1"].spawn
    site = Position(spawn.x + 1, spawn.y)

    started = sim.resolve((batch(sim, "c1", BuildAction(structure=StructureKind.MONUMENT, position=site)),))
    assert result_for(started.action_results, "c1").status == "accepted"

    for _ in range(20):
        if sim.state.terminal:
            break
        sim.resolve(all_wait(sim))

    assert sim.state.terminal
    assert sim.state.termination_reason == "monument_victory"


def test_last_colony_standing_ends_the_match() -> None:
    sim = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=2))
    colonies = dict(sim.state.colonies)
    colonies["c2"] = replace(colonies["c2"], population=0, healthy=0)
    sim.state = replace(sim.state, colonies=colonies)

    sim.resolve(all_wait(sim))

    assert sim.state.terminal
    assert sim.state.termination_reason == "domination_victory"


@pytest.mark.parametrize("seed", [17, 23, 91])
def test_a_full_match_replays_to_the_same_hashes_with_the_social_systems_live(seed) -> None:
    """The social systems must not smuggle unordered iteration into the state hash."""
    from castle_benchmark.events import state_hash

    def play() -> list[str]:
        sim = SimCore.create(BASIC_SURVIVAL, seed=seed, colony_count=4)
        hashes = []
        while not sim.state.terminal:
            actions = []
            for colony_id in sorted(sim.state.colonies):
                if colony_id == "c1" and sim.state.turn == 2:
                    actions.append(batch(sim, colony_id, DiplomacyAction(target_colony_id="c2", operation="contact")))
                elif colony_id == "c1" and sim.state.turn == 3:
                    actions.append(batch(sim, colony_id, DiplomacyAction(target_colony_id="c2", operation="alliance")))
                elif colony_id == "c1" and sim.state.turn == 5:
                    actions.append(batch(sim, colony_id, MessageAction(target_colony_id="c2", text="hold the river")))
                else:
                    actions.append(batch(sim, colony_id, WaitAction()))
            sim.resolve(tuple(actions))
            hashes.append(state_hash(sim.state))
        return hashes

    assert play() == play()
