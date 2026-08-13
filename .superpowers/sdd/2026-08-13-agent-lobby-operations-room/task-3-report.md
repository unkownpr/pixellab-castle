# Task 3 report — Versioned HTTP, MCP and remote connection contracts

## Status

DONE

Implemented the Task 3 HTTP, MCP, WebSocket and remote CLI contracts while preserving the deterministic core, Task 2 turn locking/tenure accounting, and local legacy integrations.

## TDD evidence

- Baseline before Task 3: `uv run pytest -q` → 76 passed.
- Initial RED: focused suite → 17 expected failures from missing session routes, MCP tools, schemas and remote configuration guards; 7 legacy focused tests stayed green.
- Review-driven RED cycles covered remote legacy capability leakage, claim/replacement and heartbeat/replacement races, direct identity validation, all-wrapper MCP size limits, browser WebSocket authentication, sequence event delivery, proxy trust, bounded/atomic claim throttling, heartbeat audit throttling, legacy report compatibility, chunked HTTP bodies, and Uvicorn proxy rewriting.
- Final GREEN evidence is listed under Verification.

## Implemented contracts

### HTTP and schemas

- Added schema version `1.1` across session, lobby, gameplay, operations and report adapters.
- Added `extra="forbid"` request/response models, controller identity length limits of 128 characters, a 16 KiB request boundary, stable safe validation errors, typed nested report/operations models and a discriminated operations WebSocket message union.
- Added orchestrator-protected session creation with atomic deadline and slot configuration.
- Added lobby status, draft slot configuration, pairing creation, public pairing claim, heartbeat, start, replacement with baseline selection, human capability handoff, operations snapshot, report and one-use operations WebSocket ticket routes.
- Claim returns exactly `schema_version`, `match_id`, `controller_id`, `colony_id`, `controller_token`.
- Secret-returning HTTP responses use `Cache-Control: no-store`; sanitized lobby, operations, report and WebSocket projections fail closed on capability fields.
- Legacy bulk-capability match creation and query-token gameplay WebSocket remain available only in local mode and are not registered in remote mode.

### MCP

- Added `benchmark.create_session`, `create_pairing`, `claim_slot`, `heartbeat`, `start_match`, `replace_controller` and `lobby_status` while preserving gameplay/report tools.
- Kept `benchmark.create_match` as a deprecated one-version orchestrator-only alias without controller token output.
- Enforced 16 KiB at both FastMCP transport and every wrapper boundary.
- Counted valid scoped wrapper invocations before service execution, including calls rejected by later payload/service validation, while keeping adapter-reported model/token/latency usage separate.
- Streamable HTTP peer resolution uses the actual request client IP, accepts forwarding only from explicit trusted proxy CIDRs and runs Uvicorn with `proxy_headers=False`.

### WebSocket, throttling and concurrency

- Added 30-second, hash-indexed, single-use operations WebSocket tickets with explicit origin validation; raw admin capabilities are not placed in browser WebSocket URLs or protocols.
- Added monotonic retained operational sequences and server-side push for `lobby.snapshot`, `controller.presence_changed`, `turn.opened`, `controller.submitted`, `turn.resolved`, `metric.updated` and `match.completed`; sequence gaps trigger a sanitized snapshot resync.
- Bounded retained operational events and outstanding tickets at 2048 and 1024 entries respectively.
- Added a shared, atomic, bounded 60-second per-peer and per-code pairing attempt budget used by HTTP and MCP, with explicit trusted-proxy handling.
- Added heartbeat throttling with coalesced audit events.
- Serialized slot/capability lifecycle and telemetry attribution under the lobby-to-turn lock order; claim/start/submit/heartbeat/replacement concurrency regressions are covered.
- Enforced identity invariants in the domain value object as well as adapters.

## Verification

- `uv run pytest tests/test_contracts.py tests/test_mcp.py tests/test_remote_security.py -q` → 52 passed.
- `uv run pytest -q` → 121 passed.
- `uv run python -m compileall -q src` → exit 0.
- `git diff --check` → exit 0.
- Independent final review verdict: no residual Critical or Important issues; Ready.

## Security and operational notes

- Remote non-loopback HTTP serving requires `--remote`, a configured orchestrator capability of at least 32 characters and at least one explicit non-wildcard allowed origin.
- `--trusted-proxy` is repeatable and only authorizes the named IP/CIDR to supply `X-Forwarded-For`; Uvicorn proxy rewriting is disabled.
- TLS termination remains an operational reverse-proxy or secure-tunnel boundary, as required by the design.

## Concerns

None blocking. The retained operations stream is deliberately in-memory and bounded; persistence or multi-process fan-out would be a later deployment concern, not part of Task 3.
