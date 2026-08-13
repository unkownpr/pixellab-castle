// @vitest-environment node

import { describe, expect, it } from "vitest";

import {
  actionBatch,
  animationForEvent,
  compareIsoDepth,
  isoToScreen,
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
