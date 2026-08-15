# Task 6 report — Four-agent remote E2E and operator workflow

## Result

Completed the plan's final slice. The backend admin WebSocket now maps every retained operational event kind into the admin stream (no more silent gaps before a sequence resync), the remote agent loop is proven end-to-end across all three official biomes with four independently claimed capabilities, mid-match takeover preserves tenure attribution, and the gate now audits the frontend dependency tree. A pre-existing remote-mode bug that returned 405 instead of 404 for the disabled legacy `POST /api/matches` route is fixed and regressed.

## WebSocket event completeness

`api.py` previously mapped only five event kinds plus four presence kinds. Five retained kinds — `controller_claimed`, `pairing_rejected`, `heartbeat_rejected`, `controller_timed_out`, `controller_replaced` — advanced the sequence but were silently skipped, so timeout/takeover boundaries only surfaced on the next gap-triggered snapshot refresh. They now emit `controller.claimed`, `pairing.rejected`, `controller.heartbeat_rejected`, `controller.timed_out`, and `controller.replaced` immediately. The typed tagged-union `AdminWebSocketMessage` in `schemas.py` and the frontend `AdminWebSocketMessage` union plus `EVENT_LABELS` accept and label every emitted type. No capability or digest is present in any emitted payload.

## Four-agent remote E2E

`tests/e2e/test_remote_agents.py` starts one session through the Streamable HTTP MCP surface, claims four slots with distinct identities, starts the match, drives observe/status/submit `wait` loops to terminal, fetches the report, and verifies the exported replay via `write_resolved_turns` + `ArtifactWriter.finish` + `verify_replay`. It is parametrized over `basic-survival-v1`, `desert-scarcity-v1`, and `snow-recovery-v1`.

A second test disconnects one agent mid-match, replaces it with a `survivalist` baseline, drives to terminal, and asserts the report's `tenure_metrics` retains two distinct controller IDs (`external` then `baseline`) with increasing generation — pre/post takeover metrics stay attributed to different controllers.

## Pre-existing fix

In remote mode the legacy `POST /api/matches` route is unregistered; the catch-all static mount (`StaticFiles(html=True)`) returned 405 for it. A catch-all `/api/{path:path}` handler registered before the static mount now returns 404, so disabled routes fail as not-found rather than method-not-allowed. Regression in `tests/test_remote_security.py` (already asserted 404, now green).

## Gate and docs

`scripts/gate.sh` now runs the E2E slice explicitly and `npm --prefix frontend audit --audit-level=low` (0 vulnerabilities). `README.md` documents the local stdio / remote Streamable HTTP commands, orchestrator secret setup, pairing steps, TLS proxy boundary, agent loop, takeover, report, and replay export. `docs/benchmark-protocol.md` gains a "Oturum, eşleştirme ve devir" section enumerating the sanitized operations WebSocket message types.

## TDD evidence

1. `test_operations_websocket_maps_claim_reject_heartbeat_timeout_and_replacement` was written first and failed because the five kinds were silently skipped; it passed only after the mapping, schema, and frontend union were extended.
2. The E2E was written to drive the full remote contract and failed on the 405/404 pre-existing bug before the catch-all fix.

## Verification

- `uv run pytest -q` — 142 passed (incl. 4 new E2E, security, contracts, deadlines, MCP, replay).
- `npm --prefix frontend test` — 61 passed.
- `npm --prefix frontend run build` — `tsc --noEmit` + Vite production build clean.
- `npm --prefix frontend audit --audit-level=low` — 0 vulnerabilities.
- `git diff --check` — clean.

## Files

- `src/castle_benchmark/api.py`
- `src/castle_benchmark/schemas.py`
- `frontend/src/api.ts`
- `frontend/src/operations.ts`
- `tests/test_contracts.py`
- `tests/e2e/test_remote_agents.py`
- `scripts/gate.sh`
- `README.md`
- `docs/benchmark-protocol.md`
- `task-6-report.md`
