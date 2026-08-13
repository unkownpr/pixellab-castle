from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runner import RunConfig, run_match, verify_replay
from .scenarios import get_scenario


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

        uvicorn.run(
            "castle_benchmark.api:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
    elif args.command == "report":
        payload = json.loads((args.run_dir / "report.json").read_text())
        print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
