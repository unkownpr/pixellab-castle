"""Turn a real match into the data the promo video plays back.

The video does not mock anything: it replays snapshots the simulation actually wrote,
with the sprites the client actually binds, and quotes the axes from reports on disk. The
point of a benchmark's own promo is that every frame in it is reproducible — run this
script, render, and you get the same film.

Reads a run directory produced by `castle-benchmark run` (or any suite match), writes
`public/replay.json`, and copies just the sprites that film needs into `public/sprites/`.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

PROMO = Path(__file__).resolve().parents[1]
ROOT = PROMO.parent

# Sprites the film draws. Terrain is drawn as flat colour rather than tiles: the tile art
# is 48x24 and reads as mud at video scale, while the structures are what the eye follows.
SPRITE_KEYS = (
    "structure.headquarters.operational",
    "structure.house.grass.operational",
    "structure.farm.operational",
    "structure.well.operational",
    "structure.lumber_camp.operational",
    "structure.quarry.operational",
    "structure.mine.operational",
    "structure.market.operational",
    "structure.workshop.operational",
    "structure.clinic.operational",
    "structure.barracks.operational",
    "structure.watchtower.operational",
    "structure.warehouse.operational",
    "structure.wall.operational",
    "structure.gate.operational",
    "structure.monument.operational",
    "structure.generic.ruined",
    "effect.fire.base",
    "effect.repair",
    "effect.damage",
    "effect.construction",
)


def load_snapshots(run_dir: Path) -> list[dict]:
    path = run_dir / "snapshots.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def compact(snapshots: list[dict], every: int) -> dict:
    """Keep one frame in ``every`` turns, and only the fields the film draws."""
    first = snapshots[0]
    world = first["world"]
    cells = [
        {
            "x": cell["x"],
            "y": cell["y"],
            "w": 1 if cell["water"] else 0,
            "r": cell["resource"] or "",
        }
        for cell in world["cells"]
    ]
    frames = []
    for snapshot in snapshots[::every]:
        frames.append(
            {
                "turn": snapshot["turn"],
                "structures": [
                    {
                        "id": structure["id"],
                        "c": structure["colony_id"],
                        "k": structure["kind"],
                        "s": structure["status"],
                        "x": structure["position"]["x"],
                        "y": structure["position"]["y"],
                    }
                    for structure in sorted(
                        snapshot["structures"].values(), key=lambda item: item["id"]
                    )
                ],
                "colonies": {
                    colony_id: {
                        "pop": colony["population"],
                        "food": colony["resources"]["food"],
                        "water": colony["resources"]["water"],
                        "known": len(colony["known_cells"]),
                    }
                    for colony_id, colony in sorted(snapshot["colonies"].items())
                },
            }
        )
    return {
        "scenario": first["scenario_id"],
        "seed": first["seed"],
        "width": world["width"],
        "height": world["height"],
        "biome": world["biome"],
        "cells": cells,
        "frames": frames,
    }


def copy_sprites(manifest: dict) -> dict[str, dict]:
    target = PROMO / "public" / "sprites"
    target.mkdir(parents=True, exist_ok=True)
    catalogue: dict[str, dict] = {}
    for key in SPRITE_KEYS:
        entry = manifest["assets"].get(key)
        if entry is None:
            continue
        source = ROOT / entry["path"]
        name = key.replace(".", "_") + ".png"
        shutil.copyfile(source, target / name)
        catalogue[key] = {"file": name, "size": entry["size"]}
    return catalogue


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        type=Path,
        default=ROOT / "runs" / "suite-final" / "basic-survival-v1-seed-17",
        help="run directory to replay",
    )
    parser.add_argument(
        "--every", type=int, default=2, help="keep one snapshot in this many turns"
    )
    parser.add_argument(
        "--suite",
        type=Path,
        default=ROOT / "runs" / "suite-final" / "suite.json",
        help="suite results quoted in the closing card",
    )
    args = parser.parse_args()

    manifest = json.loads((ROOT / "assets" / "manifest.json").read_text())
    replay = compact(load_snapshots(args.run), args.every)
    replay["sprites"] = copy_sprites(manifest)
    replay["report"] = json.loads((args.run / "report.json").read_text())

    if args.suite.exists():
        suite = json.loads(args.suite.read_text())
        replay["suite"] = {
            "seeds": suite["seeds"],
            "rotations": suite["rotations"],
            "controllers": {
                kind: {
                    "composite": stats["composite"]["mean"],
                    "n": stats["composite"]["n"],
                }
                for kind, stats in suite["statistics"].items()
            },
        }

    out = PROMO / "public" / "replay.json"
    out.write_text(json.dumps(replay, separators=(",", ":")))
    print(f"{out} · {len(replay['frames'])} frames · {len(replay['sprites'])} sprites")


if __name__ == "__main__":
    main()
