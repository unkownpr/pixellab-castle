from __future__ import annotations

import json
from dataclasses import asdict

from mcp.server.fastmcp import FastMCP

from .service import GameService, ServiceError


def build_mcp_server(service: GameService | None = None) -> FastMCP:
    game = service or GameService()
    mcp = FastMCP(
        "PixelLab Castle Benchmark",
        instructions=(
            "Control one survival colony through structured observations and simultaneous action turns. "
            "Never infer hidden opponent state."
        ),
        json_response=True,
    )

    def encode(callable_result: object) -> str:
        return json.dumps(callable_result, sort_keys=True, separators=(",", ":"))

    @mcp.tool(name="benchmark.list_scenarios")
    def list_scenarios() -> str:
        """List deterministic official benchmark scenarios."""
        return encode(game.list_scenarios())

    @mcp.tool(name="benchmark.create_match")
    def create_match(scenario_id: str = "basic-survival-v1", seed: int = 17, colony_count: int = 4) -> str:
        """Create a match and return controller capabilities. Keep tokens private."""
        try:
            return encode(asdict(game.create_match(scenario_id, seed, colony_count)))
        except ServiceError as exc:
            return encode({"error": {"code": exc.code, "message": exc.message}})

    @mcp.tool(name="benchmark.observe")
    def observe(controller_token: str) -> str:
        """Get the fog-limited immutable observation for your colony's current turn."""
        try:
            return encode(asdict(game.observe(controller_token)))
        except ServiceError as exc:
            return encode({"error": {"code": exc.code, "message": exc.message}})

    @mcp.tool(name="benchmark.submit_actions")
    def submit_actions(controller_token: str, turn: int, actions: list[dict[str, object]]) -> str:
        """Submit one structured action batch; resolution waits for every controller."""
        try:
            submission = game.submit_actions(controller_token, turn, actions)
            return encode(
                {
                    "status": submission.status,
                    "turn": submission.turn,
                    "waiting_for": submission.waiting_for,
                    "events": game.last_events(controller_token)
                    if submission.status == "resolved"
                    else (),
                }
            )
        except ServiceError as exc:
            return encode({"error": {"code": exc.code, "message": exc.message}})

    @mcp.tool(name="benchmark.match_status")
    def match_status(controller_token: str) -> str:
        """Read turn, terminal condition, and barrier status for your match."""
        try:
            return encode(game.match_status(controller_token))
        except ServiceError as exc:
            return encode({"error": {"code": exc.code, "message": exc.message}})

    @mcp.tool(name="benchmark.run_report")
    def run_report(admin_token: str) -> str:
        """Read the current in-memory match status and latest resolved events as admin."""
        try:
            return encode(
                {"status": game.match_status(admin_token), "latest_events": game.last_events(admin_token)}
            )
        except ServiceError as exc:
            return encode({"error": {"code": exc.code, "message": exc.message}})

    return mcp


def main() -> None:
    build_mcp_server().run(transport="streamable-http")


if __name__ == "__main__":
    main()
