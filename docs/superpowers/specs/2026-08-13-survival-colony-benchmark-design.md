# Survival Colony Benchmark Design

## Product intent

`pixellab-castle` is an independent, end-to-end playable Survival Colony
Benchmark. It evaluates how model-controlled colonies adapt to different
biomes, grow, trade, cooperate, recover from disasters, expand, and fight.
Humans use the same action contract as models, so every benchmark scenario is
also manually playable and debuggable.

The benchmark is the product, not an analytics layer added after the game. A
rule belongs in the authoritative simulation only if its inputs, outputs, and
effects can be recorded, replayed, and compared.

## Goals

- Run deterministic, seed-based matches with one to eight colonies; four is the
  default official match size.
- Let MCP clients and humans observe and control colonies through one versioned
  action schema.
- Complete the playable loop: gather, build, grow, meet, trade or fight,
  survive disasters, finish, score, and replay.
- Measure behavior on multiple independent axes instead of imposing one ideal
  strategy.
- Run headless matches much faster than real time while a browser client can
  render a live match or replay with PixelLab assets.
- Preserve and extend the existing Python/Pillow asset pipeline.

## Non-goals for the first complete release

- Pixel-based visual perception as the model's primary observation.
- Individual citizen or soldier micromanagement.
- Free-form action parsing; natural language is diplomatic flavor only.
- Real-money trading, public matchmaking, or an internet-hosted service.
- Making browser animation timing authoritative.

## Architecture

The system has one authoritative deterministic Python simulation and several
replaceable adapters:

```text
MCP clients       baseline agents        human web controls
     \                  |                      /
      +----------- action/observation contract --------+
                              |
                    turn barrier + validator
                              |
                   deterministic Python SimCore
                              |
             event log + snapshots + metrics + state hashes
                              |
                 HTTP/WebSocket read model gateway
                              |
                  TypeScript + PixiJS renderer
```

The simulation never imports Pillow, FastAPI, MCP, or frontend code. It uses
integer quantities and grid/sub-tile integer positions. All pseudo-randomness
comes from explicitly named, seed-derived streams. Rendering may interpolate,
but it cannot mutate game state.

### Technology

- Python 3.12+ with `uv` for the simulation, runner, API, MCP server, and tests.
- Pydantic for versioned boundary schemas; internal simulation state remains
  plain dataclasses and enums.
- FastAPI/uvicorn for HTTP, WebSocket, static frontend serving, and health.
- Official Python MCP SDK using `stdio` locally and Streamable HTTP for a
  standalone benchmark service.
- TypeScript, Vite, and PixiJS for the browser client.
- JSON Lines for immutable per-match event logs and SQLite for searchable run
  summaries and metric aggregates.
- Existing Pillow scripts remain an offline asset/reference renderer.

Dependency versions are locked in `uv.lock` and the frontend lockfile. Official
benchmark reports include those lockfile hashes, the scenario version, and the
simulation ruleset version.

## Authoritative domain model

### World

The world is a rectangular isometric logical grid. Each cell stores biome,
elevation class, movement cost, buildability, water state, resource deposits,
territory control, and hazard intensity. Maps are generated from a scenario and
seed. The existing `river_corners`, Wang masks, and biome generation ideas are
ported into a side-effect-free generator that returns JSON-serializable data.

Initial biomes are:

- River/grassland: balanced food and wood, reliable water, flood risk.
- Desert: scarce water and wood, strong mineral and trade opportunities,
  heat/drought risk.
- Snow: weak farming, high heating demand, strong wood and mineral access,
  cold/blizzard risk.

Official scenario suites rotate colony spawn positions over the same maps to
reduce positional bias.

### Colonies and population

A colony has resources, stockpile capacity, policies, known map cells,
relationships, structures, squads, population cohorts, and a rolling need
history. Population is aggregated into healthy, injured, sick, and hungry
cohorts plus assigned jobs.

Housing is a hard population cap. Immigration additionally requires spare
housing, sustainable food and water, safety, and colony attraction. More houses
therefore enable growth but do not guarantee it. Starvation, dehydration,
untreated illness, exposure, and combat cause measurable cohort losses.

### Resources and work

Initial resources are food, water, wood, stone, ore, tools, and influence.
Resources have stockpile limits. Production uses assigned workers, structure
condition, biome modifiers, tools, and transport distance. Deposits can deplete
or renew at explicit scenario-defined rates.

Every turn has a work budget. Construction, production, hauling, healing,
firefighting, scouting, and military readiness compete for that budget. Colony
policies adjust priorities rather than creating resources.

### Structures

The first complete ruleset includes headquarters, house, warehouse, well,
farm, lumber camp, quarry, mine, market, workshop, clinic, barracks,
watchtower, wall, and gate.

