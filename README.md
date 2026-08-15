# Castle Benchmark

*[Türkçe](README.tr.md)*

A deterministic, playable survival-colony benchmark driven over MCP. No Godot: the
authoritative simulation is Python, the live service is FastAPI, and the isometric client
is PixiJS. PixelLab output is loaded through a semantic manifest.

## What this measures

The benchmark puts several agents in the same world, each running one colony, and scores
what they do with eighty turns of scarcity. The world is deterministic and seeded, so two
agents given the same seed face exactly the same map, the same weather and the same
hazards — any difference in outcome is a difference in play.

Each colony sees only what it has explored, and only its own live intelligence. A rival's
buildings stay on the map once discovered, but what that rival is doing right now is
visible only inside your sight radius. Turns resolve simultaneously behind a barrier, so
nobody benefits from answering faster.

An agent is pressed on six things:

**Supply under scarcity.** Colonists eat and drink every turn. Fall short and they sicken;
sick colonists cannot work, which makes the next turn harder. Perishables have a storage
ceiling, so hoarding is not a strategy and a surplus has to be spent or traded.

**Long-horizon investment.** Farms, wells, camps, quarries, mines, workshops and clinics
cost resources now and repay over many turns. Gathering wood, stone or ore without the
matching extraction structure collects at half strength, so the opening is a real choice
between digging today and building to dig faster tomorrow.

**Information gathering.** Fog is not decoration. Terrain and buildings stay remembered
once seen, but discovering them costs: a scout eats provisions and occupies a colonist for
the whole journey, and that colonist gathers nothing while away. Exploring competes
directly with producing, for the whole match rather than only at the start.

**Labour allocation.** A colony gets two actions a turn, bounded further by the colonists
actually available. Gathering scales with the share of people at home, and each producing
structure needs a worker. Sending people scouting, or letting them fall sick, is felt
everywhere.

**Diplomacy and force.** Colonies can contact, trade, ally or declare war. Trade loses a
fifth in transit unless the seller runs a market; a raid steals food and damages a
building; barracks blunt the loot and walls blunt the damage, but a walled colony without
a gate cannot trade at all.

**Recovery.** Fire starts on a schedule, burns a building down over several turns and
spreads to its neighbours. Ruins persist. A colony that loses its housing leaves colonists
exposed, and they sicken until it rebuilds.

### How it is scored

`run_report` returns raw axes rather than a single number, so a run can be read rather than
just ranked: survival and end turn, population trajectory, resources held, trade and
aggression counts, invalid actions, timeouts and reconnects, server-measured MCP calls, and
adapter-reported tokens and latency. Metrics are attributed per controller *tenure*, so if
an agent drops and is replaced mid-match the two stretches stay separate.

### What keeps it fair

The rules are published, not guessed. `benchmark.rules` returns every constant the
simulation uses — build costs, yields, action budget, scout cost, sight radius, fire
damage, trade ratios — read live from the code, so an agent plans against the real numbers
instead of burning turns inferring them. No map or rival state is exposed through it.

Determinism is enforced, not assumed: every run writes a per-turn state hash and
`castle-benchmark replay` recomputes them. Identical actions produce identical hashes
regardless of how long an agent took to think.

## Quick start

Requirements: Python 3.12–3.14, `uv`, Node.js 22+ and npm.

```bash
uv sync --extra dev --locked
npm --prefix frontend ci
uv run python tools/build_asset_manifest.py
npm --prefix frontend run build
uv run castle-benchmark serve
```

Open `http://127.0.0.1:8000`. Pick a scenario and seed, select a cell on the map and
gather or build, or use the diplomacy, trade, policy and raid actions. Once the human
colony has acted, the remaining colonies submit deterministic baseline decisions through
the same contract.

## Headless benchmark

```bash
uv run castle-benchmark run --scenario basic-survival-v1 --seed 17 --colonies 4 --output runs
uv run castle-benchmark replay runs/basic-survival-v1-seed-17
uv run castle-benchmark report runs/basic-survival-v1-seed-17
```

Every run produces `metadata.json`, per-turn `turns.jsonl`, `snapshots.jsonl`,
`report.json` and `summary.sqlite3`. Replay verification recomputes the canonical SHA-256
state hash of each turn.

## Structure economy

Production structures (farm, well, lumber camp, quarry, mine, workshop, clinic, market)
and defensive ones (barracks, wall, gate) work only while `operational`. A working
`warehouse` raises the storage ceiling for perishables — food and water — while damaged,
burning, ruined or half-built ones raise nothing. Wood, stone, ore, tools and influence
stockpile without limit; food and water need a working warehouse to go beyond the base
ceiling. At the ceiling a gather is rejected (`store_full`), structure production stops,
and a trade that would overfill the store is refused.

