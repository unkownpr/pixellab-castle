from castle_benchmark.domain import Position
from castle_benchmark.scenarios import BASIC_SURVIVAL, Scenario
from castle_benchmark.world import canonical_world, generate_world, rotated_spawns, visible_cells


def test_same_seed_produces_identical_world() -> None:
    """Catches hidden global randomness in official benchmark worlds."""
    first = canonical_world(generate_world(BASIC_SURVIVAL, seed=17))
    second = canonical_world(generate_world(BASIC_SURVIVAL, seed=17))

    assert first == second


def test_different_seed_changes_resource_layout() -> None:
    """Catches accidentally ignoring the benchmark seed."""
    first = canonical_world(generate_world(BASIC_SURVIVAL, seed=17))
    second = canonical_world(generate_world(BASIC_SURVIVAL, seed=18))

    assert first["cells"] != second["cells"]


def test_spawn_rotation_preserves_spawn_set() -> None:
    """Catches seat rotation changing the map rather than only seat assignment."""
    first = rotated_spawns(BASIC_SURVIVAL, rotation=0, colony_count=4)
    second = rotated_spawns(BASIC_SURVIVAL, rotation=1, colony_count=4)

    assert set(first) == set(second)
    assert second == first[1:] + first[:1]


def test_generated_world_has_water_and_buildable_land() -> None:
    """Catches a broken river mask or a world with no playable land."""
    world = generate_world(BASIC_SURVIVAL, seed=17)

    water = [cell for cell in world.cells.values() if cell.water]
    buildable = [cell for cell in world.cells.values() if cell.buildable]
    assert len(water) >= world.height
    assert len(buildable) > len(water)


def test_visibility_is_bounded_by_radius() -> None:
    """Catches fog-of-war leaking the entire map."""
    scenario = Scenario(
        id="visibility-test",
        name="Visibility Test",
        width=9,
        height=9,
        max_turns=10,
        biome="grassland",
        spawn_points=(Position(4, 4),),
        sight_radius=2,
    )
    world = generate_world(scenario, seed=3)

    seen = visible_cells(world, (Position(4, 4),), radius=2)

    assert Position(4, 4) in seen
    assert Position(6, 4) in seen
    assert Position(7, 4) not in seen
    assert len(seen) == 13
