import json
from dataclasses import asdict
from hashlib import sha256

import pytest

from castle_benchmark.lobby import ControllerIdentity
from castle_benchmark.service import ConflictError, ForbiddenError, GameService, ServiceError


class Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def service() -> GameService:
    return GameService()


@pytest.fixture
def clock() -> Clock:
    return Clock()


def identity(display_name: str, provider: str, model: str) -> ControllerIdentity:
    return ControllerIdentity(display_name=display_name, provider=provider, model=model)


def test_pairing_claim_returns_one_scoped_capability_once(service: GameService, clock: Clock) -> None:
    """Catches a replayed pairing code minting a second controller capability."""
    session = service.create_session("orch", "basic-survival-v1", 17, 4)
    service.configure_slot(session.admin_token, "c2", "external")
    grant = service.create_pairing(session.admin_token, "c2", now=clock.now)

    claimed = service.claim_slot(
        grant.code, identity("Codex", "openai", "gpt-5"), now=clock.now
    )

    assert (claimed.match_id, claimed.colony_id) == (session.match_id, "c2")
    assert claimed.controller_token is not None
    assert "controller_token" not in service.lobby_status(session.admin_token, clock.now)["slots"][1]
    with pytest.raises(ConflictError, match="pairing_consumed"):
        service.claim_slot(grant.code, identity("Replay", "x", "y"), now=clock.now)


def test_pairing_expiry_is_exactly_ten_minutes(service: GameService, clock: Clock) -> None:
    """Catches pairing capabilities remaining valid after their 600-second TTL."""
    session = service.create_session("orch", "basic-survival-v1", 17, 1)
    service.configure_slot(session.admin_token, "c1", "external")
    grant = service.create_pairing(session.admin_token, "c1", now=clock.now)

    clock.advance(600)

    with pytest.raises(ConflictError, match="pairing_expired"):
        service.claim_slot(grant.code, identity("Codex", "openai", "gpt-5"), now=clock.now)


def test_lobby_status_never_exposes_raw_pairing_or_controller_secrets(
    service: GameService, clock: Clock
) -> None:
    """Catches admin lobby snapshots leaking a usable pairing or controller capability."""
    session = service.create_session("orch", "basic-survival-v1", 17, 1)
    service.configure_slot(session.admin_token, "c1", "external")
    grant = service.create_pairing(session.admin_token, "c1", now=clock.now)
    claimed = service.claim_slot(grant.code, identity("Codex", "openai", "gpt-5"), now=clock.now)

    snapshot = service.lobby_status(session.admin_token, clock.now)
    serialized = json.dumps(snapshot, sort_keys=True)

    assert grant.code not in serialized
    assert claimed.controller_token not in serialized
    assert sha256(grant.code.encode()).hexdigest() not in serialized
    assert sha256(claimed.controller_token.encode()).hexdigest() not in serialized
    assert session.admin_token not in serialized
    assert sha256(session.admin_token.encode()).hexdigest() not in serialized
    assert claimed.controller_token not in service._matches[session.match_id].controller_tokens.values()


def test_lobby_session_keeps_admin_capability_only_in_the_service_auth_map(
    service: GameService,
) -> None:
    """Catches the session model retaining its own raw admin capability."""
    session = service.create_session("orch", "basic-survival-v1", 17, 1)

    assert "admin_token" not in asdict(session)
    assert session.admin_token in service._access
    assert session.admin_capability_digest == sha256(session.admin_token.encode()).hexdigest()


def test_human_and_baseline_slots_are_immediately_ready_and_lobby_freezes_configuration(
    service: GameService, clock: Clock
) -> None:
    """Catches ready local slots being treated as unclaimed externals or lobby edits after opening."""
    session = service.create_session("orch", "basic-survival-v1", 17, 2)
    service.configure_slot(session.admin_token, "c1", "human")
    service.configure_slot(session.admin_token, "c2", "baseline", baseline_kind="survivalist")

    opened = service.open_lobby(session.admin_token)
    status = service.lobby_status(session.admin_token, clock.now)

    assert opened.status.value == "lobby"
    assert [slot["presence"] for slot in status["slots"]] == ["ready", "ready"]
    assert status["slots"][1]["baseline_kind"] == "survivalist"
    with pytest.raises(ForbiddenError, match="lobby configuration is frozen"):
        service.configure_slot(session.admin_token, "c1", "external")


