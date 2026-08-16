# Benchmark depth — what was decided and why

A record of the design round behind the `feat/benchmark-depth` work. Three positions were
argued: GLM-5.2 and DeepSeek V4 Pro (both driven headless through opencode against a
snapshot of `src/castle_benchmark/`), and this session's own. Two adversarial critique
rounds followed, each priced against the live economy. The numbers below are the ones that
survived; the ones that did not are recorded too, because the reason a number was rejected
is the part that is expensive to rediscover.

## The problem

The simulation measured supply and construction honestly. Everything else it claimed to
measure existed by name only:

- Damage was permanent. `REPAIRING` was a status nothing ever set, so a damaged producer
  was dead for the rest of the match and fire had no counterplay at all.
- Gathering had no geography. Any known cell was reachable from anywhere, so the map,
  expansion and territory were decoration.
- Alliance and war were labels: `RelationStatus.ALLIANCE` appeared only in a transition
  table. Diplomacy was non-consensual — a colony could force a treaty on a rival.
- The `message` fields on diplomacy and trade actions were never delivered anywhere.
- Raiding stole three food, risked nothing, and always succeeded, so no rational agent
  raided; `MilitaryPosture` and `set_policy` had no mechanical effect whatsoever.
- There was no way to win, and no aggregation rule, so two runs could not be ordered.
- Three of the six pressures the README advertised had no axis in the report at all.

## The decisions that survived

**Ground.** `GATHER_RADIUS = 5` from any own operational structure. Four was tried first and
rejected: a four-step diamond holds about seven resource cells at the map's density, which a
colony exhausts before the horizon, and nothing guarantees any of them is wood. Five matches
the sight radius, which also gives the rule a sentence a player can hold: you can work what
your buildings can see. River cells became a non-depleting water source, because the map had
a river running through every scenario and colonies were dying of thirst next to it.

**Recovery.** Repair at two fifths of build cost over two turns; extinguish for four water,
two with a well; demolish anything but the headquarters. Fire moved from one global lottery
to a per-colony clock at `hazard_cadence + 4`, because a single global fire could fall on the
same colony all match — a fairness hole in a benchmark that compares colonies. The
headquarters is exempt from fire: it cannot be demolished, is not in `BUILD_COSTS`, and
repair only touches damaged structures, so a burnt one was an unrecoverable colony.

Injuries mend on their own every second well-supplied turn. This was not in any of the three
proposals; it came out of the first four-colony match played after injuries started costing
labour, where a colony raided a few times without a clinic bled hands it could never get
back and starved for reasons no decision of its own could reverse.

**Consent.** Contact and a declaration of war stay unilateral. Alliance and peace are
proposals the other side accepts. Leaving a war requires the peace proposal — allowing a
unilateral drop to neutral would have made the peace mechanic redundant on arrival, which
the second critique round caught.

**Force.** Both sides count heads up to a party of three, plus a capped structural bonus and
a posture bonus, and the attacker must come out strictly ahead. First attempt gave both sides
the same base and let the defender stack unbounded bonuses; a single eight-stone wall then
hard-countered every possible raid, so the military axis was dead in a different way than
before. Second attempt still lost about eight resource-units on a *successful* surprise raid
once the influence and the injured colonist were priced, so attacker injuries on success went
to zero, loot to fourteen food and ten wood, and the surprise cost to three influence.

**Winning.** A monument over eight turns. The first cost — forty of each and ten turns —
was shown by arithmetic to be unreachable inside eighty turns while also eating, repairing
and defending; the correction that followed proved reachable on turn fifteen, which is the
story under "what running it actually taught us" below. It now costs wood 60 / stone 55 /
ore 24 / tools 12 / influence 40: above the opening stock on every line, and unreachable
without a workshop and a market.

**Score.** One published composite plus the per-axis Pareto front. The first weighting made
passive hoarding optimal: with uncapped wood, stone, ore and tools, `resource_value // 10`
outweighed everything else combined. Food and water left the resource term (they are
consumed, not banked), the divisor went to 25, and population settled at 3× after 5× was
shown to dominate every other term by five to ten times.

## Deliberately not done

**Removing barracks and wall effects from raid outcomes.** One critique called the outcome a
fog-of-war leak, since an attacker can infer the defender's structures from what happens.
Rejected: information gained by acting is not a fog break. The invariant is about what
`project_observation` hands a controller, and that still never contains rival private state.
A raid that teaches you the defender is fortified is the costly reconnaissance the benchmark
should reward.

**War denying gathering inside an enemy's sight.** It was in the merged spec and cut during
review: the rejection code would have told the attacker exactly which cells the enemy can
currently see, and no wording avoids that.

**Capping markets at one per colony.** Proposed to make alliance upkeep bite. Rejected in
favour of raising upkeep to two influence — a second alliance then costs a second market,
which is a real investment rather than an arbitrary structure limit.

**Hiding the composite weights or the rules.** Optimising against a stated objective is
legitimate play; optimising against a secret one is guessing. Only scenario *instances* are
held out, through `procedural-v1`.

## Invariants that constrained every choice

Determinism (seeded streams, sorted iteration, replay verifies), fog of war, capability
scoping, integer-only authoritative state. Two of the bugs found late were exactly these:
the scenario's hazard cadence was not written into run artifacts, so replay rebuilt the
scenario on the biome default and burned different buildings; and alliance vision merged in
place, which made shared sight depend on the per-turn initiative order until it was split
into a two-step union over own-sight.

## What running it actually taught us

Two findings came out of putting real models on it, and neither would have come from more
scripted matches.

**The win condition was affordable on turn zero.** The monument was priced down during
review because arithmetic said the original cost was unreachable inside eighty turns. The
correction overshot: against a starting stock of wood 50 / stone 35 / ore 10 / tools 6 /
influence 20, the new cost of wood 30 / stone 30 / ore 12 / tools 6 / influence 20 left only
ore short. A model replaying one seed three times ended every match with a monument, once on
turn 15. The cost now clears the opening stock on every line, and two lines — tools and
influence — are not on the map at all, so they can only come from a workshop and a market.
The lesson is not about that number. It is that a cost was tuned against a spreadsheet and
shipped without anyone asking what the opening stock already covers.

**The benchmark's own noise is larger than the gaps people will want to report.** Same
model, same seed, same seat, three runs: composite 165, 127, 93. A 72-point spread with
nothing about the world changed. Any single-match comparison between two models is
therefore uninterpretable, and the paired `compare` command exists to make that impossible
to forget — it prints how many more paired runs a difference needs before it can be called.

## What to watch next

- The scripted baselines now repair, douse fires, drink from the river and raid only from a
  barracks. They are a control, not a strategy — a model that merely matches them is not
  doing well, and the suite's baseline-relative z-score is the number that says so.
- `opportunity_waits` and the labour utilisation ratio are still coarse.
- Nothing yet measures whether a message changed anyone's behaviour, only that it was sent.
