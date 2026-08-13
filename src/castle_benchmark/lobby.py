from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


PAIRING_TTL_SECONDS = 600
PAIRING_MAX_ATTEMPTS = 5


_ADMIN_TOKEN_RESOLVERS: dict[str, Callable[[], str]] = {}


def register_admin_token_resolver(match_id: str, resolver: Callable[[], str]) -> None:
    """Register the process-local path to an admin capability without retaining it in a session."""
    _ADMIN_TOKEN_RESOLVERS[match_id] = resolver


def resolve_admin_token(match_id: str) -> str:
    return _ADMIN_TOKEN_RESOLVERS[match_id]()


class SessionStatus(str, Enum):
    DRAFT = "draft"
    LOBBY = "lobby"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ControllerType(str, Enum):
    HUMAN = "human"
    BASELINE = "baseline"
    EXTERNAL = "external"


class PresenceStatus(str, Enum):
    UNASSIGNED = "unassigned"
    READY = "ready"
    PAIRING = "pairing"
    CONNECTED = "connected"
    THINKING = "thinking"
    SUBMITTED = "submitted"
    TIMED_OUT = "timed_out"
    DISCONNECTED = "disconnected"
    TAKEN_OVER = "taken_over"


@dataclass(frozen=True, slots=True)
class ControllerIdentity:
    display_name: str
    provider: str
    model: str
    model_version: str | None = None
    adapter_name: str | None = None
    adapter_version: str | None = None
    connection_mode: str | None = None
    run_label: str | None = None

    def is_valid(self) -> bool:
        return all(
            isinstance(value, str) and bool(value.strip())
            for value in (self.display_name, self.provider, self.model)
        )


@dataclass(slots=True)
class ControllerSlot:
    colony_id: str
    controller_type: ControllerType
    controller_id: str | None = None
    identity: ControllerIdentity | None = None
    capability_digest: str | None = None
    pairing_digest: str | None = None
    pairing_expires_at: float | None = None
    pairing_consumed: bool = False
    generation: int = 0
    presence: PresenceStatus = PresenceStatus.UNASSIGNED
    baseline_kind: str | None = None
    pairing_attempts: int = 0


@dataclass(slots=True)
class LobbySession:
    match_id: str
    scenario_id: str
    seed: int
    colony_count: int
    admin_capability_digest: str
    status: SessionStatus = SessionStatus.DRAFT
    slots: list[ControllerSlot] = field(default_factory=list)

    @property
    def admin_token(self) -> str:
        """Compatibility handoff for callers; the raw secret remains in service authorization state."""
        return resolve_admin_token(self.match_id)


@dataclass(frozen=True, slots=True)
class PairingGrant:
    match_id: str
    colony_id: str
    code: str | None = None
    expires_at: float | None = None
    controller_token: str | None = None
