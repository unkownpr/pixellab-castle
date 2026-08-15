import {
  ApiError,
  BenchmarkApi,
  type AdminWebSocketMessage,
  type CreateSessionInput,
  type Observation,
  type ScenarioSummary,
  type SessionCreated,
  type SpectatorView,
  type VisibleCell,
} from "./api";
import {
  CastleRenderer,
  snapshotToObservation,
  type ControllerAction,
  type ReplaySnapshot,
} from "./game";
import {
  LobbyController,
  setHumanActionControlsEnabled,
  type StartedHumanController,
} from "./lobby";
import {
  OperationsController,
  bindOperationsRoom,
  currentSourceMessageHandler,
  renderOperationsRoom,
} from "./operations";
import { selectWorldObservation } from "./spectator";
import {
  biomeName,
  initLanguage,
  resourceName,
  setLanguage,
  translate,
  translateStatic,
  type Lang,
} from "./i18n";
import { updateMatchStateIndicator, type MatchPhase } from "./matchState";

type ActionKind = "wait" | "gather" | "build" | "policy" | "diplomacy" | "trade" | "raid";

function required<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(translate("ui.missingElement", { selector }));
  return element;
}

class WorkbenchApi extends BenchmarkApi {
  constructor(private readonly onSessionCreated: (session: SessionCreated) => void) {
    super();
  }

  override async createSession(
    input: CreateSessionInput,
    orchestratorToken?: string,
  ): Promise<SessionCreated> {
    const created = await super.createSession(input, orchestratorToken);
    this.onSessionCreated(created);
    return created;
  }
}

export class BenchmarkWorkbench {
  private readonly api: WorkbenchApi;
  private readonly renderer = new CastleRenderer();
  private readonly operations: OperationsController;
  private lobby: LobbyController | null = null;
  private activeMatchId: string | null = null;
  private humanController: { readonly colonyId: string; readonly token: string } | null = null;
  private observation: Observation | null = null;
  private scenarios: readonly ScenarioSummary[] = [];
  private scenarioLabel: string | null = null;
  private selectedCell: VisibleCell | null = null;
  private replayFrames: readonly ReplaySnapshot[] = [];
  private busy = false;
  private matchTerminal = false;
  private operationsCapability: { readonly matchId: string; readonly token: string } | null = null;
  private operationsSocket: WebSocket | null = null;
  private operationsReconnectTimer: number | null = null;
  private operationsReconnectAttempt = 0;
  private operationsRefreshVersion = 0;
  private matchPhase: MatchPhase = "idle";
  private connectionKey: "connection.connected" | "connection.unreachable" | "connection.localReady" = "connection.localReady";
  private connectionUp = false;
  private fogMode: "fog" | "spectator" | "replay" = "fog";
  private replayPosition: { readonly index: number; readonly total: number } | null = null;

  constructor() {
    this.api = new WorkbenchApi((session) => {
      void this.attachOperations(session.match_id, session.admin_token);
    });
    this.operations = new OperationsController({
      onChange: (controller) => {
        const app = document.querySelector<HTMLElement>("#app");
        if (app) renderOperationsRoom(app, controller);
        this.renderer.focusColony(controller.state.selectedAgentId);
      },
    });
  }

