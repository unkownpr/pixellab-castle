from __future__ import annotations

import secrets
import uuid
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from threading import RLock
from typing import Iterable

from .actions import ActionBatch, GameAction
from .engine import SimCore, TurnResult
from .metrics import MetricCollector
from .observation import Observation, project_observation
from .persistence import action_from_dict
from .scenarios import OFFICIAL_SCENARIOS, get_scenario
from .lobby import (
    PAIRING_MAX_ATTEMPTS,
    PAIRING_TTL_SECONDS,
    ControllerIdentity,
    ControllerSlot,
    ControllerType,
    LobbySession,
    PairingGrant,
    PresenceStatus,
    SessionStatus,
)


class ServiceError(Exception):
    code = "service_error"
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class UnauthorizedError(ServiceError):
    code = "unauthorized"
    status_code = 401


class ForbiddenError(ServiceError):
    code = "forbidden"
    status_code = 403


class NotFoundError(ServiceError):
    code = "not_found"
    status_code = 404


class ConflictError(ServiceError):
    code = "conflict"
    status_code = 409

    def __init__(self, message: str, code: str = "conflict"):
        super().__init__(message)
        self.code = code


class InvalidActionError(ServiceError):
    code = "invalid_action"
    status_code = 422


@dataclass(frozen=True, slots=True)
class CreatedMatch:
    match_id: str
    scenario_id: str
    controller_tokens: dict[str, str]
    admin_token: str


@dataclass(frozen=True, slots=True)
class Submission:
    status: str
    turn: int
    waiting_for: tuple[str, ...] = ()
    result: TurnResult | None = None


@dataclass(slots=True)
class LiveMatch:
    id: str
    sim: SimCore
    controller_tokens: dict[str, str]
    admin_token: str
    pending: dict[str, ActionBatch] = field(default_factory=dict)
    last_result: TurnResult | None = None
    metrics: MetricCollector | None = None
    usage: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Access:
    match_id: str
    colony_id: str | None
    admin: bool


