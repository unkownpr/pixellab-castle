"""Concurrency tests for GameService under parallel load."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Barrier, Event, Thread
from typing import Callable

import pytest

from castle_benchmark.events import state_hash
from castle_benchmark.lobby import ControllerIdentity
from castle_benchmark.service import GameService, ConflictError, UnauthorizedError, ForbiddenError


def _identity(name: str = "Codex") -> ControllerIdentity:
    return ControllerIdentity(display_name=name, provider="openai", model="gpt-5")


class TestNoBleeding:
    """State bleed: verify N concurrent matches produce identical hashes when run alone."""

    def test_no_state_bleed_small_maps_many_turns(self) -> None:
        """N matches from N threads, each driven to completion: hashes match solo runs."""
        num_matches = 4
        seed_base = 1000
        scenario = "basic-survival-v1"
        now = time.time()

        # Run each match serially first to get the expected hashes.
        expected_hashes: dict[int, list[str]] = {}
        for seed_offset in range(num_matches):
            seed = seed_base + seed_offset
            service = GameService()
            session = service.create_session("orch", scenario, seed, 2)
            service.configure_slot(session.admin_token, "c1", "baseline", baseline_kind="survivalist")
            service.configure_slot(session.admin_token, "c2", "baseline", baseline_kind="survivalist")
            service.start_match(session.admin_token, now)

            hashes: list[str] = [state_hash(service._matches[session.match_id].sim.state)]
            # Run turns with deadline closes (advance time properly).
            current_time = now
            for _ in range(5):
                current_time += 31
                service.close_deadline(session.admin_token, current_time)
                match = service._matches[session.match_id]
                hashes.append(state_hash(match.sim.state))
                if match.sim.state.terminal:
                    break
            expected_hashes[seed_offset] = hashes

        # Now run all matches concurrently.
        service = GameService()
        concurrent_hashes: dict[int, list[str]] = {}

        def run_match(seed_offset: int) -> None:
            seed = seed_base + seed_offset
            session = service.create_session("orch", scenario, seed, 2)
            service.configure_slot(session.admin_token, "c1", "baseline", baseline_kind="survivalist")
            service.configure_slot(session.admin_token, "c2", "baseline", baseline_kind="survivalist")
            service.start_match(session.admin_token, now)

            hashes: list[str] = [state_hash(service._matches[session.match_id].sim.state)]
            current_time = now
            for _ in range(5):
                current_time += 31
                service.close_deadline(session.admin_token, current_time)
                match = service._matches[session.match_id]
                hashes.append(state_hash(match.sim.state))
                if match.sim.state.terminal:
                    break
            concurrent_hashes[seed_offset] = hashes

        with ThreadPoolExecutor(max_workers=num_matches) as executor:
            futures = [executor.submit(run_match, i) for i in range(num_matches)]
            for future in as_completed(futures):
                future.result()

        # Verify hashes match.
        for seed_offset in range(num_matches):
            assert len(concurrent_hashes[seed_offset]) == len(expected_hashes[seed_offset]), \
                f"Turn count mismatch for seed {seed_base + seed_offset}"
            for turn, (concurrent, expected) in enumerate(
                zip(concurrent_hashes[seed_offset], expected_hashes[seed_offset])
            ):
                assert concurrent == expected, \
                    f"Hash mismatch at turn {turn} for seed {seed_base + seed_offset}"


class TestNoLostSubmissions:
    """No lost submissions: many controllers submitting concurrently in one turn are all seen."""

    def test_many_controllers_submitting_same_turn_all_recorded(self) -> None:
        """4 external controllers submit simultaneously; every submission is recorded."""
        num_controllers = 4
        now = time.time()
        service = GameService()
        session = service.create_session("orch", "basic-survival-v1", 42, num_controllers)

        # Claim all slots and start.
        tokens: dict[int, str] = {}
        for i in range(num_controllers):
            colony_id = f"c{i + 1}"
            pairing = service.create_pairing(session.admin_token, colony_id, now)
            claimed = service.claim_slot(pairing.code or "", _identity(f"agent-{i}"), now)
            token = claimed.controller_token
            assert token is not None
            service.heartbeat(token, 0, "connected", now)
            tokens[i] = token

        service.start_match(session.admin_token, now)
        match = service._matches[session.match_id]

        # All submit actions simultaneously on turn 0.
        results: list[object] = []

        def submit(token: str, turn: int) -> None:
            result = service.submit_actions(token, turn, [{"kind": "wait"}])
            results.append(result)

        with ThreadPoolExecutor(max_workers=num_controllers) as executor:
            futures = [executor.submit(submit, tokens[i], 0) for i in range(num_controllers)]
            for future in as_completed(futures):
                future.result()

        # Verify all submitted and the turn resolved exactly once.
        assert match.sim.state.turn == 1, "Turn should have advanced exactly once"
        assert len(match.resolved_turns) == 1, "Exactly one turn should be resolved"
        # All controllers should have submitted.
        assert len(match.resolved_turns[0].action_controller_ids) == num_controllers
        # Last result should record all submissions.
        assert match.last_result is not None
        assert len(match.last_result.action_results) == num_controllers


class TestCapabilityIsolation:
    """Capability isolation: token from match A must not work for match B while both live."""

    def test_controller_token_scoped_to_match(self) -> None:
        """Token from match A rejected by match B's actions."""
        now = time.time()

        # Create two matches with distinct tokens.
        service = GameService()
        session_a = service.create_session("orch", "basic-survival-v1", 100, 1)
        session_b = service.create_session("orch", "basic-survival-v1", 101, 1)

        pairing_a = service.create_pairing(session_a.admin_token, "c1", now)
        claimed_a = service.claim_slot(pairing_a.code or "", _identity("agent-a"), now)
        token_a = claimed_a.controller_token
        assert token_a is not None

        pairing_b = service.create_pairing(session_b.admin_token, "c1", now)
        claimed_b = service.claim_slot(pairing_b.code or "", _identity("agent-b"), now)
        token_b = claimed_b.controller_token
        assert token_b is not None

        service.heartbeat(token_a, 0, "connected", now)
        service.heartbeat(token_b, 0, "connected", now)

        service.start_match(session_a.admin_token, now)
        service.start_match(session_b.admin_token, now)

        # token_a must not work for assert_match on session_b.
        with pytest.raises(ForbiddenError):
            service.assert_match(token_a, session_b.match_id)

        # token_a must work for session_a.
        service.assert_match(token_a, session_a.match_id)

        # token_b must work for session_b, not session_a.
        with pytest.raises(ForbiddenError):
            service.assert_match(token_b, session_a.match_id)


