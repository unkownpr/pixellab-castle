from __future__ import annotations

import json
from threading import Event, Thread

import pytest

from castle_benchmark.events import state_hash
from castle_benchmark.lobby import ControllerIdentity
from castle_benchmark.service import ConflictError, GameService, UnauthorizedError


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


def test_submit_and_deadline_close_cannot_resolve_one_turn_twice(
    clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a deadline replacing a real concurrent batch or resolving the barrier twice."""
    service = GameService()
    session = service.create_session("orch", "basic-survival-v1", 41, 2)
    first_pairing = service.create_pairing(session.admin_token, "c1", clock.now)
    second_pairing = service.create_pairing(session.admin_token, "c2", clock.now)
    first = service.claim_slot(first_pairing.code or "", _identity("one"), clock.now)
    second = service.claim_slot(second_pairing.code or "", _identity("two"), clock.now)
    first_token = first.controller_token
    second_token = second.controller_token
    assert first_token is not None and second_token is not None
    service.heartbeat(first_token, 0, "connected", clock.now)
    service.heartbeat(second_token, 0, "connected", clock.now)
    service.start_match(session.admin_token, clock.now)
    baseline = service._matches[session.match_id]
    entered_resolve = Event()
    release_resolve = Event()
    original_resolve = baseline.sim.resolve
    resolve_calls = 0

    def paused_resolve(batches):  # type: ignore[no-untyped-def]
        nonlocal resolve_calls
        resolve_calls += 1
        entered_resolve.set()
        assert release_resolve.wait(timeout=2)
        return original_resolve(batches)

    monkeypatch.setattr(baseline.sim, "resolve", paused_resolve)
    service.submit_actions(first_token, 0, ({"kind": "wait"},))
    clock.advance(31)
    submitted: list[object] = []
    closed: list[object] = []
    submitter = Thread(
        target=lambda: submitted.append(
            service.submit_actions(
                second_token,
                0,
                ({"kind": "set_policy", "policy": "rationing", "value": "low"},),
            )
        )
    )

    def close() -> None:
        try:
            closed.append(service.close_deadline(session.admin_token, clock.now))
        except ConflictError as exc:
            closed.append(exc)

    closer = Thread(target=close)

    submitter.start()
    assert entered_resolve.wait(timeout=2)
    closer.start()
    release_resolve.set()
    submitter.join(timeout=2)
    closer.join(timeout=2)

    assert not submitter.is_alive()
    assert not closer.is_alive()
    assert resolve_calls == 1
    assert baseline.sim.state.turn == 1
    assert submitted and getattr(submitted[0], "status") == "resolved"
    assert getattr(submitted[0], "result").action_results[1].action_kind == "set_policy"
    assert closed and isinstance(closed[0], ConflictError)


def test_normal_heartbeats_do_not_duplicate_connected_events(
    live_session: tuple[GameService, object, str], clock: Clock
) -> None:
    """Catches every heartbeat inflating the connected event stream."""
    service, session, token = live_session
    initial = len(service.operations_snapshot(session.admin_token, clock.now)["events"])

    service.heartbeat(token, 0, "connected", clock.now + 1)
    service.heartbeat(token, 0, "thinking", clock.now + 2)

    assert len(service.operations_snapshot(session.admin_token, clock.now + 2)["events"]) == initial
    service.heartbeat(token, 0, "disconnected", clock.now + 3)
    service.heartbeat(token, 0, "connected", clock.now + 4)
    events = service.operations_snapshot(session.admin_token, clock.now + 4)["events"]
    assert len(events) == initial + 2
    assert events[-1]["kind"] == "controller_connected"
    assert events[-1]["data"]["reconnect"] is True


def test_baseline_and_human_takeovers_submit_real_turns(clock: Clock) -> None:
    """Catches locally ready takeover slots being ready-only placeholders that always wait."""
    service = GameService()
    session = service.create_session("orch", "basic-survival-v1", 31, 1)
    service.configure_slot(session.admin_token, "c1", "baseline", baseline_kind="survivalist")
    service.start_match(session.admin_token, clock.now)
    first = service.close_deadline(session.admin_token, clock.now + 31)
    assert any(item.action_kind != "wait" for item in first.action_results)

    human = service.replace_controller(session.admin_token, "c1", "human", clock.now + 32)
    token = service.human_controller_token(session.admin_token, human.colony_id)
    result = service.submit_actions(token, 1, ({"kind": "wait"},))
    assert result.status == "resolved"


def test_baseline_submits_before_an_external_controller_completes_the_barrier(clock: Clock) -> None:
    """Catches baseline slots falling back to an implicit wait when another controller submits first."""
    service = GameService()
    session = service.create_session("orch", "basic-survival-v1", 33, 2)
    service.configure_slot(session.admin_token, "c1", "baseline", baseline_kind="survivalist")
    pairing = service.create_pairing(session.admin_token, "c2", clock.now)
    claimed = service.claim_slot(pairing.code or "", _identity(), clock.now)
    token = claimed.controller_token
    assert token is not None
    service.heartbeat(token, 0, "connected", clock.now)
    service.start_match(session.admin_token, clock.now)

    result = service.submit_actions(token, 0, ({"kind": "wait"},))

    assert result.status == "resolved"
    assert result.result is not None
    assert any(
        item.colony_id == "c1" and item.action_kind != "wait"
        for item in result.result.action_results
    )


def test_resolved_turn_attribution_persists_through_service_handoff(tmp_path, clock: Clock) -> None:
    """Catches controller IDs being cleared before an artifact writer can persist them."""
    from castle_benchmark.persistence import ArtifactWriter
    from castle_benchmark.scenarios import BASIC_SURVIVAL

    service = GameService()
    session = service.create_session("orch", "basic-survival-v1", 37, 1)
    pairing = service.create_pairing(session.admin_token, "c1", clock.now)
    claimed = service.claim_slot(pairing.code or "", _identity(), clock.now)
    token = claimed.controller_token
    assert token is not None
    service.heartbeat(token, 0, "connected", clock.now)
    service.start_match(session.admin_token, clock.now)
    service.submit_actions(token, 0, ({"kind": "wait"},))
    writer = ArtifactWriter.create(tmp_path / "run", BASIC_SURVIVAL, 37, 1, {"c1": "external"})

    service.write_resolved_turns(session.admin_token, writer)

    record = json.loads(writer.events_path.read_text().splitlines()[0])
    metadata = json.loads(writer.metadata_path.read_text())
    assert record["action_controller_ids"]["c1"] != claimed.controller_token
    assert record["action_controller_ids"]["c1"]
    assert metadata["controller_tenures"][0]["controller_id"] == record["action_controller_ids"]["c1"]


def test_usage_is_segmented_by_controller_tenure(
    live_session: tuple[GameService, object, str], clock: Clock
) -> None:
    """Catches a takeover's model and deadline telemetry being attributed only to a colony total."""
    service, session, token = live_session
    service.start_match(session.admin_token, clock.now)
    service.record_usage(token, input_tokens=11, output_tokens=3, latency_ms=7)
    service.record_mcp_call(token)
    clock.advance(31)
    service.close_deadline(session.admin_token, clock.now)
    service.replace_controller(session.admin_token, "c2", "baseline", clock.now)

    report = service.run_report(session.admin_token)
    tenures = report["metrics"]["tenure_metrics"]["c2"]
    assert len(tenures) == 2
    assert tenures[0]["adapter_reported_model_usage"]["input_tokens"] == 11
    assert tenures[0]["server_measured"]["timeouts"] == 1
    assert tenures[0]["server_measured"]["mcp_calls"] == 1