class GameService:
    def __init__(self) -> None:
        self._matches: dict[str, LiveMatch] = {}
        self._access: dict[str, Access] = {}
        self._lobbies: dict[str, LobbySession] = {}
        self._pairings: dict[str, tuple[str, str]] = {}
        self._lobby_lock = RLock()

    @staticmethod
    def _secret_digest(secret: str) -> str:
        return sha256(secret.encode()).hexdigest()

    def _lobby_for_admin(self, admin_token: str) -> tuple[LobbySession, LiveMatch]:
        access, match = self._authorize(admin_token)
        if not access.admin:
            raise ForbiddenError("lobby administration requires an admin capability")
        try:
            return self._lobbies[access.match_id], match
        except KeyError as exc:
            raise NotFoundError("lobby session does not exist") from exc

    @staticmethod
    def _slot(session: LobbySession, colony_id: str) -> ControllerSlot:
        for slot in session.slots:
            if slot.colony_id == colony_id:
                return slot
        raise NotFoundError("colony does not exist")

    def create_session(
        self, orchestrator_token: str, scenario_id: str, seed: int, colony_count: int
    ) -> LobbySession:
        """Create a pre-match session whose controller capabilities are not yet minted."""
        if not orchestrator_token:
            raise UnauthorizedError("orchestrator capability is required")
        try:
            scenario = get_scenario(scenario_id)
            sim = SimCore.create(scenario, seed, colony_count)
        except (KeyError, ValueError) as exc:
            raise ServiceError(str(exc)) from exc

        match_id = uuid.uuid4().hex
        admin_token = secrets.token_urlsafe(24)
        match = LiveMatch(match_id, sim, {}, admin_token, metrics=MetricCollector.create(sim.state))
        session = LobbySession(
            match_id=match_id,
            scenario_id=scenario_id,
            seed=seed,
            colony_count=colony_count,
            admin_token=admin_token,
            slots=[
                ControllerSlot(colony_id=colony_id, controller_type=ControllerType.EXTERNAL)
                for colony_id in sorted(sim.state.colonies)
            ],
        )
        self._matches[match_id] = match
        self._access[admin_token] = Access(match_id, None, True)
        self._lobbies[match_id] = session
        return session

    def configure_slot(
        self,
        admin_token: str,
        colony_id: str,
        controller_type: ControllerType | str,
        baseline_kind: str | None = None,
    ) -> ControllerSlot:
        session, _ = self._lobby_for_admin(admin_token)
        if session.status is not SessionStatus.DRAFT:
            raise ForbiddenError("lobby configuration is frozen")
        try:
            configured_type = ControllerType(controller_type)
        except (TypeError, ValueError) as exc:
            raise ServiceError("unknown controller type") from exc
        if configured_type is not ControllerType.BASELINE and baseline_kind is not None:
            raise ServiceError("baseline kind requires a baseline controller")

        slot = self._slot(session, colony_id)
        if slot.pairing_digest is not None or slot.capability_digest is not None:
            raise ConflictError("slot has active pairing state", code="slot_configured")
        slot.controller_type = configured_type
        slot.baseline_kind = baseline_kind
        slot.controller_id = uuid.uuid4().hex if configured_type is not ControllerType.EXTERNAL else None
        slot.identity = None
        slot.capability_digest = None
        slot.pairing_digest = None
        slot.pairing_expires_at = None
        slot.pairing_consumed = False
        slot.pairing_attempts = 0
        slot.presence = (
            PresenceStatus.READY
            if configured_type in (ControllerType.HUMAN, ControllerType.BASELINE)
            else PresenceStatus.UNASSIGNED
        )
        return slot

    def open_lobby(self, admin_token: str) -> LobbySession:
        session, _ = self._lobby_for_admin(admin_token)
        if session.status is not SessionStatus.DRAFT:
            raise ConflictError("session is not a draft", code="invalid_session_status")
        session.status = SessionStatus.LOBBY
        return session

    def create_pairing(self, admin_token: str, colony_id: str, now: float) -> PairingGrant:
        with self._lobby_lock:
            session, _ = self._lobby_for_admin(admin_token)
            if session.status not in (SessionStatus.DRAFT, SessionStatus.LOBBY):
                raise ConflictError("pairing is unavailable for this session", code="invalid_session_status")
            slot = self._slot(session, colony_id)
            if slot.controller_type is not ControllerType.EXTERNAL:
                raise ConflictError("pairing requires an external controller", code="not_external_slot")
            if slot.pairing_consumed:
                raise ConflictError("slot is already claimed", code="slot_claimed")

            code = secrets.token_urlsafe(24)
            digest = self._secret_digest(code)
            slot.pairing_digest = digest
            slot.pairing_expires_at = now + PAIRING_TTL_SECONDS
            slot.pairing_consumed = False
            slot.pairing_attempts = 0
            slot.presence = PresenceStatus.PAIRING
            self._pairings[digest] = (session.match_id, colony_id)
            return PairingGrant(session.match_id, colony_id, code=code, expires_at=slot.pairing_expires_at)

    def claim_slot(self, code: str, identity: ControllerIdentity, now: float) -> PairingGrant:
        digest = self._secret_digest(code)
        with self._lobby_lock:
            target = self._pairings.get(digest)
            if target is None:
                raise UnauthorizedError("invalid pairing code")
            match_id, colony_id = target
            session = self._lobbies[match_id]
            slot = self._slot(session, colony_id)
            if slot.pairing_digest is None or not secrets.compare_digest(slot.pairing_digest, digest):
                raise UnauthorizedError("invalid pairing code")
            if slot.pairing_consumed:
                raise ConflictError("pairing_consumed", code="pairing_consumed")
            if slot.pairing_expires_at is None or now >= slot.pairing_expires_at:
                raise ConflictError("pairing_expired", code="pairing_expired")
            if slot.pairing_attempts >= PAIRING_MAX_ATTEMPTS:
                raise ConflictError("pairing_attempt_limit", code="pairing_attempt_limit")
            if not isinstance(identity, ControllerIdentity) or not identity.is_valid():
                slot.pairing_attempts += 1
                raise ServiceError("invalid controller identity")

            controller_token = secrets.token_urlsafe(24)
            slot.controller_id = uuid.uuid4().hex
            slot.identity = identity
            slot.capability_digest = self._secret_digest(controller_token)
            slot.pairing_consumed = True
            slot.generation += 1
            slot.presence = PresenceStatus.CONNECTED
            self._access[controller_token] = Access(match_id, colony_id, False)
            return PairingGrant(match_id, colony_id, controller_token=controller_token)

    def lobby_status(self, admin_token: str, now: float) -> dict[str, object]:
        session, _ = self._lobby_for_admin(admin_token)

        def serialize(slot: ControllerSlot) -> dict[str, object]:
            pairing_active = (
                slot.pairing_digest is not None
                and not slot.pairing_consumed
                and slot.pairing_expires_at is not None
                and now < slot.pairing_expires_at
            )
            return {
                "colony_id": slot.colony_id,
                "controller_type": slot.controller_type.value,
                "controller_id": slot.controller_id,
                "identity": asdict(slot.identity) if slot.identity is not None else None,
                "presence": slot.presence.value,
                "baseline_kind": slot.baseline_kind,
                "generation": slot.generation,
                "pairing_active": pairing_active,
                "pairing_expires_at": slot.pairing_expires_at,
                "pairing_consumed": slot.pairing_consumed,
                "pairing_attempts": slot.pairing_attempts,
            }

        return {
            "match_id": session.match_id,
            "scenario_id": session.scenario_id,
            "seed": session.seed,
            "colony_count": session.colony_count,
            "status": session.status.value,
            "slots": [serialize(slot) for slot in session.slots],
        }

    def list_scenarios(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "id": scenario.id,
                "name": scenario.name,
                "biome": scenario.biome,
                "width": scenario.width,
                "height": scenario.height,
                "max_turns": scenario.max_turns,
                "max_colonies": len(scenario.spawn_points),
            }
            for scenario in OFFICIAL_SCENARIOS
        )

    def create_match(self, scenario_id: str, seed: int, colony_count: int) -> CreatedMatch:
        try:
            scenario = get_scenario(scenario_id)
            sim = SimCore.create(scenario, seed, colony_count)
        except (KeyError, ValueError) as exc:
            raise ServiceError(str(exc)) from exc
        match_id = uuid.uuid4().hex
        tokens = {colony_id: secrets.token_urlsafe(24) for colony_id in sim.state.colonies}
        admin_token = secrets.token_urlsafe(24)
        match = LiveMatch(match_id, sim, tokens, admin_token, metrics=MetricCollector.create(sim.state))
        self._matches[match_id] = match
        for colony_id, token in tokens.items():
            self._access[token] = Access(match_id, colony_id, False)
        self._access[admin_token] = Access(match_id, None, True)
        return CreatedMatch(match_id, scenario_id, tokens, admin_token)

    def _authorize(self, token: str) -> tuple[Access, LiveMatch]:
        access = self._access.get(token)
        if access is None:
            raise UnauthorizedError("invalid controller capability")
        match = self._matches.get(access.match_id)
        if match is None:
            raise NotFoundError("match no longer exists")
        return access, match

    def assert_match(self, token: str, match_id: str) -> None:
        access, _ = self._authorize(token)
        if access.match_id != match_id:
            raise ForbiddenError("capability is scoped to a different match")

    def observe(self, token: str, requested_colony_id: str | None = None) -> Observation:
        access, match = self._authorize(token)
        if access.admin:
            colony_id = requested_colony_id or sorted(match.sim.state.colonies)[0]
        else:
            colony_id = access.colony_id
            if requested_colony_id is not None and requested_colony_id != colony_id:
                raise ForbiddenError("controller cannot observe another colony")
        assert colony_id is not None
        return project_observation(match.sim.state, colony_id)

    def submit_actions(
        self, token: str, turn: int, actions: Iterable[dict[str, object]]
    ) -> Submission:
        access, match = self._authorize(token)
        if access.admin or access.colony_id is None:
            raise ForbiddenError("admin capabilities cannot submit colony actions")
        if turn != match.sim.state.turn:
            raise ConflictError(
                f"expected turn {match.sim.state.turn}, received {turn}", code="stale_turn"
            )
        if access.colony_id in match.pending:
            raise ConflictError("controller already submitted this turn", code="duplicate_batch")
        try:
            parsed = tuple(action_from_dict(dict(action)) for action in actions)
            batch = ActionBatch(turn, access.colony_id, parsed)  # type: ignore[arg-type]
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidActionError(str(exc)) from exc
        match.pending[access.colony_id] = batch
        waiting = tuple(sorted(set(match.sim.state.colonies) - set(match.pending)))
        if waiting:
            return Submission("pending", match.sim.state.turn, waiting)
        batches = tuple(match.pending[colony_id] for colony_id in sorted(match.pending))
        match.pending.clear()
        match.last_result = match.sim.resolve(batches)
        assert match.metrics is not None
        match.metrics.record(match.last_result)
        return Submission("resolved", match.sim.state.turn, (), match.last_result)

    def match_status(self, token: str) -> dict[str, object]:
        access, match = self._authorize(token)
        return {
            "match_id": match.id,
            "scenario_id": match.sim.state.scenario_id,
            "turn": match.sim.state.turn,
            "terminal": match.sim.state.terminal,
            "termination_reason": match.sim.state.termination_reason,
            "pending_colonies": tuple(sorted(match.pending)),
            "scope": "admin" if access.admin else access.colony_id,
        }

    def last_events(self, token: str) -> tuple[dict[str, object], ...]:
        _, match = self._authorize(token)
        if match.last_result is None:
            return ()
        return tuple(asdict(event) for event in match.last_result.events)

    def record_usage(
        self,
        token: str,
        *,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
    ) -> dict[str, int]:
        access, match = self._authorize(token)
        if access.admin or access.colony_id is None:
            raise ForbiddenError("admin capabilities cannot record controller usage")
        if min(input_tokens, output_tokens, latency_ms) < 0:
            raise ServiceError("usage values must be non-negative")
        usage = match.usage.setdefault(
            access.colony_id,
            {"model_calls": 0, "mcp_calls": 0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0},
        )
        usage["model_calls"] += 1
        usage["input_tokens"] += input_tokens
        usage["output_tokens"] += output_tokens
        usage["latency_ms"] += latency_ms
        return dict(usage)

    def record_mcp_call(self, token: str) -> None:
        access, match = self._authorize(token)
        if access.admin or access.colony_id is None:
            return
        usage = match.usage.setdefault(
            access.colony_id,
            {"model_calls": 0, "mcp_calls": 0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0},
        )
        usage["mcp_calls"] += 1

    def run_report(self, token: str) -> dict[str, object]:
        access, match = self._authorize(token)
        if not access.admin:
            raise ForbiddenError("run reports require an admin capability")
        assert match.metrics is not None
        metrics = match.metrics.report(match.sim.state)
        cost = metrics["cost"]
        assert isinstance(cost, dict)
        for colony_id in sorted(match.sim.state.colonies):
            cost[colony_id] = dict(
                match.usage.get(
                    colony_id,
                    {"model_calls": 0, "mcp_calls": 0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0},
                )
            )
        return {
            "status": self.match_status(token),
            "metrics": metrics,
            "latest_events": self.last_events(token),
        }

    def join_match(self, admin_token: str, colony_id: str) -> str:
        access, match = self._authorize(admin_token)
        if not access.admin:
            raise ForbiddenError("joining controllers requires an admin capability")
        try:
            return match.controller_tokens[colony_id]
        except KeyError as exc:
            raise NotFoundError("colony does not exist") from exc