class TestDeadlineUnderContention:
    """Deadline manager under load: deadline firing concurrent with submissions."""

    def test_deadline_and_submissions_race_no_corruption(self) -> None:
        """Close deadline fires while submissions race for the barrier; no lost turns."""
        num_controllers = 4
        now = time.time()
        service = GameService()
        session = service.create_session("orch", "basic-survival-v1", 200, num_controllers)

        # Claim all slots and configure.
        tokens: list[str] = []
        for i in range(num_controllers):
            colony_id = f"c{i + 1}"
            pairing = service.create_pairing(session.admin_token, colony_id, now)
            claimed = service.claim_slot(pairing.code or "", _identity(f"agent-{i}"), now)
            token = claimed.controller_token
            assert token is not None
            service.heartbeat(token, 0, "connected", now)
            tokens.append(token)

        service.start_match(session.admin_token, now)
        match = service._matches[session.match_id]

        # Set up a barrier: deadline thread and N submission threads must coordinate.
        # Some threads submit, some hit the deadline—verify turn resolves cleanly.
        num_turns = 3
        current_time = now

        for turn_num in range(num_turns):
            if turn_num > 0:
                current_time += 31  # Advance for the next deadline.
            # Simulate some submissions before deadline fires.
            barrier = Barrier(num_controllers + 1)  # controllers + deadline thread

            def submit_with_sync(token: str) -> None:
                barrier.wait()  # Sync all threads to go "concurrently".
                service.submit_actions(token, turn_num, [{"kind": "wait"}])

            def close_with_sync(deadline_time: float) -> None:
                barrier.wait()  # Sync all threads.
                # Give submissions a small window, then fire deadline.
                time.sleep(0.001)
                try:
                    service.close_deadline(session.admin_token, deadline_time)
                except ConflictError:
                    pass  # Deadline already fired or turn already resolved.

            with ThreadPoolExecutor(max_workers=num_controllers + 1) as executor:
                submit_futures = [
                    executor.submit(submit_with_sync, tokens[i])
                    for i in range(num_controllers)
                ]
                deadline_future = executor.submit(close_with_sync, current_time)

                for future in as_completed(submit_futures + [deadline_future]):
                    try:
                        future.result()
                    except ConflictError:
                        pass  # Expected when turn is already resolved.

            # Verify turn is resolved exactly once.
            assert match.sim.state.turn == turn_num + 1, f"Turn should be {turn_num + 1}"
            assert len(match.resolved_turns) == turn_num + 1

    def test_deadline_manager_with_many_deadlines_fired(self) -> None:
        """Deadline manager fires N deadlines concurrently; state stays consistent."""
        num_matches = 3
        now = time.time()
        service = GameService()

        # Create N matches, all with external controllers.
        sessions = []
        tokens_by_match = []

        for match_idx in range(num_matches):
            session = service.create_session("orch", "basic-survival-v1", 300 + match_idx, 2)
            pairing_1 = service.create_pairing(session.admin_token, "c1", now)
            pairing_2 = service.create_pairing(session.admin_token, "c2", now)

            claimed_1 = service.claim_slot(pairing_1.code or "", _identity(f"agent-{match_idx}-1"), now)
            claimed_2 = service.claim_slot(pairing_2.code or "", _identity(f"agent-{match_idx}-2"), now)

            token_1 = claimed_1.controller_token
            token_2 = claimed_2.controller_token
            assert token_1 is not None and token_2 is not None

            service.heartbeat(token_1, 0, "connected", now)
            service.heartbeat(token_2, 0, "connected", now)
            service.start_match(session.admin_token, now)

            sessions.append(session)
            tokens_by_match.append([token_1, token_2])

        # Fire all deadlines concurrently.
        deadline_time = now + 31

        def fire_deadline(session: object) -> None:
            try:
                service.close_deadline(session.admin_token, deadline_time)  # type: ignore[attr-defined]
            except ConflictError:
                pass  # Turn already resolved.

        with ThreadPoolExecutor(max_workers=num_matches) as executor:
            futures = [executor.submit(fire_deadline, session) for session in sessions]
            for future in as_completed(futures):
                future.result()

        # Verify all matches have consistent state and advanced.
        for idx, session in enumerate(sessions):
            match = service._matches[session.match_id]  # type: ignore[attr-defined]
            assert match.sim.state.turn == 1, f"Match {idx} turn should be 1, got {match.sim.state.turn}"
            assert len(match.resolved_turns) == 1, f"Match {idx} should have 1 resolved turn"


