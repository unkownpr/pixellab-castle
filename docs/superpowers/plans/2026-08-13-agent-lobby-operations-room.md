# Agent Lobby and Operations Room Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add secure local/remote agent pairing, controller presence and tenure telemetry, and a professional browser operations room that can configure, observe, recover, finish, and compare mixed-controller matches.

**Architecture:** `SimCore` remains deterministic and unaware of connectivity. A focused lobby registry inside the application layer owns session lifecycle, controller slots, hashed pairing/capability state, presence, deadlines, and sanitized operations snapshots; HTTP/MCP/WebSocket adapters consume that service, while the browser renders the same read model. Controller timing becomes recorded telemetry and explicit timeout-as-wait input, never simulation randomness.

**Tech Stack:** Python 3.12+, dataclasses, Pydantic 2, FastAPI, official MCP Python SDK, pytest, TypeScript 5.9, Vite 7.3, PixiJS 8.16, Vitest 3.2, Playwright-compatible browser smoke tests.

**Spec:** `docs/superpowers/specs/2026-08-13-agent-lobby-operations-room-design.md`

## Global Constraints

- SimCore must not import FastAPI, MCP, Pillow, frontend, wall-clock, or presence modules.
- Pairing codes are single-use, match/colony scoped, hash-only at rest, and expire after exactly 10 minutes.
- Controller tokens are returned only by successful slot claim and never appear in admin snapshots, events, logs, or browser storage.
- Admin capabilities cannot submit colony actions; controller capabilities cannot perform lobby administration.
- The browser must never render chain-of-thought or accept HTML from agent-controlled identity/message fields.
- MCP invocation count is server-measured; provider tokens/cost remain explicitly marked adapter-reported.
- Missing controller input at the deadline becomes a measured `wait`; timing never changes SimCore resolution order or RNG.
- Remote non-loopback serving requires an explicit flag, an orchestrator capability, origin allowlist, TLS termination guidance, and request limits.
- UI supports 320, 375, 414, 768, and desktop widths, visible focus, 44px controls, reduced motion, and no horizontal page overflow.

## File structure

```text
src/castle_benchmark/
  lobby.py                 session, slot, pairing, identity, presence and tenure types
  service.py               lobby orchestration, deadlines, sanitized operations read model
  schemas.py               versioned HTTP boundary schemas
  api.py                   admin lobby routes and operations WebSocket
  mcp_server.py            secure session/claim/heartbeat/gameplay tools
  persistence.py           controller tenure and telemetry provenance in artifacts
frontend/src/
  api.ts                   lobby/operations contracts and clients
  lobby.ts                 slot assignment, pairing and readiness interactions
  operations.ts            roster, inspector, timeline and metric dock projection
  game.ts                  isometric world only
  ui.ts                    shell lifecycle and human action controls
  styles.css               operations-room composition and responsive states
tests/
  test_lobby.py            lifecycle, claim, expiry, rotation and authorization
  test_deadlines.py        timeout-as-wait, reconnect and tenure attribution
  test_contracts.py        HTTP/direct contract parity
  test_mcp.py              MCP pairing and server-measured invocation telemetry
  e2e/test_remote_agents.py four remote mock agents across official biomes
frontend/tests/
  lobby.test.ts            sanitized lobby projection and pairing states
  operations.test.ts       roster/timeline/metrics projection
```

---

### Task 1: Controller registry and secure pairing domain

**Files:**
- Create: `src/castle_benchmark/lobby.py`
- Modify: `src/castle_benchmark/service.py`
- Test: `tests/test_lobby.py`

**Interfaces:**
- Produces: `SessionStatus`, `ControllerType`, `PresenceStatus`, `ControllerIdentity`, `ControllerSlot`, `LobbySession`, `PairingGrant`.
- Produces service methods: `create_session(config)`, `configure_slot(admin_token, colony_id, controller_type, baseline_kind=None)`, `open_lobby(admin_token)`, `create_pairing(admin_token, colony_id, now)`, `claim_slot(code, identity, now)`, `lobby_status(admin_token, now)`.

- [ ] **Step 1: Write lifecycle and claim tests**

