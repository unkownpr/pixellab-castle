from __future__ import annotations

import json
import argparse
import os
import secrets
from dataclasses import asdict

from mcp.server.fastmcp import FastMCP

from .service import GameService, ServiceError


def build_mcp_server(
    service: GameService | None = None,
    orchestrator_token: str | None = None,
) -> FastMCP:
    game = service or GameService()
    required_orchestrator_token = orchestrator_token or os.environ.get("CASTLE_BENCHMARK_ORCHESTRATOR_TOKEN")
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
    def create_match(
        orchestrator_token: str,
        scenario_id: str = "basic-survival-v1",
        seed: int = 17,
        colony_count: int = 4,
    ) -> str:
        """Create a match and return controller capabilities. Keep tokens private."""
        try:
            if not required_orchestrator_token or not secrets.compare_digest(
                orchestrator_token, required_orchestrator_token
            ):
                return encode({"error": {"code": "unauthorized", "message": "orchestrator capability required"}})
            created = game.create_match(scenario_id, seed, colony_count)
            return encode({"match_id": created.match_id, "scenario_id": created.scenario_id, "admin_token": created.admin_token})
        except ServiceError as exc:
            return encode({"error": {"code": exc.code, "message": exc.message}})

    @mcp.tool(name="benchmark.join_match")
    def join_match(admin_token: str, colony_id: str) -> str:
        """Provision exactly one colony capability from an orchestrator-held admin token."""
        try:
            return encode({"colony_id": colony_id, "controller_token": game.join_match(admin_token, colony_id)})
        except ServiceError as exc:
            return encode({"error": {"code": exc.code, "message": exc.message}})

    @mcp.tool(name="benchmark.observe")
    def observe(controller_token: str) -> str:
        """Get the fog-limited immutable observation for your colony's current turn."""
        try:
            game.record_mcp_call(controller_token)
            return encode(asdict(game.observe(controller_token)))
        except ServiceError as exc:
            return encode({"error": {"code": exc.code, "message": exc.message}})

    @mcp.tool(name="benchmark.submit_actions")
    def submit_actions(controller_token: str, turn: int, actions: list[dict[str, object]]) -> str:
        """Submit one structured action batch; resolution waits for every controller."""
        try:
            game.record_mcp_call(controller_token)
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
            game.record_mcp_call(controller_token)
            return encode(game.match_status(controller_token))
        except ServiceError as exc:
            return encode({"error": {"code": exc.code, "message": exc.message}})

    @mcp.tool(name="benchmark.run_report")
    def run_report(admin_token: str) -> str:
        """Read the current in-memory match status and latest resolved events as admin."""
        try:
            return encode(game.run_report(admin_token))
        except ServiceError as exc:
            return encode({"error": {"code": exc.code, "message": exc.message}})

    @mcp.tool(name="benchmark.record_usage")
    def record_usage(
        controller_token: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
    ) -> str:
        """Record measured cost and latency for one model decision before submitting it."""
        try:
            game.record_mcp_call(controller_token)
            return encode(
                game.record_usage(
                    controller_token,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                )
            )
        except ServiceError as exc:
            return encode({"error": {"code": exc.code, "message": exc.message}})

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(prog="castle-benchmark-mcp")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    args = parser.parse_args()
    build_mcp_server().run(transport=args.transport)


if __name__ == "__main__":
    main()
