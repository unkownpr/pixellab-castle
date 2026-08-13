# Agent Lobby and Operations Room Design

## Purpose

Castle Benchmark currently exposes a valid MCP action protocol, but agent
connection is an operator-only technical workflow and the browser cannot show
which controller owns a colony. This release turns controller connectivity
into a first-class benchmark feature.

An operator can create a match, assign every colony to a human, deterministic
baseline, local MCP agent, or remote MCP agent, pair external controllers
without sharing admin capabilities, watch their measurable behavior live, take
over a disconnected slot, finish the match, and compare the resulting profiles.

Private chain-of-thought is never requested, transmitted, or displayed. The
interface shows observations delivered, structured actions returned, measured
usage, latency, failures, and authoritative game outcomes.

## Goals

- Make agent connection understandable without manually copying raw colony or
  admin tokens.
- Support local stdio controllers and remote Streamable HTTP MCP controllers.
- Give every colony an explicit controller slot before a match starts.
- Show connection, identity, turn, action, cost, and outcome telemetry live.
- Keep pairing capabilities separate from match administration and opponent
  observations.
- Preserve deterministic simultaneous-turn fairness when agents have different
  latency or disconnect.
- Replace the current setup-heavy page with a professional benchmark operations
  room while retaining the PixelLab isometric world.

## Non-goals

- Capturing or displaying hidden model reasoning.
- Hosting third-party model credentials in Castle Benchmark.
- General internet matchmaking or public player accounts.
- Letting browser presentation state become authoritative.
- Building a full observability vendor or generic workflow orchestration system.

## Product flow

### 1. Create a session

The operator chooses scenario, seed, colony count, action deadline, and slot
types. A session begins in `lobby`, not immediately at simulation turn zero.

Each colony slot is configured as one of:

- `human`: controlled by the browser with the normal action schema.
- `baseline`: survivalist, trader, expansionist, militarist, or random-valid.
- `external`: claimed by a local or remote MCP controller.

Four slots remain the default. The operator can mix all three controller types
in one match.

### 2. Pair external agents

For each external slot, the service creates a short-lived, single-use pairing
code. The browser shows:

- a copyable pairing code;
- the MCP endpoint;
- a generated Codex/OpenCode/Claude-compatible configuration example;
- a ready-to-copy bootstrap instruction for the agent;
- expiration and connection state.

The external agent connects to the MCP server and calls
`benchmark.claim_slot(pairing_code, identity)`. A successful claim consumes the
code and returns exactly one controller capability. It never returns the admin
capability or another colony's capability.

`identity` contains operator-visible, controller-supplied metadata:

- display name;
- provider;
- model name and optional model version;
- adapter name and version;
- local or remote connection mode;
- optional run label.

The server assigns its own immutable `controller_id`; supplied display fields
are labels, not authorization claims.

### 3. Readiness and start

Human and baseline slots are immediately ready. External slots become ready
after a valid claim and heartbeat. The operator may start only when all
required slots are ready, or explicitly replace an unclaimed external slot
with a baseline.

Starting freezes scenario, seed, slot ownership, controller identities,
ruleset version, deadline policy, and dependency provenance into match
metadata. Pairing codes are invalid after start.

### 4. Live match

Each turn opens simultaneously for every controller. The operations room shows
per slot:

- connected, waiting, thinking, submitted, timed out, disconnected, or taken
  over state;
- last heartbeat and round-trip latency;
- the observation turn and action turn;
- structured last action and validation result;
- cumulative MCP/model calls, token counts, latency, invalid actions, and
  timeouts;
- population, reserves, relation, and current strategy profile derived from
  authoritative events.

The deadline closes the barrier. Missing controller input becomes an explicit,
measured `wait`; a slow controller never changes action resolution order.

### 5. Recovery and takeover

If an external controller misses heartbeats, the slot becomes `disconnected`.
The current turn still completes under the deadline policy. The operator can:

- wait for reconnection using the existing controller capability;
- rotate the capability and create a new one-time pairing code;
- transfer the slot to a selected baseline;
- assume browser-human control.

