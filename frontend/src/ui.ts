import {
  ApiError,
  BenchmarkApi,
  type CreateSessionInput,
  type Observation,
  type ScenarioSummary,
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

type ActionKind = "wait" | "gather" | "build" | "policy" | "diplomacy" | "trade" | "raid";

function required<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`Eksik arayüz öğesi: ${selector}`);
  return element;
}

export class BenchmarkWorkbench {
  private readonly api = new BenchmarkApi();
  private readonly renderer = new CastleRenderer();
  private lobby: LobbyController | null = null;
  private activeMatchId: string | null = null;
  private humanController: { readonly colonyId: string; readonly token: string } | null = null;
  private observation: Observation | null = null;
  private selectedCell: VisibleCell | null = null;
  private replayFrames: readonly ReplaySnapshot[] = [];
  private busy = false;
  private matchTerminal = false;

  async init(): Promise<void> {
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
  }

  private async loadScenarios(): Promise<void> {
    try {
      const scenarios = await this.api.scenarios();
      const select = required<HTMLSelectElement>("#scenario-select");
      select.replaceChildren(...scenarios.map((scenario) => this.scenarioOption(scenario)));
      this.setConnection("Benchmark servisi bağlı", true);
    } catch (error) {
      this.setConnection("Servise ulaşılamadı", false);
      this.logError(error);
    }
  }

  private scenarioOption(scenario: ScenarioSummary): HTMLOptionElement {
    const option = document.createElement("option");
    option.value = scenario.id;
    option.textContent = `${scenario.name} · ${scenario.biome}`;
    option.dataset.biome = scenario.biome;
    return option;
  }

  private async createSession(): Promise<void> {
    if (!this.lobby || this.busy) return;
    const orchestratorInput = required<HTMLInputElement>("#orchestrator-token");
    const orchestratorToken = orchestratorInput.value;
    orchestratorInput.value = "";
    const input: CreateSessionInput = {
      scenario_id: required<HTMLSelectElement>("#scenario-select").value,
      seed: Number(required<HTMLInputElement>("#seed-input").value),
      colony_count: Number(required<HTMLInputElement>("#colony-input").value),
      deadline_seconds: Number(required<HTMLInputElement>("#deadline-input").value),
      slots: [],
    };
    this.setBusy(true);
    try {
      this.activeMatchId = null;
      this.humanController = null;
      await this.lobby.create(input, orchestratorToken);
      this.resetRunState();
      this.replaceLog("Draft session created. Configure every slot, pair external agents, then start explicitly.");
    } catch (error) {
      this.logError(error);
    } finally {
      this.setBusy(false);
    }
  }