```python
def test_pairing_claim_returns_one_scoped_capability_once(service, clock):
    session = service.create_session("orch", "basic-survival-v1", 17, 4)
    service.configure_slot(session.admin_token, "c2", "external")
    grant = service.create_pairing(session.admin_token, "c2", now=clock.now)
    claimed = service.claim_slot(grant.code, identity("Codex", "openai", "gpt-5"), now=clock.now)
    assert (claimed.match_id, claimed.colony_id) == (session.match_id, "c2")
    assert "controller_token" not in service.lobby_status(session.admin_token, clock.now)["slots"][1]
    with pytest.raises(ConflictError, match="pairing_consumed"):
        service.claim_slot(grant.code, identity("Replay", "x", "y"), now=clock.now)
```

- [ ] **Step 2: Run `uv run pytest tests/test_lobby.py -q` and confirm missing lobby symbols**

- [ ] **Step 3: Implement immutable lobby types and hash-only capabilities**

```python
PAIRING_TTL_SECONDS = 600

@dataclass(slots=True)
class ControllerSlot:
    colony_id: str
    controller_type: ControllerType
    controller_id: str | None = None
    identity: ControllerIdentity | None = None
    capability_digest: str | None = None
    pairing_digest: str | None = None
    pairing_expires_at: float | None = None
    pairing_consumed: bool = False
    generation: int = 0
```

Generate secrets with `secrets.token_urlsafe(24)`, store `sha256(secret.encode()).hexdigest()`, compare digests with `secrets.compare_digest`, and index raw secrets only in the process-local capability map required for authorization.

- [ ] **Step 4: Implement atomic single-use claim, ten-minute expiry, attempt throttling, sanitized slot serialization, and human/baseline immediate readiness**

- [ ] **Step 5: Run `uv run pytest tests/test_lobby.py tests/test_contracts.py -q`**

- [ ] **Step 6: Commit `feat: add secure controller lobby registry`**

### Task 2: Presence, deadline closure, reconnect and tenure metrics

**Files:**
- Modify: `src/castle_benchmark/lobby.py`
- Modify: `src/castle_benchmark/service.py`
- Modify: `src/castle_benchmark/metrics.py`
- Modify: `src/castle_benchmark/persistence.py`
- Test: `tests/test_deadlines.py`
- Test: `tests/test_replay.py`

**Interfaces:**
- Produces: `heartbeat(controller_token, turn, status, now)`, `start_match(admin_token, now)`, `close_deadline(admin_token, now)`, `replace_controller(admin_token, colony_id, replacement, now)`, `operations_snapshot(admin_token, now)`.
- Produces tenure events: `controller_claimed`, `controller_connected`, `controller_disconnected`, `controller_timed_out`, `controller_replaced`.

- [ ] **Step 1: Write failing deadline and tenure tests**

```python
def test_deadline_turns_missing_external_input_into_measured_wait(live_session, clock):
    service.start_match(live_session.admin_token, clock.now)
    clock.advance(31)
    result = service.close_deadline(live_session.admin_token, clock.now)
    assert any(e.kind == "controller_timed_out" and e.colony_id == "c2" for e in result.events)
    assert service.run_report(live_session.admin_token)["metrics"]["cost"]["c2"]["timeouts"] == 1
```

- [ ] **Step 2: Run `uv run pytest tests/test_deadlines.py -q` and confirm failure**

- [ ] **Step 3: Implement heartbeat state transitions using injected numeric timestamps and a fixed 30-second default deadline**

- [ ] **Step 4: Resolve missing batches as explicit `WaitAction` batches sorted by colony ID, then call the existing SimCore barrier once**

- [ ] **Step 5: Add controller tenure records to run metadata and per-action controller IDs to turn artifacts; keep replay dependent only on action batches**

- [ ] **Step 6: Add report fields `timeouts`, `reconnects`, `tenures`, server-measured MCP calls and adapter-reported model usage**

- [ ] **Step 7: Prove identical actions with different heartbeat timing produce identical state hashes**

- [ ] **Step 8: Run `uv run pytest tests/test_deadlines.py tests/test_replay.py tests/test_invariants.py -q`**

