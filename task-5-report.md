# Task 5 report — Professional Agent Operations Room

## Result

Built the frontend-only benchmark operations room around the existing PixelLab world renderer. The shell now keeps lobby, running match, human controls, and deterministic replay in one Workbench layout while adding a sanitized controller roster, ordered service timeline, synchronized inspector, world focus/pan/zoom controls, and raw provenance-labelled metric dock.

No backend files or contracts were changed.

## Hallmark design lock

- Audience: benchmark operator/researcher.
- Job: connect agents, observe decisions, inspect outcomes, compare raw metrics.
- Genre/tone: technical + atmospheric.
- Macrostructure: Workbench.
- Theme: Midnight warm-neutral canvas with restrained amber accent.
- Navigation/footer: N9 edge-aligned header and Ft2 inline live benchmark rail.
- Enrichment: the existing PixelLab world remains the dominant real product canvas; no decorative imagery or fake browser/IDE chrome was added.
- Motion is limited to live-number tick, active-row/background focus, and button press. `prefers-reduced-motion` reduces animation and transition durations to 1 ms.

The newest-first Hallmark decision record is in `.hallmark/log.json`. The first non-empty stylesheet line contains the required stamp and critique scores.

## Product behavior

- `agentRosterRows`, `timelineItems`, and `metricSeries` are pure projections.
- `OperationsController` owns snapshot/report projection, selected agent/turn/tab, ordered live-event application, selection preservation, reset/replay handoff, and sequence-gap detection.
- A sequence gap retains the already-applied real timeline and returns `resync`; the UI requests a fresh sanitized operations snapshot/report rather than applying the out-of-order event.
- Entering legacy development quick play disposes any earlier lobby stream, closes and clears its operations capability/socket, and resets the operations surface instead of showing a stale session feed beside the new match.
- Every server-owned controller state is exposed as text plus a distinct shape. Roster selection is roving-keyboard accessible; tabs support arrow/Home/End navigation; timeline rows support Enter/Space selection and synchronize agent, turn, and world focus.
- Raw metrics preserve contract provenance. Diplomacy displays the available `trade` and `aggression` values; resilience is explicitly unavailable; action validity displays only `invalid_actions`. No composite score, rate, provider aggregate, or currency cost is inferred.
- Server MCP calls and adapter tokens/cumulative latency prefer real tenure-segment rows, joined to that tenure's provider/model identity. Aggregate rows remain the fallback when tenure metrics are absent.
- World selection, structures, construction progress, damage/fire rendering, and replay remain in `game.ts`. Renderer palette and type values are read from CSS tokens.

## TDD evidence

RED was captured before implementation:

1. `npm --prefix frontend test -- operations.test.ts` initially failed because `src/operations.ts` did not exist.
2. Projection/controller implementation then left the DOM tests failing until safe DOM composition was added.
3. Reset/world-view/keyboard behavior was specified with failing tests before implementation.
4. Tenure attribution, private-event filtering, initial timeline tab stop, live-number marking, and tab-panel relationships each produced focused failing tests before their corresponding production changes.

Final frontend result: 55 tests passed across API, game, lobby, and operations suites; 19 are Task 5 operations tests.

## Security and data honesty

- Operations rendering uses DOM creation plus `textContent`/`replaceChildren`; it does not use HTML string injection.
- Hostile identity text is rendered inert. Non-allowlisted event fields, including private narrative, controller/admin capabilities, and digests, are never rendered.
- Admin and controller capabilities remain in memory only. The orchestrator input is cleared immediately after reading and is never placed in URL or web storage.
- No capability/digest is added to event logs, data attributes, or metric labels.
- Metric provenance is visible as `simulation-raw`, `server-measured`, `adapter-reported`, or `unavailable`.

## Accessibility and responsive audit

- All buttons and form controls have accessible names; the static DOM audit found zero duplicate IDs, zero unnamed buttons, and zero unlabeled inputs/selects.
- Touch targets use a 44 px token. Focus is instant and visible; calculated OKLCH contrast ratios include 12.81:1 for the general focus ring on canvas and 7.93:1 for the inset primary-button ring on amber. The weakest ordinary rule/surface boundary is 3.05:1.
- Live status is polite/atomic. Roster uses a labelled listbox/options pattern; inspector tabs label the persistent tabpanel; the timeline is an ordered list with keyboard-operable rows.
- Mobile-first source audit at 320, 375, and 414 px: single-column priority order is setup/roster, world, then inspector/timeline; inspector tabs use two columns; long identity fields wrap; metric tracks use `minmax(0, 1fr)`; `html` and `body` use `overflow-x: clip`; fixed affordances do not wrap.
- At 768 px the 48 rem rule moves the world across the first row and places setup/inspector beneath it in two constrained columns. The three-column desktop shell begins at 60 rem.
- Vite parsed and emitted the responsive CSS successfully. The in-app Browser runtime reported that no browser instance was available, so screenshots and actual rendered overflow measurements at the four requested widths could not be collected in this environment. This is the remaining visual-QA risk and should be checked when a browser is attached.

## Verification

- `npm --prefix frontend test` — 55 passed.
- `npm --prefix frontend run build` — TypeScript `--noEmit` and Vite production build passed; 717 modules transformed.
- `uv run pytest tests/test_contracts.py tests/test_deadlines.py tests/test_mcp.py -q` — 53 passed.
- Token scan — no hex, OKLCH, RGB/HSL, or literal font-family declarations outside `frontend/tokens.css`.
- DOM/storage scan — no `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `localStorage`, or `sessionStorage` in the Task 5 operations/UI surface.
- Contrast calculation — ink/canvas 16.01:1; muted/surface 8.00:1; faint/map 7.08:1; rule/raised 3.05:1; accent/canvas 8.28:1; accent-ink/accent 7.93:1.
- `git diff --check` — clean.

## Explicit Task 6 follow-up

The current backend WebSocket mapper advances event sequence across several unmapped operational event kinds, including explicit timeout, replacement, claim, heartbeat rejection, and pairing rejection events. Task 5 does not synthesize those events: the next mapped sequence exposes the gap and triggers a sanitized snapshot/report refresh, which restores retained history when the endpoint still has it. Task 6 should map every retained operational event kind into the admin stream so timeout/takeover boundaries arrive immediately and do not depend on the later gap refresh.

## Files

- `frontend/src/operations.ts`
- `frontend/src/game.ts`
- `frontend/src/ui.ts`
- `frontend/index.html`
- `frontend/src/styles.css`
- `frontend/tokens.css`
- `.hallmark/log.json`
- `frontend/tests/operations.test.ts`
- `task-5-report.md`
