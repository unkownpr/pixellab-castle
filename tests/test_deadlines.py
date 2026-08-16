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
    # Both colonies are accounted for, but not in a fixed order: initiative is a seeded
    # per-turn rotation now, so asserting c1 comes first would be asserting the old
    # alphabetical bias the rotation exists to remove.
    assert {item.colony_id for item in result.action_results} == {"c1", "c2"}


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


def test_replacement_waits_for_submit_resolution_before_changing_tenure(
    clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches takeover mutation racing a resolving action into the replacement tenure."""
    service = GameService()
    session = service.create_session("orch", "basic-survival-v1", 43, 1)
    pairing = service.create_pairing(session.admin_token, "c1", clock.now)
    claimed = service.claim_slot(pairing.code or "", _identity(), clock.now)
    token = claimed.controller_token
    assert token is not None
    service.heartbeat(token, 0, "connected", clock.now)
    service.start_match(session.admin_token, clock.now)
    match = service._matches[session.match_id]
    original_controller_id = service._lobbies[session.match_id].slots[0].controller_id
    entered_resolve = Event()
    release_resolve = Event()
    replacement_done = Event()
    original_resolve = match.sim.resolve

    def paused_resolve(batches):  # type: ignore[no-untyped-def]
        entered_resolve.set()
        assert release_resolve.wait(timeout=2)
        return original_resolve(batches)

    monkeypatch.setattr(match.sim, "resolve", paused_resolve)
    submitter = Thread(
        target=lambda: service.submit_actions(
            token,
            0,
            ({"kind": "set_policy", "policy": "rationing", "value": "low"},),
        )
    )

    def replace() -> None:
        service.replace_controller(session.admin_token, "c1", "baseline", clock.now + 1)
        replacement_done.set()

    replacer = Thread(target=replace)
    submitter.start()
    assert entered_resolve.wait(timeout=2)
    replacer.start()
    assert not replacement_done.wait(timeout=0.1)
    release_resolve.set()
    submitter.join(timeout=2)
    replacer.join(timeout=2)

    assert not submitter.is_alive()
    assert not replacer.is_alive()
    assert replacement_done.is_set()
    assert match.resolved_turns[0].action_controller_ids == {"c1": original_controller_id}


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


def test_server_latency_is_recorded_without_adapter_reporting(clock: Clock) -> None:
    """Server-measured latency is tracked separately from adapter-reported latency."""
    service = GameService()
    session = service.create_session("orch", "basic-survival-v1", 19, 1)
    pairing = service.create_pairing(session.admin_token, "c1", clock.now)
    claimed = service.claim_slot(pairing.code or "", _identity(), clock.now)
    token = claimed.controller_token
    assert token is not None
    service.heartbeat(token, 0, "connected", clock.now)
    service.start_match(session.admin_token, clock.now)

    # Submit without recording adapter-reported latency or tokens
    clock.advance(0.5)
    result = service.submit_actions(token, 0, ({"kind": "wait"},))

    # Turn resolves with server latency measured
    assert result.status == "resolved"
    report = service.run_report(session.admin_token)
    cost = report["metrics"]["cost"]["c1"]
    assert cost["server_latency_ms"] > 0
    assert cost["latency_ms"] == 0  # adapter never reported any latency
    assert cost["output_tokens"] == 0  # adapter never reported tokens


def test_output_token_budget_forces_waits_on_excess(clock: Clock) -> None:
    """When cumulative output tokens exceed budget, controller's remaining turns resolve as waits."""
    service = GameService()
    session = service.create_session(
        "orch",
        "basic-survival-v1",
        21,
        1,
        output_token_budget=100,  # tight budget
    )
    pairing = service.create_pairing(session.admin_token, "c1", clock.now)
    claimed = service.claim_slot(pairing.code or "", _identity(), clock.now)
    token = claimed.controller_token
    assert token is not None
    service.heartbeat(token, 0, "connected", clock.now)
    service.start_match(session.admin_token, clock.now)

    # First turn: report 60 tokens
    service.record_usage(token, input_tokens=0, output_tokens=60, latency_ms=0)
    service.submit_actions(token, 0, ({"kind": "wait"},))

    # Second turn: report 50 more tokens (total 110, exceeds budget of 100)
    service.record_usage(token, input_tokens=0, output_tokens=50, latency_ms=0)
    result = service.submit_actions(token, 1, ({"kind": "wait"},))
    assert result.status == "resolved"

    report = service.run_report(session.admin_token)
    cost = report["metrics"]["cost"]["c1"]
    assert cost["output_tokens"] == 110
    assert cost["budget_exceeded"] == 1


def test_output_token_budget_tenure_counter_counts_the_crossing_not_every_report(
    clock: Clock,
) -> None:
    """The per-tenure budget_exceeded counter must stay at 1 once crossed, not grow with
    every later usage report that is still over budget."""
    service = GameService()
    session = service.create_session(
        "orch",
        "basic-survival-v1",
        21,
        1,
        output_token_budget=100,  # tight budget
    )
    pairing = service.create_pairing(session.admin_token, "c1", clock.now)
    claimed = service.claim_slot(pairing.code or "", _identity(), clock.now)
    token = claimed.controller_token
    assert token is not None
    service.heartbeat(token, 0, "connected", clock.now)
    service.start_match(session.admin_token, clock.now)

    service.record_usage(token, input_tokens=0, output_tokens=60, latency_ms=0)
    service.submit_actions(token, 0, ({"kind": "wait"},))
    service.record_usage(token, input_tokens=0, output_tokens=50, latency_ms=0)  # crosses 100
    service.submit_actions(token, 1, ({"kind": "wait"},))
    service.record_usage(token, input_tokens=0, output_tokens=10, latency_ms=0)  # still over
    service.submit_actions(token, 2, ({"kind": "wait"},))

    match = service._matches[session.match_id]
    controller_id = next(iter(match.tenure_usage["c1"]))
    assert match.tenure_usage["c1"][controller_id]["budget_exceeded"] == 1


def test_thinking_time_budget_forces_waits_on_excess(clock: Clock) -> None:
    """When cumulative server latency exceeds thinking_time_budget, remaining turns resolve as waits."""
    service = GameService()
    session = service.create_session(
        "orch",
        "basic-survival-v1",
        23,
        1,
        thinking_time_budget_ms=1000,  # 1 second
    )
    pairing = service.create_pairing(session.admin_token, "c1", clock.now)
    claimed = service.claim_slot(pairing.code or "", _identity(), clock.now)
    token = claimed.controller_token
    assert token is not None
    service.heartbeat(token, 0, "connected", clock.now)
    service.start_match(session.admin_token, clock.now)

    # First turn: submit after 600ms
    clock.advance(0.6)
    service.submit_actions(token, 0, ({"kind": "wait"},))

    # Second turn: submit after 500ms more (total 1100ms, exceeds budget of 1000ms)
    clock.advance(0.5)
    result = service.submit_actions(token, 1, ({"kind": "wait"},))
    assert result.status == "resolved"

    report = service.run_report(session.admin_token)
    cost = report["metrics"]["cost"]["c1"]
    assert cost["server_latency_ms"] >= 1100
    assert cost["budget_exceeded"] == 1


def test_thinking_time_budget_forces_waits_on_every_turn_after_the_crossing() -> None:
    """Catches the crossing check only forcing a wait when the current submission is
    itself under budget, which never happens again once cumulative latency stays over."""
    import time as real_time

    service = GameService()
    now = real_time.time()
    session = service.create_session(
        "orch", "basic-survival-v1", 23, 1, thinking_time_budget_ms=200
    )
    pairing = service.create_pairing(session.admin_token, "c1", now)
    claimed = service.claim_slot(pairing.code or "", _identity(), now)
    token = claimed.controller_token
    assert token is not None
    service.heartbeat(token, 0, "connected", now)
    service.start_match(session.admin_token, now)

    # First turn crosses the 200ms ceiling.
    real_time.sleep(0.25)
    service.submit_actions(token, 0, ({"kind": "wait"},))

    # A later turn, still over budget: a real action must still resolve as a wait.
    real_time.sleep(0.05)
    result = service.submit_actions(token, 1, ({"kind": "gather", "x": 0, "y": 0},))

    assert result.result is not None
    submitted = next(item for item in result.result.action_results if item.colony_id == "c1")
    assert submitted.action_kind == "wait"


def test_server_latency_uses_the_same_clock_as_turn_open() -> None:
    """Catches server_latency_ms measured against a different clock than turn_opened_at,
    which either floors it to 0 or inflates it to roughly a Unix epoch's worth of ms."""
    import time as real_time

    service = GameService()
    now = real_time.time()
    session = service.create_session("orch", "basic-survival-v1", 19, 1)
    pairing = service.create_pairing(session.admin_token, "c1", now)
    claimed = service.claim_slot(pairing.code or "", _identity(), now)
    token = claimed.controller_token
    assert token is not None
    service.heartbeat(token, 0, "connected", now)
    service.start_match(session.admin_token, now)

    real_time.sleep(0.2)
    service.submit_actions(token, 0, ({"kind": "wait"},))

    report = service.run_report(session.admin_token)
    cost = report["metrics"]["cost"]["c1"]
    assert 100 <= cost["server_latency_ms"] < 5_000


def test_budgets_default_unset(clock: Clock) -> None:
    """With no budget specified, controllers can use unlimited resources."""
    service = GameService()
    session = service.create_session("orch", "basic-survival-v1", 25, 1)
    # No budgets specified
    pairing = service.create_pairing(session.admin_token, "c1", clock.now)
    claimed = service.claim_slot(pairing.code or "", _identity(), clock.now)
    token = claimed.controller_token
    assert token is not None
    service.heartbeat(token, 0, "connected", clock.now)
    service.start_match(session.admin_token, clock.now)

    # Record very large usage
    service.record_usage(token, input_tokens=0, output_tokens=100000, latency_ms=0)
    result = service.submit_actions(token, 0, ({"kind": "wait"},))

    # No budget exceeded because budgets are unset
    assert result.status == "resolved"
    report = service.run_report(session.admin_token)
    cost = report["metrics"]["cost"]["c1"]
    assert cost["budget_exceeded"] == 0
