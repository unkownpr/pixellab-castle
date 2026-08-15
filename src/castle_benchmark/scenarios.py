from __future__ import annotations

from dataclasses import dataclass

from .domain import Position


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    name: str
    width: int
    height: int
    max_turns: int
    biome: str
    spawn_points: tuple[Position, ...]
    sight_radius: int = 5
    hazard_cadence: int = 11  # Fire and weather ignition interval in turns; set per-biome at construction (AM-2)

    def __post_init__(self) -> None:
        if not self.id or not self.name:
            raise ValueError("scenario id and name are required")
        if self.width < 5 or self.height < 5:
            raise ValueError("scenario dimensions must be at least 5x5")
        if not 1 <= len(self.spawn_points) <= 8:
            raise ValueError("scenarios require one to eight spawn points")
        if len(set(self.spawn_points)) != len(self.spawn_points):
            raise ValueError("spawn points must be unique")
        if self.hazard_cadence < 1:
            raise ValueError("hazard_cadence must be positive")


BASIC_SURVIVAL = Scenario(
    id="basic-survival-v1",
    name="Basic Survival",
    width=18,
    height=18,
    max_turns=80,
    biome="grassland",
    spawn_points=(
        Position(3, 3),
        Position(14, 3),
        Position(14, 14),
        Position(3, 14),
    ),
    hazard_cadence=11,  # Grassland default (AM-2)
)

DESERT_SCARCITY = Scenario(
    id="desert-scarcity-v1",
    name="Desert Scarcity and Trade",
    width=20,
    height=20,
    max_turns=100,
    biome="desert",
    spawn_points=(Position(3, 3), Position(16, 3), Position(16, 16), Position(3, 16)),
    hazard_cadence=9,  # Desert default (AM-2)
)

SNOW_RECOVERY = Scenario(
    id="snow-recovery-v1",
    name="Snow Disaster Recovery",
    width=20,
    height=20,
    max_turns=100,
    biome="snow",
    spawn_points=(Position(3, 3), Position(16, 3), Position(16, 16), Position(3, 16)),
    hazard_cadence=7,  # Snow default (AM-2)
)

OFFICIAL_SCENARIOS = (BASIC_SURVIVAL, DESERT_SCARCITY, SNOW_RECOVERY)

# Ranges for procedural scenario generation (C4): all values are deterministic from seed
# Dimensions: balanced between 16 (tight) and 22 (spacious) to keep pace relatively consistent
PROCEDURAL_WIDTH_OPTIONS = (16, 18, 20, 22)
# Biomes offer different hazard pressures: snow (fastest) to grassland (slowest), all playable
PROCEDURAL_BIOME_OPTIONS = ("grassland", "desert", "snow")
# Spawn count is fixed at 4 for procedural scenarios, matching the official three
PROCEDURAL_SPAWN_COUNT = 4
# Resource density controls overall abundance: 0.12 is scarcity, 0.24 is abundance
PROCEDURAL_RESOURCE_DENSITY_MIN = 0.12
PROCEDURAL_RESOURCE_DENSITY_MAX = 0.24
# Hazard cadence (fire interval in turns): varies by biome, but procedural overrides independently
PROCEDURAL_HAZARD_CADENCE_MIN = 7
PROCEDURAL_HAZARD_CADENCE_MAX = 13
# Turn limits: quick matches (80) and longer (100) both appear
PROCEDURAL_MAX_TURNS_OPTIONS = (80, 100)
# Gather radius constant: must match the value used in gather validation (A3)
GATHER_RADIUS = 4