class TestAccessControlUnderLoad:
    """Access control: concurrent access checks maintain isolation."""

    def test_concurrent_authorization_checks_never_leak_capabilities(self) -> None:
        """Many concurrent _authorize calls race without returning cross-match tokens."""
        now = time.time()
        service = GameService()

        # Create tokens for different matches.
        sessions = []
        all_tokens = []
        token_to_match: dict[str, str] = {}

        for match_idx in range(4):
            session = service.create_session("orch", "basic-survival-v1", 400 + match_idx, 1)
            pairing = service.create_pairing(session.admin_token, "c1", now)
            claimed = service.claim_slot(pairing.code or "", _identity(f"agent-{match_idx}"), now)
            token = claimed.controller_token
            assert token is not None
            service.heartbeat(token, 0, "connected", now)
            sessions.append(session)
            all_tokens.append(token)
            token_to_match[token] = session.match_id

        # Start all matches.
        for session in sessions:
            service.start_match(session.admin_token, now)

        # Concurrently call _authorize on all tokens; verify no cross-contamination.
        results: dict[str, str] = {}

        def authorize_and_check(token: str) -> None:
            access, match = service._authorize(token)
            expected = token_to_match[token]
            assert access.match_id == expected, \
                f"Token authorized to wrong match: {access.match_id} != {expected}"
            results[token] = access.match_id

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(authorize_and_check, token) for token in all_tokens]
            for future in as_completed(futures):
                future.result()

        # Verify all tokens were authorized correctly.
        assert len(results) == len(all_tokens)
        for token, match_id in results.items():
            assert match_id == token_to_match[token]


