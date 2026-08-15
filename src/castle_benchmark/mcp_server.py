from __future__ import annotations

import argparse
import ipaddress
import json
import os
import secrets
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from pydantic import ValidationError

from . import engine, systems
from .domain import StructureKind
from .lobby import ControllerIdentity
from .scenarios import OFFICIAL_SCENARIOS
from .schemas import (
    MAX_PAYLOAD_BYTES,
    SCHEMA_VERSION,
    ControllerIdentityRequest,
    CreateSessionRequest,
    ServerInvocationTelemetryResponse,
    project_lobby_snapshot,
    project_match_status,
    project_run_report,
)
from .service import GameService, ServiceError


class SecureFastMCP(FastMCP):
    """FastMCP runner that leaves forwarded-peer trust to the explicit adapter policy."""

    def __init__(
        self,
        *args: object,
        invocation_meter: Callable[[str, dict[str, Any]], None],
        configured_transport: str,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._invocation_meter = invocation_meter
        self._configured_transport = configured_transport

    def _assert_transport(self, transport: str) -> None:
        if transport != self._configured_transport:
            raise ValueError("MCP server transport does not match its registered tool surface")

    def run(self, transport: str = "stdio", mount_path: str | None = None) -> None:
        self._assert_transport(transport)
        return super().run(transport=transport, mount_path=mount_path)  # type: ignore[arg-type]

    def streamable_http_app(self) -> object:
        self._assert_transport("streamable-http")
        return super().streamable_http_app()

    def sse_app(self, mount_path: str | None = None) -> object:
        self._assert_transport("sse")
        return super().sse_app(mount_path)

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> object:
        if self._tool_manager.get_tool(name) is not None:
            self._invocation_meter(name, arguments)
        return await super().call_tool(name, arguments)

    async def run_streamable_http_async(self) -> None:
        import uvicorn

        config = uvicorn.Config(
            self.streamable_http_app(),
            host=self.settings.host,
            port=self.settings.port,
            log_level=self.settings.log_level.lower(),
            proxy_headers=False,
        )
        await uvicorn.Server(config).serve()


def resolve_mcp_peer(context: object, trusted_proxies: Sequence[str]) -> str:
    """Resolve a stable transport peer, honoring forwarding only from trusted proxies."""
    try:
        request = context.request_context.request  # type: ignore[attr-defined]
        direct_peer = request.client.host
    except (AttributeError, ValueError):
        return "mcp-stdio"
    try:
        direct_ip = ipaddress.ip_address(direct_peer)
        networks = tuple(ipaddress.ip_network(value) for value in trusted_proxies)
    except ValueError:
        return str(direct_peer)
    if not any(direct_ip in network for network in networks):
        return str(direct_peer)
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    try:
        return str(ipaddress.ip_address(forwarded))
    except ValueError:
        return str(direct_peer)


_SPECIAL_EFFECTS: dict[StructureKind, tuple[str, ...]] = {
    StructureKind.MARKET: ("removes_trade_friction",),
    StructureKind.WORKSHOP: ("converts_ore_to_tools",),
    StructureKind.CLINIC: ("heals_sick_then_injured",),
    StructureKind.BARRACKS: ("reduces_raid_loot",),
    StructureKind.WALL: ("reduces_raid_damage", "blocks_trade_without_gate"),
    StructureKind.GATE: ("enables_trade_when_walled",),
    StructureKind.WATCHTOWER: ("extends_sight_radius",),
    StructureKind.WAREHOUSE: ("raises_storage_capacity",),
}


def build_rules() -> dict[str, object]:
    """Project the deterministic simulation rules from the live constants.

    Every numeric value is read from ``systems`` / ``engine`` here, never copied
    as a literal, so a constant change is reflected without a manual edit. No
    ``MatchState`` is consulted: the result is identical with or without a match.
    """
    structures: dict[str, object] = {}
    for kind in StructureKind:
        effects = list(_SPECIAL_EFFECTS.get(kind, ()))
        if kind in systems.HOUSING_BY_STRUCTURE:
            effects.append("housing")
        if kind in systems.PRODUCTION_YIELDS:
            effects.append("production")
        structures[kind.value] = {
            "build_cost": systems.BUILD_COSTS.get(kind),
            "build_turns": systems.BUILD_TURNS.get(kind),
            "housing": systems.HOUSING_BY_STRUCTURE.get(kind, 0),
            "production": systems.PRODUCTION_YIELDS.get(kind),
            "requires_worker": kind in systems.LABOUR_STRUCTURE_KINDS,
            "effects": effects,
        }

    return {
        "structures": structures,
        "workshop": {
            "ore_per_tool": systems.WORKSHOP_ORE_PER_TOOL,
            "tools_per_turn": systems.WORKSHOP_TOOLS_PER_TURN,
        },
        "clinic": {"heals_per_turn": systems.CLINIC_HEALS_PER_TURN},
        "raid": {
            "food_loot": systems.RAID_FOOD_LOOT,
            "structure_damage": systems.RAID_STRUCTURE_DAMAGE,
            "injuries": systems.RAID_INJURIES,
            "barracks_loot_reduction": systems.BARRACKS_RAID_LOOT_REDUCTION,
            "wall_damage_reduction": systems.WALL_RAID_DAMAGE_REDUCTION,
        },
        "trade": {
            "ratio_without_market": {
                "received": systems.TRADE_RATIO_BASE[0],
                "paid": systems.TRADE_RATIO_BASE[1],
            },
            "ratio_with_market": {
                "received": systems.TRADE_RATIO_MARKET[0],
                "paid": systems.TRADE_RATIO_MARKET[1],
            },
            "walled_without_gate_blocks_trade": True,
        },
        "storage": {
            "perishables": list(systems.PERISHABLES),
            "base_capacity": systems.PERISHABLE_BASE_CAPACITY,
            "warehouse_bonus": systems.WAREHOUSE_CAPACITY_BONUS,
        },
        "actions": {
            "budget_per_turn": engine.SimCore.ACTION_BUDGET,
            "bounded_by_available_population": True,
        },
        "gather": {
            "yield_per_action": engine.GATHER_YIELD_PER_ACTION,
            "scales_with_available_population": True,
            "extraction_structures": {
                resource: kind.value
                for resource, kind in engine.GATHER_EXTRACTION_STRUCTURES.items()
            },
            "penalty_divisor": engine.GATHER_PENALTY_DIVISOR,
        },
        "labour": {
            "workers_per_producer": engine.WORKERS_PER_PRODUCER,
        },
        "scouting": {
            "speed": engine.SCOUT_SPEED,
            "reveal_radius": engine.SCOUT_REVEAL_RADIUS,
            "food_cost": engine.SCOUT_FOOD_COST,
            "watchtower_sight_bonus": engine.WATCHTOWER_SIGHT_BONUS,
        },
        "fire": {
            "damage_per_turn": engine.FIRE_DAMAGE_PER_TURN,
            "spreads_to_orthogonal_adjacent_operational_structures": True,
            "ruins_persist": True,
        },
        "terminal_conditions": {
            "turn_limit": "the scenario max_turns is reached",
            "extinction": "every colony is at zero population",
        },
        "scenarios": tuple(
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
        ),
    }


def build_mcp_server(
    service: GameService | None = None,
    orchestrator_token: str | None = None,
    *,
    transport: str = "stdio",
    trusted_proxies: Sequence[str] = (),
    clock: Callable[[], float] = time.time,
) -> FastMCP:
    game = service or GameService()
    required_orchestrator_token = (
        orchestrator_token or os.environ.get("CASTLE_BENCHMARK_ORCHESTRATOR_TOKEN")
    )
    def meter_invocation(name: str, arguments: dict[str, Any]) -> None:
        """Measure every dispatch before FastMCP validates or executes its wrapper."""
        capability = arguments.get("controller_token") or arguments.get("admin_token")
        game.record_mcp_invocation(
            name, capability if isinstance(capability, str) else None
        )

    mcp = SecureFastMCP(
        "PixelLab Castle Benchmark",
        invocation_meter=meter_invocation,
        configured_transport=transport,
        instructions=(
            "Control one survival colony through structured observations and simultaneous action turns. "
            "Never infer hidden opponent state. Keep every capability private."
        ),
        json_response=True,
        max_request_body_size=MAX_PAYLOAD_BYTES,
    )

    def encode(callable_result: object) -> str:
        return json.dumps(callable_result, sort_keys=True, separators=(",", ":"))

    def versioned(payload: dict[str, object]) -> dict[str, object]:
        return {**payload, "schema_version": SCHEMA_VERSION}

    def error(exc: ServiceError | ValidationError | ValueError) -> str:
        if isinstance(exc, ServiceError):
            return encode({"error": {"code": exc.code, "message": exc.message}})
        return encode(
            {"error": {"code": "invalid_request", "message": "request validation failed"}}
        )

    def authorize_orchestrator(supplied: str) -> bool:
        return bool(
            required_orchestrator_token
            and secrets.compare_digest(supplied, required_orchestrator_token)
        )

    def payload_within_limit(payload: object) -> bool:
        return len(encode(payload).encode()) <= MAX_PAYLOAD_BYTES

    def payload_error(payload: object) -> str | None:
        if payload_within_limit(payload):
            return None
        return encode(
            {
                "error": {
                    "code": "payload_too_large",
                    "message": "request payload exceeds 16 KiB",
                }
            }
        )

    def mcp_peer(context: Context) -> str:
        return resolve_mcp_peer(context, trusted_proxies)

    @mcp.tool(name="benchmark.list_scenarios")
    def list_scenarios() -> str:
        """List deterministic official benchmark scenarios."""
        return encode(game.list_scenarios())

    @mcp.tool(name="benchmark.rules")
    def rules() -> str:
        """Publish the deterministic simulation rules; no match or capability required."""
        return encode(versioned(build_rules()))

    @mcp.tool(name="benchmark.server_telemetry")
    def server_telemetry(orchestrator_token: str) -> str:
        """Read process-wide MCP dispatch totals with the orchestrator capability."""
        if too_large := payload_error({"orchestrator_token": orchestrator_token}):
            return too_large
        if not authorize_orchestrator(orchestrator_token):
            return encode(
                {
                    "error": {
                        "code": "unauthorized",
                        "message": "orchestrator capability required",
                    }
                }
            )
        projected = ServerInvocationTelemetryResponse.model_validate(
            versioned(game.server_mcp_telemetry())
        )
        return encode(projected.model_dump(mode="json"))

    @mcp.tool(name="benchmark.create_session")
    def create_session(
        orchestrator_token: str,
        config: dict[str, object] | None = None,
        scenario_id: str = "basic-survival-v1",
        seed: int = 17,
        colony_count: int = 4,
    ) -> str:
        """Create a secure draft session and return only its admin capability."""
        try:
            if too_large := payload_error(
                {
                    "orchestrator_token": orchestrator_token,
                    "config": config,
                    "scenario_id": scenario_id,
                    "seed": seed,
                    "colony_count": colony_count,
                }
            ):
                return too_large
            if not authorize_orchestrator(orchestrator_token):
                return encode(
                    {
                        "error": {
                            "code": "unauthorized",
                            "message": "orchestrator capability required",
                        }
                    }
                )
            request = CreateSessionRequest.model_validate(
                config
                if config is not None
                else {
                    "scenario_id": scenario_id,
                    "seed": seed,
                    "colony_count": colony_count,
                }
            )
            session = game.create_session(
                orchestrator_token,
                request.scenario_id,
                request.seed,
                request.colony_count,
                request.deadline_seconds,
                (
                    (slot.colony_id, slot.controller_type, slot.baseline_kind)
                    for slot in request.slots
                ),
            )
            game.attribute_mcp_invocation(session.match_id, "benchmark.create_session")
            return encode(
                versioned(
                    {
                        "match_id": session.match_id,
                        "scenario_id": session.scenario_id,
                        "status": session.status.value,
                        "admin_token": session.admin_token,
                    }
                )
            )
        except (ServiceError, ValidationError, ValueError) as exc:
            return error(exc)

    def create_match(
        orchestrator_token: str,
        scenario_id: str = "basic-survival-v1",
        seed: int = 17,
        colony_count: int = 4,
    ) -> str:
        """Deprecated one-version local alias; never returns controller capabilities."""
        try:
            if too_large := payload_error(
                {
                    "orchestrator_token": orchestrator_token,
                    "scenario_id": scenario_id,
                    "seed": seed,
                    "colony_count": colony_count,
                }
            ):
                return too_large
            if not authorize_orchestrator(orchestrator_token):
                return encode(
                    {
                        "error": {
                            "code": "unauthorized",
                            "message": "orchestrator capability required",
                        }
                    }
                )
            created = game.create_match(scenario_id, seed, colony_count)
            game.attribute_mcp_invocation(created.match_id, "benchmark.create_match")
            return encode(
                versioned(
                    {
                        "match_id": created.match_id,
                        "scenario_id": created.scenario_id,
                        "admin_token": created.admin_token,
                        "deprecated": True,
                    }
                )
            )
        except ServiceError as exc:
            return error(exc)

    def join_match(admin_token: str, colony_id: str) -> str:
        """Provision one legacy local colony capability from an admin capability."""
        try:
            if too_large := payload_error(
                {"admin_token": admin_token, "colony_id": colony_id}
            ):
                return too_large
            return encode(
                versioned(
                    {
                        "colony_id": colony_id,
                        "controller_token": game.join_match(admin_token, colony_id),
                    }
                )
            )
        except ServiceError as exc:
            return error(exc)

    if transport == "stdio":
        mcp.tool(name="benchmark.create_match")(create_match)
        mcp.tool(name="benchmark.join_match")(join_match)

    @mcp.tool(name="benchmark.create_pairing")
    def create_pairing(admin_token: str, colony_id: str) -> str:
        """Mint one expiring, single-use pairing code for an external slot."""
        try:
            if too_large := payload_error(
                {"admin_token": admin_token, "colony_id": colony_id}
            ):
                return too_large
            grant = game.create_pairing(admin_token, colony_id, clock())
            assert grant.code is not None and grant.expires_at is not None
            return encode(
                versioned(
                    {
                        "match_id": grant.match_id,
                        "colony_id": grant.colony_id,
                        "pairing_code": grant.code,
                        "expires_at": grant.expires_at,
                    }
                )
            )
        except ServiceError as exc:
            return error(exc)

    @mcp.tool(name="benchmark.claim_slot")
    def claim_slot(
        pairing_code: str, identity: dict[str, object], ctx: Context
    ) -> str:
        """Exchange one pairing code for exactly one slot-scoped controller capability."""
        try:
            if too_large := payload_error(
                {"pairing_code": pairing_code, "identity": identity}
            ):
                return too_large
            validated = ControllerIdentityRequest.model_validate(identity)
            now = clock()
            peer = mcp_peer(ctx)
            game.reserve_pairing_attempt(peer, pairing_code, now)
            try:
                claimed = game.claim_slot_contract(
                    pairing_code,
                    ControllerIdentity(**validated.model_dump()),
                    now,
                )
            except ServiceError:
                raise
            game.clear_pairing_rate(peer, pairing_code)
            game.attribute_mcp_invocation(
                str(claimed["match_id"]), "benchmark.claim_slot"
            )
            return encode(versioned(claimed))
        except (ServiceError, ValidationError, ValueError) as exc:
            return error(exc)

    @mcp.tool(name="benchmark.heartbeat")
    def heartbeat(controller_token: str, turn: int, status: str) -> str:
        """Record one controller presence heartbeat for the authoritative turn."""
        try:
            if too_large := payload_error(
                {"controller_token": controller_token, "turn": turn, "status": status}
            ):
                return too_large
            receipt = game.heartbeat(controller_token, turn, status, clock())
            return encode(
                versioned(
                    {
                        "match_id": receipt.match_id,
                        "turn": receipt.turn,
                        "status": receipt.status,
                    }
                )
            )
        except ServiceError as exc:
            return error(exc)

    @mcp.tool(name="benchmark.start_match")
    def start_match(admin_token: str) -> str:
        """Start a ready lobby using its admin capability."""
        try:
            if too_large := payload_error({"admin_token": admin_token}):
                return too_large
            session = game.start_match(admin_token, clock())
            return encode(
                versioned({"match_id": session.match_id, "status": session.status.value})
            )
        except ServiceError as exc:
            return error(exc)

    @mcp.tool(name="benchmark.replace_controller")
    def replace_controller(
        admin_token: str,
        colony_id: str,
        replacement: str,
        baseline_kind: str | None = None,
    ) -> str:
        """Revoke a slot controller and install an explicit replacement type."""
        try:
            if too_large := payload_error(
                {
                    "admin_token": admin_token,
                    "colony_id": colony_id,
                    "replacement": replacement,
                    "baseline_kind": baseline_kind,
                }
            ):
                return too_large
            slot = game.replace_controller(
                admin_token, colony_id, replacement, clock(), baseline_kind
            )
            return encode(
                versioned(
                    {
                        "colony_id": colony_id,
                        "controller_id": slot.controller_id,
                        "status": slot.presence.value,
                    }
                )
            )
        except ServiceError as exc:
            return error(exc)

    @mcp.tool(name="benchmark.lobby_status")
    def lobby_status(admin_token: str) -> str:
        """Read the sanitized lobby snapshot without any capability material."""
        try:
            if too_large := payload_error({"admin_token": admin_token}):
                return too_large
            projected = project_lobby_snapshot(game.lobby_status(admin_token, clock()))
            return encode(projected.model_dump(mode="json"))
        except (ServiceError, ValidationError, ValueError) as exc:
            return error(exc)

    @mcp.tool(name="benchmark.observe")
    def observe(controller_token: str) -> str:
        """Get the fog-limited immutable observation for your colony's current turn. Call benchmark.rules first for the deterministic rules of the simulation."""
        try:
            if too_large := payload_error({"controller_token": controller_token}):
                return too_large
            return encode(versioned(asdict(game.observe(controller_token))))
        except ServiceError as exc:
            return error(exc)

    @mcp.tool(name="benchmark.submit_actions")
    def submit_actions(
        controller_token: str, turn: int, actions: list[dict[str, object]]
    ) -> str:
        """Submit one structured action batch; resolution waits for every controller. Call benchmark.rules first for the deterministic rules of the simulation."""
        try:
            if too_large := payload_error(
                {"controller_token": controller_token, "turn": turn, "actions": actions}
            ):
                return too_large
            submission = game.submit_actions(controller_token, turn, actions)
            return encode(
                versioned(
                    {
                        "status": submission.status,
                        "turn": submission.turn,
                        "waiting_for": submission.waiting_for,
                        "events": tuple(asdict(event) for event in submission.events),
                    }
                )
            )
        except ServiceError as exc:
            return error(exc)

    @mcp.tool(name="benchmark.match_status")
    def match_status(controller_token: str) -> str:
        """Read turn, terminal condition, and barrier status for your match."""
        try:
            if too_large := payload_error({"controller_token": controller_token}):
                return too_large
            projected = project_match_status(game.match_status(controller_token))
            return encode(projected.model_dump(mode="json"))
        except (ServiceError, ValidationError, ValueError) as exc:
            return error(exc)

    @mcp.tool(name="benchmark.run_report")
    def run_report(admin_token: str) -> str:
        """Read the sanitized run report using an admin capability."""
        try:
            if too_large := payload_error({"admin_token": admin_token}):
                return too_large
            payload = game.run_report(admin_token)
            projected = project_run_report(payload)
            return encode(projected.model_dump(mode="json"))
        except (ServiceError, ValidationError, TypeError, ValueError) as exc:
            return error(exc)

    @mcp.tool(name="benchmark.record_usage")
    def record_usage(
        controller_token: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
    ) -> str:
        """Record adapter-reported provider usage separately from server MCP calls."""
        try:
            if too_large := payload_error(
                {
                    "controller_token": controller_token,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "latency_ms": latency_ms,
                }
            ):
                return too_large
            return encode(
                versioned(
                    game.record_usage(
                        controller_token,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        latency_ms=latency_ms,
                    )
                )
            )
        except ServiceError as exc:
            return error(exc)

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(prog="castle-benchmark-mcp")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument(
        "--trusted-proxy",
        action="append",
        default=[],
        help="explicit proxy IP/CIDR allowed to supply X-Forwarded-For",
    )
    args = parser.parse_args()
    build_mcp_server(
        transport=args.transport,
        trusted_proxies=tuple(args.trusted_proxy),
    ).run(
        transport=args.transport
    )


if __name__ == "__main__":
    main()
