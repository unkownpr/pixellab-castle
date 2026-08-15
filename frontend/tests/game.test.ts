// @vitest-environment node

import { describe, expect, it } from "vitest";

import type { Observation, VisibleCell } from "../src/api";
import {
  actionBatch,
  animationForEvent,
  characterDirectionBetween,
  characterVisualKind,
  colonyHome,
  colonyWorkSites,
  compareIsoDepth,
  isoToScreen,
  resourceDensity,
  sceneryPlacements,
  snapshotToObservation,
  structureOpacity,
  workDirection,
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

describe("structure rendering", () => {
  it("renders a ruined structure at reduced opacity", () => {
    expect(structureOpacity("ruined")).toBe(0.72);
    expect(structureOpacity("operational")).toBe(1);
    expect(structureOpacity("damaged")).toBe(1);
    expect(structureOpacity("foundation")).toBe(0.62);
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

  it("resolves all eight grid directions to their own screen facings", () => {
    const home = { x: 0, y: 0 };
    const facings = [
      characterDirectionBetween(home, { x: 1, y: 0 }),
      characterDirectionBetween(home, { x: 0, y: 1 }),
      characterDirectionBetween(home, { x: -1, y: 0 }),
      characterDirectionBetween(home, { x: 0, y: -1 }),
      characterDirectionBetween(home, { x: 1, y: 1 }),
      characterDirectionBetween(home, { x: -1, y: -1 }),
      characterDirectionBetween(home, { x: 1, y: -1 }),
      characterDirectionBetween(home, { x: -1, y: 1 }),
    ];

    expect(facings).toEqual([
      "south-east",
      "south-west",
      "north-west",
      "north-east",
      "south",
      "north",
      "east",
      "west",
    ]);
    expect(new Set(facings).size).toBe(8);
  });

  it("uses the work state at a site, walk in transit, idle otherwise", () => {
    expect(characterVisualKind("working")).toBe("work");
    expect(characterVisualKind("toJob")).toBe("walk");
    expect(characterVisualKind("toHome")).toBe("walk");
    expect(characterVisualKind("idle")).toBe("idle");
  });

  it("falls back to the nearest vertical for a diagonal work facing", () => {
    expect(workDirection("north-east")).toBe("north");
    expect(workDirection("north-west")).toBe("north");
    expect(workDirection("south-east")).toBe("south");
    expect(workDirection("south-west")).toBe("south");
    expect(workDirection("east")).toBe("east");
    expect(workDirection("west")).toBe("west");
  });
});

describe("resource scenery", () => {
  const base = {
    biome: "grassland",
    water: false,
    buildable: true,
    movement_cost: 1,
  } as const;

  it("draws a forest as pines and thins it as it depletes", () => {
    const full = sceneryPlacements({ x: 2, y: 1, ...base, resource: "wood", resource_amount: 80 });
    const stripped = sceneryPlacements({ x: 2, y: 1, ...base, resource: "wood", resource_amount: 20 });

    expect(full.length).toBeGreaterThan(stripped.length);
    expect(full).toHaveLength(5);
    expect(stripped).toHaveLength(1);
    expect(full.every((placement) => placement.key.startsWith("prop.pine.grass"))).toBe(true);
  });

  it("uses snowy pines in a snow biome", () => {
    const placements = sceneryPlacements({
      x: 0, y: 0, ...base, biome: "snow", resource: "wood", resource_amount: 80,
    });
    expect(placements.every((placement) => placement.key.startsWith("prop.pine.snow"))).toBe(true);
  });

  it("draws rock for stone and ore", () => {
    const stone = sceneryPlacements({ x: 4, y: 4, ...base, resource: "stone", resource_amount: 70 });
    const ore = sceneryPlacements({ x: 4, y: 4, ...base, resource: "ore", resource_amount: 70 });
    expect(stone.length).toBe(3);
    expect(stone.every((placement) => placement.key === "prop.rock")).toBe(true);
    expect(ore.every((placement) => placement.key === "prop.rock")).toBe(true);
  });

  it("draws food as a wheat field whose opacity tracks the amount", () => {
    const field = sceneryPlacements({ x: 1, y: 2, ...base, resource: "food", resource_amount: 40 });
    expect(field).toEqual([
      { key: "terrain.wheat.base", dx: 0, dy: 0, ground: true, alpha: resourceDensity(40) },
    ]);
    expect(resourceDensity(80)).toBe(1);
    expect(resourceDensity(32)).toBeCloseTo(0.5);
    expect(resourceDensity(16)).toBeCloseTo(0.25);
  });

  it("places scenery deterministically for a given cell and amount", () => {
    const cell: VisibleCell = {
      x: 7, y: 3, ...base, biome: "snow", resource: "wood", resource_amount: 55,
    };
    expect(sceneryPlacements(cell)).toEqual(sceneryPlacements({ ...cell }));
  });

  it("draws nothing for a cell with no resource", () => {
    expect(sceneryPlacements({ x: 0, y: 0, ...base, resource: null, resource_amount: 0 })).toEqual([]);
  });
});