## MCP connection

For stdio MCP clients such as Codex or OpenCode, point the project path at your own
machine:

```toml
[mcp_servers.castle-benchmark]
command = "uv"
args = ["--directory", "/absolute/path/to/pixellab-castle", "run", "castle-benchmark-mcp"]
env = { CASTLE_BENCHMARK_ORCHESTRATOR_TOKEN = "a-long-random-capability" }
```

For HTTP-based inspection:

```bash
uv run castle-benchmark-mcp --transport streamable-http
```

Core tools:

- `benchmark.rules`: every deterministic rule and constant. Call this first.
- `benchmark.create_match`: creates a seeded match and its colony capability tokens.
- `benchmark.join_match`: hands one colony token to a controller, using the admin capability.
- `benchmark.observe`: the fog-limited observation for the controlled colony only.
- `benchmark.submit_actions`: submits actions into the simultaneous turn barrier.
- `benchmark.record_usage`: records real token and latency measurements.
- `benchmark.run_report`: live score and measurement report, using the admin token.

See the [benchmark protocol](docs/benchmark-protocol.md) for the full contract and the
fairness rules.

## Multi-agent remote session (lobby and pairing)

Alongside the single-player `create_match` flow there is a session-based flow that
connects several independent model agents to one match safely. Agents control only their
own colony; admin and orchestrator capabilities never reach them.

Orchestrator secret (local stdio):

```bash
export CASTLE_BENCHMARK_ORCHESTRATOR_TOKEN="a-long-random-capability"
uv run castle-benchmark-mcp --transport stdio
```

Remote streamable HTTP — serve only behind an explicit allowlist and TLS termination. The
MCP proxy does not terminate TLS itself, and `X-Forwarded-For` is trusted only from
`--trusted-proxy` CIDRs:

```bash
export CASTLE_BENCHMARK_ORCHESTRATOR_TOKEN="a-long-random-capability"
uv run castle-benchmark-mcp --transport streamable-http --trusted-proxy 10.0.0.0/8
```

Session flow, with each agent in its own loop:

1. `benchmark.create_session { orchestrator_token, scenario_id, seed, colony_count }`
   → `admin_token`, which stays with the orchestrator.
2. For each `cN` slot, `benchmark.create_pairing { admin_token, colony_id }`
   → a single-use `pairing_code` that expires in ten minutes.
3. On its own machine the agent calls `benchmark.claim_slot { pairing_code, identity }`
   → a `controller_token` scoped to that colony alone.
4. `benchmark.heartbeat { controller_token, turn, status }` to report `connected`/`ready`.
5. The orchestrator calls `benchmark.start_match { admin_token }`.
6. Agent loop: `benchmark.observe` → decide → `benchmark.submit_actions` →
   `benchmark.record_usage`, watching `benchmark.match_status` until terminal.
7. `benchmark.replace_controller { admin_token, colony_id, replacement, baseline_kind }`
   hands a dropped agent's colony to a baseline. The old and new controllers keep separate
   `tenure_metrics` rows in `run_report`.
8. `benchmark.run_report { admin_token }` → terminal state and raw measurements.

The four-agent end-to-end reference (`tests/e2e/test_remote_agents.py`) proves connecting,
playing, reporting and replay verification across all three official biomes. In the
service, `service.write_resolved_turns(admin_token, writer)` exports the turn stream
through an `ArtifactWriter`, and `uv run castle-benchmark replay <run-dir>` verifies those
artifacts again.

## Verification

```bash
scripts/gate.sh
```

The gate rebuilds the manifest, runs the Python and TypeScript tests, builds the production
client, produces a full headless run and verifies the replay hashes.

## PixelLab asset pipeline

Downloaded generations live under `assets/generated/`, with prompt, seed and job id
recorded in `assets/generated/lineage.json`. Character provenance lives beside the sprites
instead, in files such as `chars/scout/SOURCE.md`. `tools/build_asset_manifest.py` reads
every RGBA size and anchor and writes `assets/manifest.json`. The client binds to semantic
keys such as `structure.market.operational` and `effect.fire.loop.0` rather than to
filenames.

## Troubleshooting

- Blank map: run `uv run python tools/build_asset_manifest.py`, then
  `npm --prefix frontend run build`.
- `stale_turn`: call `benchmark.observe` again and submit with the current turn number.
- Turn stuck `pending`: the controllers in `waiting_for` have not submitted yet; the
  deadline manager should complete their action as a measured `wait`.
- Replay mismatch: do not edit the run files; `uv run castle-benchmark replay <run-dir>`
  reports the first turn that differs.
