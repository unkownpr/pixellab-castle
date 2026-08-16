# Playing it with your own model

Everything here is a real recipe: the commands were run against this repository, and the
numbers quoted in the README came out of them. Two agents on two different providers can
share one match — that is the point of the session flow.

## 1. Start the service

```bash
export CASTLE_BENCHMARK_ORCHESTRATOR_TOKEN="$(openssl rand -hex 24)"
uv run castle-benchmark serve --host 127.0.0.1 --port 8140
```

The MCP endpoint rides on the same process at `http://127.0.0.1:8140/mcp`, so every agent
below talks to one authoritative simulation.

## 2. Open a match with a seat for each model

```bash
uv run python - <<'PY'
import json, os, urllib.request

BASE = "http://127.0.0.1:8140"
ORCH = os.environ["CASTLE_BENCHMARK_ORCHESTRATOR_TOKEN"]

def call(path, payload=None, token=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(BASE + path, data=data)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())

session = call("/api/sessions", {
    "scenario_id": "basic-survival-v1", "seed": 23, "colony_count": 4,
    "deadline_seconds": 300,
    "slots": [
        {"colony_id": "c1", "controller_type": "external"},
        {"colony_id": "c2", "controller_type": "external"},
        {"colony_id": "c3", "controller_type": "baseline", "baseline_kind": "expansionist"},
        {"colony_id": "c4", "controller_type": "baseline", "baseline_kind": "survivalist"},
    ],
}, ORCH)
admin, match = session["admin_token"], session["match_id"]

tokens = {}
for seat, identity in (
    ("c1", {"display_name": "Claude", "provider": "anthropic", "model": "claude"}),
    ("c2", {"display_name": "DeepSeek V4 Flash", "provider": "opencode", "model": "deepseek-v4-flash"}),
):
    code = call(f"/api/sessions/{match}/slots/{seat}/pairing", {}, admin)["pairing_code"]
    tokens[seat] = call("/api/pairings/claim", {"pairing_code": code, "identity": identity})["controller_token"]
    call(f"/api/sessions/{match}/heartbeat", {"turn": 0, "status": "ready"}, tokens[seat])

call(f"/api/sessions/{match}/start", {}, admin)
print(json.dumps({"match_id": match, "admin_token": admin, "tokens": tokens}, indent=2))
PY
```

An agent can claim its own seat instead — hand it the pairing code and let it call
`benchmark.claim_slot`. Claiming centrally is simply easier to script, and it means the
match is already running when the agents wake up.

## 3. Point each model at the match

Both agents get the same instructions; only the plumbing differs.

**A cloud model through Claude Code.** Write `mcp.json`:

```json
{ "mcpServers": { "castle": { "type": "http", "url": "http://127.0.0.1:8140/mcp" } } }
```

```bash
claude -p "$(cat prompt.txt)" --mcp-config mcp.json --permission-mode bypassPermissions
```

**DeepSeek through OpenCode.** Write `opencode.json` in the working directory:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": { "castle": { "type": "remote", "enabled": true, "url": "http://127.0.0.1:8140/mcp" } }
}
```

```bash
opencode run -m deepseek/deepseek-v4-flash "$(cat prompt.txt)"
```

A prompt that works, with the seat's own token substituted:

```text
You are colony c1 in a live Castle Benchmark match, playing through the castle MCP tools.
Your controller_token is '<TOKEN>' — every tool call needs it. The match is running.

Call benchmark.rules once and read every constant. Then loop until match_status says
terminal: observe, decide up to two actions, submit_actions with the turn number from that
observation. If a submit returns stale_turn, observe again and resubmit.

Keep colonists fed and watered, build production early, repair damage and douse fires. You
may only gather within five steps of your own operational buildings.
```

Two things that will bite you if you skip them: start the match **before** launching the
agents, or they will burn their context polling a lobby that is not running; and run each
agent detached, because an agent that shares a terminal with the launcher dies with it.

## 4. Read the result

```bash
curl -s -H "Authorization: Bearer $ADMIN" \
  http://127.0.0.1:8140/api/matches/$MATCH/report | python3 -m json.tool
```

The composite is the ranking number; the axes under it say why. `cost.server_latency_ms`
is measured by the service, `cost.input_tokens` is whatever the adapter reported — the two
are kept apart on purpose.

## Comparing two models honestly

One match tells you almost nothing. The map and the seat move a score further than the
strategy does: the same scripted baseline swings from 58 to 119 across five seeds. Two
rules make a comparison mean something.

**Pair on identical worlds.** Run each model through the same seeds and the same seat
rotations, then compare match against match rather than average against average:

```bash
uv run castle-benchmark compare runs/claude runs/deepseek --label-a claude --label-b deepseek
```

It pairs runs on `(scenario, seed, rotation, seat)`, reports the mean difference with a
95% interval, the win rate, and — the useful part — how many more pairs you would need
before the interval is tight enough to call. Unpaired runs are reported, never averaged in.

**Know your own noise first.** Before believing any gap between two models, measure one
model against itself:

```bash
uv run castle-benchmark compare --within runs/claude
```

If a single controller's own interval is ±20 composite at your sample size, a 15-point gap
between two models is nothing. This is the number to publish alongside any comparison.

## A human reference

Scores mean more with a human anchor. The protocol:

1. Play `basic-survival-v1` on seeds 11, 17, 23, 29 and 37, seat `c1`, against the four
   scripted baselines — the same set the models play.
2. Use the browser client at `http://127.0.0.1:8140`, take over colony `c1`, and keep the
   turn deadline the models get. No pausing to think past it, no reloading a bad turn.
3. Read `benchmark.rules` first, exactly as an agent does. A human who has not read the
   rules is measuring reading comprehension, not play.
4. The match writes the same artifacts as any other, so the run drops into `compare`
   beside the models with no special handling.

Two runs by different people are worth more than ten by one: the point of the anchor is
the range a competent human occupies, not one person's best game.
