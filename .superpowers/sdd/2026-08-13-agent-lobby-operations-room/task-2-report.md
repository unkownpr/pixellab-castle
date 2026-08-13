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

## Review fix wave

### Root causes and fixes

- `submit_actions` and `close_deadline` independently mutated and cleared
  `LiveMatch.pending`. A deterministic threaded regression paused `SimCore`
  resolution and demonstrated two resolves for one turn. Both paths now hold a
  per-match turn lock through batch insertion, missing-slot calculation, and
  the single barrier resolution; submission re-authorizes under that lock to
  reject a capability revoked by a concurrent takeover.
- `pending_controller_ids` was cleared at resolution with no durable handoff.
  Resolved turns now retain immutable batch/controller-ID attribution in the
  live match. `write_resolved_turns()` persists them through `ArtifactWriter`
  and updates controller tenure metadata; replay continues to read only action
  batches.
- Usage was only accumulated per colony, and heartbeats emitted connected events
  for every normal heartbeat. Reports now retain compatible colony totals plus
  tenure/controller-ID `server_measured` (MCP, timeout, reconnect) and
  `adapter_reported_model_usage` sections. A connected event is emitted only
  after a disconnected/timed-out transition.
- Ready local slots previously had no executable path. Baselines now generate
  deterministic batches before either a controller submission or deadline
  closure. Human slots receive an admin-only, colony-scoped capability handoff
  after start/takeover; the admin capability itself remains unable to submit.

### Review verification

- `uv run pytest tests/test_deadlines.py tests/test_replay.py tests/test_lobby.py tests/test_contracts.py tests/test_invariants.py -q` — 32 passed
- `uv run pytest -q` — 75 passed
- `git diff --check` — clean