  private async createDevelopmentQuickPlay(): Promise<void> {
    if (this.busy) return;
    this.setBusy(true);
    try {
      const created = await this.api.createDevelopmentMatch({
        scenario_id: required<HTMLSelectElement>("#scenario-select").value,
        seed: Number(required<HTMLInputElement>("#seed-input").value),
      });
      const token = created.controller_tokens.c1;
      if (!token) throw new Error("Development quick-play human capability is missing");
      this.activeMatchId = created.match_id;
      this.humanController = { colonyId: "c1", token };
      this.resetRunState();
      this.replaceLog("DEVELOPMENT quick play started with one human colony.");
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
    this.replaceLog("Match started. Baselines and turn deadlines are server-owned.");
    if (this.humanController) {
      try {
        await this.refreshObservation();
        this.enableActions(true);
      } catch (error) {
        this.logError(error);
      }
    } else {
      this.enableActions(false);
      this.log("No human slot was handed off; monitor the connected agents in the lobby.", "muted");
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
        this.log(`Waiting for server/controllers: ${result.waiting_for.join(", ")}`, "muted");
      }
      await this.refreshObservation();
      const status = await this.api.status(this.activeMatchId, this.humanController.token);
      this.matchTerminal = status.terminal === true;
      if (this.matchTerminal) {
        this.log(`Karşılaşma tamamlandı: ${String(status.termination_reason ?? "terminal")}`, "event");
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
        this.log("Diplomasi menzilinde başka koloni yok.", "warning");
        return null;
      }
      if (kind === "diplomacy") {
        return { kind: "diplomacy", target_colony_id: targetId, operation: "contact", message: "Açık hat kuruldu." };
      }
      if (kind === "trade") {
        return { kind: "trade_offer", target_colony_id: targetId, give: [["wood", 2]], receive: [["food", 2]], message: "Oduna karşı erzak." };
      }
      return { kind: "raid", target_colony_id: targetId };
    }
    if (!this.selectedCell) {
      this.log("Önce haritada bir hücre seç.", "warning");
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
    if (!this.activeMatchId || !this.humanController) return;
    this.observation = await this.api.observe(
      this.activeMatchId,
      this.humanController.colonyId,
      this.humanController.token,
    );
    await this.renderer.render(this.observation);
    this.renderStats(this.observation);
  }

  private async loadReplay(file: File | undefined): Promise<void> {
    if (!file) return;
    try {
      const frames = (await file.text())
        .split(/\r?\n/)
        .filter((line) => line.trim())
        .map((line) => JSON.parse(line) as ReplaySnapshot);
      if (!frames.length) throw new Error("Replay dosyasında tamamlanmış snapshot yok");
      this.replayFrames = frames;
      this.activeMatchId = null;
      this.humanController = null;
      this.matchTerminal = true;
      const range = required<HTMLInputElement>("#replay-range");
      range.max = String(frames.length - 1);
      range.value = "0";
      required<HTMLElement>("#replay-controls").hidden = false;
      this.enableActions(false);
      this.replaceLog(`${frames.length} replay turu yüklendi; görünüm omniscient.`);
      await this.renderReplay(0);
    } catch (error) {
      this.logError(error);
    }
  }

  private async renderReplay(index: number): Promise<void> {
    const frame = this.replayFrames[index];
    if (!frame) return;
    const colonyId = Object.keys(frame.colonies).sort()[0];
    if (!colonyId) throw new Error("Replay kolonisi bulunamadı");
    this.observation = snapshotToObservation(frame, colonyId);
    await this.renderer.render(this.observation);
    this.renderStats(this.observation);
    required("#fog-label").textContent = `REPLAY · ${index + 1}/${this.replayFrames.length}`;
  }

  private stepReplay(delta: number): void {
    const range = required<HTMLInputElement>("#replay-range");
    const next = Math.max(0, Math.min(this.replayFrames.length - 1, Number(range.value) + delta));
    range.value = String(next);
    void this.renderReplay(next);
  }

  private renderStats(observation: Observation): void {
    required<HTMLOutputElement>("#turn-output").value = `T${observation.turn}`;
    required("#scenario-label").textContent = observation.scenario_id.toUpperCase();
    const resources = Object.entries(observation.colony.resources)
      .map(([name, value]) => `<div><span>${this.resourceName(name)}</span><strong>${value}</strong></div>`)
      .join("");
    required("#colony-stats").innerHTML = `
      <div class="population-line"><span>Nüfus</span><strong>${observation.colony.population}<small> / ${observation.colony.housing} konut</small></strong></div>
      <div class="resource-grid">${resources}</div>`;
    const survival = Math.min(100, Math.round(
      ((observation.colony.health.healthy ?? 0) / Math.max(1, observation.colony.population)) * 100,
    ));
    required("#score-survival").textContent = String(survival);
    required("#score-prosperity").textContent = String(
      Object.values(observation.colony.resources).reduce((sum, value) => sum + value, 0),
    );
    required("#score-diplomacy").textContent = String(Object.keys(observation.known_colonies).length);
    required("#score-resilience").textContent = String(observation.colony.health.healthy ?? 0);
  }

  private selectCell(cell: VisibleCell): void {
    this.selectedCell = cell;
    required<HTMLOutputElement>("#cell-coordinates").value = `${cell.x}:${cell.y}`;
    required("#cell-details").textContent = [
      cell.biome,
      cell.water ? "su" : cell.buildable ? "inşa edilebilir" : "kapalı",
      cell.resource ? `${this.resourceName(cell.resource)} ${cell.resource_amount}` : "kaynak yok",
    ].join(" · ");
  }

  private appendEvents(events: readonly Readonly<Record<string, unknown>>[]): void {
    if (!events.length) {
      this.log("Tur olaysız çözüldü.", "muted");
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
    this.enableActions(Boolean(this.activeMatchId && this.humanController) && !this.matchTerminal && !busy);
  }

  private enableActions(enabled: boolean): void {
    setHumanActionControlsEnabled(enabled);
  }

  private setConnection(label: string, connected: boolean): void {
    required("#connection-label").textContent = label;
    document.body.classList.toggle("is-offline", !connected);
  }

  private resourceName(name: string): string {
    return ({ food: "Erzak", water: "Su", wood: "Odun", stone: "Taş", ore: "Cevher", tools: "Alet", influence: "Nüfuz" } as Record<string, string>)[name] ?? name;
  }
}
