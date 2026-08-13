# Task 2 report — Presence, deadlines, reconnects, and tenure metrics

## Delivered

- Added numeric-timestamp heartbeats, 30-second deadline closure, explicit sorted
  `WaitAction` batches, and a single SimCore barrier resolution.
- Added controller claim/connect/disconnect/timeout/replacement events, tenure
  histories, capability revocation on replacement, and live external re-pairing.
- Added timeout/reconnect, server-measured MCP, and adapter-reported model-usage
  report sections without changing legacy match cost-report compatibility.
- Added artifact metadata for controller tenures and turn-level controller IDs;
  replay still consumes only action batches.

## TDD evidence

1. Added `tests/test_deadlines.py` before service implementation.
2. Confirmed RED with `uv run pytest tests/test_deadlines.py -q`: all new cases
   failed because `GameService.heartbeat` did not exist (`AttributeError`).
3. Implemented the narrow application-layer service changes, then confirmed
   GREEN: `3 passed`.
4. Added the live external takeover pairing regression before its fix; confirmed
   RED with `ConflictError: pairing is unavailable for this session`, then allowed
   a newly replaced external slot to receive a fresh pairing grant while running.
5. Added replay artifact regression coverage; confirmed RED because
   `ArtifactWriter.create()` lacked `controller_tenures`, then added optional,
   non-replay metadata and per-turn attribution.

## Verification

- `uv run pytest tests/test_deadlines.py tests/test_replay.py tests/test_invariants.py -q` — 11 passed
- `uv run pytest -q` — 69 passed
- `git diff --check` — clean

## Self-review

- No raw pairing, controller, or admin capability/digest is added to snapshots,
  reports, events, or artifacts.
- Presence timestamps and deadline scheduling remain outside SimCore state; the
  state-hash regression proves heartbeat timing does not alter deterministic play.
- No domain, events, or engine source changed. The existing public barrier accepts
  explicit `WaitAction` batches, so no simulation-layer exception was needed.

## Concerns / follow-up

- `ArtifactWriter` now accepts tenure/attribution data; a later persistence
  integration should pass live-service tenure records into the actual run writer
  when operations-room artifact export is wired.
- MCP wrapper call instrumentation belongs to Task 3; this task exposes the
  server-measured report field while retaining `record_mcp_call` as its service
  boundary.