  async init(): Promise<void> {
    const lang = initLanguage();
    this.syncLanguageControl(lang);
    translateStatic(document);
    const app = required<HTMLElement>("#app");
    this.operations.announce(translate("ops.announcement.waiting"));
    renderOperationsRoom(app, this.operations);
    bindOperationsRoom(app, this.operations);
    await Promise.all([this.renderer.init(required("#world-host")), this.loadScenarios()]);
    this.lobby = new LobbyController(required("#lobby-root"), this.api, {
      onStarted: (controller) => void this.sessionStarted(controller),
      onError: (error) => this.logError(error),
    });
    this.renderer.onCellSelected((cell) => this.selectCell(cell));
    required<HTMLFormElement>("#match-form").addEventListener("submit", (event) => {
      event.preventDefault();
      void this.createSession();
    });
    required<HTMLButtonElement>("#dev-quick-play").addEventListener("click", () => {
      void this.createDevelopmentQuickPlay();
    });
    document.querySelectorAll<HTMLButtonElement>("[data-action]").forEach((button) => {
      button.addEventListener("click", () => void this.takeAction(button.dataset.action as ActionKind));
    });
    required<HTMLButtonElement>("#clear-events").addEventListener("click", () => {
      required<HTMLOListElement>("#event-log").replaceChildren();
    });
    required<HTMLInputElement>("#replay-input").addEventListener("change", (event) => {
      void this.loadReplay((event.currentTarget as HTMLInputElement).files?.[0]);
    });
    required<HTMLInputElement>("#replay-range").addEventListener("input", (event) => {
      void this.renderReplay(Number((event.currentTarget as HTMLInputElement).value));
    });
    required<HTMLButtonElement>("#replay-prev").addEventListener("click", () => void this.stepReplay(-1));
    required<HTMLButtonElement>("#replay-next").addEventListener("click", () => void this.stepReplay(1));
    document.querySelectorAll<HTMLButtonElement>("[data-world-view]").forEach((button) => {
      button.addEventListener("click", () => this.changeWorldView(button.dataset.worldView ?? ""));
    });
    required<HTMLSelectElement>("#language-select").addEventListener("change", (event) => {
      const next = (event.currentTarget as HTMLSelectElement).value as Lang;
      this.applyLanguage(next);
    });
    this.applyMatchState();
    this.applyConnection();
    this.applyWorldLabels();
  }

  private applyLanguage(lang: Lang): void {
    setLanguage(lang);
    translateStatic(document);
    const app = document.querySelector<HTMLElement>("#app");
    if (app) renderOperationsRoom(app, this.operations);
    this.lobby?.rerender();
    this.applyMatchState();
    this.applyConnection();
    this.applyWorldLabels();
    // Anything holding live data has just been overwritten by translateStatic, or
    // was built once in the previous language: the scenario list carries translated
    // biome names, the scenario caption carries the running match, and the turn
    // caption is painted into the canvas.
    this.renderScenarioOptions();
    this.restoreScenarioLabel();
    if (this.observation) void this.renderer.render(this.observation);
  }

  private setScenarioLabel(text: string): void {
    this.scenarioLabel = text;
    required("#scenario-label").textContent = text;
  }

  private restoreScenarioLabel(): void {
    if (this.scenarioLabel) required("#scenario-label").textContent = this.scenarioLabel;
  }

  private syncLanguageControl(lang: Lang): void {
    const select = document.querySelector<HTMLSelectElement>("#language-select");
    if (select) select.value = lang;
  }

  private applyMatchState(): void {
    updateMatchStateIndicator(document, this.matchPhase);
  }

  private applyConnection(): void {
    required("#connection-label").textContent = translate(this.connectionKey);
    document.body.classList.toggle("is-offline", !this.connectionUp);
    const shape = document.querySelector<HTMLElement>(".run-state .status-shape");
    if (shape) shape.dataset.statusShape = this.connectionUp ? "circle" : "ring";
  }

  private applyWorldLabels(): void {
    const fog = required("#fog-label");
    if (this.fogMode === "spectator") fog.textContent = translate("map.spectator");
    else if (this.fogMode === "replay" && this.replayPosition) {
      fog.textContent = translate("map.replay", this.replayPosition);
    } else fog.textContent = translate("map.fogActive");
  }

  private setMatchPhase(phase: MatchPhase): void {
    if (this.matchPhase === phase) return;
    this.matchPhase = phase;
    this.applyMatchState();
  }

  private async loadScenarios(): Promise<void> {
    try {
      this.scenarios = await this.api.scenarios();
      this.renderScenarioOptions();
      this.setConnection("connection.connected", true);
    } catch (error) {
      this.setConnection("connection.unreachable", false);
      this.logError(error);
    }
  }

  private renderScenarioOptions(): void {
    const select = required<HTMLSelectElement>("#scenario-select");
    const chosen = select.value;
    select.replaceChildren(...this.scenarios.map((scenario) => this.scenarioOption(scenario)));
    if (chosen) select.value = chosen;
  }

  private scenarioOption(scenario: ScenarioSummary): HTMLOptionElement {
    const option = document.createElement("option");
    option.value = scenario.id;
    option.textContent = `${scenario.name} · ${biomeName(scenario.biome)}`;
    option.dataset.biome = scenario.biome;
    return option;
  }

