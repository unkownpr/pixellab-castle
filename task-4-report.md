# Task 4 report — Browser Agent Lobby

## Delivered

- Added typed schema 1.1 session, lobby, slot, pairing, heartbeat, start,
  handoff, replacement, operations, report, WebSocket ticket and event clients.
- Added safe lobby projections, slot readiness states, explicit pairing panels,
  absolute-expiry countdowns and Codex, Claude/Claude Code, OpenCode and generic
  MCP instructions.
- Added `LobbyController` with draft configuration, explicit start, live sanitized
  operations updates, fresh-ticket reconnects, pairing rotation, baseline fallback
  and human takeover handoff.
- Replaced immediate match creation with draft → lobby → explicit start. The old
  route is reachable only through the named one-colony DEVELOPMENT quick-play
  button.
- Removed browser-driven c2+ baseline actions. The browser retains only its
  in-memory admin capability and, when explicitly handed off, one active human
  controller capability.
- Preserved the existing Pixi renderer and replay composition for Task 5.

## TDD evidence

RED runs observed before production changes:

- `npm --prefix frontend test -- lobby.test.ts` failed because `src/lobby.ts`
  did not exist.
- The live-operations test failed because no fresh WebSocket ticket was requested.
- The action-isolation test failed because no scoped human-action toggle existed;
  this caught lobby controls being disabled along with in-match controls.
- The consumed-grant and running-human-takeover tests failed because the pairing
  code remained rendered and the replacement capability was not handed off.

GREEN verification:

- `npm --prefix frontend test -- lobby.test.ts`: 17/17 passed.
- `npm --prefix frontend test`: 30/30 passed across 3 files.
- `npm --prefix frontend run build`: TypeScript and Vite production build passed.
- `git diff --check`: passed.

## Security checks

- Admin, orchestrator, human-controller and WebSocket ticket capabilities are
  never placed in URLs, generated provider instructions, logs, local storage or
  rendered DOM.
- The pairing code is rendered only in its explicit grant panel and is removed
  on expiry, consumption or rotation.
- Controller identity is rendered through safe DOM text APIs; the hostile-HTML
  fixture remains inert.
- Operations WebSocket tickets travel as subprotocol values, not query strings.

## Concern outside Task 4 ownership

`uv run pytest tests/test_contracts.py tests/test_mcp.py tests/test_remote_security.py -q`
ran 68 tests: 67 passed and one existing backend contract failed. In remote mode,
`POST /api/matches` returns 405 while `test_remote_app_disables_legacy_bulk_capability_creation`
expects 404. Task 4 changed no backend route/schema/service file, so this remains
for the backend owner rather than being masked by a frontend change.
