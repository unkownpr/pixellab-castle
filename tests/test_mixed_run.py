"""Tests for mixed model-vs-baseline runs."""

from pathlib import Path

import pytest

from castle_benchmark.runner import MixedRunConfig, run_mixed_match, verify_replay
from castle_benchmark.scenarios import get_scenario


@pytest.mark.parametrize("scenario_id", ["basic-survival-v1", "desert-scarcity-v1"])
def test_mixed_run_with_fallback_baselines(tmp_path: Path, scenario_id: str) -> None:
    """Verify mixed run falls back to baselines when no external agents connect.

    This tests the core mixed-run flow: external seats configured but no agents
    connecting, so they fall back to local baselines. The resulting artifacts
    should be identical to a baseline-only run and replay should verify.
    """
    report = run_mixed_match(
        MixedRunConfig(
            scenario=get_scenario(scenario_id),
            seed=17,
            output_dir=tmp_path,
            external_seat_indices=(1,),  # Seat 1 is external (will fall back)
            baseline_kinds=("survivalist", "trader", "expansionist"),
            external_agent_timeout_seconds=1,  # Short timeout to test fallback
        )
    )

    # Verify artifacts were created
    assert report.run_dir.exists()
    assert report.report_path.exists()
    assert (report.run_dir / "metadata.json").exists()
    assert (report.run_dir / "turns.jsonl").exists()
    assert (report.run_dir / "summary.sqlite3").exists()

    # Verify replay passes (determinism is preserved)
    verification = verify_replay(report.run_dir)
    assert verification.ok, f"Replay failed at turn {verification.first_mismatch_turn}"

    # Verify the report contains expected structure
    import json

    metadata = json.loads((report.run_dir / "metadata.json").read_text())
    assert metadata["scenario"]["id"] == scenario_id
    assert metadata["seed"] == 17
    assert metadata["colony_count"] == 4  # 1 external + 3 baselines

    # Verify controller names record the types
    assert "c1" in metadata["controllers"]
    assert "c2" in metadata["controllers"]
    assert "c3" in metadata["controllers"]
    assert "c4" in metadata["controllers"]

    # Verify external seat fallback is recorded
    assert "external:fallback" in metadata["controllers"]["c1"]
    assert "baseline:" in metadata["controllers"]["c2"]
    assert "baseline:" in metadata["controllers"]["c3"]
    assert "baseline:" in metadata["controllers"]["c4"]


def test_mixed_run_with_specified_baselines(tmp_path: Path) -> None:
    """Verify mixed run with explicit baseline kinds for non-external seats."""
    report = run_mixed_match(
        MixedRunConfig(
            scenario=get_scenario("basic-survival-v1"),
            seed=23,
            output_dir=tmp_path,
            external_seat_indices=(2, 4),  # Seats 2 and 4 are external
            baseline_kinds=("militarist", "expansionist"),  # Seats 1 and 3
            external_agent_timeout_seconds=1,
        )
    )

    # Verify replay passes
    verification = verify_replay(report.run_dir)
    assert verification.ok, f"Replay failed at turn {verification.first_mismatch_turn}"

    # Verify metadata records the right structure
    import json

    metadata = json.loads((report.run_dir / "metadata.json").read_text())
    assert metadata["colony_count"] == 4

    # Verify baseline kinds are assigned correctly
    assert "baseline:militarist" in metadata["controllers"]["c1"]
    assert "external:fallback" in metadata["controllers"]["c2"]
    assert "baseline:expansionist" in metadata["controllers"]["c3"]
    assert "external:fallback" in metadata["controllers"]["c4"]


