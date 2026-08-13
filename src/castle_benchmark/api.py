from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, Header, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .schemas import CreateMatchRequest, CreateMatchResponse, SubmissionResponse, SubmitActionsRequest
from .service import GameService, ServiceError


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        from .service import UnauthorizedError

        raise UnauthorizedError("Bearer capability is required")
    return authorization.removeprefix("Bearer ").strip()


def create_app(service: GameService | None = None) -> FastAPI:
    game = service or GameService()
    app = FastAPI(title="PixelLab Castle Benchmark", version="0.1.0")

    @app.exception_handler(ServiceError)
    async def service_error_handler(_request: object, exc: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": {"code": exc.code, "message": exc.message}},
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/scenarios")
    def scenarios() -> tuple[dict[str, object], ...]:
        return game.list_scenarios()

    @app.post("/api/matches", status_code=201, response_model=CreateMatchResponse)
    def create_match(request: CreateMatchRequest) -> CreateMatchResponse:
        return CreateMatchResponse(
            **asdict(game.create_match(request.scenario_id, request.seed, request.colony_count))
        )

    @app.get("/api/matches/{match_id}/observation")
    def observation(
        match_id: str,
        colony_id: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        token = _bearer(authorization)
        game.assert_match(token, match_id)
        return asdict(game.observe(token, colony_id))

    @app.post("/api/matches/{match_id}/actions", response_model=SubmissionResponse)
    def submit(
        match_id: str,
        request: SubmitActionsRequest,
        authorization: str | None = Header(default=None),
    ) -> SubmissionResponse:
        token = _bearer(authorization)
        game.assert_match(token, match_id)
        submission = game.submit_actions(token, request.turn, request.actions)
        events = game.last_events(token) if submission.status == "resolved" else ()
        return SubmissionResponse(
            status=submission.status,  # type: ignore[arg-type]
            turn=submission.turn,
            waiting_for=submission.waiting_for,
            events=events,
        )

    @app.get("/api/matches/{match_id}/status")
    def status(match_id: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
        token = _bearer(authorization)
        game.assert_match(token, match_id)
        return game.match_status(token)

    @app.websocket("/api/matches/{match_id}/ws")
    async def live(websocket: WebSocket, match_id: str, token: str) -> None:
        try:
            game.assert_match(token, match_id)
            await websocket.accept()
            await websocket.send_json({"type": "observation", "payload": asdict(game.observe(token))})
            while True:
                message = await websocket.receive_json()
                if message.get("type") == "observe":
                    await websocket.send_json(
                        {"type": "observation", "payload": asdict(game.observe(token))}
                    )
                elif message.get("type") == "actions":
                    submission = game.submit_actions(token, int(message["turn"]), message["actions"])
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

    app.state.game_service = game
    return app

