// @vitest-environment node

import { describe, expect, it } from "vitest";

import {
  actionBatch,
  animationForEvent,
  compareIsoDepth,
  isoToScreen,
  snapshotToObservation,
} from "../src/game";

describe("isometric projection", () => {
  it("projects authoritative grid positions without mutating them", () => {
    const position = { x: 2, y: 1 };

    expect(isoToScreen(position, { x: 0, y: 0 })).toEqual({ x: 24, y: 36 });
    expect(position).toEqual({ x: 2, y: 1 });
  });

  it("sorts sprites by diagonal and then x for stable painter order", () => {
    const cells = [
      { x: 3, y: 0 },
      { x: 0, y: 2 },
      { x: 1, y: 1 },
    ];

    expect(cells.toSorted(compareIsoDepth)).toEqual([
      { x: 0, y: 2 },
      { x: 1, y: 1 },
      { x: 3, y: 0 },
    ]);
  });
});

describe("controller protocol", () => {
  it("binds actions to the observed turn and colony", () => {
    expect(actionBatch(7, "c2", [{ kind: "wait" }])).toEqual({
      version: "1",
      turn: 7,
      colony_id: "c2",
      actions: [{ kind: "wait" }],
    });
  });

  it.each([
    ["construction_started", "construction"],
    ["construction_completed", "completion"],
    ["combat_damage", "impact"],
    ["fire_started", "fire"],
    ["weather", "weather"],
    ["unknown_event", "none"],
  ])("maps %s to %s without interpreting game state", (kind, animation) => {
    expect(animationForEvent({ kind })).toBe(animation);
  });
});

describe("replay adapter", () => {
  it("projects an omniscient canonical snapshot without hiding ruins", () => {
    const observation = snapshotToObservation({
      scenario_id: "basic-survival-v1",
      turn: 9,
      world: {
        cells: [{ x: 1, y: 2, biome: "grassland", water: false, buildable: true, movement_cost: 1, resource: null, resource_amount: 0 }],
      },
      colonies: {
        c1: { id: "c1", population: 7, housing: 8, healthy: 6, injured: 1, sick: 0, hungry: 0, resources: { food: 9 }, policies: {}, relations: {} },
      },
      structures: {
        s1: { id: "s1", colony_id: "c1", kind: "house", status: "ruined", progress: 3, required_progress: 3, condition: 0, position: { x: 1, y: 2 } },
      },
      offers: {},
    }, "c1");

    expect(observation.turn).toBe(9);
    expect(observation.visible_cells).toHaveLength(1);
    expect(observation.visible_structures[0]?.status).toBe("ruined");
  });
});
