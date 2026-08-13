# Survival Colony Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, MCP-controllable, browser-playable survival colony benchmark with scoring and reproducible replay.

**Architecture:** A pure Python SimCore owns all state and resolves simultaneous turns. Thin runner, HTTP/WebSocket, MCP, baseline-agent, persistence, and PixiJS adapters consume one versioned observation/action contract; the browser is never authoritative.

**Tech Stack:** Python 3.12+, uv, Pydantic, FastAPI, official MCP Python SDK, pytest, Hypothesis, TypeScript, Vite, PixiJS, Vitest, Playwright, Pillow asset tools.

**Spec:** `docs/superpowers/specs/2026-08-13-survival-colony-benchmark-design.md`

## Global Constraints

- The Python simulation must not import Pillow, FastAPI, MCP, or frontend modules.
- Quantities and authoritative positions are integers; all randomness comes from named seed-derived streams.
- Four colonies are the default, while scenarios support one through eight.
- Missing, malformed, stale, or timed-out controller input becomes a measured `wait` without stopping the match.
- Every completed turn writes domain events, metrics, a canonical snapshot, and a SHA-256 state hash.
- The browser and replay renderer may interpolate but cannot mutate simulation state.
- Runtime code references assets through semantic manifest keys only.
- Official result artifacts include scenario, ruleset, controller, dependency-lock, event, metric, and cost provenance.

## File structure

```text
pyproject.toml                       Python package, commands, locked dependencies
src/castle_benchmark/
  domain.py                         enums and immutable boundary-neutral dataclasses
  actions.py                        versioned action dataclasses and validation results
  scenarios.py                      scenario definitions and official suites
  world.py                          deterministic biome/map generation and visibility
  engine.py                         turn barrier and fixed-order SimCore resolution
  systems.py                        economy, population, diplomacy, combat and hazards
  observation.py                    fog-of-war observation projection
  events.py                         canonical events, snapshots and hash calculation
  metrics.py                        metric accumulation and reports
  persistence.py                    JSONL artifacts, snapshots and SQLite summaries
  agents.py                         deterministic baseline controllers
  runner.py                         headless match orchestration and replay verifier
  schemas.py                        Pydantic HTTP/MCP boundary schemas
  service.py                        match lifecycle application service
  api.py                            FastAPI, WebSocket and static client adapter
  mcp_server.py                     official MCP tool adapter
  cli.py                            serve, run, replay and report commands
frontend/
  src/api.ts                        typed HTTP/WebSocket client
  src/game.ts                       Pixi isometric renderer and event animations
  src/ui.ts                         human controls, timelines and benchmark panels
  src/main.ts                       application lifecycle
  tests/                            Vitest unit tests
assets/manifest.json                semantic asset metadata and PixelLab lineage
tests/                              Python unit, property, contract and smoke tests
```

---

### Task 1: Package foundation and authoritative types

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/castle_benchmark/__init__.py`
- Create: `src/castle_benchmark/domain.py`
- Create: `src/castle_benchmark/actions.py`
- Test: `tests/test_domain.py`

**Interfaces:**
- Produces: `Position`, `ResourceStock`, `ColonyState`, `WorldState`, `MatchState`, `ActionBatch`, `ActionResult`.

- [ ] **Step 1: Write failing invariants and serialization tests**

```python
def test_resource_stock_rejects_negative_values():
    with pytest.raises(ValueError):
        ResourceStock(food=-1)

def test_action_batch_is_bound_to_turn_and_colony():
    batch = ActionBatch(turn=3, colony_id="c1", actions=(WaitAction(),))
    assert (batch.turn, batch.colony_id, batch.actions[0].kind) == (3, "c1", "wait")
```

- [ ] **Step 2: Run `uv run pytest tests/test_domain.py -q` and confirm missing-module failure**

- [ ] **Step 3: Implement frozen/slot dataclasses, string enums, non-negative stock checks, and tagged action types**

```python
@dataclass(frozen=True, slots=True)
class Position:
    x: int
    y: int

@dataclass(frozen=True, slots=True)
class ActionBatch:
    turn: int
    colony_id: str
    actions: tuple[GameAction, ...]
