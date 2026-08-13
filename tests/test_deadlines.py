from __future__ import annotations

import pytest

from castle_benchmark.events import state_hash
from castle_benchmark.lobby import ControllerIdentity
from castle_benchmark.service import GameService, UnauthorizedError


class Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _identity(name: str = "Codex") -> ControllerIdentity:
    return ControllerIdentity(display_name=name, provider="openai", model="gpt-5")


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def live_session(clock: Clock) -> tuple[GameService, object, str]:
    service = GameService()
    session = service.create_session("orch", "basic-survival-v1", 17, 2)
    service.configure_slot(session.admin_token, "c1", "baseline", baseline_kind="survivalist")
    service.configure_slot(session.admin_token, "c2", "external")
    pairing = service.create_pairing(session.admin_token, "c2", clock.now)
    claimed = service.claim_slot(pairing.code or "", _identity(), clock.now)
    token = claimed.controller_token
    assert token is not None
    service.heartbeat(token, turn=0, status="connected", now=clock.now)
    return service, session, token


def test_deadline_turns_missing_external_input_into_measured_wait(
    live_session: tuple[GameService, object, str], clock: Clock
) -> None:
    """Catches a missed controller turn being omitted instead of recorded as a wait."""
    service, session, _ = live_session
    service.start_match(session.admin_token, clock.now)
    clock.advance(31)

    result = service.close_deadline(session.admin_token, clock.now)

    assert any(event.kind == "controller_timed_out" and event.colony_id == "c2" for event in result.events)
    assert service.run_report(session.admin_token)["metrics"]["cost"]["c2"]["timeouts"] == 1
    assert result.action_results[0].colony_id == "c1"
    assert result.action_results[1].colony_id == "c2"


def test_reconnect_and_replacement_preserve_tenure_and_revoke_old_capability(
    live_session: tuple[GameService, object, str], clock: Clock
) -> None:
    """Catches a takeover rewriting prior attribution or leaving its old token usable."""
    service, session, old_token = live_session
    service.start_match(session.admin_token, clock.now)
    clock.advance(31)
    service.close_deadline(session.admin_token, clock.now)

    replacement = service.replace_controller(session.admin_token, "c2", "baseline", clock.now)

    with pytest.raises(UnauthorizedError):
        service.heartbeat(old_token, turn=1, status="connected", now=clock.now)
    report = service.run_report(session.admin_token)
    assert report["metrics"]["presence"]["reconnects"]["c2"] == 0
    assert len(report["metrics"]["presence"]["tenures"]["c2"]) == 2
    assert replacement.controller_type.value == "baseline"
    assert any(event["kind"] == "controller_replaced" for event in service.operations_snapshot(session.admin_token, clock.now)["events"])


def test_heartbeat_reconnect_does_not_change_deterministic_state_hash(clock: Clock) -> None:
    """Catches wall-clock presence being accidentally folded into simulation state."""
    def resolve_with_heartbeat(heartbeat_at: float) -> str:
        service = GameService()
        session = service.create_session("orch", "basic-survival-v1", 29, 1)
        pairing = service.create_pairing(session.admin_token, "c1", clock.now)
        claimed = service.claim_slot(pairing.code or "", _identity(), clock.now)
        token = claimed.controller_token
        assert token is not None
        service.heartbeat(token, turn=0, status="connected", now=heartbeat_at)
        service.start_match(session.admin_token, heartbeat_at)
        service.submit_actions(token, 0, ({"kind": "wait"},))
        return state_hash(service._matches[session.match_id].sim.state)

    assert resolve_with_heartbeat(1_001.0) == resolve_with_heartbeat(9_999.0)


def test_live_external_takeover_can_issue_a_fresh_pairing_code(
    live_session: tuple[GameService, object, str], clock: Clock
) -> None:
    """Catches recovery leaving an external slot impossible to re-pair after match start."""
    service, session, _ = live_session
    service.start_match(session.admin_token, clock.now)

    slot = service.replace_controller(session.admin_token, "c2", "external", clock.now)
    grant = service.create_pairing(session.admin_token, slot.colony_id, clock.now)

    assert grant.code is not None