  private async createSession(): Promise<void> {
    if (!this.lobby || this.busy) return;
    const orchestratorInput = required<HTMLInputElement>("#orchestrator-token");
    const orchestratorToken = orchestratorInput.value;
    orchestratorInput.value = "";
    const colonyCount = Number(required<HTMLInputElement>("#colony-input").value);
    const input: CreateSessionInput = {
      scenario_id: required<HTMLSelectElement>("#scenario-select").value,
      seed: Number(required<HTMLInputElement>("#seed-input").value),
      colony_count: colonyCount,
      deadline_seconds: Number(required<HTMLInputElement>("#deadline-input").value),
      slots: colonyCount === 1 ? [{ colony_id: "c1", controller_type: "human" }] : [],
    };
    this.setBusy(true);
    try {
      this.activeMatchId = null;
      this.humanController = null;
      await this.lobby.create(input, orchestratorToken);
      this.resetRunState();
      this.setMatchPhase("waiting");
      this.replaceLog(translate("ui.draftCreated"));
    } catch (error) {
      this.logError(error);
    } finally {
      this.setBusy(false);
    }
  }

  private async createDevelopmentQuickPlay(): Promise<void> {
    if (this.busy) return;
    const orchestratorInput = required<HTMLInputElement>("#orchestrator-token");
    const orchestratorToken = orchestratorInput.value;
    orchestratorInput.value = "";
    this.setBusy(true);
    try {
      const created = await this.api.createDevelopmentMatch(
        {
          scenario_id: required<HTMLSelectElement>("#scenario-select").value,
          seed: Number(required<HTMLInputElement>("#seed-input").value),
        },
        orchestratorToken,
      );
      const token = created.controller_tokens.c1;
      if (!token) throw new Error(translate("ui.devCapabilityMissing"));
      this.lobby?.dispose();
      this.closeOperationsLive();
      this.operationsCapability = null;
      this.operations.reset(translate("ui.devNoOps"));
      this.activeMatchId = created.match_id;
      this.humanController = { colonyId: "c1", token };
      this.resetRunState();
      this.setMatchPhase("running");
      this.replaceLog(translate("ui.devQuickPlay"));
      await this.refreshObservation();
      this.enableActions(true);
    } catch (error) {
      this.logError(error);
    } finally {
      this.setBusy(false);
    }
  }

  private async sessionStarted(controller: StartedHumanController): Promise<void> {
    this.activeMatchId = controller.matchId;
    this.humanController = controller.colonyId && controller.controllerToken
      ? { colonyId: controller.colonyId, token: controller.controllerToken }
      : null;
    this.resetRunState();
    this.setMatchPhase("running");
    this.replaceLog(translate("ui.matchStarted"));
    void this.refreshOperations();
    this.enableActions(Boolean(this.humanController));
    try {
      await this.refreshObservation();
    } catch (error) {
      this.logError(error);
    }
    if (!this.humanController) {
      this.log(translate("ui.spectatorNote"), "muted");
    }
  }

  private resetRunState(): void {
    this.selectedCell = null;
    this.matchTerminal = false;
    this.replayFrames = [];
    required<HTMLElement>("#replay-controls").hidden = true;
  }

  private async takeAction(kind: ActionKind): Promise<void> {
    if (!this.activeMatchId || !this.humanController || !this.observation || this.busy) return;
    const action = this.humanAction(kind);
    if (!action) return;
    this.setBusy(true);
    try {
      const result = await this.api.submitActions(this.activeMatchId, this.humanController.token, {
        turn: this.observation.turn,
        actions: [action],
      });
      this.appendEvents(result.events ?? []);
      if (result.waiting_for.length) {
        this.log(translate("ui.waitingFor", { waiting: result.waiting_for.join(", ") }), "muted");
      }
      await this.refreshObservation();
      const status = await this.api.status(this.activeMatchId, this.humanController.token);
      this.matchTerminal = status.terminal === true;
      if (this.matchTerminal) {
        this.setMatchPhase("finished");
        this.log(translate("ui.matchComplete", { reason: String(status.termination_reason ?? "terminal") }), "event");
      }
    } catch (error) {
      this.logError(error);
    } finally {
      this.setBusy(false);
    }
  }

