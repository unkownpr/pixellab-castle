// @vitest-environment node

import { describe, expect, it } from "vitest";

import type { Observation } from "../src/api";
import {
  actionBatch,
  animationForEvent,
  characterDirectionBetween,
  colonyHome,
  colonyWorkSites,
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

describe("character work", () => {
  const observation: Observation = {
    schema_version: "1.0",
    scenario_id: "basic-survival-v1",
    turn: 3,
    colony_id: "c1",
    colony: { id: "c1", population: 5, housing: 6, health: {}, resources: {}, policies: {} },
    visible_cells: [
      { x: 0, y: 0, biome: "grassland", water: false, buildable: true, movement_cost: 1, resource: null, resource_amount: 0 },
      { x: 2, y: 1, biome: "grassland", water: false, buildable: true, movement_cost: 1, resource: "wood", resource_amount: 4 },
    ],
    visible_structures: [
      { id: "hq", colony_id: "c1", kind: "headquarters", status: "operational", progress: 1, required_progress: 1, condition: 100, x: 0, y: 0 },
      { id: "b", colony_id: "c1", kind: "house", status: "building", progress: 2, required_progress: 6, condition: 100, x: 3, y: 0 },
      { id: "other", colony_id: "c2", kind: "house", status: "building", progress: 1, required_progress: 6, condition: 100, x: 5, y: 5 },
    ],
    known_colonies: {},
    active_offers: [],
    valid_action_kinds: [],
  };

  it("locates the colony home from its headquarters", () => {
    expect(colonyHome(observation, "c1")).toEqual({ x: 0, y: 0 });
    expect(colonyHome(observation, "c9")).toBeNull();
  });

  it("collects build and gather work sites for one colony only", () => {
    expect(colonyWorkSites(observation, "c1")).toEqual([
      { kind: "build", x: 3, y: 0 },
      { kind: "gather", x: 2, y: 1 },
    ]);
  });

  it("maps movement to the four cardinal screen directions", () => {
    expect(characterDirectionBetween({ x: 0, y: 0 }, { x: 3, y: 3 })).toBe("south");
    expect(characterDirectionBetween({ x: 3, y: 3 }, { x: 0, y: 0 })).toBe("north");
    expect(characterDirectionBetween({ x: 0, y: 0 }, { x: 3, y: -3 })).toBe("east");
    expect(characterDirectionBetween({ x: 0, y: 0 }, { x: -3, y: 3 })).toBe("west");
  });
});
