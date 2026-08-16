from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import os
from pathlib import Path

from .runner import MixedRunConfig, RunConfig, SuiteConfig, run_match, run_mixed_match, run_suite, verify_replay
from .scenarios import get_scenario


def configure_logging() -> None:
    level = os.environ.get("CASTLE_BENCHMARK_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


_SERVE_ORIGINS_ENV = "CASTLE_BENCHMARK_SERVE_ALLOWED_ORIGINS"
_SERVE_PROXIES_ENV = "CASTLE_BENCHMARK_SERVE_TRUSTED_PROXIES"
_SERVE_REMOTE_ENV = "CASTLE_BENCHMARK_SERVE_REMOTE"


def create_serve_app() -> object:
    """Importable Uvicorn factory so reload workers reconstruct the secured app."""
    from .api import create_app

    origins = tuple(json.loads(os.environ.get(_SERVE_ORIGINS_ENV, "[]")))
    proxies = tuple(json.loads(os.environ.get(_SERVE_PROXIES_ENV, "[]")))
    return create_app(
        orchestrator_token=os.environ.get("CASTLE_BENCHMARK_ORCHESTRATOR_TOKEN"),
        allowed_origins=origins,
        trusted_proxies=proxies,
        remote=os.environ.get(_SERVE_REMOTE_ENV) == "1",
    )


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_remote_configuration(
    host: str,
    remote: bool,
    orchestrator_token: str | None,
    allowed_origins: tuple[str, ...],
) -> None:
    """Reject remote serving unless every explicit safety control is present."""
    if any("*" in origin for origin in allowed_origins):
        raise ValueError("wildcard credential origins are not allowed")
    if _is_loopback_host(host):
        return
    if not remote:
        raise ValueError("non-loopback binds require --remote")
    if not orchestrator_token:
        raise ValueError("remote serving requires an orchestrator capability")
    if len(orchestrator_token) < 32:
        raise ValueError("remote serving requires a high-entropy orchestrator capability")
    if not allowed_origins:
        raise ValueError("remote serving requires at least one explicit allowed origin")
    for origin in allowed_origins:
        if not origin.startswith(("https://", "http://")):
            raise ValueError("allowed origin must be an explicit HTTP(S) origin")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="castle-benchmark")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--scenario", default="basic-survival-v1")
    run.add_argument("--seed", type=int, default=17)
    run.add_argument("--colonies", type=int, default=4)
    run.add_argument("--output", type=Path, default=Path("runs"))
    mixed = commands.add_parser("mixed-run")
    mixed.add_argument(
        "--scenario", default="basic-survival-v1", help="scenario to run"
    )
    mixed.add_argument("--seed", type=int, default=17, help="random seed")
    mixed.add_argument(
        "--external-seats",
        type=str,
        default="1",
        help="comma-separated 1-indexed seat numbers for external agents",
    )
    mixed.add_argument(
        "--baseline-kinds",
        type=str,
        help="comma-separated baseline kinds for non-external seats (default: all survivalist)",
    )
    mixed.add_argument(
        "--external-timeout",
        type=int,
        default=30,
        help="seconds to wait for external agents to connect",
    )
    mixed.add_argument("--output", type=Path, default=Path("runs"))
    suite = commands.add_parser("suite")
    suite.add_argument("--scenario", default="basic-survival-v1")
    suite.add_argument("--seeds", default="11,17,23,29,37", help="comma-separated seed list")
    suite.add_argument("--rotations", default="all", help="'all' or number of rotations")
    suite.add_argument("--colonies", type=int, default=4)
    suite.add_argument(
        "--controllers",
        default="survivalist,trader,expansionist,militarist",
        help="comma-separated controller kinds",
    )
    suite.add_argument("--output", type=Path, default=Path("runs"))
    suite.add_argument("--baseline-reference", type=Path, help="baseline suite.json for z-score comparison")
    replay = commands.add_parser("replay")
    replay.add_argument("run_dir", type=Path)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    serve.add_argument(
        "--remote",
        action="store_true",
        help="allow a non-loopback bind; terminate TLS at a reverse proxy or secure tunnel",
    )
    serve.add_argument(
        "--allowed-origin",
        action="append",
        default=[],
        help="explicit credentialed browser origin; repeat for each trusted origin",
    )
    serve.add_argument(
        "--trusted-proxy",
        action="append",
        default=[],
        help="explicit proxy IP/CIDR allowed to supply X-Forwarded-For; repeat as needed",
    )
    report = commands.add_parser("report")
    report.add_argument("run_dir", type=Path)
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    if args.command == "run":
        kinds = ("survivalist", "trader", "expansionist", "militarist")[: args.colonies]
        report = run_match(
            RunConfig(get_scenario(args.scenario), args.seed, args.colonies, args.output, kinds)
        )
        print(report.report_path)
    elif args.command == "mixed-run":
        # Parse external seat indices (1-indexed)
        external_seats = tuple(
            int(s.strip()) for s in args.external_seats.split(",") if s.strip()
        )
        # Parse baseline kinds if provided
        baseline_kinds = None
        if args.baseline_kinds:
            baseline_kinds = tuple(
                k.strip() for k in args.baseline_kinds.split(",") if k.strip()
            )
        report = run_mixed_match(
            MixedRunConfig(
                get_scenario(args.scenario),
                args.seed,
                args.output,
                external_seats,
                baseline_kinds,
                args.external_timeout,
            )
        )
        print(report.report_path)
    elif args.command == "suite":
        # Parse comma-separated seed list
        seeds = tuple(int(s.strip()) for s in args.seeds.split(","))
        # Parse comma-separated controllers
        controllers = tuple(c.strip() for c in args.controllers.split(","))
        # Get scenario or use procedural-v1
        if args.scenario == "procedural-v1":
            scenario_arg: str | object = "procedural-v1"
        else:
            scenario_arg = get_scenario(args.scenario)
        suite_output = run_suite(
            SuiteConfig(
                scenario_arg,
                seeds,
                args.rotations,
                args.colonies,
                controllers,
                args.output,
                args.baseline_reference,
            )
        )
        print(f"{args.output}/suite.json")
    elif args.command == "replay":
        verification = verify_replay(args.run_dir)
        print("ok" if verification.ok else f"mismatch:{verification.first_mismatch_turn}")
        raise SystemExit(0 if verification.ok else 1)
    elif args.command == "serve":
        import uvicorn

        orchestrator_token = os.environ.get("CASTLE_BENCHMARK_ORCHESTRATOR_TOKEN")
        allowed_origins = tuple(args.allowed_origin)
        try:
            validate_remote_configuration(
                args.host,
                args.remote,
                orchestrator_token,
                allowed_origins,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc

        os.environ[_SERVE_ORIGINS_ENV] = json.dumps(allowed_origins)
        os.environ[_SERVE_PROXIES_ENV] = json.dumps(tuple(args.trusted_proxy))
        os.environ[_SERVE_REMOTE_ENV] = "1" if args.remote else "0"
        uvicorn.run(
            "castle_benchmark.cli:create_serve_app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            factory=True,
            proxy_headers=False,
        )
    elif args.command == "report":
        payload = json.loads((args.run_dir / "report.json").read_text())
        print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
