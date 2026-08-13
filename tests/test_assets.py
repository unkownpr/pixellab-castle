import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "assets" / "manifest.json"


def test_asset_manifest_paths_and_geometry_are_valid() -> None:
    """Catches missing, opaque, or dimensionally inconsistent runtime sprites."""
    payload = json.loads(MANIFEST.read_text())

    assert payload["version"] == "1.0"
    assert payload["tile_geometry"] == {"width": 48, "height": 24}
    assert len(payload["assets"]) >= 190
    for key, entry in payload["assets"].items():
        path = ROOT / entry["path"]
        assert path.exists(), key
        with Image.open(path) as image:
            assert image.mode == "RGBA", key
            assert list(image.size) == entry["size"], key
        assert len(entry["anchor"]) == 2


def test_character_manifest_has_all_eight_directions() -> None:
    """Catches a role silently losing a facing direction in the browser renderer."""
    assets = json.loads(MANIFEST.read_text())["assets"]
    directions = {"north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"}

    for role in ("farmer", "blacksmith", "merchant", "guard_red", "villager_blue"):
        present = {
            entry["direction"]
            for key, entry in assets.items()
            if key.startswith(f"character.{role}.idle.")
        }
        assert present == directions


def test_legacy_modules_do_not_write_images_when_imported() -> None:
    """Catches MCP/API imports unexpectedly regenerating large render artifacts."""
    outputs = (ROOT / "castle_2d.png", ROOT / "village_river.png", ROOT / "desert_castle.png")
    before = {path: path.stat().st_mtime_ns for path in outputs}

    subprocess.run(
        [sys.executable, "-c", "import castle, render_biomes"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    after = {path: path.stat().st_mtime_ns for path in outputs}
    assert after == before


def test_manifest_records_pixellab_lineage() -> None:
    """Catches generated assets entering the benchmark without reproducible provenance."""
    payload = json.loads(MANIFEST.read_text())

    assert payload["pixellab"]["inventory_checked_at"] == "2026-08-13"
    assert len(payload["pixellab"]["known_isometric_tile_ids"]) == 5
    assert all("prompt" in item and "id" in item for item in payload["pixellab"]["known_isometric_tile_ids"])
    assert len(payload["pixellab"]["generated_states"]) >= 15
    assert all("job_id" in item and "seed" in item and "prompt" in item for item in payload["pixellab"]["generated_states"])
    for structure in ("warehouse", "well", "farm", "lumber_camp", "quarry", "mine", "workshop", "clinic", "barracks", "wall"):
        assert f"structure.{structure}.operational" in payload["assets"]
    assert "effect.fire.base" in payload["assets"]
    assert "effect.construction" in payload["assets"]
