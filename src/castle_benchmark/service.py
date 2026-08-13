from __future__ import annotations

import secrets
import uuid
from dataclasses import asdict, dataclass, field
from typing import Iterable

from .actions import ActionBatch, GameAction
from .engine import SimCore, TurnResult
from .observation import Observation, project_observation
from .persistence import action_from_dict
from .scenarios import OFFICIAL_SCENARIOS, get_scenario


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


@dataclass(frozen=True, slots=True)
class Access:
    match_id: str
    colony_id: str | None
    admin: bool


class GameService:
    def __init__(self) -> None:
        self._matches: dict[str, LiveMatch] = {}
        self._access: dict[str, Access] = {}

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
        match = LiveMatch(match_id, sim, tokens, admin_token)
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

