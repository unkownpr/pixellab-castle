from castle_benchmark.engine import SimCore
from castle_benchmark.observation import project_observation
from castle_benchmark.scenarios import BASIC_SURVIVAL


def test_observation_never_leaks_hidden_enemy_stock() -> None:
    """Catches a controller receiving an opponent's private resources."""
    sim = SimCore.create(BASIC_SURVIVAL, seed=41, colony_count=2)

    observation = project_observation(sim.state, "c1")

    assert observation.colony["id"] == "c1"
    assert "resources" in observation.colony
    assert "resources" not in observation.known_colonies["c2"]


def test_observation_contains_only_known_cells() -> None:
    """Catches fog-of-war projection serializing the full authoritative grid."""
    sim = SimCore.create(BASIC_SURVIVAL, seed=43, colony_count=2)

    observation = project_observation(sim.state, "c1")

    known = sim.state.colonies["c1"].known_cells
    assert len(observation.visible_cells) == len(known)
    assert len(observation.visible_cells) < len(sim.state.world.cells)  # type: ignore[attr-defined]

