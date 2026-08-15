import { describe, expect, it } from "vitest";

import type { Observation, SpectatorView } from "../src/api";
import {
  SPECTATOR_COLONY_ID,
  selectWorldObservation,
  spectatorToObservation,
} from "../src/spectator";

function cell(x: number, y: number) {
  return { x, y, biome: "grassland" as const, water: false, buildable: true, movement_cost: 1, resource: null, resource_amount: 0 };
}

const fullView: SpectatorView = {
  schema_version: "1.1",
  scenario_id: "basic-survival-v1",
  turn: 4,
  colony_id: "spectator",
  colonies: {
    c1: { id: "c1", population: 8, housing: 8, healthy: 8, injured: 0, sick: 0, hungry: 0, resources: { food: 10 } },
    c2: { id: "c2", population: 8, housing: 8, healthy: 8, injured: 0, sick: 0, hungry: 0, resources: { food: 12 } },
  },
  visible_cells: [cell(0, 0), cell(1, 1), cell(14, 3)],
  visible_structures: [
    { id: "s1", colony_id: "c1", kind: "headquarters", status: "operational", progress: 1, required_progress: 1, condition: 100, x: 3, y: 3 },
    { id: "s2", colony_id: "c2", kind: "headquarters", status: "operational", progress: 1, required_progress: 1, condition: 100, x: 14, y: 3 },
  ],
  scouts: [],
  active_offers: [],
};

const fogObservation: Observation = {
  schema_version: "1.0",
  scenario_id: "basic-survival-v1",
  turn: 4,
  colony_id: "c1",
  colony: { id: "c1", population: 8, housing: 8, health: {}, resources: {}, policies: {} },
  visible_cells: [cell(3, 3)],
  visible_structures: [
    { id: "s1", colony_id: "c1", kind: "headquarters", status: "operational", progress: 1, required_progress: 1, condition: 100, x: 3, y: 3 },
  ],
  known_colonies: {},
  active_offers: [],
  valid_action_kinds: [],
};

describe("spectator projection", () => {
  it("maps the whole world into a renderer-ready observation with distinguishable colonies", () => {
    const observation = spectatorToObservation(fullView);

    expect(observation.colony_id).toBe(SPECTATOR_COLONY_ID);
    expect(observation.visible_cells).toHaveLength(fullView.visible_cells.length);
    expect(observation.visible_structures.map(({ colony_id }) => colony_id)).toEqual(["c1", "c2"]);
    expect(observation.schema_version).toBe("1.0");
  });

  it("selects the fog-limited observation when the operator holds a colony", () => {
    const selection = selectWorldObservation(true, fogObservation, fullView);

    expect(selection).not.toBeNull();
    expect(selection!.spectator).toBe(false);
    expect(selection!.observation).toBe(fogObservation);
    expect(selection!.observation.visible_cells).toHaveLength(1);
  });

  it("selects the whole-world observation when the operator holds no colony", () => {
    const selection = selectWorldObservation(false, null, fullView);

    expect(selection).not.toBeNull();
    expect(selection!.spectator).toBe(true);
    expect(selection!.observation.colony_id).toBe(SPECTATOR_COLONY_ID);
    expect(selection!.observation.visible_cells).toHaveLength(fullView.visible_cells.length);
  });

  it("drives the renderer with the whole world for a controllerless operator", async () => {
    const rendered: Observation[] = [];
    const renderer = { render: async (observation: Observation) => { rendered.push(observation); } };
    const selection = selectWorldObservation(false, null, fullView)!;

    await renderer.render(selection.observation);

    expect(rendered).toHaveLength(1);
    expect(rendered[0]!.colony_id).toBe(SPECTATOR_COLONY_ID);
    expect(rendered[0]!.visible_cells).toHaveLength(fullView.visible_cells.length);
    expect(rendered[0]!.visible_structures).toHaveLength(2);
  });

  it("drives the renderer with only the fog-limited view when the operator holds a colony", async () => {
    const rendered: Observation[] = [];
    const renderer = { render: async (observation: Observation) => { rendered.push(observation); } };
    const selection = selectWorldObservation(true, fogObservation, fullView)!;

    await renderer.render(selection.observation);

    expect(rendered).toHaveLength(1);
    expect(rendered[0]).toBe(fogObservation);
    expect(rendered[0]!.visible_cells).toHaveLength(1);
  });
});
