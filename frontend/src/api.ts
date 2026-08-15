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

export type SchemaVersion = "1.1";
export type ControllerType = "human" | "baseline" | "external";
export type BaselineKind =
  | "random_valid"
  | "survivalist"
  | "trader"
  | "expansionist"
  | "militarist";
export type HeartbeatStatus =
  | "ready"
  | "connected"
  | "thinking"
  | "submitted"
  | "disconnected";

export interface SessionSlotConfiguration {
  readonly colony_id: string;
  readonly controller_type: ControllerType;
  readonly baseline_kind?: BaselineKind | null;
}

export interface CreateSessionInput {
  readonly scenario_id: string;
  readonly seed: number;
  readonly colony_count: number;
  readonly deadline_seconds: number;
  readonly slots: readonly SessionSlotConfiguration[];
}

export interface SessionCreated {
  readonly schema_version: SchemaVersion;
  readonly match_id: string;
  readonly scenario_id: string;
  readonly status: "draft";
  readonly admin_token: string;
}

export interface ControllerIdentity {
  readonly display_name: string;
  readonly provider: string;
  readonly model: string;
  readonly model_version?: string | null;
  readonly adapter_name?: string | null;
  readonly adapter_version?: string | null;
  readonly connection_mode?: string | null;
  readonly run_label?: string | null;
}

export interface LobbySlot {
  readonly colony_id: string;
  readonly controller_type: ControllerType;
  readonly controller_id: string | null;
  readonly identity: ControllerIdentity | null;
  readonly presence: string;
  readonly baseline_kind: string | null;
  readonly generation: number;
  readonly pairing_active: boolean;
  readonly pairing_expires_at: number | null;
  readonly pairing_consumed: boolean;
  readonly pairing_attempts: number;
  readonly last_heartbeat_at: number | null;
  readonly last_heartbeat_turn: number | null;
}

export interface LobbySnapshot {
  readonly schema_version: SchemaVersion;
  readonly match_id: string;
  readonly scenario_id: string;
  readonly seed: number;
  readonly colony_count: number;
  readonly deadline_seconds: number;
  readonly status: string;
  readonly slots: readonly LobbySlot[];
}

export interface PairingGrant {
  readonly schema_version: SchemaVersion;
  readonly match_id: string;
  readonly colony_id: string;
  readonly pairing_code: string;
  readonly expires_at: number;
}

export interface MutationResult {
  readonly schema_version: SchemaVersion;
  readonly match_id: string;
  readonly status: string;
}

export interface SlotMutationResult extends MutationResult {
  readonly colony_id: string;
}

export interface SlotConfigurationResult {
  readonly schema_version: SchemaVersion;
  readonly match_id: string;
  readonly colony_id: string;
  readonly controller_type: ControllerType;
  readonly presence: string;
}

export interface HumanControllerCapability {
  readonly schema_version: SchemaVersion;
  readonly match_id: string;
  readonly colony_id: string;
  readonly controller_token: string;
}

export interface OperationalEvent {
  readonly sequence: number;
  readonly turn: number;
  readonly kind: string;
  readonly colony_id: string | null;
  readonly data: Readonly<Record<string, unknown>>;
}

export interface ControllerTenure {
  readonly colony_id: string;
  readonly controller_id: string;
  readonly controller_type: ControllerType;
  readonly identity: ControllerIdentity | null;
  readonly generation: number;
  readonly started_at: number;
  readonly ended_at: number | null;
}

export interface OperationsSnapshot extends LobbySnapshot {
  readonly turn: number;
  readonly deadline_at: number | null;
  readonly pending_colonies: readonly string[];
  readonly events: readonly OperationalEvent[];
  readonly tenures: Readonly<Record<string, readonly ControllerTenure[]>>;
}

export interface RunReport {
  readonly schema_version: SchemaVersion;
  readonly status: Readonly<Record<string, unknown>>;
  readonly metrics: Readonly<Record<string, unknown>>;
  readonly latest_events: readonly Readonly<Record<string, unknown>>[];
}

export interface OperationsWebSocketTicket {
  readonly schema_version: SchemaVersion;
  readonly match_id: string;
  readonly websocket_ticket: string;
  readonly expires_at: number;
}

export type AdminWebSocketMessage =
  | { readonly schema_version: SchemaVersion; readonly type: "lobby.snapshot"; readonly payload: OperationsSnapshot }
  | { readonly schema_version: SchemaVersion; readonly type: "controller.presence_changed" | "turn.opened" | "controller.submitted" | "turn.resolved" | "match.completed" | "controller.claimed" | "pairing.rejected" | "controller.heartbeat_rejected" | "controller.timed_out" | "controller.replaced"; readonly payload: OperationalEvent }
  | { readonly schema_version: SchemaVersion; readonly type: "metric.updated"; readonly payload: { readonly event: OperationalEvent; readonly metrics: Readonly<Record<string, unknown>> } };