```

- [ ] **Step 4: Run the focused tests, then `uv lock`**

- [ ] **Step 5: Commit `feat: establish benchmark domain model`**

### Task 2: Deterministic scenarios, world generation and visibility

**Files:**
- Create: `src/castle_benchmark/scenarios.py`
- Create: `src/castle_benchmark/world.py`
- Test: `tests/test_world.py`
- Test: `tests/golden/world_seed_17.json`

**Interfaces:**
- Consumes: `Position`, terrain/resource enums from `domain.py`.
- Produces: `Scenario`, `derive_seed(seed: int, stream: str) -> int`, `generate_world(scenario, seed) -> WorldState`, `visible_cells(state, colony_id) -> frozenset[Position]`.

- [ ] **Step 1: Add a fixed-seed golden test and spawn-rotation fairness test**

```python
def test_world_seed_17_matches_golden(golden_json):
    world = generate_world(BASIC_SURVIVAL, 17)
    assert canonical_world(world) == golden_json("world_seed_17.json")

def test_spawn_rotation_preserves_spawn_set():
    assert set(rotated_spawns(BASIC_SURVIVAL, 0)) == set(rotated_spawns(BASIC_SURVIVAL, 1))
```

- [ ] **Step 2: Run tests and confirm generator symbols are absent**

- [ ] **Step 3: Port river/Wang concepts from `biome.py` into pure generators and add grassland, desert, and snow modifiers**

```python
def derive_seed(seed: int, stream: str) -> int:
    digest = hashlib.sha256(f"{seed}:{stream}".encode()).digest()
    return int.from_bytes(digest[:8], "big")
```

- [ ] **Step 4: Generate and review the golden fixture, then prove a second run is byte-identical**

- [ ] **Step 5: Commit `feat: generate deterministic biome worlds`**

### Task 3: Simultaneous turn engine and colony survival loop

**Files:**
- Create: `src/castle_benchmark/engine.py`
- Create: `src/castle_benchmark/systems.py`
- Test: `tests/test_engine.py`
- Test: `tests/test_invariants.py`

**Interfaces:**
- Consumes: `MatchState`, `ActionBatch`, `Scenario`.
- Produces: `SimCore.create(scenario, seed, colony_count)`, `SimCore.observe_turn()`, `SimCore.resolve(batches) -> TurnResult`.

- [ ] **Step 1: Test gather/build/grow, simultaneous conflicts, resource conservation, and timeout-as-wait**

```python
def test_house_enables_but_does_not_force_immigration(sim):
    result = sim.resolve((build_house(sim, "c1"),))
    assert result.state.colonies["c1"].housing > 8
    assert result.state.colonies["c1"].population == 8

def test_two_colonies_cannot_build_on_same_cell(sim):
    result = sim.resolve((build_at(sim, "c1", 4, 4), build_at(sim, "c2", 4, 4)))
    assert sum(e.kind == "construction_started" for e in result.events) == 1
```

- [ ] **Step 2: Run tests and verify failure before implementation**

- [ ] **Step 3: Implement fixed resolution order, work budgets, structures, stockpiles, production, needs, construction states, immigration, and death**

```python
RESOLUTION_ORDER = (
    "policies", "reservations", "movement", "work", "construction",
    "production", "needs", "trade", "combat", "hazards", "visibility",
    "immigration", "terminal",
)
```

- [ ] **Step 4: Run unit and Hypothesis invariant tests over 100 generated valid action sequences**

- [ ] **Step 5: Commit `feat: resolve deterministic colony turns`**

### Task 4: Diplomacy, trade, combat, policies and disasters

**Files:**
- Modify: `src/castle_benchmark/actions.py`
- Modify: `src/castle_benchmark/systems.py`
- Modify: `src/castle_benchmark/scenarios.py`
- Test: `tests/test_strategy_systems.py`

**Interfaces:**
- Produces: structured offers/responses, squad orders, relation transitions, policy actions, seeded hazard schedule.

- [ ] **Step 1: Test escrow conservation, agreement breach, non-aggression at peace, surprise-raid reputation cost, fire spread, and biome hazards**

```python
def test_trade_reserves_then_transfers_exact_resources(trade_sim):
    offered = trade_sim.offer("c1", "c2", give={"wood": 10}, receive={"food": 5})
    assert trade_sim.stock("c1", "wood") == 40
    trade_sim.accept("c2", offered.id)
    assert trade_sim.stock("c1", "food") == 55

