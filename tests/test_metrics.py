"""Tests for Workstream C: metrics, composite score, Pareto front, and new axes."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from castle_benchmark.domain import MatchState, Position, ColonyState, ResourceStock, Structure, StructureStatus, StructureKind
from castle_benchmark.engine import SimCore, TurnResult
from castle_benchmark.metrics import MetricCollector
from castle_benchmark.scenarios import (
    BASIC_SURVIVAL,
    get_scenario,
    generate_scenario,
    PROCEDURAL_SPAWN_COUNT,
    PROCEDURAL_WIDTH_OPTIONS,
    PROCEDURAL_BIOME_OPTIONS,
    GATHER_RADIUS,
)
from castle_benchmark.runner import run_match, RunConfig


def _minimal_state(scenario_id: str = "basic-survival-v1") -> MatchState:
    """Create a minimal match state for testing."""
    return MatchState(
        scenario_id=scenario_id,
        seed=42,
        turn=1,
        world=None,
        colonies={
            "c1": ColonyState(
                id="c1",
                spawn=Position(3, 3),
                resources=ResourceStock(food=10, water=10, wood=5, stone=5, ore=0, tools=0, influence=0),
                population=8,
            ),
            "c2": ColonyState(
                id="c2",
                spawn=Position(15, 15),
                resources=ResourceStock(food=8, water=8, wood=3, stone=3, ore=0, tools=0, influence=0),
                population=8,
            ),
        },
        structures={},
    )


def test_metric_collector_create():
    """Composite and new axes are initialized correctly."""
    state = _minimal_state()
    collector = MetricCollector.create(state)

    assert collector.initial_population == {"c1": 8, "c2": 8}
    assert collector.peak_population == {"c1": 8, "c2": 8}
    assert collector.min_population == {"c1": 8, "c2": 8}
    assert collector.action_kinds_used == {"c1": set(), "c2": set()}


def test_composite_score_calculation():
    """Composite score follows the published formula exactly."""
    state = _minimal_state()
    collector = MetricCollector.create(state)

    # Set up some metrics
    collector.trades["c1"] = 2
    collector.raids["c1"] = 1
    collector.invalid_actions["c1"] = 3
    collector.starvation_turns["c1"] = 1

    # Add some structures
    state.structures["s1"] = Structure(
        id="s1",
        colony_id="c1",
        kind=StructureKind.HOUSE,
        position=Position(3, 3),
        status=StructureStatus.OPERATIONAL,
        progress=0,
        required_progress=0,
    )

    # Manually set known_cells using replace
    known_positions = frozenset(Position(x, y) for x in range(5) for y in range(5))
    state.colonies["c1"] = replace(state.colonies["c1"], known_cells=known_positions)

    composite = collector._calculate_composite(state, "c1")

    # Expected calculation (AM-19, final):
    # population_alive: 3 * 8 = 24
    # peak_population: 1 * 8 = 8
    # operational_structures: 2 * 1 = 2
    # explored_cells: 25 // 10 = 2
    # trades: 2 * 2 = 4
    # raids: 2 * 1 = 2
    # resource_value: (5*2 + 5*2 + 0*3 + 0*5 + 0*1) // 25 = 20 // 25 = 0 (food/water excluded)
    # invalid_actions: -1 * 3 = -3
    # starvation_turns: -1 * 1 = -1
    # monument: 0
    # Total: 24 + 8 + 2 + 2 + 4 + 2 + 0 - 3 - 1 = 38

    assert composite == 38.0, f"Expected 38, got {composite}"


def test_composite_with_monument_victory():
    """Monument victory bonus is added correctly (AM-19: 40 not 25)."""
    state_no_monument = _minimal_state()
    collector = MetricCollector.create(state_no_monument)

    composite_no_monument = collector._calculate_composite(state_no_monument, "c1")

    state_with_monument = replace(state_no_monument, termination_reason="monument_victory")
    composite_with_monument = collector._calculate_composite(state_with_monument, "c1")

    assert composite_with_monument - composite_no_monument == 40.0


def test_pareto_front_calculation():
    """Pareto front identifies non-dominated colonies."""
    state = _minimal_state()
    collector = MetricCollector.create(state)

    # c1 is strictly better on all axes
    collector.peak_population = {"c1": 10, "c2": 5}
    # Create new states with better resources for c1
    c1_better = replace(
        state.colonies["c1"],
        resources=ResourceStock(food=20, water=10, wood=10, stone=10, ore=5, tools=5, influence=2)
    )
    c2_worse = replace(
        state.colonies["c2"],
        resources=ResourceStock(food=5, water=5, wood=5, stone=5, ore=0, tools=0, influence=0)
    )
    state = replace(state, colonies={"c1": c1_better, "c2": c2_worse})

    collector.trades = {"c1": 5, "c2": 1}
    collector.raids = {"c1": 3, "c2": 0}

    front = collector._calculate_pareto_front(state, ["c1", "c2"])

    # c1 dominates c2
    assert "c1" in front
    # c2 is dominated by c1
    assert "c2" not in front


def test_pareto_front_all_on_front():
    """When colonies have incomparable trade-offs, all are on Pareto front."""
    state = _minimal_state()
    collector = MetricCollector.create(state)

    # c1 is better on trade, c2 is better on raids
    collector.peak_population = {"c1": 8, "c2": 8}
    collector.trades = {"c1": 5, "c2": 1}
    collector.raids = {"c1": 0, "c2": 3}

    front = collector._calculate_pareto_front(state, ["c1", "c2"])

    # Both should be on front (no dominance)
    assert "c1" in front
    assert "c2" in front


def test_report_structure_includes_new_axes():
    """Report includes all new axes: exploration, labour, recovery, communication, decision_quality."""
    state = _minimal_state()
    collector = MetricCollector.create(state)

    # Set some values for new axes
    collector.scouts_dispatched["c1"] = 2
    collector.scout_revealed_cells["c1"] = 5
    collector.idle_producers_sum["c1"] = 10
    collector.colonist_turns_sick["c1"] = 3
    collector.structures_repaired["c1"] = 1
    collector.structures_demolished["c1"] = 1
    collector.messages_sent["c1"] = 4

    report = collector.report(state)

    assert "exploration" in report
    assert report["exploration"]["c1"]["scouts_dispatched"] == 2
    assert report["exploration"]["c1"]["cells_revealed_by_scouts"] == 5

    assert "labour" in report
    assert report["labour"]["c1"]["idle_producers_sum"] == 10
    assert report["labour"]["c1"]["colonist_turns_sick"] == 3

    assert "recovery" in report
    assert report["recovery"]["c1"]["structures_repaired"] == 1
    assert report["recovery"]["c1"]["structures_demolished"] == 1

    assert "communication" in report
    assert report["communication"]["c1"]["messages_sent"] == 4

    assert "decision_quality" in report
    assert "invalid_actions" in report["decision_quality"]["c1"]


def test_report_includes_composite_and_pareto():
    """Report includes composites and Pareto front."""
    state = _minimal_state()
    collector = MetricCollector.create(state)

    report = collector.report(state)

    assert "composites" in report
    assert "c1" in report["composites"]
    assert "c2" in report["composites"]
    assert isinstance(report["composites"]["c1"], int)  # Composite is integer for ranking stability

    assert "pareto_front" in report
    assert isinstance(report["pareto_front"], list)


def test_procedural_scenario_generation():
    """Procedural scenarios generate deterministically from seed."""
    # Generate same seed twice
    scenario1 = generate_scenario(1000)
    scenario2 = generate_scenario(1000)

    assert scenario1.id == scenario2.id
    assert scenario1.width == scenario2.width
    assert scenario1.height == scenario2.height
    assert scenario1.biome == scenario2.biome
    assert scenario1.max_turns == scenario2.max_turns
    assert scenario1.spawn_points == scenario2.spawn_points


def test_procedural_scenario_different_seeds():
    """Different seeds produce different scenarios."""
    scenario1 = generate_scenario(1000)
    scenario2 = generate_scenario(1001)

    # At least some aspect should differ
    assert (
        scenario1.width != scenario2.width
        or scenario1.biome != scenario2.biome
        or scenario1.max_turns != scenario2.max_turns
    )


def test_procedural_scenario_ranges():
    """Procedural scenarios sample within specified ranges."""
    # Sample multiple seeds to verify ranges
    widths = set()
    biomes = set()
    max_turns_list = set()

    for seed in range(1000, 1020):
        scenario = generate_scenario(seed)
        widths.add(scenario.width)
        biomes.add(scenario.biome)
        max_turns_list.add(scenario.max_turns)

    # Should sample multiple values from each range
    assert len(widths) > 1
    assert all(w in PROCEDURAL_WIDTH_OPTIONS for w in widths)

    assert len(biomes) > 0
    assert all(b in PROCEDURAL_BIOME_OPTIONS for b in biomes)

    assert len(max_turns_list) > 0


def test_procedural_scenario_spawn_points():
    """Procedural scenarios have exactly 4 spawn points within map bounds."""
    for seed in range(1000, 1010):
        scenario = generate_scenario(seed)

        assert len(scenario.spawn_points) == PROCEDURAL_SPAWN_COUNT
        for spawn in scenario.spawn_points:
            assert 0 <= spawn.x < scenario.width
            assert 0 <= spawn.y < scenario.height


def test_get_scenario_with_procedural_id():
    """get_scenario can reconstruct procedural scenarios by ID."""
    original = generate_scenario(1234)
    reconstructed = get_scenario(original.id)

    assert original.id == reconstructed.id
    assert original.width == reconstructed.width
    assert original.height == reconstructed.height
    assert original.biome == reconstructed.biome
    assert original.spawn_points == reconstructed.spawn_points


def test_gather_radius_constant():
    """GATHER_RADIUS constant is accessible for validation."""
    # This is used in procedural scenario validation
    assert GATHER_RADIUS == 4
    assert isinstance(GATHER_RADIUS, int)


def test_efficiency_metrics_with_nonzero_cost():
    """Efficiency ratios are calculated correctly when denominators are nonzero."""
    state = _minimal_state()
    collector = MetricCollector.create(state)

    composite = 100  # Integer composite score
    cost_data = {
        "model_calls": 10,
        "mcp_calls": 50,
        "input_tokens": 1000,
        "output_tokens": 2000,
        "latency_ms": 5000,
        "server_latency_ms": 120000,  # 2 minutes
        "timeouts": 0,
        "reconnects": 0,
        "budget_exceeded": 0,
    }

    efficiency = collector._calculate_efficiency_metrics(composite, cost_data)

    # composite / (2000 / 1000) = 100 / 2 = 50.0
    assert efficiency["composite_per_thousand_output_tokens"] == 50.0

    # composite / (120000 / 60000) = 100 / 2 = 50.0
    assert efficiency["composite_per_minute_thinking_time"] == 50.0

    # composite / (50 / 100) = 100 / 0.5 = 200.0
    assert efficiency["composite_per_hundred_mcp_calls"] == 200.0


def test_efficiency_metrics_with_zero_cost():
    """Efficiency ratios are null when denominators are zero (scripted baseline case)."""
    state = _minimal_state()
    collector = MetricCollector.create(state)

    composite = 100
    cost_data = {
        "model_calls": 0,
        "mcp_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,  # Scripted baseline: no tokens
        "latency_ms": 0,
        "server_latency_ms": 0,  # No thinking time
        "timeouts": 0,
        "reconnects": 0,
        "budget_exceeded": 0,
    }

    efficiency = collector._calculate_efficiency_metrics(composite, cost_data)

    # All ratios are null when denominators are zero
    assert efficiency["composite_per_thousand_output_tokens"] is None
    assert efficiency["composite_per_minute_thinking_time"] is None
    assert efficiency["composite_per_hundred_mcp_calls"] is None


def test_efficiency_metrics_rounding():
    """Efficiency metrics are rounded to 4 decimals."""
    state = _minimal_state()
    collector = MetricCollector.create(state)

    composite = 123
    cost_data = {
        "model_calls": 0,
        "mcp_calls": 100,
        "input_tokens": 0,
        "output_tokens": 3333,  # Not divisible evenly
        "latency_ms": 0,
        "server_latency_ms": 77777,
        "timeouts": 0,
        "reconnects": 0,
        "budget_exceeded": 0,
    }

    efficiency = collector._calculate_efficiency_metrics(composite, cost_data)

    # Check that values are rounded to 4 decimals
    if efficiency["composite_per_thousand_output_tokens"] is not None:
        # Round to check it has at most 4 decimals
        val = efficiency["composite_per_thousand_output_tokens"]
        assert len(str(val).split(".")[-1]) <= 4

    if efficiency["composite_per_minute_thinking_time"] is not None:
        val = efficiency["composite_per_minute_thinking_time"]
        assert len(str(val).split(".")[-1]) <= 4

    if efficiency["composite_per_hundred_mcp_calls"] is not None:
        val = efficiency["composite_per_hundred_mcp_calls"]
        assert len(str(val).split(".")[-1]) <= 4


def test_cost_quality_front_dominated_colony():
    """Cost-quality front identifies dominated colonies."""
    state = _minimal_state()
    collector = MetricCollector.create(state)

    composites = {"c1": 100, "c2": 150}  # c2 has higher score
    cost_data = {
        "c1": {"output_tokens": 1000, "mcp_calls": 50},
        "c2": {"output_tokens": 1000, "mcp_calls": 50},  # c2 has same cost but higher score
    }

    front = collector._calculate_cost_quality_front(composites, cost_data, ["c1", "c2"])

    # c2 dominates c1 (higher score, same cost), so c1 is off the front
    assert "c2" in front
    assert "c1" not in front


def test_cost_quality_front_tradeoff():
    """Cost-quality front includes colonies with score-cost tradeoff."""
    state = _minimal_state()
    collector = MetricCollector.create(state)

    composites = {"c1": 100, "c2": 120}  # c2 has higher score
    cost_data = {
        "c1": {"output_tokens": 500, "mcp_calls": 10},    # c1 is more efficient
        "c2": {"output_tokens": 2000, "mcp_calls": 100},  # c2 costs more
    }

    front = collector._calculate_cost_quality_front(composites, cost_data, ["c1", "c2"])

    # Both should be on the front: c1 is on the efficient frontier, c2 is too
    # (trade-off between cost and score)
    assert "c1" in front
    assert "c2" in front


def test_report_includes_efficiency_and_cost_quality_front():
    """Report includes efficiency metrics and cost-quality front."""
    state = _minimal_state()
    collector = MetricCollector.create(state)

    # Manually set some cost data
    report = collector.report(state)

    assert "efficiency" in report
    assert "cost_quality_front" in report

    # Efficiency should have entries for each colony
    assert "c1" in report["efficiency"]
    assert "c2" in report["efficiency"]

    # cost_quality_front should be a list of colony IDs
    assert isinstance(report["cost_quality_front"], list)


def test_efficiency_and_composites_determinism():
    """Efficiency metrics and Pareto fronts are deterministic for identical inputs."""
    state1 = _minimal_state()
    collector1 = MetricCollector.create(state1)
    report1 = collector1.report(state1)

    state2 = _minimal_state()
    collector2 = MetricCollector.create(state2)
    report2 = collector2.report(state2)

    # Composites should be identical
    assert report1["composites"] == report2["composites"]

    # Pareto fronts should be identical
    assert report1["pareto_front"] == report2["pareto_front"]
    assert report1["cost_quality_front"] == report2["cost_quality_front"]

    # Efficiency metrics should be identical (including null values)
    assert report1["efficiency"] == report2["efficiency"]


def test_end_to_end_match_with_metrics():
    """End-to-end: run a small match and verify metrics collection."""
    with TemporaryDirectory() as tmpdir:
        scenario = BASIC_SURVIVAL
        config = RunConfig(
            scenario=scenario,
            seed=42,
            colony_count=2,
            output_dir=Path(tmpdir),
            controller_kinds=("survivalist", "trader"),
        )
        report = run_match(config)

        # Verify metrics are collected
        assert report.metrics is not None
        assert "survival" in report.metrics
        assert "composites" in report.metrics
        assert "pareto_front" in report.metrics
        assert "efficiency" in report.metrics
        assert "cost_quality_front" in report.metrics

        # Verify report.json was written with new fields
        report_data = json.loads(report.report_path.read_text())
        assert "composites" in report_data["metrics"]
        assert "pareto_front" in report_data["metrics"]
        assert "efficiency" in report_data["metrics"]
        assert "cost_quality_front" in report_data["metrics"]
        assert "exploration" in report_data["metrics"]
        assert "labour" in report_data["metrics"]
        assert "recovery" in report_data["metrics"]
        assert "communication" in report_data["metrics"]