  private humanAction(kind: ActionKind): ControllerAction | null {
    if (kind === "wait") return { kind: "wait" };
    if (kind === "policy") return { kind: "set_policy", policy: "military_posture", value: "defensive" };
    if (["diplomacy", "trade", "raid"].includes(kind)) {
      const known = Object.values(this.observation?.known_colonies ?? {});
      const target = known.find((colony) => colony.contacted !== true) ?? known[0];
      const targetId = typeof target?.id === "string" ? target.id : null;
      if (!targetId) {
        this.log(translate("ui.noColonyInRange"), "warning");
        return null;
      }
      if (kind === "diplomacy") {
        return { kind: "diplomacy", target_colony_id: targetId, operation: "contact", message: translate("ui.diplomacyMessage") };
      }
      if (kind === "trade") {
        return { kind: "trade_offer", target_colony_id: targetId, give: [["wood", 2]], receive: [["food", 2]], message: translate("ui.tradeMessage") };
      }
      return { kind: "raid", target_colony_id: targetId };
    }
    if (!this.selectedCell) {
      this.log(translate("ui.selectCellFirst"), "warning");
      return null;
    }
    const position = { x: this.selectedCell.x, y: this.selectedCell.y };
    if (kind === "gather") return { kind: "gather", ...position };
    return {
      kind: "build",
      structure: required<HTMLSelectElement>("#structure-select").value,
      ...position,
    };
  }

  private async refreshObservation(): Promise<void> {
    if (!this.activeMatchId) return;
    let humanObservation: Observation | null = null;
    let spectatorView: SpectatorView | null = null;
    if (this.humanController) {
      humanObservation = await this.api.observe(
        this.activeMatchId,
        this.humanController.colonyId,
        this.humanController.token,
      );
    } else if (this.operationsCapability) {
      spectatorView = await this.api.spectator(
        this.operationsCapability.matchId,
        this.operationsCapability.token,
      );
    }
    const selection = selectWorldObservation(
      Boolean(this.humanController),
      humanObservation,
      spectatorView,
    );
    if (!selection) return;
    this.observation = selection.observation;
    await this.renderer.render(this.observation);
    if (selection.spectator) {
      this.renderSpectatorStats(spectatorView!);
      this.fogMode = "spectator";
    } else {
      this.renderStats(this.observation);
      this.fogMode = "fog";
    }
    this.applyWorldLabels();
  }

  private renderSpectatorStats(view: SpectatorView): void {
    required<HTMLOutputElement>("#turn-output").value = `T${view.turn}`;
    this.setScenarioLabel(view.scenario_id.toUpperCase());
    const container = document.createElement("div");
    container.className = "spectator-colonies";
    for (const [colonyId, colony] of Object.entries(view.colonies)) {
      const row = document.createElement("div");
      row.className = "spectator-colony";
      const label = document.createElement("strong");
      label.textContent = colonyId;
      const detail = document.createElement("span");
      detail.textContent = translate("ledger.populationValue", { population: colony.population, housing: colony.housing });
      row.append(label, detail);
      container.append(row);
    }
    required("#colony-stats").replaceChildren(container);
  }

  private async loadReplay(file: File | undefined): Promise<void> {
    if (!file) return;
    try {
      const frames = (await file.text())
        .split(/\r?\n/)
        .filter((line) => line.trim())
        .map((line) => JSON.parse(line) as ReplaySnapshot);
      if (!frames.length) throw new Error(translate("ui.replayNoFrames"));
      this.replayFrames = frames;
      this.activeMatchId = null;
      this.humanController = null;
      this.matchTerminal = true;
      this.lobby?.dispose();
      this.closeOperationsLive();
      this.operationsCapability = null;
      this.operations.reset(translate("ui.replayMode"));
      const range = required<HTMLInputElement>("#replay-range");
      range.max = String(frames.length - 1);
      range.value = "0";
      required<HTMLElement>("#replay-controls").hidden = false;
      this.enableActions(false);
      this.setMatchPhase("finished");
      this.replaceLog(translate("ui.replayLoaded", { count: frames.length }));
      await this.renderReplay(0);
    } catch (error) {
      this.logError(error);
    }
  }

  private async renderReplay(index: number): Promise<void> {
    const frame = this.replayFrames[index];
    if (!frame) return;
    const colonyId = Object.keys(frame.colonies).sort()[0];
    if (!colonyId) throw new Error(translate("ui.replayNoColony"));
    this.observation = snapshotToObservation(frame, colonyId);
    await this.renderer.render(this.observation);
    this.renderStats(this.observation);
    this.fogMode = "replay";
    this.replayPosition = { index: index + 1, total: this.replayFrames.length };
    this.applyWorldLabels();
  }

