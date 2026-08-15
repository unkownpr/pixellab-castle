# Exploration, structure economy and fire — design

Status: agreed 2026-08-14. Supersedes nothing; extends the survival colony benchmark.

## Why

Three gaps were found while driving a live four-colony match:

1. **No exploration.** `sight_radius` is a fixed scenario constant applied around the
   colony spawn every turn (`engine.py:496`). Nothing ever widens it, and there is no
   move/scout action. A colony sees the same cells on turn 80 as on turn 0, so the
   benchmark cannot measure information gathering at all.
2. **Thirteen inert structures.** `StructureKind` has 15 members but only `HOUSE` and
   `HEADQUARTERS` do anything (they supply housing, `systems.py:26-29`). The other
   thirteen charge resources and return nothing, so building them is strictly
   dominated. The "prosperity" axis therefore rewards *not* building.
3. **Fire never lasts.** `_apply_fire` sets a burning structure straight to `DAMAGED`
   or `RUINED` (`engine.py:584`), dropping `BURNING` after a single turn. Ruins then
   persist forever and are only cleared when something is built on top
   (`engine.py:273-276`).

## Decisions

### Exploration

A new `scout` action. A colony dispatches a scout to a target cell; the scout walks
there over successive turns and reveals cells along the way.

Cost is deliberately doubled so exploration stays a live trade-off rather than a
one-time purchase:

- **Population**: the scout occupies one member of the colony for the duration. That
  member cannot gather, so scouting competes directly with production.
- **Food**: a fixed provisioning cost charged when the scout is dispatched.

The per-turn action budget stays at 1..16 (`schemas.py:201`).

### Fog

Hybrid memory. Three tiers:

| What | Visibility |
|---|---|
| Terrain (biome, water, movement cost) | Permanent once seen |
| Structures (kind, position, status) | Permanent once seen |
| Units and resource amounts | Only current inside the active sight radius |

This keeps the map legible — a rival's keep stays drawn on your map, trade caravans
and raiders animate against terrain you have explored — while live intelligence stays
bounded by sight. Scouting therefore keeps its value for the whole match instead of
expiring once the map is uncovered.

### Structure economy

Twelve of the thirteen inert kinds gain mechanics:

| Kind | Effect |
|---|---|
| `FARM` | +food per turn |
| `WELL` | +water per turn |
| `LUMBER_CAMP` | +wood per turn |
| `QUARRY` | +stone per turn |
| `MINE` | +ore per turn |
| `WORKSHOP` | converts ore into tools per turn |
| `CLINIC` | heals sick and injured population per turn |
| `BARRACKS` | reduces resources lost to a raid |
| `WATCHTOWER` | increases sight radius |
| `WALL` | reduces structure damage taken from a raid |
| `GATE` | permits trade while walled |
| `MARKET` | improves trade ratio and grants influence |

`WAREHOUSE` is **excluded**. Making it meaningful requires per-resource storage caps,
which reshapes the whole production/consumption balance and deserves its own round.
It stays buildable and inert until then, and the README must say so.

Only `OPERATIONAL` structures produce. Damaged, burning, ruined and under-construction
structures contribute nothing.

### Fire

- A burning structure stays `BURNING` across turns until its condition reaches zero,
  then becomes `RUINED`. It no longer drops back to `DAMAGED` after one turn.
- Ruins are never removed from the world. They fade visually instead, so the scar of a
  raid or fire stays readable for the rest of the match.

## Non-goals

- Storage caps (see `WAREHOUSE` above).
- Per-activity character animations. Characters keep the shared idle/walk set; the
  scout has its own idle sprites (`character.scout.idle.*`) and reuses the shared walk
  reference.
- Combat between units. Raids stay colony-level.

## Invariants that must survive

- **Determinism.** Identical seed and identical action sequences must produce identical
  state hashes regardless of wall-clock timing.
- **Replay.** `snapshots.jsonl` must round-trip through `castle-benchmark replay`.
- **Fog integrity.** No observation may leak a cell the colony has not seen, and no
  observation may leak live unit or resource data from outside the sight radius.
