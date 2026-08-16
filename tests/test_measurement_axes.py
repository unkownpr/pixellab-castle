"""The axes have to count the thing they are named after.

Every one of these started as a field that existed, appeared in the report, and stayed
at zero for the whole match because nothing ever incremented it. A metric that is always
zero is worse than a missing one: it reads as evidence that nothing happened.
"""

from dataclasses import replace

from castle_benchmark.actions import (
    ActionBatch,
    DiplomacyAction,
    DiplomacyRespondAction,
    MessageAction,
    WaitAction,
)
from castle_benchmark.actions import VALID_ACTION_KINDS
from castle_benchmark.domain import ResourceStock
from castle_benchmark.engine import SimCore
from castle_benchmark.metrics import MetricCollector
from castle_benchmark.scenarios import BASIC_SURVIVAL


def batch(sim: SimCore, colony_id: str, *actions: object) -> ActionBatch:
    return ActionBatch(turn=sim.state.turn, colony_id=colony_id, actions=actions)  # type: ignore[arg-type]


def quiet_hazards(sim: SimCore) -> SimCore:
    sim.scenario = replace(sim.scenario, hazard_cadence=10**6)
    return sim


def test_communication_axis_counts_what_the_colonies_actually_said() -> None:
    sim = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=2))
    metrics = MetricCollector.create(sim.state)

    def play(*batches: ActionBatch) -> None:
        metrics.record(sim.resolve(batches))

    play(batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="contact")),
         batch(sim, "c2", WaitAction()))
    play(batch(sim, "c1", MessageAction(target_colony_id="c2", text="Grain for stone?")),
         batch(sim, "c2", WaitAction()))
    play(batch(sim, "c1", DiplomacyAction(target_colony_id="c2", operation="alliance")),
         batch(sim, "c2", WaitAction()))
    proposal_id = next(iter(sim.state.proposals))
    play(batch(sim, "c1", WaitAction()),
         batch(sim, "c2", DiplomacyRespondAction(proposal_id=proposal_id, accept=True)))

    report = metrics.report(sim.state)
    communication = report["communication"]
    assert communication["c1"]["messages_sent"] == 1
    assert communication["c1"]["proposals_made"] == 1
    # A treaty is something two colonies did; crediting only the colony that clicked
    # accept would make the proposer look like it never negotiated.
    assert communication["c1"]["proposals_accepted"] == 1
    assert communication["c2"]["proposals_accepted"] == 1
    assert communication["c2"]["messages_sent"] == 0


def test_starvation_turns_count_the_turns_a_colony_went_short() -> None:
    sim = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=1))
    colonies = dict(sim.state.colonies)
    colonies["c1"] = replace(colonies["c1"], resources=ResourceStock())
    sim.state = replace(sim.state, colonies=colonies)
    metrics = MetricCollector.create(sim.state)

    for _ in range(3):
        metrics.record(sim.resolve((batch(sim, "c1", WaitAction()),)))

    report = metrics.report(sim.state)
    assert report["decision_quality"]["c1"]["starvation_turns"] == 3


def test_a_fed_colony_records_no_starvation() -> None:
    sim = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=1))
    metrics = MetricCollector.create(sim.state)

    for _ in range(3):
        metrics.record(sim.resolve((batch(sim, "c1", WaitAction()),)))

    assert metrics.report(sim.state)["decision_quality"]["c1"]["starvation_turns"] == 0


def test_a_colony_with_no_population_records_no_starvation() -> None:
    """Nobody left to feed is not the same as a colony that went hungry."""
    sim = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=3))
    colonies = dict(sim.state.colonies)
    colonies["c1"] = replace(colonies["c1"], population=0, hungry=0, resources=ResourceStock())
    sim.state = replace(sim.state, colonies=colonies)
    metrics = MetricCollector.create(sim.state)

    for _ in range(3):
        metrics.record(
            sim.resolve(
                (
                    batch(sim, "c1", WaitAction()),
                    batch(sim, "c2", WaitAction()),
                    batch(sim, "c3", WaitAction()),
                )
            )
        )

    assert metrics.report(sim.state)["decision_quality"]["c1"]["starvation_turns"] == 0


def test_an_idle_colony_records_opportunity_waits() -> None:
    """Waiting with hands and materials is the passivity the decision axis exists to see."""
    sim = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=1))
    metrics = MetricCollector.create(sim.state)

    for _ in range(3):
        metrics.record(sim.resolve((batch(sim, "c1", WaitAction()),)))

    assert metrics.report(sim.state)["decision_quality"]["c1"]["opportunity_waits"] == 3


def test_waiting_with_nothing_to_spend_is_not_an_opportunity_wait() -> None:
    """A colony with no able colonists has no other move; that is not passivity."""
    sim = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=1))
    colonies = dict(sim.state.colonies)
    colonies["c1"] = replace(colonies["c1"], sick=colonies["c1"].population)
    sim.state = replace(sim.state, colonies=colonies)
    metrics = MetricCollector.create(sim.state)

    metrics.record(sim.resolve((batch(sim, "c1", WaitAction()),)))

    assert metrics.report(sim.state)["decision_quality"]["c1"]["opportunity_waits"] == 0


def test_action_diversity_is_measured_against_the_published_action_list() -> None:
    sim = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=1))
    metrics = MetricCollector.create(sim.state)

    metrics.record(sim.resolve((batch(sim, "c1", WaitAction()),)))

    expected = round(1 / len(VALID_ACTION_KINDS), 4)
    assert metrics.report(sim.state)["decision_quality"]["c1"]["action_diversity"] == expected


def test_the_composite_is_an_integer() -> None:
    """It ranks agents; a float here is an invitation for platform rounding to rank them."""
    sim = quiet_hazards(SimCore.create(BASIC_SURVIVAL, seed=19, colony_count=2))
    metrics = MetricCollector.create(sim.state)
    metrics.record(sim.resolve((batch(sim, "c1", WaitAction()), batch(sim, "c2", WaitAction()))))

    composites = metrics.report(sim.state)["composites"]

    assert composites
    assert all(isinstance(value, int) for value in composites.values())