class TestConcurrentDeadlineClose:
    """Close deadline: serialize turn resolution even with concurrent deadline fires."""

    def test_only_one_deadline_close_per_turn(self) -> None:
        """Multiple close_deadline calls on same turn; turn resolves exactly once."""
        now = time.time()
        service = GameService()
        session = service.create_session("orch", "basic-survival-v1", 500, 2)

        pairing_1 = service.create_pairing(session.admin_token, "c1", now)
        pairing_2 = service.create_pairing(session.admin_token, "c2", now)

        claimed_1 = service.claim_slot(pairing_1.code or "", _identity("agent-1"), now)
        claimed_2 = service.claim_slot(pairing_2.code or "", _identity("agent-2"), now)

        token_1 = claimed_1.controller_token
        token_2 = claimed_2.controller_token
        assert token_1 is not None and token_2 is not None

        service.heartbeat(token_1, 0, "connected", now)
        service.heartbeat(token_2, 0, "connected", now)
        service.start_match(session.admin_token, now)

        match = service._matches[session.match_id]
        results: list[object] = []

        def close() -> None:
            try:
                result = service.close_deadline(session.admin_token, now + 31)
                results.append(result)
            except ConflictError as e:
                results.append(e)

        # Fire 3 threads all trying to close the deadline.
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(close) for _ in range(3)]
            for future in as_completed(futures):
                future.result()

        # Verify turn resolved exactly once.
        assert match.sim.state.turn == 1
        assert len(match.resolved_turns) == 1
        # At least one must have succeeded (gotten the result), rest got ConflictError.
        successes = [r for r in results if not isinstance(r, ConflictError)]
        assert len(successes) >= 1


class TestSubmitActionsSerialization:
    """Submit actions: concurrent submissions serialize properly via turn_lock."""

    def test_both_controllers_submit_each_turn(self) -> None:
        """Two controllers both submit on each turn; turns resolve in order."""
        now = time.time()
        service = GameService()
        session = service.create_session("orch", "basic-survival-v1", 600, 2)

        pairing_1 = service.create_pairing(session.admin_token, "c1", now)
        pairing_2 = service.create_pairing(session.admin_token, "c2", now)

        claimed_1 = service.claim_slot(pairing_1.code or "", _identity("agent-1"), now)
        claimed_2 = service.claim_slot(pairing_2.code or "", _identity("agent-2"), now)

        token_1 = claimed_1.controller_token
        token_2 = claimed_2.controller_token
        assert token_1 is not None and token_2 is not None

        service.heartbeat(token_1, 0, "connected", now)
        service.heartbeat(token_2, 0, "connected", now)
        service.start_match(session.admin_token, now)

        match = service._matches[session.match_id]

        # Submit turn 0 from both controllers concurrently.
        results_turn_0 = []

        def submit_turn_0_c1() -> None:
            result = service.submit_actions(token_1, 0, [{"kind": "wait"}])
            results_turn_0.append(("c1", result))

        def submit_turn_0_c2() -> None:
            result = service.submit_actions(token_2, 0, [{"kind": "wait"}])
            results_turn_0.append(("c2", result))

        # Run both submissions concurrently.
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(submit_turn_0_c1),
                executor.submit(submit_turn_0_c2),
            ]
            for future in as_completed(futures):
                future.result()

        # Turn should have advanced.
        assert match.sim.state.turn == 1
        # Both submissions should be recorded.
        assert len(results_turn_0) == 2
        # At least one should report the turn resolved.
        resolved = [r for _, r in results_turn_0 if r.status == "resolved"]
        assert len(resolved) >= 1