  private stepReplay(delta: number): void {
    const range = required<HTMLInputElement>("#replay-range");
    const next = Math.max(0, Math.min(this.replayFrames.length - 1, Number(range.value) + delta));
    range.value = String(next);
    void this.renderReplay(next);
  }

  private renderStats(observation: Observation): void {
    required<HTMLOutputElement>("#turn-output").value = `T${observation.turn}`;
    this.setScenarioLabel(observation.scenario_id.toUpperCase());
    const population = document.createElement("div");
    population.className = "population-line";
    const populationLabel = document.createElement("span");
    populationLabel.textContent = translate("ledger.population");
    const populationValue = document.createElement("strong");
    populationValue.textContent = translate("ledger.populationValue", {
      population: observation.colony.population,
      housing: observation.colony.housing,
    });
    population.append(populationLabel, populationValue);
    const resources = document.createElement("div");
    resources.className = "resource-grid";
    for (const [name, value] of Object.entries(observation.colony.resources)) {
      const row = document.createElement("div");
      const label = document.createElement("span");
      label.textContent = resourceName(name);
      const output = document.createElement("strong");
      output.textContent = String(value);
      row.append(label, output);
      resources.append(row);
    }
    required("#colony-stats").replaceChildren(population, resources);
  }

  private selectCell(cell: VisibleCell): void {
    this.selectedCell = cell;
    required<HTMLOutputElement>("#cell-coordinates").value = `${cell.x}:${cell.y}`;
    required("#cell-details").textContent = [
      biomeName(cell.biome),
      cell.water ? translate("cell.water") : cell.buildable ? translate("cell.buildable") : translate("cell.blocked"),
      cell.resource ? `${resourceName(cell.resource)} ${cell.resource_amount}` : translate("cell.noResource"),
    ].join(" · ");
  }

  private appendEvents(events: readonly Readonly<Record<string, unknown>>[]): void {
    if (!events.length) {
      this.log(translate("ui.turnResolved"), "muted");
      return;
    }
    for (const event of events) {
      const kind = String(event.kind ?? "event");
      const actor = event.colony_id ? ` · ${String(event.colony_id)}` : "";
      this.log(`${kind.replaceAll("_", " ")}${actor}`, kind.includes("fire") ? "danger" : "event");
    }
  }

  private replaceLog(message: string): void {
    const list = required<HTMLOListElement>("#event-log");
    list.replaceChildren();
    this.log(message, "event");
  }

  private logError(error: unknown): void {
    const message = error instanceof ApiError ? `${error.code}: ${error.message}` :
      error instanceof Error ? error.message : String(error);
    this.log(message, "danger");
  }

  private log(message: string, kind: string): void {
    const item = document.createElement("li");
    item.className = kind;
    item.textContent = message;
    const list = required<HTMLOListElement>("#event-log");
    list.prepend(item);
    while (list.children.length > 24) list.lastElementChild?.remove();
  }

  private setBusy(busy: boolean): void {
    this.busy = busy;
    document.body.classList.toggle("is-busy", busy);
    document.body.setAttribute("aria-busy", String(busy));
    const createButton = document.querySelector<HTMLButtonElement>("#match-form .primary");
    if (createButton) {
      if (busy) createButton.dataset.state = "loading";
      else delete createButton.dataset.state;
    }
    this.enableActions(Boolean(this.activeMatchId && this.humanController) && !this.matchTerminal && !busy);
  }

  private enableActions(enabled: boolean): void {
    setHumanActionControlsEnabled(enabled);
  }

  private setConnection(key: "connection.connected" | "connection.unreachable" | "connection.localReady", connected: boolean): void {
    this.connectionKey = key;
    this.connectionUp = connected;
    this.applyConnection();
  }

  private async attachOperations(matchId: string, adminToken: string): Promise<void> {
    this.closeOperationsLive();
    const capability = { matchId, token: adminToken };
    this.operationsCapability = capability;
    this.operationsReconnectAttempt = 0;
    this.operations.reset(translate("ops.announcement.loading"));
    try {
      await this.refreshOperations();
      if (this.operationsCapability !== capability) return;
      await this.connectOperationsLive();
    } catch (error) {
      if (this.operationsCapability !== capability) return;
      this.logError(error);
      this.scheduleOperationsReconnect();
    }
  }

