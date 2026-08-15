from __future__ import annotations

import threading
import sys

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from castle_benchmark.api import create_app
from castle_benchmark import cli
from castle_benchmark.service import GameService


ORCHESTRATOR = "o" * 32


def test_session_creation_requires_configured_orchestrator_capability() -> None:
    """Catches remote session creation falling open when no server capability is configured."""
    client = TestClient(create_app(GameService()))

    response = client.post(
        "/api/sessions",
        headers={"Authorization": f"Bearer {ORCHESTRATOR}"},
        json={"scenario_id": "basic-survival-v1", "seed": 131, "colony_count": 1},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthorized"


@pytest.mark.parametrize(
    ("host", "remote", "token", "origins", "message"),
    [
        ("0.0.0.0", False, ORCHESTRATOR, ("https://ops.example",), "--remote"),
        ("192.168.1.5", True, None, ("https://ops.example",), "orchestrator"),
        ("192.168.1.5", True, "short", ("https://ops.example",), "high-entropy"),
        ("192.168.1.5", True, ORCHESTRATOR, (), "allowed origin"),
        ("192.168.1.5", True, ORCHESTRATOR, ("*",), "wildcard"),
    ],
)
def test_remote_configuration_fails_closed(
    host: str,
    remote: bool,
    token: str | None,
    origins: tuple[str, ...],
    message: str,
) -> None:
    """Catches unsafe bind/origin/capability combinations reaching Uvicorn."""
    with pytest.raises(ValueError, match=message):
        cli.validate_remote_configuration(host, remote, token, origins)


def test_serve_parser_accepts_repeatable_explicit_allowed_origins() -> None:
    """Catches CLI parsing collapsing or silently discarding the explicit origin allowlist."""
    args = cli.build_parser().parse_args(
        [
            "serve",
            "--host",
            "0.0.0.0",
            "--remote",
            "--allowed-origin",
            "https://one.example",
            "--allowed-origin",
            "https://two.example",
            "--trusted-proxy",
            "10.0.0.0/8",
        ]
    )

    assert args.remote is True
    assert args.allowed_origin == ["https://one.example", "https://two.example"]
    assert args.trusted_proxy == ["10.0.0.0/8"]


def test_forwarded_client_ip_is_used_only_for_explicit_trusted_proxy() -> None:
    """Catches spoofed proxy headers bypassing or globally sharing the peer attempt budget."""
    payload = lambda index: {
        "pairing_code": f"unknown-{index}",
        "identity": {"display_name": "Agent", "provider": "p", "model": "m"},
    }
    untrusted = TestClient(
        create_app(GameService(), orchestrator_token=ORCHESTRATOR),
        client=("10.1.2.3", 50000),
    )
    for index in range(5):
        assert untrusted.post(
            "/api/pairings/claim",
            json=payload(index),
            headers={"X-Forwarded-For": f"203.0.113.{index + 1}"},
        ).status_code == 401
    assert untrusted.post(
        "/api/pairings/claim",
        json=payload(6),
        headers={"X-Forwarded-For": "203.0.113.99"},
    ).status_code == 409

    trusted = TestClient(
        create_app(
            GameService(),
            orchestrator_token=ORCHESTRATOR,
            trusted_proxies=("10.0.0.0/8",),
        ),
        client=("10.1.2.3", 50000),
    )
    for index in range(6):
        assert trusted.post(
            "/api/pairings/claim",
            json=payload(index),
            headers={"X-Forwarded-For": f"203.0.113.{index + 1}"},
        ).status_code == 401


def test_actual_serve_cli_rejects_unsafe_remote_before_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches the CLI entry point bypassing its remote configuration validator."""
    import uvicorn

    called = False

    def unexpected_run(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(uvicorn, "run", unexpected_run)
    monkeypatch.delenv("CASTLE_BENCHMARK_ORCHESTRATOR_TOKEN", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "castle-benchmark",
            "serve",
            "--host",
            "0.0.0.0",
            "--remote",
            "--allowed-origin",
            "https://ops.example",
        ],
    )

    with pytest.raises(SystemExit, match="orchestrator"):
        cli.main()
    assert called is False


def test_actual_serve_cli_reload_uses_importable_app_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches Uvicorn reload receiving a live app object and refusing startup."""
    import uvicorn

    captured: dict[str, object] = {}

    def capture_run(app: object, **kwargs: object) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", capture_run)
    monkeypatch.setattr(sys, "argv", ["castle-benchmark", "serve", "--reload"])

    cli.main()

    assert captured["app"] == "castle_benchmark.cli:create_serve_app"
    assert captured["factory"] is True
    assert captured["reload"] is True
    assert captured["proxy_headers"] is False


def test_reload_factory_reconstructs_remote_origin_and_route_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches reload workers losing the validated remote security configuration."""
    monkeypatch.setenv("CASTLE_BENCHMARK_ORCHESTRATOR_TOKEN", ORCHESTRATOR)
    monkeypatch.setenv("CASTLE_BENCHMARK_SERVE_ALLOWED_ORIGINS", '["https://ops.example"]')
    monkeypatch.setenv("CASTLE_BENCHMARK_SERVE_TRUSTED_PROXIES", '["10.0.0.0/8"]')
    monkeypatch.setenv("CASTLE_BENCHMARK_SERVE_REMOTE", "1")

    app = cli.create_serve_app()
    paths = {route.path for route in app.routes}  # type: ignore[attr-defined]
    cors = next(
        middleware
        for middleware in app.user_middleware  # type: ignore[attr-defined]
        if middleware.cls.__name__ == "CORSMiddleware"
    )

    assert "/api/matches" not in paths
    assert cors.kwargs["allow_origins"] == ["https://ops.example"]


def test_http_rejects_oversized_identity_with_stable_safe_error() -> None:
    """Catches unbounded controller labels or validation internals crossing the HTTP boundary."""
    service = GameService()
    client = TestClient(
        create_app(service, orchestrator_token=ORCHESTRATOR, clock=lambda: 100.0)
    )
    created = client.post(
        "/api/sessions",
        headers={"Authorization": f"Bearer {ORCHESTRATOR}"},
        json={"scenario_id": "basic-survival-v1", "seed": 137, "colony_count": 1},
    ).json()
    pairing = client.post(
        f"/api/sessions/{created['match_id']}/slots/c1/pairing",
        headers={"Authorization": f"Bearer {created['admin_token']}"},
    ).json()

    response = client.post(
        "/api/pairings/claim",
        json={
            "pairing_code": pairing["pairing_code"],
            "identity": {"display_name": "x" * 129, "provider": "p", "model": "m"},
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "invalid_request", "message": "request validation failed"}
    }


def test_http_rejects_payload_over_16_kib_before_route_execution() -> None:
    """Catches remote request bodies bypassing the protocol-wide payload ceiling."""
    client = TestClient(create_app(GameService(), orchestrator_token=ORCHESTRATOR))

    response = client.post(
        "/api/sessions",
        headers={"Authorization": f"Bearer {ORCHESTRATOR}"},
        content=b"x" * (16 * 1024 + 1),
    )

    assert response.status_code == 413
    assert response.json() == {
        "detail": {"code": "payload_too_large", "message": "request payload exceeds 16 KiB"}
    }


@pytest.mark.asyncio
async def test_http_rejects_chunked_payload_without_buffering_the_remaining_stream() -> None:
    """Catches chunked requests bypassing the limit or being fully buffered before rejection."""
    consumed = 0
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        nonlocal consumed
        consumed += 1
        return {"type": "http.request", "body": b"x" * 1024, "more_body": True}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    app = create_app(GameService(), orchestrator_token=ORCHESTRATOR)
    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/sessions",
            "raw_path": b"/api/sessions",
            "query_string": b"",
            "headers": [],
            "client": ("203.0.113.1", 50000),
            "server": ("testserver", 80),
            "root_path": "",
        },
        receive,
        send,
    )

    assert sent[0]["status"] == 413
    assert consumed == 17


def test_http_pairing_attempt_limit_cannot_be_reset_by_valid_identity() -> None:
    """Catches repeated malformed claims being able to brute-force forever."""
    service = GameService()
    client = TestClient(
        create_app(service, orchestrator_token=ORCHESTRATOR, clock=lambda: 100.0)
    )
    created = client.post(
        "/api/sessions",
        headers={"Authorization": f"Bearer {ORCHESTRATOR}"},
        json={"scenario_id": "basic-survival-v1", "seed": 139, "colony_count": 1},
    ).json()
    pairing = client.post(
        f"/api/sessions/{created['match_id']}/slots/c1/pairing",
        headers={"Authorization": f"Bearer {created['admin_token']}"},
    ).json()

    for _ in range(5):
        malformed = client.post(
            "/api/pairings/claim",
            json={
                "pairing_code": pairing["pairing_code"],
                "identity": {"display_name": "   ", "provider": "p", "model": "m"},
            },
        )
        assert malformed.status_code == 400

    blocked = client.post(
        "/api/pairings/claim",
        json={
            "pairing_code": pairing["pairing_code"],
            "identity": {"display_name": "Valid", "provider": "p", "model": "m"},
        },
    )

    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "pairing_attempt_limit"


def test_http_invalid_pairing_code_is_limited_per_peer_and_code() -> None:
    """Catches remote callers brute-forcing unknown pairing codes without an IP/code limit."""
    client = TestClient(create_app(GameService(), orchestrator_token=ORCHESTRATOR))
    payload = {
        "pairing_code": "unknown-code",
        "identity": {"display_name": "Agent", "provider": "p", "model": "m"},
    }

    for _ in range(5):
        assert client.post("/api/pairings/claim", json=payload).status_code == 401
    blocked = client.post("/api/pairings/claim", json=payload)

    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "pairing_attempt_limit"


def test_create_app_rejects_wildcard_credential_origin() -> None:
    """Catches programmatic startup bypassing the CLI wildcard-origin guard."""
    with pytest.raises(ValueError, match="wildcard"):
        create_app(
            GameService(),
            orchestrator_token=ORCHESTRATOR,
            allowed_origins=("*",),
        )


def test_remote_app_disables_legacy_bulk_capability_creation() -> None:
    """Catches the legacy local shortcut bypassing orchestrator auth on a remote bind."""
    client = TestClient(
        create_app(
            GameService(),
            orchestrator_token=ORCHESTRATOR,
            allowed_origins=("https://ops.example",),
            remote=True,
        )
    )

    response = client.post(
        "/api/matches",
        json={"scenario_id": "basic-survival-v1", "seed": 149, "colony_count": 2},
    )

    assert response.status_code == 404


def test_local_match_creation_requires_orchestrator_capability() -> None:
    """Catches the legacy local shortcut minting capabilities without any secret."""
    client = TestClient(create_app(GameService(), orchestrator_token=ORCHESTRATOR))

    anonymous = client.post(
        "/api/matches",
        json={"scenario_id": "basic-survival-v1", "seed": 149, "colony_count": 1},
    )
    assert anonymous.status_code == 401
    assert anonymous.json()["detail"]["code"] == "unauthorized"

    authorized = client.post(
        "/api/matches",
        headers={"Authorization": f"Bearer {ORCHESTRATOR}"},
        json={"scenario_id": "basic-survival-v1", "seed": 149, "colony_count": 1},
    )
    assert authorized.status_code == 201


def test_local_match_creation_without_configured_capability_fails_closed() -> None:
    """Catches local match creation falling open when no orchestrator secret is set."""
    client = TestClient(create_app(GameService()))

    response = client.post(
        "/api/matches",
        headers={"Authorization": f"Bearer {ORCHESTRATOR}"},
        json={"scenario_id": "basic-survival-v1", "seed": 149, "colony_count": 1},
    )

    assert response.status_code == 401


def test_operations_websocket_ticket_is_short_lived_and_single_use() -> None:
    """Catches browser operations auth reusing an admin secret or replayable ticket."""
    now = 400.0
    client = TestClient(
        create_app(
            GameService(),
            orchestrator_token=ORCHESTRATOR,
            allowed_origins=("https://ops.example",),
            remote=True,
            clock=lambda: now,
        )
    )
    created = client.post(
        "/api/sessions",
        headers={"Authorization": f"Bearer {ORCHESTRATOR}"},
        json={"scenario_id": "basic-survival-v1", "seed": 197, "colony_count": 1},
    ).json()
    ticket_response = client.post(
        f"/api/matches/{created['match_id']}/operations/ticket",
        headers={"Authorization": f"Bearer {created['admin_token']}"},
    )
    assert ticket_response.status_code == 200
    assert ticket_response.headers["cache-control"] == "no-store"
    ticket = ticket_response.json()
    assert ticket["expires_at"] == 430.0
    assert created["admin_token"] not in str(ticket)

    with client.websocket_connect(
        f"/api/matches/{created['match_id']}/operations/ws",
        subprotocols=["castle.operations", ticket["websocket_ticket"]],
        headers={"Origin": "https://ops.example"},
    ) as websocket:
        assert websocket.receive_json()["type"] == "lobby.snapshot"

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/api/matches/{created['match_id']}/operations/ws",
            subprotocols=["castle.operations", ticket["websocket_ticket"]],
            headers={"Origin": "https://ops.example"},
        ):
            pass


def test_direct_claim_rejects_oversized_identity() -> None:
    """Catches direct callers bypassing the shared controller identity invariant."""
    from castle_benchmark.lobby import ControllerIdentity

    service = GameService()
    session = service.create_session("direct", "basic-survival-v1", 151, 1)
    pairing = service.create_pairing(session.admin_token, "c1", now=1.0)

    with pytest.raises(Exception, match="invalid controller identity"):
        service.claim_slot(
            pairing.code or "",
            ControllerIdentity("x" * 129, "provider", "model"),
            now=1.0,
        )


def test_controller_identity_value_object_owns_all_length_invariants() -> None:
    """Catches non-HTTP callers constructing invalid optional identity metadata."""
    from castle_benchmark.lobby import ControllerIdentity

    assert not ControllerIdentity("Agent", "p", "m", run_label="x" * 129).is_valid()
    assert not ControllerIdentity("Agent", "p", "m", adapter_name=123).is_valid()  # type: ignore[arg-type]


def test_claim_projection_and_replacement_share_one_slot_lifecycle_lock() -> None:
    """Catches replacement revoking a claim between token minting and contract projection."""
    from castle_benchmark.lobby import ControllerIdentity

    service = GameService()
    session = service.create_session("direct", "basic-survival-v1", 157, 1)
    service.open_lobby(session.admin_token)
    pairing = service.create_pairing(session.admin_token, "c1", now=1.0)
    claimed_inside = threading.Event()
    continue_claim = threading.Event()
    original_claim = service.claim_slot

    def paused_claim(code: str, identity: ControllerIdentity, now: float):
        grant = original_claim(code, identity, now)
        claimed_inside.set()
        continue_claim.wait(timeout=0.2)
        return grant

    service.claim_slot = paused_claim  # type: ignore[method-assign]
    outcomes: list[object] = []

    def claim() -> None:
        try:
            outcomes.append(
                service.claim_slot_contract(
                    pairing.code or "",
                    ControllerIdentity("Claim", "p", "m"),
                    now=1.0,
                )
            )
        except Exception as exc:  # pragma: no cover - asserted as an outcome
            outcomes.append(exc)

    claim_thread = threading.Thread(target=claim)
    claim_thread.start()
    assert claimed_inside.wait(timeout=1)
    replace_thread = threading.Thread(
        target=lambda: service.replace_controller(
            session.admin_token, "c1", "human", now=2.0
        )
    )
    replace_thread.start()
    continue_claim.set()
    claim_thread.join(timeout=1)
    replace_thread.join(timeout=1)

    assert len(outcomes) == 1
    assert isinstance(outcomes[0], dict)
    assert set(outcomes[0]) == {
        "match_id",
        "controller_id",
        "colony_id",
        "controller_token",
    }


def test_start_and_replacement_cannot_leave_a_stale_human_capability() -> None:
    """Catches start minting a human token after concurrent replacement revoked the slot."""
    service = GameService()
    session = service.create_session("direct", "basic-survival-v1", 233, 1)
    service.configure_slot(session.admin_token, "c1", "human")
    service.open_lobby(session.admin_token)
    mint_inside = threading.Event()
    continue_mint = threading.Event()
    minted: list[str] = []
    original_mint = service._mint_controller_capability

    def paused_mint(match: object, slot: object) -> str:
        mint_inside.set()
        continue_mint.wait(timeout=0.2)
        token = original_mint(match, slot)  # type: ignore[arg-type]
        minted.append(token)
        return token

    service._mint_controller_capability = paused_mint  # type: ignore[method-assign]
    start_thread = threading.Thread(
        target=lambda: service.start_match(session.admin_token, now=1.0)
    )
    start_thread.start()
    assert mint_inside.wait(timeout=1)
    replace_thread = threading.Thread(
        target=lambda: service.replace_controller(
            session.admin_token, "c1", "external", now=2.0
        )
    )
    replace_thread.start()
    continue_mint.set()
    start_thread.join(timeout=1)
    replace_thread.join(timeout=1)

    assert len(minted) == 1
    with pytest.raises(Exception, match="invalid controller capability"):
        service.submit_actions(minted[0], 0, ({"kind": "wait"},))


def test_pairing_attempt_reservation_is_atomic_under_concurrency() -> None:
    """Catches simultaneous adapter checks all crossing the five-attempt boundary."""
    from castle_benchmark.service import ConflictError

    service = GameService()
    barrier = threading.Barrier(6)
    outcomes: list[str] = []

    def reserve() -> None:
        barrier.wait()
        try:
            service.reserve_pairing_attempt("peer", "guess", now=1.0)
            outcomes.append("allowed")
        except ConflictError:
            outcomes.append("blocked")

    threads = [threading.Thread(target=reserve) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=1)

    assert outcomes.count("allowed") == 5
    assert outcomes.count("blocked") == 1


def test_heartbeat_cannot_mutate_a_replacement_slot_after_revocation() -> None:
    """Catches an in-flight revoked heartbeat overwriting the replacement's presence."""
    from castle_benchmark.lobby import ControllerIdentity

    service = GameService()
    session = service.create_session("direct", "basic-survival-v1", 173, 1)
    service.open_lobby(session.admin_token)
    pairing = service.create_pairing(session.admin_token, "c1", now=1.0)
    claimed = service.claim_slot_contract(
        pairing.code or "", ControllerIdentity("Race", "p", "m"), now=1.0
    )
    token = claimed["controller_token"]
    authorized_inside = threading.Event()
    continue_heartbeat = threading.Event()
    original_authorize = service._authorize

    def paused_authorize(capability: str):
        result = original_authorize(capability)
        if capability == token:
            authorized_inside.set()
            continue_heartbeat.wait(timeout=0.2)
        return result

    service._authorize = paused_authorize  # type: ignore[method-assign]
    heartbeat_thread = threading.Thread(
        target=lambda: service.heartbeat(token, 0, "disconnected", now=2.0)
    )
    heartbeat_thread.start()
    assert authorized_inside.wait(timeout=1)
    replacement_thread = threading.Thread(
        target=lambda: service.replace_controller(
            session.admin_token, "c1", "human", now=3.0
        )
    )
    replacement_thread.start()
    continue_heartbeat.set()
    heartbeat_thread.join(timeout=1)
    replacement_thread.join(timeout=1)

    snapshot = service.lobby_status(session.admin_token, now=3.0)
    assert snapshot["slots"][0]["presence"] == "taken_over"


def test_heartbeat_throttle_fails_with_stable_code_and_audit_event() -> None:
    """Catches a controller flooding presence updates without a safe observable rejection."""
    from castle_benchmark.lobby import ControllerIdentity
    from castle_benchmark.service import ConflictError

    service = GameService()
    session = service.create_session("direct", "basic-survival-v1", 199, 1)
    pairing = service.create_pairing(session.admin_token, "c1", now=1.0)
    claimed = service.claim_slot_contract(
        pairing.code or "", ControllerIdentity("Pulse", "p", "m"), now=1.0
    )
    token = claimed["controller_token"]
    service.heartbeat(token, 0, "connected", now=2.0)

    with pytest.raises(ConflictError, match="heartbeat_rate_limited") as exc:
        service.heartbeat(token, 0, "thinking", now=2.01)

    assert exc.value.code == "heartbeat_rate_limited"
    events = service.operations_snapshot(session.admin_token, now=2.01)["events"]
    assert events[-1]["kind"] == "heartbeat_rejected"
