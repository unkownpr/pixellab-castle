"""Test message effect measurement: answered messages, agreements after contact, betrayals after contact."""

from dataclasses import replace

from castle_benchmark.engine import SimCore, MESSAGE_ANSWER_WINDOW
from castle_benchmark.metrics import MetricCollector
from castle_benchmark.domain import MilitaryPosture, RelationStatus
from castle_benchmark.scenarios import BASIC_SURVIVAL
from castle_benchmark.actions import ActionBatch, MessageAction, TradeOfferAction, TradeRespondAction, DiplomacyAction, DiplomacyRespondAction, RaidAction, WaitAction


def _setup_test_match(seed: int = 42, colonies: int = 2) -> SimCore:
    """Create a fresh match with a known scenario and seed, and no weather.

    These tests are about who spoke to whom before what; a fire burning a building down
    mid-test would change the actions a colony can afford and turn a communication
    assertion into a hazard assertion.
    """
    sim = SimCore.create(BASIC_SURVIVAL, seed, colonies)
    sim.scenario = replace(sim.scenario, hazard_cadence=10**6)
    # Messages only travel between colonies that have met, so the relation is established
    # up front rather than spending a turn on it: these tests are about what talking leads
    # to, not about the handshake that lets it start.
    contacted = {}
    for colony_id, colony in sim.state.colonies.items():
        relations = {other: RelationStatus.CONTACTED for other in sim.state.colonies if other != colony_id}
        contacted[colony_id] = replace(colony, relations=relations)
    sim.state = replace(sim.state, colonies=contacted)
    return sim


def _arm(sim: SimCore, colony_id: str) -> SimCore:
    """Put a colony on an expansionist footing.

    A raid from the default peaceful posture is refused outright, so a test about what a
    raid records has to let the colony mean it first — and doing that through the policy
    action would spend the turn the test wants to spend raiding.
    """
    colonies = dict(sim.state.colonies)
    colony = colonies[colony_id]
    policies = dict(colony.policies)
    policies["military_posture"] = MilitaryPosture.EXPANSIONIST.value
    colonies[colony_id] = replace(colony, policies=policies)
    sim.state = replace(sim.state, colonies=colonies)
    return sim


class TestMessageAnswering:
    """Verify message answer detection: a message is answered when the recipient replies within the window."""

    def test_message_answered_within_window(self) -> None:
        """A message that gets a reply within MESSAGE_ANSWER_WINDOW counts as answered."""
        sim = _setup_test_match()
        collector = MetricCollector.create(sim.state)

        # Turn 0: c1 contacts c2 (required before messaging)
        batch_c1 = ActionBatch(0, "c1", [DiplomacyAction("c2", "contact", "")])
        result_0 = sim.resolve([batch_c1, ActionBatch(0, "c2", [WaitAction()])])
        collector.record(result_0)

        # Turn 1: c1 sends message to c2
        batch_c1 = ActionBatch(1, "c1", [MessageAction("c2", "Hello")])
        result_1 = sim.resolve([batch_c1, ActionBatch(1, "c2", [WaitAction()])])
        collector.record(result_1)

        # Turn 2: c2 sends message back to c1 (within window)
        batch_c2 = ActionBatch(2, "c2", [MessageAction("c1", "Hi there")])
        result_2 = sim.resolve([ActionBatch(2, "c1", [WaitAction()]), batch_c2])
        collector.record(result_2)

        # Generate report to compute message answers
        report = collector.report(sim.state)

        # c1 should have 1 message answered
        assert collector.messages_answered.get("c1", 0) >= 1
        assert collector.messages_sent.get("c1", 0) >= 1

    def test_message_answered_outside_window(self) -> None:
        """A message that gets a reply after MESSAGE_ANSWER_WINDOW does not count as answered."""
        sim = _setup_test_match()
        collector = MetricCollector.create(sim.state)

        # Turn 0: c1 contacts c2
        batch_c1 = ActionBatch(0, "c1", [DiplomacyAction("c2", "contact", "")])
        result_0 = sim.resolve([batch_c1, ActionBatch(0, "c2", [WaitAction()])])
        collector.record(result_0)

        # Turn 1: c1 sends message to c2
        batch_c1 = ActionBatch(1, "c1", [MessageAction("c2", "Hello")])
        result_1 = sim.resolve([batch_c1, ActionBatch(1, "c2", [WaitAction()])])
        collector.record(result_1)

        # Quiet turns spanning the whole window, so the reply below lands past its end.
        for turn in range(2, MESSAGE_ANSWER_WINDOW + 2):
            result = sim.resolve([ActionBatch(turn, "c1", [WaitAction()]), ActionBatch(turn, "c2", [WaitAction()])])
            collector.record(result)

        # One turn past the window that opened when the message went out on turn 1.
        late_turn = 1 + MESSAGE_ANSWER_WINDOW + 1
        batch_c2 = ActionBatch(late_turn, "c2", [MessageAction("c1", "Late reply")])
        result_late = sim.resolve([ActionBatch(late_turn, "c1", [WaitAction()]), batch_c2])
        collector.record(result_late)

        # c1 should have 0 messages answered (reply was too late)
        assert collector.messages_answered.get("c1", 0) == 0
        assert collector.messages_sent.get("c1", 0) == 1
        assert collector.report(sim.state)["communication"]["c1"]["messages_answer_rate"] == 0.0

    def test_no_messages_colony_scores_zero(self) -> None:
        """A colony that sends no messages should have 0 answered and 0.0 answer rate."""
        sim = _setup_test_match()
        collector = MetricCollector.create(sim.state)

        # Just wait
        result = sim.resolve([ActionBatch(0, "c1", [WaitAction()]), ActionBatch(0, "c2", [WaitAction()])])
        collector.record(result)

        # Both colonies should have 0 sent, 0 answered
        assert collector.messages_sent.get("c1", 0) == 0
        assert collector.messages_answered.get("c1", 0) == 0
        assert collector.messages_sent.get("c2", 0) == 0
        assert collector.messages_answered.get("c2", 0) == 0