def test_peaceful_squads_do_not_auto_attack(contact_sim):
    result = contact_sim.resolve_wait_turn()
    assert not [event for event in result.events if event.kind == "combat_damage"]
```

- [ ] **Step 2: Run focused tests and confirm expected failures**

- [ ] **Step 3: Implement offers with escrow/expiry, trust/influence, explicit hostility, integer squad combat, fire/disease/weather, and policy cooldowns**

- [ ] **Step 4: Run all simulation and invariant tests**

- [ ] **Step 5: Commit `feat: add strategic colony systems`**

### Task 5: Observations, events, metrics, persistence and replay

**Files:**
- Create: `src/castle_benchmark/observation.py`
- Create: `src/castle_benchmark/events.py`
- Create: `src/castle_benchmark/metrics.py`
- Create: `src/castle_benchmark/persistence.py`
- Test: `tests/test_observation.py`
- Test: `tests/test_replay.py`

**Interfaces:**
- Produces: `project_observation(state, colony_id)`, `canonical_snapshot(state)`, `state_hash(state)`, `ArtifactWriter`, `MetricCollector`, `verify_replay(path)`.

- [ ] **Step 1: Test fog isolation, canonical hashes, append/recovery boundaries, metric axes, and replay equality**

```python
def test_observation_never_leaks_hidden_enemy_stock(sim):
    observation = project_observation(sim.state, "c1")
    assert "resources" not in observation.known_colonies["c2"]

def test_replay_reproduces_hash_sequence(completed_run):
    assert verify_replay(completed_run).actual_hashes == completed_run.expected_hashes
```

- [ ] **Step 2: Run focused tests and confirm missing projection/persistence failures**

- [ ] **Step 3: Implement sorted canonical serialization, SHA-256 hashes, JSONL turn transactions, periodic snapshots, SQLite summaries, and raw metric vectors**

- [ ] **Step 4: Corrupt one replay intentionally in a temporary test and prove verification fails closed**

- [ ] **Step 5: Commit `feat: record measurable reproducible matches`**

### Task 6: Baseline agents, headless runner and official scenario suite

**Files:**
- Create: `src/castle_benchmark/agents.py`
- Create: `src/castle_benchmark/runner.py`
- Create: `src/castle_benchmark/cli.py`
- Test: `tests/test_runner.py`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Produces: `Controller.decide(observation) -> ActionBatch`, five baseline controllers, `run_match(config) -> RunReport`, CLI commands `run`, `replay`, `report`.

- [ ] **Step 1: Test deterministic controllers, complete four-colony match, report artifacts, and replay verification**

```python
def test_full_baseline_match_is_replayable(tmp_path):
    report = run_match(smoke_config(output_dir=tmp_path))
    assert report.termination_reason
    assert verify_replay(report.run_dir).ok
    assert set(report.metrics) >= {"survival", "growth", "prosperity", "aggression"}
```

- [ ] **Step 2: Run smoke test and confirm runner is absent**

- [ ] **Step 3: Implement random-valid, survivalist, trader, expansionist and militarist controllers plus development/candidate/official seed policies**

- [ ] **Step 4: Run a complete headless smoke match twice and compare artifact hashes**

- [ ] **Step 5: Commit `feat: run headless benchmark tournaments`**

### Task 7: HTTP, WebSocket and MCP application service

**Files:**
- Create: `src/castle_benchmark/schemas.py`
- Create: `src/castle_benchmark/service.py`
- Create: `src/castle_benchmark/api.py`
- Create: `src/castle_benchmark/mcp_server.py`
- Test: `tests/test_contracts.py`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Produces: `GameService`, `create_app(service)`, MCP tools named in the spec, controller/admin capability tokens.

- [ ] **Step 1: Write one adapter-neutral contract suite and run it against direct service and HTTP; add MCP tool-list/call tests**

```python
@pytest.mark.parametrize("adapter", ["direct", "http"])
def test_controller_can_only_observe_own_colony(adapter, contract_harness):
    client = contract_harness(adapter)
    assert client.observe("c1-token").colony.id == "c1"
    assert client.observe("c1-token", colony_id="c2").error.code == "forbidden"