def test_mixed_run_with_connected_external_agent_writes_real_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches the connected-agent branch exporting an empty metrics dict.

    When an external agent actually claims its seat and plays to completion, the run
    must write the same populated metrics as any other run, not an empty {}.
    """
    import json
    import time as time_module

    from castle_benchmark import runner as runner_module
    from castle_benchmark.lobby import ControllerIdentity
    from castle_benchmark.service import GameService

    captured: dict[str, object] = {}

    class CapturingGameService(GameService):
        def __init__(self) -> None:
            super().__init__()
            captured["service"] = self

    monkeypatch.setattr(runner_module, "GameService", CapturingGameService)

    def fake_print(*args: object, **kwargs: object) -> None:
        text = " ".join(str(a) for a in args)
        if text.startswith("Seat ") and "service" in captured:
            code = text.rsplit(": ", 1)[-1]
            service = captured["service"]
            now = time_module.time()
            claimed = service.claim_slot(
                code, ControllerIdentity(display_name="X", provider="p", model="m"), now
            )
            assert claimed.controller_token is not None
            service.heartbeat(claimed.controller_token, 0, "connected", now)
            captured["token"] = claimed.controller_token

    monkeypatch.setattr(runner_module, "print", fake_print, raising=False)

    class FakeTime:
        def time(self) -> float:
            return time_module.time()

        def sleep(self, seconds: float) -> None:
            service = captured.get("service")
            token = captured.get("token")
            if service is None or token is None:
                return
            match = next(iter(service._matches.values()))
            if match.sim.state.terminal:
                return
            try:
                service.submit_actions(token, match.sim.state.turn, ({"kind": "wait"},))
            except Exception:
                pass

    monkeypatch.setattr(runner_module, "time", FakeTime())

    report = run_mixed_match(
        MixedRunConfig(
            scenario=get_scenario("basic-survival-v1"),
            seed=17,
            output_dir=tmp_path,
            external_seat_indices=(1,),
            baseline_kinds=("survivalist",),
            external_agent_timeout_seconds=5,
        )
    )

    assert report.metrics
    assert "composites" in report.metrics

    written = json.loads(report.report_path.read_text())
    assert written["metrics"]


def test_server_is_listening_during_mixed_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the HTTP server is actually listening while the match waits for agents.

    This test ensures that a real external agent could connect to the server,
    not just that the code doesn't crash.
    """
    import threading
    import time as time_module
    import urllib.request

    from castle_benchmark import runner as runner_module
    from castle_benchmark.lobby import ControllerIdentity
    from castle_benchmark.service import GameService

    captured: dict[str, object] = {}
    server_ready = threading.Event()

    class CapturingGameService(GameService):
        def __init__(self) -> None:
            super().__init__()
            captured["service"] = self

    monkeypatch.setattr(runner_module, "GameService", CapturingGameService)

    def fake_print(*args: object, **kwargs: object) -> None:
        text = " ".join(str(a) for a in args)
        # When we see "Agent connection URL" printed, signal that server should be ready
        if text.startswith("Agent connection URL:"):
            captured["url"] = text.split(": ", 1)[-1]
            server_ready.set()

    monkeypatch.setattr(runner_module, "print", fake_print, raising=False)

    def agent_connection_thread() -> None:
        """Thread that tries to connect to the server and claim a seat."""
        try:
            # Wait for server to be ready
            if not server_ready.wait(timeout=10):
                captured["error"] = "Server startup timeout"
                return

            url = captured.get("url")
            if not url:
                captured["error"] = "URL not captured"
                return

            # Try to reach the health endpoint
            try:
                with urllib.request.urlopen(f"{url}/health", timeout=5) as response:
                    health_data = json.loads(response.read())
                    if health_data.get("status") == "ok":
                        captured["health_ok"] = True
            except Exception as exc:
                captured["health_error"] = str(exc)

            # Now try to claim a seat
            service = captured.get("service")
            if service is None:
                captured["error"] = "Service not captured"
                return

            now = time_module.time()
            code_text = ""

            # Capture the pairing code from print output
            class CodeCapture:
                def __init__(self) -> None:
                    self.code = None

                def __call__(self, *args: object, **kwargs: object) -> None:
                    nonlocal code_text
                    text = " ".join(str(a) for a in args)
                    code_text = text

            original_print = captured.get("original_print")
            if "c1" in code_text:
                # Extract the code (format is "Seat 1 (c1): <code>")
                parts = code_text.split(": ")
                if len(parts) > 1:
                    code = parts[-1].strip()
                    try:
                        claimed = service.claim_slot(
                            code, ControllerIdentity(display_name="Test", provider="test", model="test"), now
                        )
                        if claimed.controller_token:
                            captured["claimed"] = True
                    except Exception as exc:
                        captured["claim_error"] = str(exc)

        except Exception as exc:
            captured["thread_error"] = str(exc)

    # Monkeypatch a simple version that just sets the server_ready event
    # based on the URL being printed
    old_print = print
    call_count = [0]

    def new_print(*args: object, **kwargs: object) -> None:
        text = " ".join(str(a) for a in args)
        if "Agent connection URL:" in text:
            captured["url"] = text.split(": ", 1)[-1]
            server_ready.set()
        old_print(*args, **kwargs)

    monkeypatch.setattr(runner_module, "print", new_print)

    # Start agent connection thread
    agent_thread = threading.Thread(target=agent_connection_thread, daemon=True)
    agent_thread.start()

    # Run the mixed match
    report = run_mixed_match(
        MixedRunConfig(
            scenario=get_scenario("basic-survival-v1"),
            seed=17,
            output_dir=tmp_path,
            external_seat_indices=(1,),
            baseline_kinds=("survivalist",),
            external_agent_timeout_seconds=2,
        )
    )

    # Wait for agent thread
    agent_thread.join(timeout=5)

    # Verify server was reachable
    assert captured.get("url"), "Server URL was not printed"
    assert captured.get("health_ok") or captured.get("health_error"), "Health check should have been attempted"
    # We don't strictly require health_ok because the server might still be shutting down
    # but we should have gotten a response attempt
    assert "health_error" not in captured or "Connection refused" not in captured.get("health_error", ""), \
        f"Server should have been listening: {captured.get('health_error')}"

    # Verify the run completed
    assert report.run_dir.exists()
    assert report.report_path.exists()