Every transition is an immutable domain event. Takeover does not rewrite the
controller identity that produced earlier actions; reports segment metrics by
controller tenure.

### 6. Completion and comparison

At terminal state, the operations room switches to results mode. It retains the
map and replay timeline and adds side-by-side strategy profiles for survival,
growth, prosperity, resilience, diplomacy, trade, aggression, decision quality,
and measured cost. Raw axes remain visible; no opaque combined score replaces
them.

## Architecture

```text
local stdio bridge       remote MCP client       human browser
        |                       |                     |
        +--------- Streamable HTTP / stdio ----------+
                                |
                  pairing + controller gateway
                                |
        lobby registry ---- presence/telemetry registry
                  \             /
                   deterministic turn barrier
                              |
                           SimCore
                              |
              domain events + metrics + artifacts
                              |
                 Operations Room read model
```

The existing SimCore remains authoritative and does not import connectivity,
MCP, HTTP, or frontend modules. Lobby and presence state belong to the
application service. Controller transitions are recorded into artifacts but do
not affect deterministic rules except through submitted actions or measured
`wait` substitutions.

## Session and controller model

### Session lifecycle

`draft -> lobby -> running -> completed | cancelled`

- `draft`: mutable scenario and slot configuration.
- `lobby`: configuration frozen except controller replacement and pairing.
- `running`: slot ownership changes only through explicit takeover operations.
- `completed`: immutable results and replay.
- `cancelled`: no benchmark result is published.

### Controller slot

Each slot stores:

- match and colony identifiers;
- controller type and stable `controller_id`;
- identity metadata;
- connection mode;
- readiness/presence status;
- capability hash and rotation generation;
- pairing code hash, expiry, attempt count, and consumed timestamp;
- last heartbeat, observation, submission, latency, and failure code;
- tenure boundaries for report attribution.

Raw pairing codes and raw controller capabilities are never persisted in event
logs or returned by status endpoints.

## MCP contract

Existing gameplay tools remain:

- `benchmark.list_scenarios`
- `benchmark.observe`
- `benchmark.submit_actions`
- `benchmark.match_status`
- `benchmark.record_usage`

Orchestrator and pairing tools become:

- `benchmark.create_session(orchestrator_token, config)`
- `benchmark.create_pairing(admin_token, colony_id)`
- `benchmark.claim_slot(pairing_code, identity)`
- `benchmark.heartbeat(controller_token, turn, status)`
- `benchmark.start_match(admin_token)`
- `benchmark.replace_controller(admin_token, colony_id, replacement)`
- `benchmark.lobby_status(admin_token)`
- `benchmark.run_report(admin_token)`

`benchmark.create_match` is retained as a deprecated orchestrator-only alias
during one protocol version. It does not return controller tokens.

Claiming a slot returns:

```json
{
  "controller_id": "ctl_...",
  "colony_id": "c2",
  "controller_token": "one-secret-capability",
  "scenario_id": "basic-survival-v1",
  "schema_version": "1.1"
}
```

The agent then loops:

1. `benchmark.heartbeat(..., status="ready")`
2. `benchmark.observe(controller_token)`
3. make a decision within its own provider runtime
4. `benchmark.record_usage(...)`
5. `benchmark.submit_actions(...)`
6. repeat until match status is terminal

MCP tool invocation count is measured server-side. Token and provider billing
data remain declared by the adapter and are marked `reported`, not inferred.

## HTTP and live read model

Admin HTTP endpoints:

- `POST /api/sessions`
- `GET /api/sessions/{id}/lobby`
- `POST /api/sessions/{id}/slots/{colony_id}/pairing`
- `POST /api/sessions/{id}/start`
- `POST /api/sessions/{id}/slots/{colony_id}/replace`
- `GET /api/matches/{id}/operations`
- `GET /api/matches/{id}/report`

The admin WebSocket publishes compact typed messages:

- `lobby.snapshot`
- `controller.presence_changed`
- `turn.opened`
- `controller.submitted`
- `turn.resolved`
- `metric.updated`
- `match.completed`

The browser receives sanitized status and action summaries. It never receives
controller capabilities or raw pairing hashes. The raw pairing code is returned
once by the pairing creation command and retained only in browser memory until
copied or regenerated.

## Remote connectivity and security

Remote MCP uses Streamable HTTP behind TLS. Castle Benchmark itself can bind to
a private interface, while production remote access is expected to use a TLS
reverse proxy or secure tunnel.

Security requirements:

- An operator-configured high-entropy orchestrator capability is mandatory for
  session creation.
- Pairing codes are random, single use, scoped to match and colony, stored only
  as hashes, expire after ten minutes, and are rate limited by code and IP.
- Claiming rotates the slot generation so replaying an old claim cannot mint a
  second token.
- Controller capabilities are high entropy, stored hashed, revocable, and
  scoped to one slot.
- Admin capabilities cannot submit colony actions.
- Allowed origins and proxy trust are explicit configuration; wildcard CORS is
  not used with credentials.
- Remote endpoints have request-size limits, heartbeat throttling, stable safe
  error codes, and audit events.
- The UI escapes all controller-supplied labels and diplomatic messages.
- Model-provider API keys remain inside the external agent runtime and never
  enter Castle Benchmark.

Local development can use `127.0.0.1`; enabling a non-loopback bind requires an
explicit remote flag and orchestrator capability.

## Operations Room UX

### Visual direction

The interface becomes a dark, restrained medieval operations console rather
than a form dashboard. PixelLab art supplies texture and identity; the control
surface uses disciplined typography, thin rules, dense but readable data, and
one warm command accent. The result should feel closer to a professional
simulation control room than a game landing page.

### Desktop composition

- **Command rail:** compact session identity, scenario/seed, global connection
  health, turn clock, start/pause controls, and report/export actions.
- **Agent roster:** one vertical slot per colony with color, identity, model,
  connection badge, turn state, latency, and compact cost totals.
- **World stage:** the largest region; isometric terrain, structures, fog,
  construction, fire, damage, selection, and event focus.
- **Inspector:** switches between selected agent, colony, structure, trade, and
  event detail without opening floating modal stacks.
- **Timeline:** synchronized controller submissions and authoritative events.
  Waiting, timeout, invalid, trade, policy, raid, fire, and takeover moments use
  distinct marks.
- **Metric dock:** raw comparative axes with small multiples, not decorative
  dashboard cards.

The lobby uses the same shell. Before start, the world stage shows the seeded
map preview while the roster expands into slot assignment and pairing panels.

### Agent slot interaction

An external slot has four clear states:

1. `Unassigned`: choose external and generate pairing.
2. `Pairing`: code, expiry, endpoint, copy config, and waiting indicator.
3. `Connected`: identity plus capability-safe readiness confirmation.
4. `Attention`: disconnected, timed out, invalid output, or capability rotated,
   with contextual recovery actions.

Color is never the sole signal. Every state includes a label and icon/shape.
Live latency changes do not cause layout shifts.

### Responsive behavior

- At desktop widths, roster/world/inspector remain simultaneous.
- On tablets, inspector becomes a persistent lower panel.
- On phones, the order is roster summary, world, selected inspector, timeline;
  pairing config uses a full-width sheet and all controls remain at least 44px.
- The world remains usable with touch pan/zoom and does not force horizontal
  page scrolling.

### Accessibility and motion

- All status changes are available through polite live regions.
- Agent and colony colors meet contrast requirements and have textual labels.
- Keyboard users can move through slots, map entities, timeline events, and
  action controls in a stable order.
- Motion is restricted to meaningful state transitions, map effects, and
  timeline insertion. Reduced-motion mode replaces spatial transitions with
  short opacity changes and may freeze ambient PixelLab loops.

## Benchmark integrity

Controller identity and tenure are written to metadata and events. Reports
distinguish:

- server-measured MCP calls and network latency;
- adapter-reported model calls, tokens, and monetary cost;
- validation errors, stale actions, missed deadlines, and reconnects;
- takeover boundaries and which controller produced each action.

Pairing and presence timing never seed SimCore randomness. Official runs use a
published action deadline and timeout policy. Comparing agents requires the
same scenario, seed suite, ruleset, seat rotations, context budget, tool schema,
and deadline policy.

## Failure handling

- Expired or consumed pairing code: stable error; operator may rotate it.
- Duplicate claim: first atomic claim wins; later claim receives no slot data.
- Heartbeat loss: presence changes, current deadline continues, timeout becomes
  measured wait.
- Malformed identity or telemetry: rejected independently; controller capability
  remains valid unless abuse thresholds are reached.
- WebSocket loss: browser reconnects and requests a full operations snapshot;
  match continues headlessly.
- External MCP loss: other controllers and SimCore continue through deadlines.
- Operator browser loss: no effect on controller connections or match state.

## Testing

### Service and security

- One pairing code can claim exactly one slot once.
- Pairing expiry, rotation, attempt limits, and concurrent claims fail closed.
- A controller cannot observe, heartbeat, or command another slot.
- Admin cannot submit colony actions; controller cannot call admin operations.
- Non-loopback serve requires explicit remote configuration.
- User-supplied identity and messages render as text, never HTML.

### Determinism and fairness

- Different heartbeat and response timing with identical action batches yields
  identical state hashes.
- Timeout substitution produces explicit events and stable metric increments.
- Controller replacement changes attribution but not historical events.
- Replaying the action/event stream ignores presentation timing and reproduces
  every SimCore hash.

### MCP and remote integration

- Contract tests cover create session, pairing, claim, heartbeat, observe,
  usage, submit, completion, and report through direct service and MCP.
- A real Streamable HTTP smoke test pairs four mock remote agents and completes
  each official biome.
- Server-measured MCP call counts match tool invocations even if adapters omit
  usage reporting.

### Browser

- Lobby renders all controller types and pairing state transitions.
- Generated config contains no admin or opponent secret.
- Connected agents update roster, timeline, inspector, and metric dock.
- Disconnect/takeover and terminal results modes are exercised end to end.
- Responsive checks cover 320, 375, 414, 768, and desktop widths.
- Production build, keyboard navigation, focus visibility, reduced motion, and
  absence of horizontal overflow are gated.

## Delivery slices

1. **Controller registry:** session lifecycle, slots, identities, tenure,
   pairing claims, presence, and security tests.
2. **Connection adapters:** MCP tools, Streamable HTTP remote smoke, local config
   generator, deadlines, and server-measured telemetry.
3. **Agent Lobby:** slot assignment, pairing instructions, readiness, start,
   disconnect, rotation, and takeover.
4. **Operations Room:** professional shell, live roster, world stage, inspector,
   timeline, metric dock, results comparison, and replay integration.
5. **Integrity gate:** all official scenarios with mixed local/remote mocks,
   clean-checkout build, security cases, visual/responsive browser suite, and
   updated operator documentation.

## Acceptance criteria

- An operator can create a four-slot lobby and assign any mix of human,
  baseline, local MCP, and remote MCP controllers.
- A new external controller can connect using only the displayed endpoint,
  one-time pairing code, and generated bootstrap instructions.
- Claiming a slot never exposes an admin capability or another colony token.
- Agent name, provider/model, online state, turn state, latency, last structured
  action, errors, token usage, and cost appear live in the operations room.
- A disconnected external agent becomes a measured wait and can reconnect,
  rotate, or be replaced without stopping the match.
- Four separately paired remote mock agents finish every official biome and
  produce verified replay artifacts.
- Operations and connection timing do not alter deterministic SimCore hashes.
- The redesigned desktop and mobile interface passes accessibility,
  responsiveness, production build, and end-to-end browser gates.
- Final reports preserve raw benchmark axes and segment metrics across
  controller takeovers.