def test_invalid_claim_attempts_are_throttled(service: GameService, clock: Clock) -> None:
    """Catches unlimited malformed identity attempts against a valid pairing code."""
    session = service.create_session("orch", "basic-survival-v1", 17, 1)
    service.configure_slot(session.admin_token, "c1", "external")
    grant = service.create_pairing(session.admin_token, "c1", now=clock.now)

    for _ in range(5):
        with pytest.raises(ServiceError, match="invalid controller identity"):
            service.claim_slot(grant.code, object(), now=clock.now)  # type: ignore[arg-type]

    with pytest.raises(ConflictError, match="pairing_attempt_limit"):
        service.claim_slot(grant.code, identity("Codex", "openai", "gpt-5"), now=clock.now)


def test_slot_configuration_cannot_orphan_an_issued_capability(
    service: GameService, clock: Clock
) -> None:
    """Catches draft configuration replacing a claimed slot while its token remains authorized."""
    session = service.create_session("orch", "basic-survival-v1", 17, 1)
    service.configure_slot(session.admin_token, "c1", "external")
    grant = service.create_pairing(session.admin_token, "c1", now=clock.now)
    claimed = service.claim_slot(grant.code, identity("Codex", "openai", "gpt-5"), now=clock.now)

    with pytest.raises(ConflictError, match="slot has active pairing state"):
        service.configure_slot(session.admin_token, "c1", "human")

    service.assert_match(claimed.controller_token, session.match_id)


def test_claimed_controller_cannot_use_gameplay_until_lobby_session_is_running(
    service: GameService, clock: Clock
) -> None:
    """Catches externally claimed controllers acting before the operator starts the match."""
    session = service.create_session("orch", "basic-survival-v1", 17, 1)
    service.configure_slot(session.admin_token, "c1", "external")
    grant = service.create_pairing(session.admin_token, "c1", now=clock.now)
    claimed = service.claim_slot(grant.code, identity("Codex", "openai", "gpt-5"), now=clock.now)

    with pytest.raises(ConflictError, match="session_not_running"):
        service.observe(claimed.controller_token)
    with pytest.raises(ConflictError, match="session_not_running"):
        service.submit_actions(claimed.controller_token, turn=0, actions=({"kind": "wait"},))


def test_controller_capability_cannot_administer_its_lobby(service: GameService, clock: Clock) -> None:
    """Catches a controller capability crossing into lobby administration."""
    session = service.create_session("orch", "basic-survival-v1", 17, 1)
    service.configure_slot(session.admin_token, "c1", "external")
    grant = service.create_pairing(session.admin_token, "c1", now=clock.now)
    claimed = service.claim_slot(grant.code, identity("Codex", "openai", "gpt-5"), now=clock.now)

    with pytest.raises(ForbiddenError, match="lobby administration"):
        service.configure_slot(claimed.controller_token, "c1", "human")
    with pytest.raises(ForbiddenError, match="lobby administration"):
        service.open_lobby(claimed.controller_token)
    with pytest.raises(ForbiddenError, match="lobby administration"):
        service.create_pairing(claimed.controller_token, "c1", now=clock.now)
    with pytest.raises(ForbiddenError, match="lobby administration"):
        service.lobby_status(claimed.controller_token, now=clock.now)


def test_admin_capability_cannot_submit_lobby_gameplay(service: GameService) -> None:
    """Catches an admin capability bypassing controller-only action submission."""
    session = service.create_session("orch", "basic-survival-v1", 17, 1)
    legacy = service.create_match("basic-survival-v1", seed=17, colony_count=1)

    with pytest.raises(ForbiddenError, match="admin capabilities cannot submit"):
        service.submit_actions(session.admin_token, turn=0, actions=({"kind": "wait"},))
    with pytest.raises(ForbiddenError, match="admin capabilities cannot submit"):
        service.submit_actions(legacy.admin_token, turn=0, actions=({"kind": "wait"},))
