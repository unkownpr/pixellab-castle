import type { ControllerAction } from "./game";

export type StructureKind =
  | "headquarters" | "house" | "warehouse" | "well" | "farm"
  | "lumber_camp" | "quarry" | "mine" | "market" | "workshop"
  | "clinic" | "barracks" | "watchtower" | "wall" | "gate";

export type StructureStatus =
  | "planned" | "foundation" | "building" | "operational"
  | "damaged" | "burning" | "ruined" | "repairing";

export interface ScenarioSummary {
  readonly id: string;
  readonly name: string;
  readonly biome: "grassland" | "desert" | "snow";
  readonly width: number;
  readonly height: number;
  readonly max_turns: number;
  readonly max_colonies: number;
}

export interface MatchCreated {
  readonly match_id: string;
  readonly scenario_id: string;
  readonly controller_tokens: Readonly<Record<string, string>>;
  readonly admin_token: string;
}

export interface VisibleCell {
  readonly x: number;
  readonly y: number;
  readonly biome: "grassland" | "desert" | "snow";
  readonly water: boolean;
  readonly buildable: boolean;
  readonly movement_cost: number;
  readonly resource: string | null;
  readonly resource_amount: number;
}

export interface VisibleStructure {
  readonly id: string;
  readonly colony_id: string;
  readonly kind: StructureKind;
  readonly status: StructureStatus;
  readonly progress: number;
  readonly required_progress: number;
  readonly condition: number;
  readonly x: number;
  readonly y: number;
}

export interface ColonyView {
  readonly id: string;
  readonly population: number;
  readonly housing: number;
  readonly health: Readonly<Record<string, number>>;
  readonly resources: Readonly<Record<string, number>>;
  readonly policies: Readonly<Record<string, string>>;
}

export interface Observation {
  readonly schema_version: "1.0";
  readonly scenario_id: string;
  readonly turn: number;
  readonly colony_id: string;
  readonly colony: ColonyView;
  readonly visible_cells: readonly VisibleCell[];
  readonly visible_structures: readonly VisibleStructure[];
  readonly known_colonies: Readonly<Record<string, Readonly<Record<string, unknown>>>>;
  readonly active_offers: readonly Readonly<Record<string, unknown>>[];
  readonly valid_action_kinds: readonly string[];
}

export interface ActionRequest {
  readonly turn: number;
  readonly actions: readonly ControllerAction[];
}

export interface SubmissionResult {
  readonly status: "pending" | "resolved";
  readonly turn: number;
  readonly waiting_for: readonly string[];
  readonly events?: readonly Readonly<Record<string, unknown>>[];
}

interface ErrorEnvelope {
  readonly detail?: { readonly code?: string; readonly message?: string };
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export class BenchmarkApi {
  constructor(private readonly baseUrl = "") {}

  async scenarios(): Promise<readonly ScenarioSummary[]> {
    return this.request("/api/scenarios");
  }

  async createMatch(input: {
    readonly scenario_id: string;
    readonly seed: number;
    readonly colony_count: number;
  }): Promise<MatchCreated> {
    return this.request("/api/matches", { method: "POST", body: JSON.stringify(input) });
  }

  async observe(matchId: string, colonyId: string, token: string): Promise<Observation> {
    const path = `/api/matches/${encodeURIComponent(matchId)}/observation?colony_id=${encodeURIComponent(colonyId)}`;
    return this.request(path, {}, token);
  }

  async submitActions(
    matchId: string,
    token: string,
    input: ActionRequest,
  ): Promise<SubmissionResult> {
    return this.request(
      `/api/matches/${encodeURIComponent(matchId)}/actions`,
      { method: "POST", body: JSON.stringify(input) },
      token,
    );
  }

  async status(matchId: string, token: string): Promise<Readonly<Record<string, unknown>>> {
    return this.request(`/api/matches/${encodeURIComponent(matchId)}/status`, {}, token);
  }

  private async request<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
    const headers: Record<string, string> = {};
    if (init.body) headers["Content-Type"] = "application/json";
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(`${this.baseUrl}${path}`, { ...init, headers });
    const payload: unknown = await response.json();
    if (!response.ok) {
      const envelope = payload as ErrorEnvelope;
      throw new ApiError(
        response.status,
        envelope.detail?.code ?? "request_failed",
        envelope.detail?.message ?? `Request failed with status ${response.status}`,
      );
    }
    return payload as T;
  }
}