class TestAgreementsAfterContact:
    """Verify that accepted trades and proposals are tracked by contact status."""

    def test_trade_accepted_after_prior_contact(self) -> None:
        """A trade accepted after the proposer sent a message counts toward agreements_after_contact."""
        sim = _setup_test_match()
        collector = MetricCollector.create(sim.state)

        # Turn 0: c1 contacts c2
        batch_c1 = ActionBatch(0, "c1", [DiplomacyAction("c2", "contact", "")])
        result_0 = sim.resolve([batch_c1, ActionBatch(0, "c2", [WaitAction()])])
        collector.record(result_0)

        # Turn 1: c1 messages c2
        batch_c1 = ActionBatch(1, "c1", [MessageAction("c2", "Want to trade?")])
        result_1 = sim.resolve([batch_c1, ActionBatch(1, "c2", [WaitAction()])])
        collector.record(result_1)

        # Turn 2: c1 offers a trade
        batch_c1 = ActionBatch(2, "c1", [
            TradeOfferAction("c2", (("food", 5),), (("wood", 3),), "")
        ])
        result_2 = sim.resolve([batch_c1, ActionBatch(2, "c2", [WaitAction()])])
        collector.record(result_2)

        # Get the offer ID from events
        offer_id = None
        for event in result_2.events:
            if event.kind == "trade_offered":
                offer_id = event.data.get("offer_id")
        assert offer_id is not None

        # Turn 3: c2 accepts the trade. The offer went out on turn 2, and a batch stamped
        # with a turn the simulation has already resolved is refused as stale.
        batch_c2 = ActionBatch(3, "c2", [TradeRespondAction(offer_id, True)])
        result_3 = sim.resolve([ActionBatch(3, "c1", [WaitAction()]), batch_c2])
        collector.record(result_3)

        # Both colonies should have 1 agreement_after_contact
        assert collector.agreements_after_contact.get("c1", 0) >= 1
        assert collector.agreements_after_contact.get("c2", 0) >= 1

    def test_trade_accepted_without_prior_contact(self) -> None:
        """A trade accepted without prior contact counts toward agreements_without_contact."""
        sim = _setup_test_match()
        collector = MetricCollector.create(sim.state)

        # Turn 0: c1 offers a trade with NO prior message
        batch_c1 = ActionBatch(0, "c1", [
            TradeOfferAction("c2", (("food", 5),), (("wood", 3),), "")
        ])
        result_0 = sim.resolve([batch_c1, ActionBatch(0, "c2", [WaitAction()])])
        collector.record(result_0)

        # Get offer ID
        offer_id = None
        for event in result_0.events:
            if event.kind == "trade_offered":
                offer_id = event.data.get("offer_id")
        assert offer_id is not None

        # Turn 1: c2 accepts the trade (without prior contact from c1)
        batch_c2 = ActionBatch(1, "c2", [TradeRespondAction(offer_id, True)])
        result_1 = sim.resolve([ActionBatch(1, "c1", [WaitAction()]), batch_c2])
        collector.record(result_1)

        # Both colonies should have 1 agreement_without_contact
        assert collector.agreements_without_contact.get("c1", 0) >= 1
        assert collector.agreements_without_contact.get("c2", 0) >= 1
        # And 0 after_contact
        assert collector.agreements_after_contact.get("c1", 0) == 0
        assert collector.agreements_after_contact.get("c2", 0) == 0