  private async refreshOperations(): Promise<void> {
    const capability = this.operationsCapability;
    if (!capability) return;
    const refreshVersion = ++this.operationsRefreshVersion;
    const snapshot = await this.api.operations(capability.matchId, capability.token);
    if (this.operationsCapability !== capability || refreshVersion !== this.operationsRefreshVersion) return;
    this.operations.applySnapshot(snapshot);
    try {
      const report = await this.api.report(capability.matchId, capability.token);
      if (this.operationsCapability === capability && refreshVersion === this.operationsRefreshVersion) {
        this.operations.setReport(report);
      }
    } catch (error) {
      if (error instanceof ApiError && [404, 409].includes(error.status)) return;
      throw error;
    }
  }

  private async connectOperationsLive(): Promise<void> {
    const capability = this.operationsCapability;
    if (!capability) return;
    this.operations.announce(translate("ops.announcement.connecting"));
    const ticket = await this.api.operationsTicket(capability.matchId, capability.token);
    if (this.operationsCapability !== capability) return;
    const socket = this.api.openOperationsSocket(capability.matchId, ticket.websocket_ticket);
    this.operationsSocket = socket;
    socket.addEventListener("open", () => {
      if (this.operationsSocket === socket) {
        this.operationsReconnectAttempt = 0;
        this.operations.announce(translate("ops.announcement.connected"));
      }
    });
    socket.addEventListener("message", currentSourceMessageHandler(
      socket,
      () => this.operationsSocket,
      (message) => this.handleOperationsMessage(message),
    ));
    socket.addEventListener("error", () => {
      if (this.operationsSocket === socket) socket.close();
    });
    socket.addEventListener("close", () => {
      if (this.operationsSocket !== socket) return;
      this.operationsSocket = null;
      this.operations.announce(translate("ops.announcement.disconnected"));
      this.scheduleOperationsReconnect();
    });
  }

  private handleOperationsMessage(message: MessageEvent): void {
    let parsed: AdminWebSocketMessage;
    try {
      parsed = JSON.parse(String(message.data)) as AdminWebSocketMessage;
    } catch {
      return;
    }
    const result = this.operations.applyMessage(parsed);
    if (result === "resync") void this.refreshOperations().catch((error) => this.logError(error));
    if (parsed.type === "match.completed") {
      this.setMatchPhase("finished");
      void this.refreshOperations().catch((error) => this.logError(error));
    }
    if (
      (parsed.type === "turn.resolved" || parsed.type === "match.completed") &&
      !this.humanController
    ) {
      void this.refreshObservation().catch((error) => this.logError(error));
    }
  }

  private scheduleOperationsReconnect(): void {
    if (
      !this.operationsCapability ||
      this.operationsReconnectTimer !== null ||
      this.operationsReconnectAttempt >= 5
    ) {
      if (this.operationsCapability && this.operationsReconnectAttempt >= 5) {
        this.operations.announce(translate("ops.announcement.reconnectLimit"));
      }
      return;
    }
    const delay = Math.min(1_000 * (2 ** this.operationsReconnectAttempt), 16_000);
    this.operationsReconnectAttempt += 1;
    this.operationsReconnectTimer = window.setTimeout(() => {
      this.operationsReconnectTimer = null;
      void this.connectOperationsLive().catch((error) => {
        this.logError(error);
        this.scheduleOperationsReconnect();
      });
    }, delay);
  }

  private closeOperationsLive(): void {
    this.operationsRefreshVersion += 1;
    if (this.operationsReconnectTimer !== null) window.clearTimeout(this.operationsReconnectTimer);
    this.operationsReconnectTimer = null;
    const socket = this.operationsSocket;
    this.operationsSocket = null;
    socket?.close();
  }

  private changeWorldView(action: string): void {
    if (action === "zoom-in") this.renderer.zoomBy(0.15);
    else if (action === "zoom-out") this.renderer.zoomBy(-0.15);
    else if (action === "pan-up") this.renderer.panBy(0, -24);
    else if (action === "pan-down") this.renderer.panBy(0, 24);
    else if (action === "pan-left") this.renderer.panBy(-24, 0);
    else if (action === "pan-right") this.renderer.panBy(24, 0);
    else if (action === "reset") this.renderer.resetView();
  }
}