Structures progress through `planned`, `foundation`, `building`, `operational`,
`damaged`, `burning`, `ruined`, and `repairing`. Construction requires a valid
cell footprint, resources, workers, and turns. Only sufficiently complete and
healthy structures provide their full function. Houses add capacity, markets
unlock formal trade, barracks unlock squads, and workshops unlock tools and
advanced repairs.

### Diplomacy and trade

Relationships progress through unknown, contacted, neutral, trade agreement,
alliance, and war. Structured proposals support one-off exchange, recurring
trade, aid, passage, ceasefire, and alliance. A short natural-language message
may accompany a proposal, but only structured terms have rules effects.

Offers reserve promised resources until accepted, rejected, expired, or
cancelled. Agreement breaches and surprise attacks affect trust and influence.
All offers, messages, responses, deliveries, and breaches are recorded.

### Combat

Combat is squad-based. Orders are defend, patrol, escort, raid, attack, and
retreat. There is no automatic inter-colony aggression while at peace. Models
may declare war or initiate a surprise raid; the latter has explicit diplomatic
costs. Resolution uses integer strength, readiness, terrain, fortification,
supply, and a seeded combat stream. Civilians are not direct controllable
combat units.

### Hazards and disasters

Weather, fire, and limited disease are included. Scenario seeds schedule
hazards independently of controllers. Fire can begin through weather, combat,
or neglect; it damages a structure and can spread through deterministic rolls.
Water access, available work, emergency policy, and spacing affect suppression.
Disaster fairness is evaluated from the pre-generated schedule, not wall-clock
timing.

### Policies

Controllers can set rationing, migration, labor priority, military posture,
trade openness, and emergency response. Policy changes have a cooldown and are
logged, making crisis response latency measurable.

## Turn protocol

The game appears continuous in the browser but resolves simultaneous turns:

1. SimCore closes turn `T-1` and creates immutable observation `T` for each
   colony, filtered by knowledge and sight.
2. The orchestrator publishes observations and opens the action deadline.
3. Every controller submits one action batch with the observed turn number.
4. The validator rejects stale, unauthorized, malformed, over-budget, or
   impossible actions with stable error codes.
5. At the deadline or when all controllers are ready, missing/invalid batches
   become `wait` and are counted.
6. SimCore resolves policies, reservations, movement, work, construction,
   production, needs, trade, combat, hazards, visibility, immigration, deaths,
   and terminal conditions in a fixed documented order.
7. It emits domain events, metrics deltas, a canonical snapshot, and SHA-256
   state hash.

Actions never partially apply silently. An action batch has independent items;
each item produces `accepted`, `rejected`, or `deferred` with a reason code.
Accepted actions resolve according to the simultaneous-turn rules, so acceptance
does not guarantee success against competing actions.

## Controller and MCP contract

The versioned observation contains match/scenario metadata, current turn,
deadline budget, colony summary, visible grid delta, known entities, active
plans, relationships, messages, recent events, valid action kinds, and resource
budgets. Hidden cells and enemy private state are never serialized.

Core controller operations are:

- `benchmark.list_scenarios`
- `benchmark.create_match`
- `benchmark.join_match`
- `benchmark.observe`
- `benchmark.submit_actions`
- `benchmark.match_status`
- `benchmark.run_report`

MCP tools wrap the same application service used by HTTP, baseline agents, and
tests. A controller token is scoped to exactly one colony and cannot request an
omniscient snapshot. Admin endpoints use a separate capability.

Baseline controllers are random-valid, survivalist, trader, expansionist, and
militarist. They are deterministic for a controller seed and provide
interpretable comparison floors.

## Benchmark design

### Scenario suites

The first official suite contains basic survival, biome adaptation, scarcity
and trade, disaster recovery, diplomacy and alliance, contested frontier, and a
four-colony mixed tournament. Development uses three seeds, candidate checks ten
seeds, and an official comparison at least thirty seeds per scenario version.

### Measurements

Reports preserve independent axes:

- Survival: turns alive, death rate, hunger and dehydration exposure.
- Growth: population curve, migration, housing utilization.
- Prosperity: production, reserves, health, safety.
- Efficiency: output per resource/work unit, idle and wasted work.
- Resilience: disaster loss and time to recover.
- Trade: proposals, acceptance, volume, surplus, dependency.
- Diplomacy: alliances, trust, commitments, breaches.
- Aggression: first hostility, raids, declarations, damage caused.
- Expansion: controlled area, outposts, frontier movement.
- Adaptation: latency and effectiveness of policy changes after shocks.
- Decision quality: invalid, stale, cancelled, and failed action rates.
- Agent cost: model calls, MCP calls, input/output tokens when provided,
  latency, timeouts, and monetary cost when provided.

