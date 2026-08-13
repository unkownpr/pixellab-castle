# Task 1 report — Controller registry and secure pairing domain

## Delivered

- Added `castle_benchmark.lobby` with session, controller, presence, identity,
  slot, and pairing grant domain types.
- Added draft/lobby session lifecycle and slot configuration to `GameService`.
- Added ten-minute pairing grants with SHA-256-only pairing and controller
  capability state, constant-time digest comparison, a process-local raw
  capability authorization map, atomic single-use claims, and five-attempt
  malformed-identity throttling.
- Added sanitized lobby snapshots that omit all raw pairing codes, controller
  capabilities, and secret digests.
- Human and baseline slots are immediately ready; external slots become
  connected after a successful claim. Once pairing/capability state exists,
  draft configuration cannot orphan an authorized controller capability.

## TDD evidence

1. Added lifecycle, claim, expiry, secret-sanitization, readiness/freeze, and
   throttling tests in `tests/test_lobby.py`.
2. `uv run pytest tests/test_lobby.py -q` initially failed at collection because
   `castle_benchmark.lobby` did not exist.
3. Implemented the smallest registry/service behavior to satisfy the tests.
4. Added a security regression asserting claimed controller secrets are not
   duplicated in `LiveMatch.controller_tokens`; it failed before removal of the
   duplicate raw-token write, then passed.
5. Added a regression asserting a claimed draft slot cannot be reconfigured;
   it failed before the active-pairing-state guard, then passed.

## Verification

- `uv run pytest tests/test_lobby.py tests/test_contracts.py -q` — 11 passed.
- `uv run pytest -q` — 60 passed.
- `git diff --check` — clean.

## Self-review

- Pairing claims are guarded by an `RLock`, so only the first concurrent claim
  can mint a controller token.
- Codes expire at `now >= created_at + 600` and report stable consumed, expired,
  and attempt-limit conflict codes.
- Admin snapshots contain only sanitized identity/slot metadata; raw secrets
  are returned solely by the relevant create-pairing or successful-claim call.
- Existing `create_match` compatibility behavior remains unchanged.

## Concerns / follow-up boundaries

- HTTP/MCP orchestrator authentication, IP-level throttling, heartbeats,
  lifecycle start, and controller rotation are intentionally deferred to later
  plan tasks.
- No existing project record was present in the configured Obsidian vault.

## Review fix wave

Addressed review findings after commit `4d2bd4a`:

- `LobbySession` now stores only `admin_capability_digest`. Its compatibility
  `admin_token` property resolves the raw capability through the process-local
  service authorization map; it is not a dataclass field and is absent from
  `asdict(session)`.
- Removed the unused raw admin-token field from `LiveMatch`, so lobby-session
  admin capabilities are retained only in the service authorization map.
- New lobby sessions now reject `observe` and `submit_actions` until status is
  `running`; legacy `create_match` instances have no lobby registry and retain
  their established gameplay behavior.
- Strengthened snapshot sanitization to recursively inspect the serialized
  snapshot for raw pairing/controller/admin secrets and their SHA-256 digests.
- Added explicit authorization-separation tests for controller lobby mutation
  attempts and admin action submission.

### Review fix verification

- `uv run pytest tests/test_lobby.py -q` — 10 passed.
- `uv run pytest tests/test_lobby.py tests/test_contracts.py -q` — 15 passed.
- `uv run pytest -q` — 64 passed.
- `git diff --check` — clean.