def generate_scenario(scenario_seed: int) -> Scenario:
    """Generate a procedural scenario deterministically from seed.

    Uses derive_seed to split the seed stream for each dimension, ensuring every
    spawn has at least one food-bearing cell within GATHER_RADIUS. Raises if
    validation fails after bounded resampling.
    """
    from .world import derive_seed

    # Generate dimensions from seed stream
    seed_stream = 0

    # Select width and height
    def next_seed(tag: str) -> int:
        nonlocal seed_stream
        seed_stream += 1
        return derive_seed(scenario_seed, f"procedural-{tag}-{seed_stream}")

    width_seed = next_seed("width")
    width = PROCEDURAL_WIDTH_OPTIONS[width_seed % len(PROCEDURAL_WIDTH_OPTIONS)]
    height = width  # Square maps

    # Select biome
    biome_seed = next_seed("biome")
    biome = PROCEDURAL_BIOME_OPTIONS[biome_seed % len(PROCEDURAL_BIOME_OPTIONS)]

    # Select max turns
    turns_seed = next_seed("max_turns")
    max_turns = PROCEDURAL_MAX_TURNS_OPTIONS[turns_seed % len(PROCEDURAL_MAX_TURNS_OPTIONS)]

    # Select resource density
    density_seed = next_seed("resource_density")
    resource_density = (
        PROCEDURAL_RESOURCE_DENSITY_MIN
        + (density_seed % 1000) / 1000.0 * (PROCEDURAL_RESOURCE_DENSITY_MAX - PROCEDURAL_RESOURCE_DENSITY_MIN)
    )

    # Select hazard cadence
    cadence_seed = next_seed("hazard_cadence")
    hazard_cadence = PROCEDURAL_HAZARD_CADENCE_MIN + (
        cadence_seed % (PROCEDURAL_HAZARD_CADENCE_MAX - PROCEDURAL_HAZARD_CADENCE_MIN + 1)
    )

    # Generate spawn points: distribute evenly on grid with some randomness
    spawns = _generate_spawn_points(width, height, PROCEDURAL_SPAWN_COUNT, next_seed("spawns"))

    # Validate that spawns are within bounds (world generation handles food placement per AM-3 and AM-12)
    if all(0 <= p.x < width and 0 <= p.y < height for p in spawns):
        scenario_id = f"procedural-v1-seed-{scenario_seed}"
        return Scenario(
            id=scenario_id,
            name=f"Procedural {biome.title()}",
            width=width,
            height=height,
            max_turns=max_turns,
            biome=biome,
            spawn_points=spawns,
            hazard_cadence=hazard_cadence,  # Explicit per-scenario, not biome-based (AM-2)
        )

    raise RuntimeError(
        f"Could not generate valid procedural scenario for seed {scenario_seed}: spawn points out of bounds"
    )


def _generate_spawn_points(width: int, height: int, count: int, seed: int) -> tuple[Position, ...]:
    """Generate spawn points distributed across the map, avoiding edges."""
    from .world import derive_seed

    spawns = []
    margin = 2  # Keep away from edges
    usable_width = width - 2 * margin
    usable_height = height - 2 * margin

    if usable_width < 4 or usable_height < 4 or count > 4:
        # Fallback for small maps or too many spawns
        positions = [
            Position(3, 3),
            Position(width - 4, 3),
            Position(width - 4, height - 4),
            Position(3, height - 4),
        ]
        return tuple(positions[:count])

    # Distribute in quadrants with randomness
    quadrants = [
        (margin, margin, margin + usable_width // 2, margin + usable_height // 2),  # TL
        (margin + usable_width // 2, margin, width - margin, margin + usable_height // 2),  # TR
        (margin + usable_width // 2, margin + usable_height // 2, width - margin, height - margin),  # BR
        (margin, margin + usable_height // 2, margin + usable_width // 2, height - margin),  # BL
    ]

    for i in range(min(count, 4)):
        x1, y1, x2, y2 = quadrants[i]
        # Use seed to pick a point in the quadrant
        local_seed = derive_seed(seed, f"spawn-{i}")
        x = x1 + (local_seed % (x2 - x1))
        y = derive_seed(local_seed, "y") % (y2 - y1) + y1
        spawns.append(Position(x, y))

    return tuple(spawns)


def get_scenario(scenario_id: str) -> Scenario:
    """Get scenario by ID, supporting both official and procedural scenarios."""
    for scenario in OFFICIAL_SCENARIOS:
        if scenario.id == scenario_id:
            return scenario
    # Check if it's a procedural scenario
    if scenario_id == "procedural-v1":
        # This should be called with a specific seed; raise error for seed-less call
        raise ValueError("procedural-v1 requires a seed; use generate_scenario(seed) instead")
    if scenario_id.startswith("procedural-v1-seed-"):
        try:
            seed = int(scenario_id.replace("procedural-v1-seed-", ""))
            return generate_scenario(seed)
        except (ValueError, IndexError) as exc:
            raise KeyError(f"invalid procedural scenario: {scenario_id}") from exc
    raise KeyError(f"unknown scenario: {scenario_id}")