- [ ] **Step 9: Commit `feat: measure controller presence and deadlines`**

### Task 3: Versioned HTTP, MCP and remote connection contracts

**Files:**
- Modify: `src/castle_benchmark/schemas.py`
- Modify: `src/castle_benchmark/api.py`
- Modify: `src/castle_benchmark/mcp_server.py`
- Modify: `src/castle_benchmark/cli.py`
- Test: `tests/test_contracts.py`
- Test: `tests/test_mcp.py`
- Create: `tests/test_remote_security.py`

**Interfaces:**
- Produces HTTP routes `POST /api/sessions`, `GET /api/sessions/{id}/lobby`, `POST .../pairing`, `POST .../start`, `POST .../replace`, `GET /api/matches/{id}/operations`, and admin operations WebSocket.
- Produces MCP tools `benchmark.create_session`, `create_pairing`, `claim_slot`, `heartbeat`, `start_match`, `replace_controller`, `lobby_status` plus existing gameplay/report tools.

- [ ] **Step 1: Write direct/HTTP/MCP parity tests for create → pair → claim → heartbeat → start → observe → submit**

```python
async def test_mcp_claim_never_returns_admin_or_opponent_capability(server):
    claimed = await call(server, "benchmark.claim_slot", {"pairing_code": code, "identity": identity})
    assert set(claimed) == {"schema_version", "match_id", "controller_id", "colony_id", "controller_token"}
```

- [ ] **Step 2: Write remote security tests for missing orchestrator capability, wildcard credential origins, non-loopback bind without `--remote`, oversized identity, and pairing attempt limits**

- [ ] **Step 3: Run focused tests and confirm missing schemas/routes/tools**

- [ ] **Step 4: Implement Pydantic `extra="forbid"` schemas with identity field lengths <=128, message payload <=16 KiB, stable error codes, and no secret fields in response models**

- [ ] **Step 5: Implement admin WebSocket messages `lobby.snapshot`, `controller.presence_changed`, `turn.opened`, `controller.submitted`, `turn.resolved`, `metric.updated`, `match.completed` from sanitized snapshots**

- [ ] **Step 6: Instrument MCP tool calls at the wrapper before service invocation; do not derive MCP count from `record_usage`**

- [ ] **Step 7: Add CLI flags `--remote`, `--allowed-origin` and reject non-loopback host unless remote mode, orchestrator token, and non-empty allowlist are present**

- [ ] **Step 8: Run `uv run pytest tests/test_contracts.py tests/test_mcp.py tests/test_remote_security.py -q`**

- [ ] **Step 9: Commit `feat: expose secure local and remote agent pairing`**

### Task 4: Typed frontend connection client and agent lobby

**Files:**
- Modify: `frontend/src/api.ts`
- Create: `frontend/src/lobby.ts`
- Modify: `frontend/src/ui.ts`
- Modify: `frontend/index.html`
- Test: `frontend/tests/lobby.test.ts`

**Interfaces:**
- Consumes sanitized lobby/operations schemas from Task 3.
- Produces `LobbyController`, `renderLobby(snapshot)`, `renderPairingGrant(grant)`, provider config builders, readiness/start/replace interactions.

- [ ] **Step 1: Write failing tests for slot states and secret-safe config generation**

```typescript
it("builds a Codex pairing config without admin secrets", () => {
  const config = pairingInstructions(grant, "codex");
  expect(config).toContain("benchmark.claim_slot");
  expect(config).toContain(grant.pairing_code);
  expect(config).not.toContain("admin_token");
});
```

- [ ] **Step 2: Run `npm --prefix frontend test -- lobby.test.ts` and confirm missing module failure**

- [ ] **Step 3: Add typed API calls for sessions, slot configuration, pairing, start, replace, operations snapshot, and admin WebSocket events**

- [ ] **Step 4: Implement lobby slot rows for human/baseline/external, baseline choice, pairing generation, copyable code/endpoint/config, expiry, readiness and explicit fallback**

- [ ] **Step 5: Escape all labels through `textContent`; never interpolate identity/message values into `innerHTML`**

