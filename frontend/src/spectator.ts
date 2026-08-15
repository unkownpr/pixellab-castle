import type { Observation, SpectatorView } from "./api";

export const SPECTATOR_COLONY_ID = "spectator";

export function spectatorToObservation(view: SpectatorView): Observation {
  return {
    schema_version: "1.0",
    scenario_id: view.scenario_id,
    turn: view.turn,
    colony_id: SPECTATOR_COLONY_ID,
    colony: {
      id: SPECTATOR_COLONY_ID,
      population: 0,
      housing: 0,
      health: { healthy: 0, injured: 0, sick: 0, hungry: 0 },
      resources: {},
      policies: {},
    },
    visible_cells: view.visible_cells,
    visible_structures: view.visible_structures,
    scouts: view.scouts,
    known_colonies: {},
    active_offers: view.active_offers,
    valid_action_kinds: [],
  };
}

export interface WorldViewSelection {
  readonly observation: Observation;
  readonly spectator: boolean;
}

export function selectWorldObservation(
  hasHumanController: boolean,
  humanObservation: Observation | null,
  spectator: SpectatorView | null,
): WorldViewSelection | null {
  if (hasHumanController) {
    return humanObservation ? { observation: humanObservation, spectator: false } : null;
  }
  return spectator ? { observation: spectatorToObservation(spectator), spectator: true } : null;
}