class TestRaidAfterContact:
    """Verify that raids are tracked by whether the attacker had messaged the target."""

    def test_raid_after_prior_contact(self) -> None:
        """A raid launched after messaging the target counts as raid_after_contact."""
        sim = _arm(_setup_test_match(), "c1")
        collector = MetricCollector.create(sim.state)

        # Turn 0: c1 messages c2
        batch_c1 = ActionBatch(0, "c1", [MessageAction("c2", "I'm coming for you")])
        result_0 = sim.resolve([batch_c1, ActionBatch(0, "c2", [WaitAction()])])
        collector.record(result_0)

        # Turn 1: c1 declares war on c2
        batch_c1 = ActionBatch(1, "c1", [DiplomacyAction("c2", "declare_war", "")])
        result_1 = sim.resolve([batch_c1, ActionBatch(1, "c2", [WaitAction()])])
        collector.record(result_1)

        # Turn 2: c1 raids c2 (now both are at war, and c1 had messaged c2 on turn 0)
        batch_c1 = ActionBatch(2, "c1", [RaidAction("c2")])
        result_2 = sim.resolve([batch_c1, ActionBatch(2, "c2", [WaitAction()])])
        collector.record(result_2)

        # c1 should have 1 raid_after_contact
        assert collector.raids_after_contact.get("c1", 0) >= 1

    def test_raid_without_prior_contact(self) -> None:
        """A raid launched without messaging the target does not count as raid_after_contact."""
        sim = _arm(_setup_test_match(), "c1")
        collector = MetricCollector.create(sim.state)

        # Turn 0: c1 declares war on c2 (no message first)
        batch_c1 = ActionBatch(0, "c1", [DiplomacyAction("c2", "declare_war", "")])
        result_0 = sim.resolve([batch_c1, ActionBatch(0, "c2", [WaitAction()])])
        collector.record(result_0)

        # Turn 1: c1 raids c2
        batch_c1 = ActionBatch(1, "c1", [RaidAction("c2")])
        result_1 = sim.resolve([batch_c1, ActionBatch(1, "c2", [WaitAction()])])
        collector.record(result_1)

        # c1 should have 0 raids_after_contact
        assert collector.raids_after_contact.get("c1", 0) == 0