- [ ] **Step 6: Replace the current immediate-match form flow with draft → lobby → start; keep one-colony quick play as a named development shortcut**

- [ ] **Step 7: Run frontend unit tests and TypeScript build**

- [ ] **Step 8: Commit `feat: add browser agent pairing lobby`**

### Task 5: Professional Operations Room read model and UI

**Files:**
- Create: `frontend/src/operations.ts`
- Modify: `frontend/src/game.ts`
- Modify: `frontend/src/ui.ts`
- Modify: `frontend/index.html`
- Modify: `frontend/src/styles.css`
- Create: `tokens.css`
- Create: `.hallmark/log.json`
- Test: `frontend/tests/operations.test.ts`

**Interfaces:**
- Produces pure projections `agentRosterRows(snapshot)`, `timelineItems(events)`, `metricSeries(report)`, and stateful `OperationsController`.
- Consumes only sanitized operations snapshots and existing observations/events.

- [ ] **Step 1: Write projection tests for connected/thinking/submitted/timed-out/disconnected/taken-over slots, stable latency layout, takeover segmentation, and raw metric axes**

- [ ] **Step 2: Run the tests and confirm missing operations module**

- [ ] **Step 3: Apply Hallmark redesign references selected for an atmospheric simulation workbench: agent roster, dominant world stage, persistent inspector, event timeline, and raw metric dock**

- [ ] **Step 4: Split controller rendering from `ui.ts`; keep `game.ts` responsible only for Pixi world rendering, selection and authoritative visual states**

- [ ] **Step 5: Implement roster keyboard navigation, text+shape status indicators, inspector tabs, synchronized timeline focus, and comparison small multiples**

- [ ] **Step 6: Move every color/font/spacing/motion/radius token into root `tokens.css`, import it from the entry stylesheet, stamp the Hallmark macrostructure, and record the design in `.hallmark/log.json`**

- [ ] **Step 7: Add 320/375/414/768/desktop layouts, 44px targets, `overflow-x: clip`, visible focus, `aria-live`, touch pan/zoom affordance, and reduced-motion animation freezing**

- [ ] **Step 8: Run Vitest, `tsc --noEmit`, production build, Hallmark slop test, and verify no secrets appear in rendered DOM fixtures**

- [ ] **Step 9: Commit `feat: redesign benchmark as agent operations room`**

### Task 6: Four-agent remote E2E and operator workflow

**Files:**
- Create: `tests/e2e/test_remote_agents.py`
- Modify: `tests/e2e/test_stack.py`
- Modify: `scripts/gate.sh`
- Modify: `README.md`
- Modify: `docs/benchmark-protocol.md`

**Interfaces:**
- Produces a Streamable HTTP mock-controller harness using four independently claimed capabilities.
- Produces documented Codex, Claude, OpenCode, generic MCP, reverse-proxy/TLS, reconnect and takeover recipes.

- [ ] **Step 1: Write an E2E test that starts one lobby, creates four external pairing grants, claims them with distinct identities, starts the same match, drives observe/usage/submit loops to terminal, fetches its report, and verifies its exported replay**

- [ ] **Step 2: Parametrize the test over `basic-survival-v1`, `desert-scarcity-v1`, and `snow-recovery-v1`**

- [ ] **Step 3: Add disconnect and baseline takeover mid-match; assert pre/post-tenure metrics remain attributed to different controller IDs**

- [ ] **Step 4: Update `scripts/gate.sh` to run security tests, frontend tests/build, all-biome remote E2E, full report and replay verification from a clean install**

- [ ] **Step 5: Document exact local stdio and remote Streamable HTTP commands, orchestrator secret setup, pairing steps, TLS proxy boundary, generated configs, agent loop, and troubleshooting**

- [ ] **Step 6: Run `scripts/gate.sh` and `npm --prefix frontend audit --audit-level=low`; require zero test/build/audit failures**

- [ ] **Step 7: Request an independent code review against the spec and fix every Critical/Important finding with regression tests**

- [ ] **Step 8: Commit `docs: complete multi-agent benchmark operations workflow`**
