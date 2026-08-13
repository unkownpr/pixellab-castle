from __future__ import annotations

import secrets
import uuid
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from threading import RLock
from typing import Iterable

from .actions import ActionBatch, GameAction, WaitAction
from .agents import AGENT_TYPES
from .engine import DomainEvent, SimCore, TurnResult
from .metrics import MetricCollector
from .observation import Observation, project_observation
from .persistence import ArtifactWriter, action_from_dict
from .scenarios import OFFICIAL_SCENARIOS, get_scenario
from .lobby import (
    PAIRING_MAX_ATTEMPTS,
    PAIRING_TTL_SECONDS,
    DEFAULT_DEADLINE_SECONDS,
    ControllerIdentity,
    ControllerSlot,
    ControllerType,
    LobbySession,
    PairingGrant,
    PresenceStatus,
    SessionStatus,
    register_admin_token_resolver,
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


@dataclass(frozen=True, slots=True)
class ResolvedTurn:
    batches: tuple[ActionBatch, ...]
    action_controller_ids: dict[str, str | None]
    result: TurnResult


@dataclass(slots=True)
class LiveMatch:
    id: str
    sim: SimCore
    controller_tokens: dict[str, str]
    pending: dict[str, ActionBatch] = field(default_factory=dict)
    last_result: TurnResult | None = None
    metrics: MetricCollector | None = None
    usage: dict[str, dict[str, int]] = field(default_factory=dict)
    deadline_at: float | None = None
    deadline_seconds: int = DEFAULT_DEADLINE_SECONDS
    pending_controller_ids: dict[str, str | None] = field(default_factory=dict)
    operational_events: list[DomainEvent] = field(default_factory=list)
    tenures: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    tenure_usage: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)
    resolved_turns: list[ResolvedTurn] = field(default_factory=list)
    persisted_turn_count: int = 0
    turn_lock: object = field(default_factory=RLock)


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

    def _admin_token_for_match(self, match_id: str) -> str:
        for token, access in self._access.items():
            if access.match_id == match_id and access.admin:
                return token
        raise NotFoundError("admin capability no longer exists")

    def _assert_session_running(self, access: Access) -> None:
        session = self._lobbies.get(access.match_id)
        if session is not None and session.status is not SessionStatus.RUNNING:
            raise ConflictError("session_not_running", code="session_not_running")

    @staticmethod
    def _slot(session: LobbySession, colony_id: str) -> ControllerSlot:
        for slot in session.slots:
            if slot.colony_id == colony_id:
                return slot
        raise NotFoundError("colony does not exist")

    @staticmethod
    def _event_data(slot: ControllerSlot, now: float, **extra: object) -> dict[str, object]:
        return {
            "at": now,
            "controller_id": slot.controller_id,
            "generation": slot.generation,
            **extra,
        }

    def _record_controller_event(
        self, match: LiveMatch, kind: str, slot: ControllerSlot, now: float, **extra: object
    ) -> DomainEvent:
        event = DomainEvent(
            match.sim.state.turn,
            kind,
            slot.colony_id,
            self._event_data(slot, now, **extra),
        )
        match.operational_events.append(event)
        return event

    def _begin_tenure(self, match: LiveMatch, slot: ControllerSlot, now: float) -> None:
        if slot.controller_id is None:
            return
        history = match.tenures.setdefault(slot.colony_id, [])
        if (
            history
            and history[-1].get("ended_at") is None
            and history[-1].get("controller_id") == slot.controller_id
        ):
            return
        history.append(
            {
                "colony_id": slot.colony_id,
                "controller_id": slot.controller_id,
                "controller_type": slot.controller_type.value,
                "identity": asdict(slot.identity) if slot.identity is not None else None,
                "generation": slot.generation,
                "started_at": now,
                "ended_at": None,
            }
        )
        assert slot.controller_id is not None
        match.tenure_usage.setdefault(slot.colony_id, {}).setdefault(
            slot.controller_id, self._usage_defaults(include_presence=True)
        )

    @staticmethod
    def _end_tenure(match: LiveMatch, colony_id: str, now: float) -> None:
        history = match.tenures.get(colony_id, [])
        if history and history[-1].get("ended_at") is None:
            history[-1]["ended_at"] = now

    @staticmethod
    def _usage_defaults(include_presence: bool = False) -> dict[str, int]:
        values = {
            "model_calls": 0,
            "mcp_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_ms": 0,
        }
        if include_presence:
            values.update({"timeouts": 0, "reconnects": 0})
        return values

    def _tenure_usage(self, match: LiveMatch, slot: ControllerSlot) -> dict[str, int]:
        if slot.controller_id is None:
            raise UnauthorizedError("controller is no longer assigned")
        return match.tenure_usage.setdefault(slot.colony_id, {}).setdefault(
            slot.controller_id, self._usage_defaults(include_presence=True)
        )

    def _mint_controller_capability(
        self, match: LiveMatch, slot: ControllerSlot
    ) -> str:
        token = secrets.token_urlsafe(24)
        slot.capability_digest = self._secret_digest(token)
        self._access[token] = Access(match.id, slot.colony_id, False)
        return token

    def _submit_baseline_batches(self, match: LiveMatch, session: LobbySession) -> None:
        for slot in session.slots:
            if (
                slot.controller_type is not ControllerType.BASELINE
                or slot.colony_id in match.pending
            ):
                continue
            kind = slot.baseline_kind or "survivalist"
            try:
                factory = AGENT_TYPES[kind]
            except KeyError as exc:
                raise ServiceError("unknown baseline controller") from exc
            controller = factory(seed=match.sim.state.seed)
            batch = controller.decide(project_observation(match.sim.state, slot.colony_id))
            match.pending[slot.colony_id] = batch
            match.pending_controller_ids[slot.colony_id] = slot.controller_id

    def _resolve_pending(
        self,
        match: LiveMatch,
        session: LobbySession | None,
        application_events: tuple[DomainEvent, ...] = (),
        now: float | None = None,
    ) -> TurnResult:
        batches = tuple(match.pending[colony_id] for colony_id in sorted(match.pending))
        action_controller_ids = dict(match.pending_controller_ids)
        match.pending.clear()
        raw_result = match.sim.resolve(batches)
        assert match.metrics is not None
        match.metrics.record(raw_result)
        result = TurnResult(
            raw_result.state,
            application_events + raw_result.events,
            raw_result.action_results,
        )
        match.last_result = result
        match.resolved_turns.append(ResolvedTurn(batches, action_controller_ids, result))
        match.pending_controller_ids.clear()
        if session is not None:
            if match.sim.state.terminal:
                session.status = SessionStatus.COMPLETED
                match.deadline_at = None
            elif now is not None:
                match.deadline_at = now + match.deadline_seconds
            elif match.deadline_at is not None:
                match.deadline_at += match.deadline_seconds
            for slot in session.slots:
                if (
                    slot.controller_type is ControllerType.EXTERNAL
                    and slot.presence is PresenceStatus.SUBMITTED
                ):
                    slot.presence = PresenceStatus.THINKING
        return result

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
        match = LiveMatch(match_id, sim, {}, metrics=MetricCollector.create(sim.state))
        session = LobbySession(
            match_id=match_id,
            scenario_id=scenario_id,
            seed=seed,
            colony_count=colony_count,
            admin_capability_digest=self._secret_digest(admin_token),
            slots=[
                ControllerSlot(colony_id=colony_id, controller_type=ControllerType.EXTERNAL)
                for colony_id in sorted(sim.state.colonies)
            ],
        )
        self._matches[match_id] = match
        self._access[admin_token] = Access(match_id, None, True)
        register_admin_token_resolver(match_id, lambda: self._admin_token_for_match(match_id))
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
        slot.last_heartbeat_at = None
        slot.last_heartbeat_turn = None
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
            if session.status not in (
                SessionStatus.DRAFT,
                SessionStatus.LOBBY,
                SessionStatus.RUNNING,
            ):
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
            match = self._matches[match_id]
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

            slot.controller_id = uuid.uuid4().hex
            slot.identity = identity
            slot.pairing_consumed = True
            slot.generation += 1
            slot.presence = PresenceStatus.CONNECTED
            slot.last_heartbeat_at = None
            slot.last_heartbeat_turn = None
            controller_token = self._mint_controller_capability(match, slot)
            self._begin_tenure(match, slot, now)
            self._record_controller_event(match, "controller_claimed", slot, now)
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
                "last_heartbeat_at": slot.last_heartbeat_at,
                "last_heartbeat_turn": slot.last_heartbeat_turn,
            }

        return {
            "match_id": session.match_id,
            "scenario_id": session.scenario_id,
            "seed": session.seed,
            "colony_count": session.colony_count,
            "status": session.status.value,
            "slots": [serialize(slot) for slot in session.slots],
        }

    def heartbeat(
        self, controller_token: str, turn: int, status: PresenceStatus | str, now: float
    ) -> None:
        """Record controller-owned presence without making wall time part of SimCore."""
        access, match = self._authorize(controller_token)
        if access.admin or access.colony_id is None:
            raise ForbiddenError("admin capabilities cannot send controller heartbeats")
        session = self._lobbies.get(access.match_id)
        if session is None:
            raise ConflictError("session_not_running", code="session_not_running")
        if turn != match.sim.state.turn:
            raise ConflictError("stale_turn", code="stale_turn")
        try:
            presence = PresenceStatus(status)
        except ValueError as exc:
            raise ServiceError("unknown controller presence") from exc
        if presence not in {
            PresenceStatus.CONNECTED,
            PresenceStatus.THINKING,
            PresenceStatus.SUBMITTED,
            PresenceStatus.DISCONNECTED,
        }:
            raise ServiceError("invalid heartbeat presence")
        slot = self._slot(session, access.colony_id)
        if slot.controller_id is None:
            raise UnauthorizedError("controller is no longer assigned")
        was_disconnected = slot.presence in {PresenceStatus.DISCONNECTED, PresenceStatus.TIMED_OUT}
        slot.last_heartbeat_at = now
        slot.last_heartbeat_turn = turn
        slot.presence = presence
        if presence is PresenceStatus.DISCONNECTED:
            self._record_controller_event(match, "controller_disconnected", slot, now)
        elif was_disconnected:
            assert match.metrics is not None
            match.metrics.record_reconnect(slot.colony_id)
            self._tenure_usage(match, slot)["reconnects"] += 1
            self._record_controller_event(match, "controller_connected", slot, now, reconnect=True)

    def start_match(self, admin_token: str, now: float) -> LobbySession:
        session, match = self._lobby_for_admin(admin_token)
        if session.status not in {SessionStatus.DRAFT, SessionStatus.LOBBY}:
            raise ConflictError("invalid_session_status", code="invalid_session_status")
        unready = [
            slot.colony_id
            for slot in session.slots
            if not (
                slot.controller_type in {ControllerType.HUMAN, ControllerType.BASELINE}
                or (
                    slot.controller_type is ControllerType.EXTERNAL
                    and slot.controller_id is not None
                    and slot.last_heartbeat_at is not None
                    and slot.presence is not PresenceStatus.DISCONNECTED
                )
            )
        ]
        if unready:
            raise ConflictError("session_not_ready", code="session_not_ready")
        session.status = SessionStatus.RUNNING
        match.deadline_at = now + match.deadline_seconds
        for slot in session.slots:
            self._begin_tenure(match, slot, now)
            if slot.controller_type is ControllerType.EXTERNAL:
                slot.presence = PresenceStatus.THINKING
            elif slot.controller_type is ControllerType.HUMAN:
                self._mint_controller_capability(match, slot)
        return session

    def close_deadline(self, admin_token: str, now: float) -> TurnResult:
        session, match = self._lobby_for_admin(admin_token)
        with match.turn_lock:
            if session.status is not SessionStatus.RUNNING:
                raise ConflictError("session_not_running", code="session_not_running")
            if match.deadline_at is None or now < match.deadline_at:
                raise ConflictError("deadline_not_reached", code="deadline_not_reached")
            self._submit_baseline_batches(match, session)
            application_events: list[DomainEvent] = []
            for colony_id in sorted(match.sim.state.colonies):
                if colony_id in match.pending:
                    continue
                slot = self._slot(session, colony_id)
                match.pending[colony_id] = ActionBatch(
                    match.sim.state.turn, colony_id, (WaitAction(),)
                )
                match.pending_controller_ids[colony_id] = slot.controller_id
                if slot.controller_type is ControllerType.EXTERNAL:
                    slot.presence = PresenceStatus.TIMED_OUT
                    assert match.metrics is not None
                    match.metrics.record_timeout(colony_id)
                    self._tenure_usage(match, slot)["timeouts"] += 1
                    application_events.append(
                        self._record_controller_event(match, "controller_timed_out", slot, now)
                    )
            return self._resolve_pending(match, session, tuple(application_events), now)

    def replace_controller(
        self,
        admin_token: str,
        colony_id: str,
        replacement: ControllerType | str,
        now: float,
    ) -> ControllerSlot:
        """End the current tenure, revoke its capability, and install a takeover slot."""
        session, match = self._lobby_for_admin(admin_token)
        if session.status not in {SessionStatus.LOBBY, SessionStatus.RUNNING}:
            raise ConflictError("invalid_session_status", code="invalid_session_status")
        try:
            replacement_type = ControllerType(replacement)
        except ValueError as exc:
            raise ServiceError("unknown controller type") from exc
        slot = self._slot(session, colony_id)
        self._end_tenure(match, colony_id, now)
        for token, access in tuple(self._access.items()):
            if not access.admin and access.match_id == match.id and access.colony_id == colony_id:
                del self._access[token]
        slot.generation += 1
        slot.controller_type = replacement_type
        slot.baseline_kind = None
        slot.identity = None
        slot.capability_digest = None
        slot.pairing_digest = None
        slot.pairing_expires_at = None
        slot.pairing_consumed = False
        slot.pairing_attempts = 0
        slot.last_heartbeat_at = None
        slot.last_heartbeat_turn = None
        slot.controller_id = (
            uuid.uuid4().hex if replacement_type is not ControllerType.EXTERNAL else None
        )
        slot.presence = (
            PresenceStatus.TAKEN_OVER
            if replacement_type in {ControllerType.HUMAN, ControllerType.BASELINE}
            else PresenceStatus.UNASSIGNED
        )
        self._begin_tenure(match, slot, now)
        if replacement_type is ControllerType.HUMAN and session.status is SessionStatus.RUNNING:
            self._mint_controller_capability(match, slot)
        self._record_controller_event(
            match, "controller_replaced", slot, now, replacement_type=replacement_type.value
        )
        return slot

    def human_controller_token(self, admin_token: str, colony_id: str) -> str:
        """Admin-only handoff of the current locally controlled colony capability."""
        session, match = self._lobby_for_admin(admin_token)
        if session.status is not SessionStatus.RUNNING:
            raise ConflictError("session_not_running", code="session_not_running")
        slot = self._slot(session, colony_id)
        if slot.controller_type is not ControllerType.HUMAN:
            raise ConflictError("not_human_slot", code="not_human_slot")
        for token, access in self._access.items():
            if not access.admin and access.match_id == match.id and access.colony_id == colony_id:
                return token
        raise NotFoundError("human controller capability does not exist")

    def write_resolved_turns(self, admin_token: str, writer: ArtifactWriter) -> None:
        """Persist finalized action attribution without making it a replay input."""
        _, match = self._lobby_for_admin(admin_token)
        with match.turn_lock:
            writer.set_controller_tenures(
                [tenure for tenures in match.tenures.values() for tenure in tenures]
            )
            for resolved in match.resolved_turns[match.persisted_turn_count :]:
                writer.write_turn(
                    resolved.batches,
                    resolved.result,
                    action_controller_ids=resolved.action_controller_ids,
                )
            match.persisted_turn_count = len(match.resolved_turns)

    def operations_snapshot(self, admin_token: str, now: float) -> dict[str, object]:
        session, match = self._lobby_for_admin(admin_token)
        snapshot = self.lobby_status(admin_token, now)
        snapshot.update(
            {
                "turn": match.sim.state.turn,
                "deadline_at": match.deadline_at,
                "pending_colonies": tuple(sorted(match.pending)),
                "events": [
                    {
                        "turn": event.turn,
                        "kind": event.kind,
                        "colony_id": event.colony_id,
                        "data": event.data,
                    }
                    for event in match.operational_events
                ],
                "tenures": match.tenures,
            }
        )
        return snapshot

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
        match = LiveMatch(match_id, sim, tokens, metrics=MetricCollector.create(sim.state))
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
        self._assert_session_running(access)
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
        try:
            parsed = tuple(action_from_dict(dict(action)) for action in actions)
            batch = ActionBatch(turn, access.colony_id, parsed)  # type: ignore[arg-type]
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidActionError(str(exc)) from exc
        with match.turn_lock:
            access, match = self._authorize(token)
            self._assert_session_running(access)
            if turn != match.sim.state.turn:
                raise ConflictError(
                    f"expected turn {match.sim.state.turn}, received {turn}", code="stale_turn"
                )
            if access.colony_id in match.pending:
                raise ConflictError(
                    "controller already submitted this turn", code="duplicate_batch"
                )
            session = self._lobbies.get(access.match_id)
            if session is not None:
                self._submit_baseline_batches(match, session)
            match.pending[access.colony_id] = batch
            if session is not None:
                slot = self._slot(session, access.colony_id)
                slot.presence = PresenceStatus.SUBMITTED
                match.pending_controller_ids[access.colony_id] = slot.controller_id
            waiting = tuple(sorted(set(match.sim.state.colonies) - set(match.pending)))
            if waiting:
                return Submission("pending", match.sim.state.turn, waiting)
            result = self._resolve_pending(match, session)
            return Submission("resolved", match.sim.state.turn, (), result)

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
            self._usage_defaults(access.match_id in self._lobbies),
        )
        usage["model_calls"] += 1
        usage["input_tokens"] += input_tokens
        usage["output_tokens"] += output_tokens
        usage["latency_ms"] += latency_ms
        session = self._lobbies.get(access.match_id)
        if session is not None:
            slot = self._slot(session, access.colony_id)
            tenure_usage = self._tenure_usage(match, slot)
            tenure_usage["model_calls"] += 1
            tenure_usage["input_tokens"] += input_tokens
            tenure_usage["output_tokens"] += output_tokens
            tenure_usage["latency_ms"] += latency_ms
        return dict(usage)

    def record_mcp_call(self, token: str) -> None:
        access, match = self._authorize(token)
        if access.admin or access.colony_id is None:
            return
        usage = match.usage.setdefault(
            access.colony_id,
            self._usage_defaults(access.match_id in self._lobbies),
        )
        usage["mcp_calls"] += 1
        session = self._lobbies.get(access.match_id)
        if session is not None:
            slot = self._slot(session, access.colony_id)
            self._tenure_usage(match, slot)["mcp_calls"] += 1

    def run_report(self, token: str) -> dict[str, object]:
        access, match = self._authorize(token)
        if not access.admin:
            raise ForbiddenError("run reports require an admin capability")
        assert match.metrics is not None
        metrics = match.metrics.report(match.sim.state)
        cost = metrics["cost"]
        assert isinstance(cost, dict)
        session = self._lobbies.get(access.match_id)
        for colony_id in sorted(match.sim.state.colonies):
            usage = dict(match.usage.get(colony_id, self._usage_defaults(session is not None)))
            if session is not None:
                usage["timeouts"] = match.metrics.timeouts.get(colony_id, 0)
                usage["reconnects"] = match.metrics.reconnects.get(colony_id, 0)
            cost[colony_id] = usage
        if session is not None:
            metrics["presence"] = {
                "timeouts": {
                    colony_id: match.metrics.timeouts.get(colony_id, 0)
                    for colony_id in sorted(match.sim.state.colonies)
                },
                "reconnects": {
                    colony_id: match.metrics.reconnects.get(colony_id, 0)
                    for colony_id in sorted(match.sim.state.colonies)
                },
                "tenures": match.tenures,
            }
            metrics["server_measured"] = {
                "mcp_calls": {
                    colony_id: cost[colony_id]["mcp_calls"]
                    for colony_id in sorted(match.sim.state.colonies)
                }
            }
            metrics["adapter_reported_model_usage"] = {
                colony_id: {
                    key: cost[colony_id][key]
                    for key in ("model_calls", "input_tokens", "output_tokens", "latency_ms")
                }
                for colony_id in sorted(match.sim.state.colonies)
            }
            metrics["tenure_metrics"] = {
                colony_id: [
                    {
                        **tenure,
                        "server_measured": {
                            key: match.tenure_usage[colony_id][str(tenure["controller_id"])][
                                key
                            ]
                            for key in ("mcp_calls", "timeouts", "reconnects")
                        },
                        "adapter_reported_model_usage": {
                            key: match.tenure_usage[colony_id][str(tenure["controller_id"])][
                                key
                            ]
                            for key in (
                                "model_calls",
                                "input_tokens",
                                "output_tokens",
                                "latency_ms",
                            )
                        },
                    }
                    for tenure in match.tenures.get(colony_id, [])
                ]
                for colony_id in sorted(match.sim.state.colonies)
            }
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