export type WebSocketConstructor = new (url: string, protocols?: string | string[]) => WebSocket;

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

export interface VisibleScout {
  readonly id: string;
  readonly colony_id: string;
  readonly x: number;
  readonly y: number;
  readonly target_x: number;
  readonly target_y: number;
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
  readonly schema_version: "1.0" | "1.1";
  readonly scenario_id: string;
  readonly turn: number;
  readonly colony_id: string;
  readonly colony: ColonyView;
  readonly visible_cells: readonly VisibleCell[];
  readonly visible_structures: readonly VisibleStructure[];
  readonly scouts?: readonly VisibleScout[];
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
    if (input.colony_count !== 1) {
      throw new Error("Legacy development quick play supports one colony only");
    }
    return this.request("/api/matches", { method: "POST", body: JSON.stringify(input) });
  }

  async createDevelopmentMatch(input: {
    readonly scenario_id: string;
    readonly seed: number;
  }): Promise<MatchCreated> {
    return this.createMatch({ ...input, colony_count: 1 });
  }

  async createSession(input: CreateSessionInput, orchestratorToken?: string): Promise<SessionCreated> {
    return this.request(
      "/api/sessions",
      { method: "POST", body: JSON.stringify(input) },
      orchestratorToken,
    );
  }

  async lobby(matchId: string, adminToken: string): Promise<LobbySnapshot> {
    return this.request(`/api/sessions/${encodeURIComponent(matchId)}/lobby`, {}, adminToken);
  }

  async configureSlot(
    matchId: string,
    colonyId: string,
    adminToken: string,
    input: { readonly controller_type: ControllerType; readonly baseline_kind?: BaselineKind | null },
  ): Promise<SlotConfigurationResult> {
    return this.request(
      `/api/sessions/${encodeURIComponent(matchId)}/slots/${encodeURIComponent(colonyId)}`,
      { method: "POST", body: JSON.stringify(input) },
      adminToken,
    );
  }

  async createPairing(matchId: string, colonyId: string, adminToken: string): Promise<PairingGrant> {
    return this.request(
      `/api/sessions/${encodeURIComponent(matchId)}/slots/${encodeURIComponent(colonyId)}/pairing`,
      { method: "POST" },
      adminToken,
    );
  }

  async heartbeat(
    matchId: string,
    controllerToken: string,
    input: { readonly turn: number; readonly status: HeartbeatStatus },
  ): Promise<MutationResult> {
    return this.request(
      `/api/sessions/${encodeURIComponent(matchId)}/heartbeat`,
      { method: "POST", body: JSON.stringify(input) },
      controllerToken,
    );
  }

  async startSession(matchId: string, adminToken: string): Promise<MutationResult> {
    return this.request(
      `/api/sessions/${encodeURIComponent(matchId)}/start`,
      { method: "POST" },
      adminToken,
    );
  }

  async humanCapability(
    matchId: string,
    colonyId: string,
    adminToken: string,
  ): Promise<HumanControllerCapability> {
    return this.request(
      `/api/sessions/${encodeURIComponent(matchId)}/slots/${encodeURIComponent(colonyId)}/human-capability`,
      { method: "POST" },
      adminToken,
    );
  }

  async replaceSlot(
    matchId: string,
    colonyId: string,
    adminToken: string,
    input: { readonly replacement: ControllerType; readonly baseline_kind?: BaselineKind | null },
  ): Promise<SlotMutationResult> {
    return this.request(
      `/api/sessions/${encodeURIComponent(matchId)}/slots/${encodeURIComponent(colonyId)}/replace`,
      { method: "POST", body: JSON.stringify(input) },
      adminToken,
    );
  }

  async operations(matchId: string, adminToken: string): Promise<OperationsSnapshot> {
    return this.request(`/api/matches/${encodeURIComponent(matchId)}/operations`, {}, adminToken);
  }

  async report(matchId: string, adminToken: string): Promise<RunReport> {
    return this.request(`/api/matches/${encodeURIComponent(matchId)}/report`, {}, adminToken);
  }

  async operationsTicket(matchId: string, adminToken: string): Promise<OperationsWebSocketTicket> {
    return this.request(
      `/api/matches/${encodeURIComponent(matchId)}/operations/ticket`,
      { method: "POST" },
      adminToken,
    );
  }

  openOperationsSocket(
    matchId: string,
    ticket: string,
    Socket: WebSocketConstructor = WebSocket,
  ): WebSocket {
    const pageBase = typeof window === "undefined" ? "http://localhost" : window.location.href;
    const url = new URL(
      `${this.baseUrl}/api/matches/${encodeURIComponent(matchId)}/operations/ws`,
      pageBase,
    );
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return new Socket(url.toString(), ["castle.operations", ticket]);
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
