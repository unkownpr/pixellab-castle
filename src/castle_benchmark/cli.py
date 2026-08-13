from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path

from .runner import RunConfig, run_match, verify_replay
from .scenarios import get_scenario


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
    args = build_parser().parse_args()
    if args.command == "run":
        kinds = ("survivalist", "trader", "expansionist", "militarist")[: args.colonies]
        report = run_match(
            RunConfig(get_scenario(args.scenario), args.seed, args.colonies, args.output, kinds)
        )
        print(report.report_path)
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