```

- [ ] **Step 2: Run contract tests and confirm missing adapters**

- [ ] **Step 3: Implement match lifecycle, token scope, Pydantic schemas, REST routes, live event WebSocket, health, and MCP wrappers over `GameService`**

- [ ] **Step 4: Run direct/HTTP/MCP parity tests including stale actions, invalid schemas, disconnects, and timeout-as-wait**

- [ ] **Step 5: Commit `feat: expose benchmark through HTTP and MCP`**

### Task 8: Asset manifest and PixelLab lineage

**Files:**
- Create: `assets/manifest.json`
- Create: `tools/build_asset_manifest.py`
- Modify: `castle.py`
- Modify: `render_biomes.py`
- Test: `tests/test_assets.py`

**Interfaces:**
- Produces: stable terrain/structure/character/effect semantic keys with paths, anchors, frames, states, and PixelLab provenance.

- [ ] **Step 1: Test every manifest path, RGBA requirement, frame geometry, direction set, and absence of import-time output generation**

```python
def test_manifest_assets_are_valid_pngs(asset_manifest):
    for entry in asset_manifest.values():
        image = Image.open(entry["path"])
        assert image.mode == "RGBA"
        assert image.size == tuple(entry["size"])
```

- [ ] **Step 2: Run asset tests and capture legacy side-effect failures**

- [ ] **Step 3: Isolate legacy scripts behind `main()`, generate the semantic manifest from existing assets, and record known PixelLab tile IDs**

- [ ] **Step 4: Use PixelLab MCP for missing building/state/animation assets, validate completed downloads, and store prompt/seed/job/object lineage in the manifest**

- [ ] **Step 5: Commit `feat: establish reproducible PixelLab asset pipeline`**

### Task 9: PixiJS live game, human control and replay UI

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/api.ts`
- Create: `frontend/src/game.ts`
- Create: `frontend/src/ui.ts`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/style.css`
- Test: `frontend/tests/game.test.ts`

**Interfaces:**
- Consumes: observation, snapshot and event schemas; `assets/manifest.json`.
- Produces: spectator, human controller and replay browser modes.

- [ ] **Step 1: Test isometric coordinates, painter ordering, event-to-animation mapping, and human action serialization with Vitest**

```typescript
it("preserves legacy isometric projection", () => {
  expect(toScreen({x: 2, y: 1}, {x: 0, y: 0})).toEqual({x: 24, y: 36});
});
```

- [ ] **Step 2: Run `npm test` and confirm missing modules**

- [ ] **Step 3: Implement Pixi terrain/entities/fog, camera, construction/fire overlays, timeline, colony metrics, diplomacy feed, action controls, and replay seeking**

- [ ] **Step 4: Run Vitest, TypeScript checks, and production build; manually inspect a live baseline match and replay**

- [ ] **Step 5: Commit `feat: add playable isometric benchmark client`**

### Task 10: End-to-end gate, operator docs and clean-checkout proof

**Files:**
- Create: `README.md`
- Create: `docs/benchmark-protocol.md`
- Create: `scripts/gate.sh`
- Create: `tests/e2e/test_stack.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: documented `uv run castle-benchmark serve`, `run`, `replay`, `report`, `scripts/gate.sh`.

- [ ] **Step 1: Add an end-to-end test that starts the service, creates a match, submits one human action, lets baselines finish, fetches the report, and verifies replay**

```python
def test_complete_stack(stack):
    match = stack.create_demo(seed=17, human_colony="c1")
    stack.submit(match, "c1", [{"kind": "build", "structure": "house", "x": 3, "y": 3}])
    report = stack.finish_with_baselines(match)
    assert report["replay_verified"] is True
```

- [ ] **Step 2: Run the end-to-end test and fix only failures required by the acceptance criteria**

- [ ] **Step 3: Document setup, MCP configuration, scenario/result schemas, benchmark fairness, PixelLab regeneration, and troubleshooting with exact commands**

- [ ] **Step 4: Run `scripts/gate.sh` from a clean environment and confirm Python tests, replay smoke, MCP contracts, frontend tests/build, and end-to-end test all pass**

- [ ] **Step 5: Commit `docs: complete benchmark operator workflow`**
