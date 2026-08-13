"""Build the deterministic runtime asset catalogue from checked-in PixelLab output."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).parents[1]
OUTPUT = ROOT / "assets" / "manifest.json"
DIRECTIONS = (
    "north",
    "north-east",
    "east",
    "south-east",
    "south",
    "south-west",
    "west",
    "north-west",
)

PIXELLAB_TILES = (
    {
        "id": "e7492368-8085-42db-a091-8d54b53c59a6",
        "prompt": "golden yellow desert sand ground, flat cartoon",
        "seed": 0,
    },
    {
        "id": "39ef93ca-86e8-427f-bb24-640f5fea099b",
        "prompt": "flat plain brown dirt ground, bare soil, no bricks",
        "seed": 42,
    },
    {
        "id": "c8c884c7-343b-4419-b77f-406f89b5bb1f",
        "prompt": "dirt path road, packed brown earth",
        "seed": 0,
    },
    {
        "id": "95c03461-15d0-48b8-a831-935ca3e961db",
        "prompt": "golden yellow wheat crop field, flat cartoon low poly style",
        "seed": 0,
    },
    {
        "id": "facc87ed-a414-480d-9ce7-69e3f6269e6c",
        "prompt": "bright green grass field on dirt, flat cartoon low poly style",
        "seed": 0,
    },
)


def entry(path: Path, anchor: tuple[int, int], **metadata: object) -> dict[str, object]:
    relative = path.relative_to(ROOT).as_posix()
    with Image.open(path) as image:
        size = list(image.size)
        mode = image.mode
    if mode != "RGBA":
        raise ValueError(f"runtime asset must be RGBA: {relative} ({mode})")
    return {
        "path": relative,
        "size": size,
        "anchor": list(anchor),
        "source": "pixellab",
        **metadata,
    }


def build_manifest() -> dict[str, object]:
    assets: dict[str, dict[str, object]] = {}

    for index in range(58):
        path = ROOT / "kit" / f"tile_{index}.png"
        assets[f"kit.tile.{index}"] = entry(path, (14, 55), category="building_kit")

    for biome, directory in (("grass", "ws_grass"), ("sand", "ws_sand"), ("snow", "ws_snow")):
        for index in range(16):
            path = ROOT / directory / f"tile_{index}.png"
            assets[f"terrain.{biome}.wang.{index}"] = entry(
                path,
                (0, 12),
                category="terrain",
                biome=biome,
                wang_mask=index,
            )

    for role_dir in sorted((ROOT / "chars").iterdir()):
        if not role_dir.is_dir():
            continue
        for direction in DIRECTIONS:
            path = role_dir / f"{direction}.png"
            with Image.open(path) as image:
                anchor = (image.width // 2, image.height - 4)
            assets[f"character.{role_dir.name}.idle.{direction}"] = entry(
                path,
                anchor,
                category="character",
                role=role_dir.name,
                state="idle",
                direction=direction,
                frames=1,
            )

    for direction in DIRECTIONS:
        rotation = ROOT / "anim" / "Idle" / "rotations" / f"{direction}.png"
        assets[f"character.reference.idle.{direction}"] = entry(
            rotation,
            (24, 44),
            category="character",
            role="villager_blue",
            state="idle_reference",
            direction=direction,
            frames=1,
        )
        for frame in range(6):
            path = ROOT / "anim" / "Idle" / "animations" / "walk" / direction / f"frame_{frame:03}.png"
            assets[f"character.reference.walk.{direction}.{frame}"] = entry(
                path,
                (24, 44),
                category="character",
                role="villager_blue",
                state="walk",
                direction=direction,
                frame=frame,
                frames=6,
                frame_duration_ms=120,
            )

    named_assets = {
        "structure.house.grass.operational": "house_s.png",
        "structure.house.desert.operational": "house_desert.png",
        "structure.headquarters.operational": "keep_s.png",
        "structure.watchtower.operational": "tower_s.png",
        "structure.market.operational": "stall_s.png",
        "prop.monument": "monument_s.png",
        "prop.pine.grass": "pine_s.png",
        "prop.pine.grass.small": "pine_small.png",
        "prop.pine.snow": "pine_snow.png",
        "prop.pine.snow.small": "pine_small_snow.png",
        "prop.rock": "rock_s.png",
        "prop.bush": "bush_s.png",
        "terrain.grass.base": "grass_tile.png",
        "terrain.sand.base": "sand_tile.png",
        "terrain.snow.base": "snow_tile.png",
        "terrain.dirt.base": "dirt_tile.png",
        "terrain.wheat.base": "wheat_tile.png",
    }
    for key, filename in named_assets.items():
        path = ROOT / filename
        with Image.open(path) as image:
            anchor = (image.width // 2, image.height - 6)
        assets[key] = entry(path, anchor, category=key.split(".", 1)[0])

    lineage_path = ROOT / "assets" / "generated" / "lineage.json"
    generated_states = json.loads(lineage_path.read_text()) if lineage_path.exists() else []
    for generated in generated_states:
        path = ROOT / generated["path"]
        if not path.exists():
            continue
        with Image.open(path) as image:
            anchor = (image.width // 2, image.height - 6)
        assets[generated["key"]] = entry(
            path,
            anchor,
            category=generated["key"].split(".", 1)[0],
            job_id=generated["job_id"],
            seed=generated["seed"],
            **{
                name: generated[name]
                for name in ("frame", "frames", "frame_duration_ms")
                if name in generated
            },
        )

    return {
        "version": "1.0",
        "projection": "isometric",
        "tile_geometry": {"width": 48, "height": 24},
        "painter_order": ["x_plus_y", "x"],
        "assets": dict(sorted(assets.items())),
        "pixellab": {
            "inventory_checked_at": "2026-08-13",
            "project_tag": "pixellab-castle",
            "known_isometric_tile_ids": PIXELLAB_TILES,
            "generated_states": generated_states,
        },
    }


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(build_manifest(), indent=2, sort_keys=True) + "\n")
    print(OUTPUT)


if __name__ == "__main__":
    main()
