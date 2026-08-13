from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import secrets
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from hashlib import sha256
from threading import RLock

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .lobby import ControllerIdentity
from .schemas import (
    MAX_PAYLOAD_BYTES,
    SCHEMA_VERSION,
    ADMIN_WEBSOCKET_MESSAGE_ADAPTER,
    ClaimSlotRequest,
    ClaimSlotResponse,
    ConfigureSlotRequest,
    CreateMatchRequest,
    CreateMatchResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    HumanControllerCapabilityResponse,
    LobbySnapshotResponse,
    MatchStatusResponse,
    MutationResponse,
    OperationsSnapshotResponse,
    OperationsWebSocketTicketResponse,
    PairingGrantResponse,
    ReplaceControllerRequest,
    ReplacementResponse,
    RunReportResponse,
    SlotConfigurationResponse,
    SubmissionResponse,
    SubmitActionsRequest,
    project_lobby_snapshot,
    project_match_status,
    project_run_report,
)
from .service import GameService, ServiceError, UnauthorizedError


class RequestBodyLimitMiddleware:
    """Reject oversized API bodies while reading at most one chunk past the limit."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "detail": {
                    "code": "payload_too_large",
                    "message": "request payload exceeds 16 KiB",
                }
            },
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or not scope.get("path", "").startswith("/api/")
            or scope.get("method") not in {"POST", "PUT", "PATCH"}
        ):
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                await self._reject(scope, receive, send)
                return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                await self.app(scope, receive, send)
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_bytes:
                await self._reject(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if replayed:
                return {"type": "http.disconnect"}
            replayed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay_receive, send)


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedError("Bearer capability is required")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise UnauthorizedError("Bearer capability is required")
    return token


def _versioned(payload: dict[str, object]) -> dict[str, object]:
    return {**payload, "schema_version": SCHEMA_VERSION}


def _websocket_message(message_type: str, payload: object) -> dict[str, object]:
    message = ADMIN_WEBSOCKET_MESSAGE_ADAPTER.validate_python(
        {"type": message_type, "payload": payload}
    )
    return message.model_dump(mode="json")


def _assert_secret_free(payload: object) -> None:
    """Fail closed if a sanitized adapter projection ever grows a secret field."""
    forbidden = {
        "admin_token",
        "controller_token",
        "orchestrator_token",
        "pairing_code",
        "admin_capability_digest",
        "capability_digest",
        "pairing_digest",
    }
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized_key = str(key).lower()
            if (
                normalized_key in forbidden
                or normalized_key.endswith(("_token", "_digest", "_secret"))
            ):
                raise ServiceError("unsafe response projection")
            _assert_secret_free(value)
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            _assert_secret_free(value)


def create_app(
    service: GameService | None = None,
    static_dir: str | Path | None = None,
    *,
    orchestrator_token: str | None = None,
    allowed_origins: Sequence[str] = (),
    trusted_proxies: Sequence[str] = (),
    remote: bool = False,
    clock: Callable[[], float] = time.time,
) -> FastAPI:
    origins = tuple(allowed_origins)
    try:
        trusted_proxy_networks = tuple(
            ipaddress.ip_network(value) for value in trusted_proxies
        )
    except ValueError as exc:
        raise ValueError("trusted proxy must be an explicit IP network") from exc
    if any("*" in origin for origin in origins):
        raise ValueError("wildcard credential origins are not allowed")
    game = service or GameService()
    required_orchestrator_token = (
        orchestrator_token or os.environ.get("CASTLE_BENCHMARK_ORCHESTRATOR_TOKEN")
    )
    if remote:
        if not required_orchestrator_token or len(required_orchestrator_token) < 32:
            raise ValueError("remote serving requires a high-entropy orchestrator capability")
        if not origins:
            raise ValueError("remote serving requires at least one explicit allowed origin")
    app = FastAPI(title="PixelLab Castle Benchmark", version="0.1.0")
    websocket_tickets: dict[str, tuple[str, float, str]] = {}
    websocket_ticket_lock = RLock()

    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["Authorization", "Content-Type"],
        )
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=MAX_PAYLOAD_BYTES)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "invalid_request",
                    "message": "request validation failed",
                }
            },
        )

    @app.exception_handler(ServiceError)
    async def service_error_handler(_request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": {"code": exc.code, "message": exc.message}},
        )

    def authorize_orchestrator(authorization: str | None) -> str:
        supplied = _bearer(authorization)
        if not required_orchestrator_token or not secrets.compare_digest(
            supplied, required_orchestrator_token
        ):
            raise UnauthorizedError("orchestrator capability required")
        return supplied

    def assert_scoped(token: str, match_id: str) -> None:
        game.assert_match(token, match_id)

    def request_peer(request: Request) -> str:
        direct_peer = request.client.host if request.client is not None else "unknown"
        try:
            direct_ip = ipaddress.ip_address(direct_peer)
        except ValueError:
            return direct_peer
        if not any(direct_ip in network for network in trusted_proxy_networks):
            return direct_peer
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            return direct_peer

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/scenarios")
    def scenarios() -> tuple[dict[str, object], ...]:
        return game.list_scenarios()

    def create_match(request: CreateMatchRequest, response: Response) -> CreateMatchResponse:
        response.headers["Cache-Control"] = "no-store"
        return CreateMatchResponse(
            **asdict(game.create_match(request.scenario_id, request.seed, request.colony_count))
        )

    if not remote:
        app.post("/api/matches", status_code=201, response_model=CreateMatchResponse)(
            create_match
        )

    @app.post("/api/sessions", status_code=201, response_model=CreateSessionResponse)
    def create_session(
        request: CreateSessionRequest,
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> CreateSessionResponse:
        response.headers["Cache-Control"] = "no-store"
        supplied = authorize_orchestrator(authorization)
        session = game.create_session(
            supplied,
            request.scenario_id,
            request.seed,
            request.colony_count,
            request.deadline_seconds,
            (
                (slot.colony_id, slot.controller_type, slot.baseline_kind)
                for slot in request.slots
            ),
        )
        return CreateSessionResponse(
            match_id=session.match_id,
            scenario_id=session.scenario_id,
            status="draft",
            admin_token=session.admin_token,
        )

    @app.get(
        "/api/sessions/{match_id}/lobby", response_model=LobbySnapshotResponse
    )
    def lobby_status(
        match_id: str, authorization: str | None = Header(default=None)
    ) -> LobbySnapshotResponse:
        token = _bearer(authorization)
        assert_scoped(token, match_id)
        snapshot = game.lobby_status(token, clock())
        _assert_secret_free(snapshot)
        return project_lobby_snapshot(snapshot)

    @app.post(
        "/api/sessions/{match_id}/slots/{colony_id}",
        response_model=SlotConfigurationResponse,
    )
    def configure_slot(
        match_id: str,
        colony_id: str,
        request: ConfigureSlotRequest,
        authorization: str | None = Header(default=None),
    ) -> SlotConfigurationResponse:
        token = _bearer(authorization)
        assert_scoped(token, match_id)
        slot = game.configure_slot(
            token, colony_id, request.controller_type, request.baseline_kind
        )
        return SlotConfigurationResponse(
            match_id=match_id,
            colony_id=slot.colony_id,
            controller_type=slot.controller_type.value,
            presence=slot.presence.value,
        )

    @app.post(
        "/api/sessions/{match_id}/slots/{colony_id}/pairing",
        response_model=PairingGrantResponse,
    )
    def create_pairing(
        match_id: str,
        colony_id: str,
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> PairingGrantResponse:
        response.headers["Cache-Control"] = "no-store"
        token = _bearer(authorization)
        assert_scoped(token, match_id)
        grant = game.create_pairing(token, colony_id, clock())
        assert grant.code is not None and grant.expires_at is not None
        return PairingGrantResponse(
            match_id=grant.match_id,
            colony_id=grant.colony_id,
            pairing_code=grant.code,
            expires_at=grant.expires_at,
        )

    @app.post("/api/pairings/claim", response_model=ClaimSlotResponse)
    def claim_slot(
        request: ClaimSlotRequest, http_request: Request, response: Response
    ) -> ClaimSlotResponse:
        response.headers["Cache-Control"] = "no-store"
        peer = request_peer(http_request)
        game.reserve_pairing_attempt(peer, request.pairing_code, clock())
        identity = ControllerIdentity(**request.identity.model_dump())
        try:
            claimed = game.claim_slot_contract(request.pairing_code, identity, clock())
        except ServiceError:
            raise
        game.clear_pairing_rate(peer, request.pairing_code)
        return ClaimSlotResponse(**claimed)

    @app.post(
        "/api/sessions/{match_id}/heartbeat", response_model=HeartbeatResponse
    )
    def heartbeat(
        match_id: str,
        request: HeartbeatRequest,
        authorization: str | None = Header(default=None),
    ) -> HeartbeatResponse:
        token = _bearer(authorization)
        assert_scoped(token, match_id)
        receipt = game.heartbeat(token, request.turn, request.status, clock())
        return HeartbeatResponse(match_id=receipt.match_id, status=receipt.status)

    @app.post("/api/sessions/{match_id}/start", response_model=MutationResponse)
    def start_match(
        match_id: str, authorization: str | None = Header(default=None)
    ) -> MutationResponse:
        token = _bearer(authorization)
        assert_scoped(token, match_id)
        session = game.start_match(token, clock())
        return MutationResponse(match_id=match_id, status=session.status.value)

    @app.post(
        "/api/sessions/{match_id}/slots/{colony_id}/human-capability",
        response_model=HumanControllerCapabilityResponse,
    )
    def human_controller_capability(
        match_id: str,
        colony_id: str,
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> HumanControllerCapabilityResponse:
        response.headers["Cache-Control"] = "no-store"
        token = _bearer(authorization)
        assert_scoped(token, match_id)
        return HumanControllerCapabilityResponse(
            match_id=match_id,
            colony_id=colony_id,
            controller_token=game.human_controller_token(token, colony_id),
        )

    @app.post(
        "/api/sessions/{match_id}/slots/{colony_id}/replace",
        response_model=ReplacementResponse,
    )
    def replace_controller(
        match_id: str,
        colony_id: str,
        request: ReplaceControllerRequest,
        authorization: str | None = Header(default=None),
    ) -> ReplacementResponse:
        token = _bearer(authorization)
        assert_scoped(token, match_id)
        slot = game.replace_controller(
            token,
            colony_id,
            request.replacement,
            clock(),
            request.baseline_kind,
        )
        return ReplacementResponse(
            match_id=match_id, colony_id=colony_id, status=slot.presence.value
        )

    @app.get(
        "/api/matches/{match_id}/operations", response_model=OperationsSnapshotResponse
    )
    def operations(
        match_id: str, authorization: str | None = Header(default=None)
    ) -> OperationsSnapshotResponse:
        token = _bearer(authorization)
        assert_scoped(token, match_id)
        snapshot = game.operations_snapshot(token, clock())
        _assert_secret_free(snapshot)
        return OperationsSnapshotResponse(**_versioned(snapshot))

    @app.post(
        "/api/matches/{match_id}/operations/ticket",
        response_model=OperationsWebSocketTicketResponse,
    )
    def operations_ticket(
        match_id: str,
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> OperationsWebSocketTicketResponse:
        response.headers["Cache-Control"] = "no-store"
        token = _bearer(authorization)
        assert_scoped(token, match_id)
        game.operations_snapshot(token, clock())
        ticket = secrets.token_urlsafe(24)
        expires_at = clock() + 30.0
        digest = sha256(ticket.encode()).hexdigest()
        with websocket_ticket_lock:
            for old_digest, (_, old_expiry, _) in tuple(websocket_tickets.items()):
                if old_expiry <= clock():
                    del websocket_tickets[old_digest]
            while len(websocket_tickets) >= 1024:
                oldest = min(
                    websocket_tickets,
                    key=lambda value: websocket_tickets[value][1],
                )
                del websocket_tickets[oldest]
            websocket_tickets[digest] = (match_id, expires_at, token)
        return OperationsWebSocketTicketResponse(
            match_id=match_id,
            websocket_ticket=ticket,
            expires_at=expires_at,
        )

    @app.get("/api/matches/{match_id}/report", response_model=RunReportResponse)
    def report(
        match_id: str, authorization: str | None = Header(default=None)
    ) -> RunReportResponse:
        token = _bearer(authorization)
        assert_scoped(token, match_id)
        payload = game.run_report(token)
        _assert_secret_free(payload)
        return project_run_report(payload)

    @app.get("/api/matches/{match_id}/observation")
    def observation(
        match_id: str,
        colony_id: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        token = _bearer(authorization)
        assert_scoped(token, match_id)
        return _versioned(asdict(game.observe(token, colony_id)))

    @app.post("/api/matches/{match_id}/actions", response_model=SubmissionResponse)
    def submit(
        match_id: str,
        request: SubmitActionsRequest,
        authorization: str | None = Header(default=None),
    ) -> SubmissionResponse:
        token = _bearer(authorization)
        assert_scoped(token, match_id)
        submission = game.submit_actions(token, request.turn, request.actions)
        return SubmissionResponse(
            status=submission.status,  # type: ignore[arg-type]
            turn=submission.turn,
            waiting_for=submission.waiting_for,
            events=tuple(asdict(event) for event in submission.events),
        )

    @app.get("/api/matches/{match_id}/status", response_model=MatchStatusResponse)
    def status(
        match_id: str, authorization: str | None = Header(default=None)
    ) -> MatchStatusResponse:
        token = _bearer(authorization)
        assert_scoped(token, match_id)
        payload = game.match_status(token)
        _assert_secret_free(payload)
        return project_match_status(payload)

    @app.websocket("/api/matches/{match_id}/operations/ws")
    async def operations_live(websocket: WebSocket, match_id: str) -> None:
        try:
            offered_subprotocols = tuple(websocket.scope.get("subprotocols", ()))
            ticket_protocol = (
                len(offered_subprotocols) == 2
                and offered_subprotocols[0] == "castle.operations"
            )
            origin = websocket.headers.get("origin")
            if origins and origin not in origins:
                raise UnauthorizedError("WebSocket origin is not allowed")
            if ticket_protocol:
                digest = sha256(offered_subprotocols[1].encode()).hexdigest()
                with websocket_ticket_lock:
                    ticket_data = websocket_tickets.pop(digest, None)
                if (
                    ticket_data is None
                    or ticket_data[0] != match_id
                    or clock() >= ticket_data[1]
                ):
                    raise UnauthorizedError("invalid WebSocket ticket")
                token = ticket_data[2]
            elif not remote:
                token = _bearer(websocket.headers.get("authorization"))
            else:
                raise UnauthorizedError("WebSocket ticket required")
            assert_scoped(token, match_id)
            previous = game.operations_snapshot(token, clock())
            _assert_secret_free(previous)
            await websocket.accept(
                subprotocol="castle.operations" if ticket_protocol else None
            )
            await websocket.send_json(_websocket_message("lobby.snapshot", previous))
            last_sequence = max(
                (int(event["sequence"]) for event in previous["events"]),  # type: ignore[index]
                default=0,
            )
            while True:
                try:
                    raw = await asyncio.wait_for(
                        websocket.receive_text(), timeout=0.25
                    )
                except TimeoutError:
                    raw = None
                if raw is not None:
                    if len(raw.encode()) > MAX_PAYLOAD_BYTES:
                        await websocket.close(code=4400, reason="payload_too_large")
                        return
                    try:
                        command = json.loads(raw)
                    except json.JSONDecodeError:
                        await websocket.close(code=4400, reason="invalid_request")
                        return
                    if command != {"type": "refresh"}:
                        await websocket.close(code=4400, reason="invalid_request")
                        return
                current = game.operations_snapshot(token, clock())
                _assert_secret_free(current)
                current_events = current["events"]  # type: ignore[assignment]
                if (
                    current_events
                    and int(current_events[0]["sequence"]) > last_sequence + 1  # type: ignore[index]
                ):
                    await websocket.send_json(
                        _websocket_message("lobby.snapshot", current)
                    )
                    last_sequence = int(current_events[-1]["sequence"])  # type: ignore[index]
                    previous = current
                    continue
                event_types = {
                    "turn_opened": "turn.opened",
                    "controller_submitted": "controller.submitted",
                    "turn_resolved": "turn.resolved",
                    "metric_updated": "metric.updated",
                    "match_completed": "match.completed",
                    "controller_claimed": "controller.claimed",
                    "pairing_rejected": "pairing.rejected",
                    "heartbeat_rejected": "controller.heartbeat_rejected",
                    "controller_timed_out": "controller.timed_out",
                    "controller_replaced": "controller.replaced",
                }
                for event in current_events:  # type: ignore[union-attr]
                    sequence = int(event["sequence"])
                    if sequence <= last_sequence:
                        continue
                    event_kind = str(event["kind"])
                    message_type = event_types.get(event_kind)
                    if (
                        message_type is None
                        and event_kind
                        in {
                            "controller_presence_changed",
                            "controller_ready",
                            "controller_disconnected",
                            "controller_connected",
                        }
                    ):
                        message_type = "controller.presence_changed"
                    if message_type is not None:
                        payload = event
                        if message_type == "metric.updated":
                            payload = {
                                "event": event,
                                "metrics": game.run_report(token)["metrics"],
                            }
                        await websocket.send_json(
                            _websocket_message(message_type, payload)
                        )
                    last_sequence = sequence
                previous = current
        except WebSocketDisconnect:
            return
        except ServiceError as exc:
            await websocket.close(code=4400 + min(exc.status_code, 99), reason=exc.code)

    async def live(websocket: WebSocket, match_id: str, token: str) -> None:
        try:
            assert_scoped(token, match_id)
            await websocket.accept()
            await websocket.send_json(
                {"type": "observation", "payload": asdict(game.observe(token))}
            )
            while True:
                message = await websocket.receive_json()
                if message.get("type") == "observe":
                    await websocket.send_json(
                        {"type": "observation", "payload": asdict(game.observe(token))}
                    )
                elif message.get("type") == "actions":
                    submission = game.submit_actions(
                        token, int(message["turn"]), message["actions"]
                    )
                    await websocket.send_json(
                        {
                            "type": "submission",
                            "payload": {
                                "status": submission.status,
                                "turn": submission.turn,
                                "waiting_for": submission.waiting_for,
                            },
                        }
                    )
        except WebSocketDisconnect:
            return
        except ServiceError as exc:
            await websocket.close(code=4400 + min(exc.status_code, 99), reason=exc.code)

    if not remote:
        app.websocket("/api/matches/{match_id}/ws")(live)

    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        include_in_schema=False,
    )
    def api_route_not_found(path: str) -> Response:
        raise HTTPException(status_code=404, detail="not found")

    client_dir = (
        Path(static_dir)
        if static_dir is not None
        else Path(__file__).parents[2] / "frontend" / "dist"
    )
    if client_dir.is_dir():
        app.mount("/", StaticFiles(directory=client_dir, html=True), name="client")

    app.state.game_service = game
    return app