Leaderboards show a vector/profile plus scenario-specific outcomes. Any
composite score publishes its exact normalized formula and never replaces raw
axes.

### Reproducibility artifacts

Each run stores scenario and seed, controller identities and versions, seat
rotation, rule/config hashes, dependency lock hashes, observations, raw submitted
action payloads, validation outcomes, applied events, snapshots at intervals,
per-turn hashes, metrics, termination reason, and cost metadata. Private model
reasoning is neither requested nor stored.

Replaying the same event/action stream must reproduce the same state-hash
sequence. A mismatch fails the benchmark run.

## Browser client

The browser offers live spectator, human controller, and replay modes. It shows
the isometric world, fog of war when controlling a colony, timelines, colony
cards, relationships, metrics, action feedback, and playback controls.

PixiJS renders raw tiles and sprites, not precomposed biome screenshots. The
existing `TW=48`, `TH=24`, `(i+j, i)` painter order, sprite anchors, and eight
directions become explicit asset metadata. Movement and construction are
interpolated from authoritative events. Building states select sprite variants;
fire and smoke are overlay animations. UI animation may be skipped at high
headless/replay speed without losing events.

Human commands are translated into the same validated action batches as MCP
commands. Omniscient spectator state is available only through an admin-scoped
connection.

## PixelLab asset pipeline

Current assets are the first playable set: three terrain families, 58 kit
tiles, buildings/props, ten eight-direction villagers, and a six-frame walk
animation. Existing Python compositors remain reference renders and offline
preview tools; import-time side effects in legacy scripts are isolated.

An asset manifest maps stable semantic keys to source files, dimensions,
anchors, directions, frames, states, and PixelLab source/job identifiers.
Runtime code refers only to semantic keys.

PixelLab MCP is used incrementally after gameplay works:

1. Reuse and catalogue existing output.
2. Produce missing operational buildings in one consistent isometric style.
3. Produce construction, damaged, burning, and ruined states.
4. Produce character role variants and essential work/combat animations.
5. Validate transparent bounds, anchors, directions, and frame sizes before an
   asset enters the manifest.

Generation prompts, seeds, object IDs, job IDs, and selected outputs are stored
in the repository so the asset lineage is reproducible. Generated output is
never allowed to change simulation balance.

## Error handling and isolation

- Boundary validation returns stable machine-readable codes and safe messages.
- Controller timeout or disconnect becomes `wait`; the match continues.
- A renderer or WebSocket failure cannot stop a headless match.
- Match state is owned by one runner process in the first release. Commands are
  serialized at the turn barrier; SQLite is not the authoritative live store.
- Event logs append atomically. A completed-turn marker is written only after
  events, snapshot/hash, and metrics are durable.
- A crashed run can resume only from the last completed snapshot and event
  boundary; otherwise it is marked invalid rather than guessed forward.
- Unknown asset keys render a visible placeholder and generate a client error,
  without affecting the simulation.

## Testing strategy

- Unit tests cover every pure rule with fixed seeds and boundary cases.
- Property tests cover conservation, capacity, non-negative resources,
  visibility isolation, action budgets, and invariant preservation.
- Golden tests lock world generation, observation filtering, resolution order,
  and state hashes for versioned scenarios.
- Replay tests run matches twice and require identical hash sequences.
- Contract tests exercise the same action suite through direct Python, HTTP,
  and MCP adapters.
- Browser tests verify loading, human command submission, fog of war, event
  animation, and replay seeking.
- A smoke gate runs a complete small scenario using baseline agents, produces a
  report, and replays it successfully.

## Delivery slices

1. Benchmark kernel: deterministic world, economy, building/population loop,
   baseline agents, event log, metrics, report, and replay verification.
2. Playable gateway: HTTP/WebSocket/MCP contracts and browser live/replay client.
3. Strategic systems: three biomes, diplomacy/trade, squads/combat, fire,
   weather/disease, policies, and all scenario suites.
4. PixelLab completion: semantic manifest, missing building states and essential
   animations, visual validation, and polished benchmark dashboard.

Each slice ends in executable, tested software. The first public-ready release
requires all four slices and the full smoke gate.

## Acceptance criteria

- A user can start the stack with documented commands, open the browser, join a
  colony, and complete a match.
- Four baseline or MCP-controlled colonies can finish every official scenario
  headlessly without human intervention.
- The gather/build/grow/contact/trade-or-fight/finish loop is present.
- All three biomes materially alter resource and hazard strategy.
- Construction, damage, fire, and ruin have authoritative states and visible
  representations.
- A completed run produces event log, snapshots, hash sequence, metric vector,
  cost metadata, report, and browser replay.
- Replaying a run reproduces every state hash.
- A controller cannot observe or command another colony without an admin token.
- Automated Python, contract, browser, and end-to-end smoke gates pass from a
  clean checkout.
