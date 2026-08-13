import {
  ApiError,
  BenchmarkApi,
  type MatchCreated,
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

type ActionKind = "wait" | "gather" | "build" | "policy" | "diplomacy" | "trade" | "raid";

function required<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`Eksik arayüz öğesi: ${selector}`);
  return element;
}

export class BenchmarkWorkbench {
  private readonly api = new BenchmarkApi();
  private readonly renderer = new CastleRenderer();
  private match: MatchCreated | null = null;
  private observation: Observation | null = null;
  private selectedCell: VisibleCell | null = null;
  private replayFrames: readonly ReplaySnapshot[] = [];
  private busy = false;
  private matchTerminal = false;

  async init(): Promise<void> {
    await Promise.all([this.renderer.init(required("#world-host")), this.loadScenarios()]);
    this.renderer.onCellSelected((cell) => this.selectCell(cell));
    required<HTMLFormElement>("#match-form").addEventListener("submit", (event) => {
      event.preventDefault();
      void this.createMatch();
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

  private async createMatch(): Promise<void> {
    if (this.busy) return;
    this.setBusy(true);
    try {
      this.match = await this.api.createMatch({
        scenario_id: required<HTMLSelectElement>("#scenario-select").value,
        seed: Number(required<HTMLInputElement>("#seed-input").value),
        colony_count: Number(required<HTMLInputElement>("#colony-input").value),
      });
      this.selectedCell = null;
      this.matchTerminal = false;
      this.replayFrames = [];
      required<HTMLElement>("#replay-controls").hidden = true;
      this.replaceLog("Karşılaşma oluşturuldu; c1 insan kontrolünde, diğer koloniler deterministik baseline.");
      await this.refreshObservation();
      this.enableActions(true);
    } catch (error) {
      this.logError(error);
    } finally {
      this.setBusy(false);
    }
  }

  private async takeAction(kind: ActionKind): Promise<void> {
    if (!this.match || !this.observation || this.busy) return;
    const action = this.humanAction(kind);
    if (!action) return;
    this.setBusy(true);
    try {
      const humanToken = this.match.controller_tokens[this.observation.colony_id];
      if (!humanToken) throw new Error("İnsan kontrol tokenı bulunamadı");
      let result = await this.api.submitActions(this.match.match_id, humanToken, {
        turn: this.observation.turn,
        actions: [action],
      });

      for (const colonyId of result.waiting_for) {
        const token = this.match.controller_tokens[colonyId];
        if (!token) continue;
        const observation = await this.api.observe(this.match.match_id, colonyId, token);
        result = await this.api.submitActions(this.match.match_id, token, {
          turn: observation.turn,
          actions: [this.baselineAction(observation)],
        });
      }

      this.appendEvents(result.events ?? []);
      await this.refreshObservation();
      const status = await this.api.status(this.match.match_id, this.match.admin_token);
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

  private baselineAction(observation: Observation): ControllerAction {
    const stock = observation.colony.resources;
    const useful = observation.visible_cells
      .filter((cell) => cell.resource && cell.resource_amount > 0)
      .sort((a, b) => {
        const urgent = (cell: VisibleCell) =>
          (cell.resource === "food" && (stock.food ?? 0) < observation.colony.population * 2) ||
          (cell.resource === "water" && (stock.water ?? 0) < observation.colony.population * 2) ? 0 : 1;
        return urgent(a) - urgent(b) || b.resource_amount - a.resource_amount;
      })[0];
    if (useful) return { kind: "gather", x: useful.x, y: useful.y };
    return { kind: "wait" };
  }

  private async refreshObservation(): Promise<void> {
    if (!this.match) return;
    const token = this.match.controller_tokens.c1;
    if (!token) throw new Error("c1 tokenı bulunamadı");
    this.observation = await this.api.observe(this.match.match_id, "c1", token);
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
      this.match = null;
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
    this.enableActions(Boolean(this.match) && !this.matchTerminal && !busy);
  }

  private enableActions(enabled: boolean): void {
    document.querySelectorAll<HTMLButtonElement>("[data-action]").forEach((button) => {
      button.disabled = !enabled;
    });
  }

  private setConnection(label: string, connected: boolean): void {
    required("#connection-label").textContent = label;
    document.body.classList.toggle("is-offline", !connected);
  }

  private resourceName(name: string): string {
    return ({ food: "Erzak", water: "Su", wood: "Odun", stone: "Taş", ore: "Cevher", tools: "Alet", influence: "Nüfuz" } as Record<string, string>)[name] ?? name;
  }
}