class TestTreatyBreakAfterContact:
    """Verify that treaty breaks are tracked by whether the breaker had messaged the ally."""

    def test_treaty_break_after_prior_contact(self) -> None:
        """A treaty broken after messaging the ally counts as treaty_break_after_contact."""
        sim = _setup_test_match()
        collector = MetricCollector.create(sim.state)

        # Turn 0: c1 messages c2
        batch_c1 = ActionBatch(0, "c1", [MessageAction("c2", "Let's be friends")])
        result_0 = sim.resolve([batch_c1, ActionBatch(0, "c2", [WaitAction()])])
        collector.record(result_0)

        # Turn 1: c1 proposes alliance to c2
        batch_c1 = ActionBatch(1, "c1", [DiplomacyAction("c2", "alliance", "")])
        result_1 = sim.resolve([batch_c1, ActionBatch(1, "c2", [WaitAction()])])
        collector.record(result_1)

        # Get proposal ID
        proposal_id = None
        for event in result_1.events:
            if event.kind == "proposal_made":
                proposal_id = event.data.get("proposal_id")
        assert proposal_id is not None

        # Turn 2: c2 accepts alliance
        batch_c2 = ActionBatch(2, "c2", [DiplomacyRespondAction(proposal_id, True)])
        result_2 = sim.resolve([ActionBatch(2, "c1", [WaitAction()]), batch_c2])
        collector.record(result_2)

        # Turn 3: c1 declares war on c2 (breaks treaty after messaging)
        batch_c1 = ActionBatch(3, "c1", [DiplomacyAction("c2", "declare_war", "")])
        result_3 = sim.resolve([batch_c1, ActionBatch(3, "c2", [WaitAction()])])
        collector.record(result_3)

        # c1 should have 1 treaty_break_after_contact
        assert collector.treaty_breaks_after_contact.get("c1", 0) >= 1

    def test_treaty_break_without_prior_contact(self) -> None:
        """A treaty broken without messaging the ally does not count as treaty_break_after_contact."""
        sim = _setup_test_match()
        collector = MetricCollector.create(sim.state)

        # Turn 0: c1 proposes alliance (no message first)
        batch_c1 = ActionBatch(0, "c1", [DiplomacyAction("c2", "alliance", "")])
        result_0 = sim.resolve([batch_c1, ActionBatch(0, "c2", [WaitAction()])])
        collector.record(result_0)

        # Get proposal ID
        proposal_id = None
        for event in result_0.events:
            if event.kind == "proposal_made":
                proposal_id = event.data.get("proposal_id")
        assert proposal_id is not None

        # Turn 1: c2 accepts alliance
        batch_c2 = ActionBatch(1, "c2", [DiplomacyRespondAction(proposal_id, True)])
        result_1 = sim.resolve([ActionBatch(1, "c1", [WaitAction()]), batch_c2])
        collector.record(result_1)

        # Turn 2: c1 declares war on c2 (breaks treaty without prior message)
        batch_c1 = ActionBatch(2, "c1", [DiplomacyAction("c2", "declare_war", "")])
        result_2 = sim.resolve([batch_c1, ActionBatch(2, "c2", [WaitAction()])])
        collector.record(result_2)

        # c1 should have 0 treaty_breaks_after_contact
        assert collector.treaty_breaks_after_contact.get("c1", 0) == 0


class TestReportIncludesEffects:
    """Verify that the report includes the new communication effect fields."""

    def test_report_has_message_answer_fields(self) -> None:
        """The report includes messages_answered and messages_answer_rate."""
        sim = _setup_test_match()
        collector = MetricCollector.create(sim.state)

        # Message exchange
        batch_c1 = ActionBatch(0, "c1", [MessageAction("c2", "Hi")])
        result_0 = sim.resolve([batch_c1, ActionBatch(0, "c2", [WaitAction()])])
        collector.record(result_0)

        batch_c2 = ActionBatch(1, "c2", [MessageAction("c1", "Hello")])
        result_1 = sim.resolve([ActionBatch(1, "c1", [WaitAction()]), batch_c2])
        collector.record(result_1)

        report = collector.report(sim.state)

        # Both colonies should have communication data
        assert "communication" in report
        assert "c1" in report["communication"]
        assert "c2" in report["communication"]

        # Check for new fields
        c1_comm = report["communication"]["c1"]
        assert "messages_answered" in c1_comm
        assert "messages_answer_rate" in c1_comm
        assert "agreements_after_contact" in c1_comm
        assert "agreements_without_contact" in c1_comm
        assert "raids_after_contact" in c1_comm
        assert "treaty_breaks_after_contact" in c1_comm

        # Verify values are non-negative integers/floats
        assert c1_comm["messages_answered"] >= 0
        assert c1_comm["messages_answer_rate"] >= 0.0

    def test_report_zero_values_not_null(self) -> None:
        """Colonies with no messages should have 0, not null."""
        sim = _setup_test_match()
        collector = MetricCollector.create(sim.state)

        # No messages
        result = sim.resolve([ActionBatch(0, "c1", [WaitAction()]), ActionBatch(0, "c2", [WaitAction()])])
        collector.record(result)

        report = collector.report(sim.state)

        c1_comm = report["communication"]["c1"]
        assert c1_comm["messages_sent"] == 0
        assert c1_comm["messages_answered"] == 0
        assert c1_comm["messages_answer_rate"] == 0.0
        assert c1_comm["agreements_after_contact"] == 0
        assert c1_comm["agreements_without_contact"] == 0
        assert c1_comm["raids_after_contact"] == 0
        assert c1_comm["treaty_breaks_after_contact"] == 0
