import {
  BenchmarkApi,
  type AdminWebSocketMessage,
  type BaselineKind,
  type ControllerType,
  type CreateSessionInput,
  type LobbySnapshot,
  type LobbySlot,
  type PairingGrant,
} from "./api";
import { translate, type TranslationKey } from "./i18n";

export type PairingProvider = "codex" | "claude" | "opencode" | "generic";
export type LobbyRowState =
  | "unassigned"
  | "pairing"
  | "expired"
  | "waiting-heartbeat"
  | "ready"
  | "attention";

export interface LobbyRow {
  readonly slot: LobbySlot;
  readonly state: LobbyRowState;
  readonly ready: boolean;
  readonly statusText: string;
}

export interface StartedHumanController {
  readonly matchId: string;
  readonly colonyId?: string;
  readonly controllerToken?: string;
}

export type LobbyApi = Pick<
  BenchmarkApi,
  | "createSession"
  | "lobby"
  | "configureSlot"
  | "createPairing"
  | "startSession"
  | "humanCapability"
  | "replaceSlot"
  | "operations"
  | "report"
  | "operationsTicket"
  | "openOperationsSocket"
>;

interface LobbyControllerOptions {
  readonly endpoint?: string;
  readonly now?: () => number;
  readonly onStarted?: (controller: StartedHumanController) => void;
  readonly onError?: (error: unknown) => void;
}

const BASELINES: readonly BaselineKind[] = [
  "random_valid",
  "survivalist",
  "trader",
  "expansionist",
  "militarist",
];

const PROVIDERS: readonly { readonly value: PairingProvider; readonly label: string }[] = [
  { value: "codex", label: "Codex" },
  { value: "claude", label: "Claude / Claude Code" },
  { value: "opencode", label: "OpenCode" },
  { value: "generic", label: "Generic MCP" },
];

function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
}

function appendLabel(control: HTMLElement, text: string, id: string): HTMLLabelElement {
  const label = element("label", text);
  label.htmlFor = id;
  label.append(control);
  return label;
}

function pairingEndpoint(): string {
  if (typeof window === "undefined") return "http://127.0.0.1:8001/mcp";
  return new URL("/mcp", window.location.origin).toString();
}

export function setHumanActionControlsEnabled(
  enabled: boolean,
  root: ParentNode = document,
): void {
  root.querySelectorAll<HTMLButtonElement>("#action-grid [data-action]").forEach((button) => {
    button.disabled = !enabled;
  });
}

function providerConfig(provider: PairingProvider, endpoint: string): string {
  if (provider === "codex") {
    return [
      "# ~/.codex/config.toml",
      "[mcp_servers.castle_benchmark]",
      `url = ${JSON.stringify(endpoint)}`,
    ].join("\n");
  }
  if (provider === "claude") {
    return JSON.stringify({
      mcpServers: {
        "castle-benchmark": { type: "http", url: endpoint },
      },
    }, null, 2);
  }
  if (provider === "opencode") {
    return JSON.stringify({
      mcp: {
        "castle-benchmark": { type: "remote", url: endpoint, enabled: true },
      },
    }, null, 2);
  }
  return `MCP Streamable HTTP endpoint: ${endpoint}`;
}

export function pairingInstructions(
  grant: PairingGrant,
  provider: PairingProvider,
  endpoint = pairingEndpoint(),
): string {
  const claim = JSON.stringify({
    pairing_code: grant.pairing_code,
    identity: {
      display_name: "YOUR AGENT NAME",
      provider: "YOUR PROVIDER",
      model: "YOUR MODEL",
    },
  }, null, 2);
  return [
    providerConfig(provider, endpoint),
    "",
    `1. ${translate("pairing.step1")}`,
    `2. ${translate("pairing.step2")} ${claim}`,
    `3. ${translate("pairing.step3")}`,
    `4. ${translate("pairing.step4")}`,
    `5. ${translate("pairing.step5")}`,
  ].join("\n");
}

export function lobbyRows(
  snapshot: LobbySnapshot,
  nowSeconds = Date.now() / 1_000,
): readonly LobbyRow[] {
  return snapshot.slots.map((slot) => {
    if (slot.controller_type === "human") {
      return { slot, state: "ready", ready: true, statusText: translate("lobby.humanReady") };
    }
    if (slot.controller_type === "baseline") {
      return {
        slot,
        state: "ready",
        ready: true,
        statusText: translate("lobby.baselineReady", { kind: slot.baseline_kind ?? "random_valid" }),
      };
    }
    if (slot.presence === "disconnected") {
      return {
        slot,
        state: "attention",
        ready: false,
        statusText: translate("lobby.disconnected"),
      };
    }
    if (slot.controller_id !== null && slot.last_heartbeat_at !== null) {
      return { slot, state: "ready", ready: true, statusText: translate("lobby.externalReady") };
    }
    if (slot.controller_id !== null) {
      return {
        slot,
        state: "waiting-heartbeat",
        ready: false,
        statusText: translate("lobby.claimed"),
      };
    }
    if (slot.pairing_expires_at !== null && slot.pairing_expires_at <= nowSeconds) {
      return { slot, state: "expired", ready: false, statusText: translate("lobby.expired") };
    }
    if (slot.pairing_active) {
      return { slot, state: "pairing", ready: false, statusText: translate("lobby.pairingActive") };
    }
    return { slot, state: "unassigned", ready: false, statusText: translate("lobby.unassigned") };
  });
}

function controllerSelect(
  slot: LobbySlot,
  index: number,
  humanColonyId: string | undefined,
): HTMLSelectElement {
  const select = element("select");
  select.id = `slot-controller-${index}`;
  select.dataset.controllerSelect = slot.colony_id;
  for (const [value, label] of [
    ["human", translate("lobby.human")],
    ["baseline", translate("lobby.deterministicBaseline")],
    ["external", translate("lobby.externalMCP")],
  ] as const) {
    const option = element("option", label);
    option.value = value;
    option.selected = slot.controller_type === value;
    option.disabled = value === "human" && humanColonyId !== undefined && humanColonyId !== slot.colony_id;
    select.append(option);
  }
  return select;
}

function baselineSelect(slot: LobbySlot, index: number): HTMLSelectElement {
  const select = element("select");
  select.id = `slot-baseline-${index}`;
  select.dataset.baselineSelect = slot.colony_id;
  select.hidden = slot.controller_type !== "baseline";
  for (const baseline of BASELINES) {
    const option = element("option", baseline.replaceAll("_", " "));
    option.value = baseline;
    option.selected = (slot.baseline_kind ?? "random_valid") === baseline;
    select.append(option);
  }
  return select;
}

function actionButton(action: string, colonyId: string, label: string): HTMLButtonElement {
  const button = element("button", label);
  button.type = "button";
  button.dataset.action = action;
  button.dataset.colonyId = colonyId;
  return button;
}

export function renderLobby(
  snapshot: LobbySnapshot,
  nowSeconds = Date.now() / 1_000,
): HTMLElement {
  const section = element("section");
  section.className = "agent-lobby";
  section.dataset.matchId = snapshot.match_id;
  section.setAttribute("aria-labelledby", "lobby-title");

  const heading = element("h2", translate("lobby.title", { scenario: snapshot.scenario_id }));
  heading.id = "lobby-title";
  section.append(heading);

  const rows = lobbyRows(snapshot, nowSeconds);
  const humanColonyId = snapshot.slots.find((slot) => slot.controller_type === "human")?.colony_id;
  const list = element("ol");
  list.className = "lobby-slots";
  for (const [index, row] of rows.entries()) {
    const item = element("li");
    item.dataset.colonyId = row.slot.colony_id;
    item.dataset.slotState = row.state;

    item.append(element("h3", translate("lobby.colony", { id: row.slot.colony_id })));
    const status = element("p", row.statusText);
    status.dataset.slotStatus = row.slot.colony_id;
    item.append(status);
    if (row.slot.identity) {
      const identity = element(
        "p",
        `${row.slot.identity.display_name} · ${row.slot.identity.provider} · ${row.slot.identity.model}`,
      );
      identity.dataset.controllerIdentity = row.slot.colony_id;
      item.append(identity);
    }

    const assignment = controllerSelect(row.slot, index, humanColonyId);
    item.append(appendLabel(assignment, translate("lobby.controller"), assignment.id));
    const baseline = baselineSelect(row.slot, index);
    item.append(appendLabel(baseline, translate("lobby.baseline"), baseline.id));
    item.append(actionButton("configure", row.slot.colony_id, translate("lobby.apply")));

    const pairing = actionButton("pair", row.slot.colony_id, translate("lobby.pair"));
    pairing.disabled = row.slot.controller_type !== "external";
    item.append(pairing);

    const fallback = element("div");
    fallback.className = "slot-fallbacks";
    fallback.setAttribute("aria-label", translate("lobby.fallbackAria", { id: row.slot.colony_id }));
    fallback.append(
      actionButton("replace-human", row.slot.colony_id, translate("lobby.takeOver")),
      actionButton("replace-baseline", row.slot.colony_id, translate("lobby.baselineFallback")),
      actionButton("replace-external", row.slot.colony_id, translate("lobby.rotateExternal")),
    );
    item.append(fallback);
    list.append(item);
  }
  section.append(list);

  const waiting = rows.filter((row) => !row.ready).length;
  const readiness = element(
    "p",
    waiting === 0
      ? translate("lobby.allReady")
      : translate(waiting === 1 ? "lobby.oneWaiting" : "lobby.manyWaiting", { count: waiting }),
  );
  readiness.dataset.readiness = "";
  readiness.setAttribute("aria-live", "polite");
  section.append(readiness);

  const start = element("button", snapshot.status === "running" ? translate("lobby.running") : translate("lobby.start"));
  start.type = "button";
  start.dataset.action = "start";
  start.disabled = waiting > 0 || snapshot.status !== "draft";
  const refresh = element("button", translate("lobby.refresh"));
  refresh.type = "button";
  refresh.dataset.action = "refresh";
  section.append(start, refresh);
  return section;
}

function duration(seconds: number): string {
  const safe = Math.max(0, Math.ceil(seconds));
  const minutes = Math.floor(safe / 60);
  const remainder = safe % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

export function renderPairingGrant(
  grant: PairingGrant,
  provider: PairingProvider = "codex",
  endpoint = pairingEndpoint(),
  nowSeconds = Date.now() / 1_000,
): HTMLElement {
  const panel = element("section");
  panel.className = "pairing-grant";
  panel.dataset.pairingColony = grant.colony_id;
  panel.setAttribute("aria-label", translate("pairing.aria", { colony: grant.colony_id }));

  panel.append(element("h3", translate("pairing.title", { colony: grant.colony_id })));
  const code = element("code", grant.pairing_code);
  code.dataset.pairingCode = "";
  panel.append(code);

  const countdown = element("p", translate("pairing.expires", { duration: duration(grant.expires_at - nowSeconds) }));
  countdown.dataset.pairingCountdown = "";
  countdown.dataset.expiresAt = String(grant.expires_at);
  countdown.setAttribute("aria-live", "polite");
  panel.append(countdown);

  const endpointOutput = element("code", endpoint);
  endpointOutput.dataset.pairingEndpoint = "";
  panel.append(endpointOutput);

  const providerSelect = element("select");
  providerSelect.id = `pairing-provider-${grant.colony_id.replaceAll(/[^a-zA-Z0-9_-]/g, "-")}`;
  providerSelect.dataset.providerColony = grant.colony_id;
  for (const choice of PROVIDERS) {
    const option = element("option", choice.label);
    option.value = choice.value;
    option.selected = choice.value === provider;
    providerSelect.append(option);
  }
  panel.append(appendLabel(providerSelect, translate("pairing.provider"), providerSelect.id));

  const instructions = element("pre", pairingInstructions(grant, provider, endpoint));
  instructions.dataset.pairingInstructions = "";
  panel.append(instructions);

  for (const [target, label] of [
    ["code", translate("pairing.copyCode")],
    ["endpoint", translate("pairing.copyEndpoint")],
    ["config", translate("pairing.copyConfig")],
  ] as const) {
    const copy = element("button", label);
    copy.type = "button";
    copy.dataset.copy = target;
    copy.dataset.colonyId = grant.colony_id;
    panel.append(copy);
  }
  return panel;
}

export class LobbyController {
  private matchId: string | null = null;
  private adminToken: string | null = null;
  private snapshot: LobbySnapshot | null = null;
  private readonly grants = new Map<string, PairingGrant>();
  private readonly providers = new Map<string, PairingProvider>();
  private countdownTimer: number | null = null;
  private reconnectTimer: number | null = null;
  private liveSocket: WebSocket | null = null;
  private reconnectAttempt = 0;
  private disposed = false;
  private errorMessage: string | null = null;
  private readonly endpoint: string;
  private readonly now: () => number;

  constructor(
    private readonly root: HTMLElement,
    private readonly api: LobbyApi = new BenchmarkApi(),
    private readonly options: LobbyControllerOptions = {},
  ) {
    this.endpoint = options.endpoint ?? pairingEndpoint();
    this.now = options.now ?? (() => Date.now() / 1_000);
    root.addEventListener("click", (event) => this.handleClick(event));
    root.addEventListener("change", (event) => this.handleChange(event));
  }

  async create(input: CreateSessionInput, orchestratorToken?: string): Promise<void> {
    this.closeLive();
    this.disposed = false;
    this.reconnectAttempt = 0;
    this.errorMessage = null;
    if (input.slots.filter((slot) => slot.controller_type === "human").length > 1) {
      throw this.policyError();
    }
    const created = await this.api.createSession(input, orchestratorToken || undefined);
    this.matchId = created.match_id;
    this.adminToken = created.admin_token;
    this.grants.clear();
    this.providers.clear();
    await this.refresh();
    await this.connectLive();
  }

  async refresh(): Promise<void> {
    const { matchId, adminToken } = this.credentials();
    this.snapshot = await this.api.lobby(matchId, adminToken);
    this.render();
  }

  async configure(
    colonyId: string,
    controllerType: ControllerType,
    baselineKind?: BaselineKind,
  ): Promise<void> {
    const { matchId, adminToken } = this.credentials();
    if (
      controllerType === "human" &&
      this.snapshot?.slots.some(
        (slot) => slot.controller_type === "human" && slot.colony_id !== colonyId,
      )
    ) {
      throw this.policyError();
    }
    this.errorMessage = null;
    if (this.snapshot?.status === "draft") {
      await this.api.configureSlot(matchId, colonyId, adminToken, {
        controller_type: controllerType,
        baseline_kind: controllerType === "baseline" ? baselineKind ?? "random_valid" : null,
      });
    } else {
      await this.api.replaceSlot(matchId, colonyId, adminToken, {
        replacement: controllerType,
        baseline_kind: controllerType === "baseline" ? baselineKind ?? "random_valid" : null,
      });
    }
    this.grants.delete(colonyId);
    await this.refresh();
  }

  async pair(colonyId: string): Promise<void> {
    const { matchId, adminToken } = this.credentials();
    const grant = await this.api.createPairing(matchId, colonyId, adminToken);
    this.grants.set(colonyId, grant);
    this.providers.set(colonyId, this.providers.get(colonyId) ?? "codex");
    this.startCountdown();
    this.render();
  }

  async start(): Promise<void> {
    const { matchId, adminToken } = this.credentials();
    if ((this.snapshot?.slots.filter((slot) => slot.controller_type === "human").length ?? 0) > 1) {
      throw this.policyError();
    }
    if (!this.snapshot || lobbyRows(this.snapshot, this.now()).some((row) => !row.ready)) {
      throw new Error(translate("lobby.startNotReady"));
    }
    await this.api.startSession(matchId, adminToken);
    const human = this.snapshot.slots.find((slot) => slot.controller_type === "human");
    if (human) {
      const capability = await this.api.humanCapability(matchId, human.colony_id, adminToken);
      this.options.onStarted?.({
        matchId,
        colonyId: capability.colony_id,
        controllerToken: capability.controller_token,
      });
    } else {
      this.options.onStarted?.({ matchId });
    }
    this.grants.clear();
    await this.refresh();
  }

  async replace(
    colonyId: string,
    replacement: ControllerType,
    baselineKind?: BaselineKind,
  ): Promise<void> {
    await this.configure(colonyId, replacement, baselineKind);
    if (replacement === "external") {
      await this.pair(colonyId);
    } else if (replacement === "human" && this.snapshot?.status !== "draft") {
      const { matchId, adminToken } = this.credentials();
      const capability = await this.api.humanCapability(matchId, colonyId, adminToken);
      this.options.onStarted?.({
        matchId,
        colonyId: capability.colony_id,
        controllerToken: capability.controller_token,
      });
    }
  }

  dispose(): void {
    this.disposed = true;
    if (this.countdownTimer !== null) window.clearInterval(this.countdownTimer);
    this.countdownTimer = null;
    this.closeLive();
    this.adminToken = null;
    this.matchId = null;
    this.snapshot = null;
    this.errorMessage = null;
    this.grants.clear();
    this.root.replaceChildren();
  }

  rerender(): void {
    this.render();
  }

  private credentials(): { readonly matchId: string; readonly adminToken: string } {
    if (!this.matchId || !this.adminToken) throw new Error(translate("lobby.noSession"));
    return { matchId: this.matchId, adminToken: this.adminToken };
  }

  private render(): void {
    if (!this.snapshot) return;
    const now = this.now();
    for (const [colonyId, grant] of this.grants) {
      const slot = this.snapshot.slots.find((candidate) => candidate.colony_id === colonyId);
      if (
        grant.expires_at <= now ||
        slot?.pairing_consumed === true ||
        slot?.controller_id !== null
      ) {
        this.grants.delete(colonyId);
      }
    }
    const lobby = renderLobby(this.snapshot, now);
    for (const grant of this.grants.values()) {
      lobby.append(renderPairingGrant(
        grant,
        this.providers.get(grant.colony_id) ?? "codex",
        this.endpoint,
        now,
      ));
    }
    if (this.errorMessage) {
      const alert = element("p", this.errorMessage);
      alert.setAttribute("role", "alert");
      lobby.prepend(alert);
    }
    this.root.replaceChildren(lobby);
  }

  private startCountdown(): void {
    if (this.countdownTimer !== null) return;
    this.countdownTimer = window.setInterval(() => {
      if (this.grants.size === 0) {
        if (this.countdownTimer !== null) window.clearInterval(this.countdownTimer);
        this.countdownTimer = null;
        return;
      }
      this.render();
    }, 1_000);
  }

  private async connectLive(): Promise<void> {
    if (this.disposed) return;
    const ticketMethod = (this.api as Partial<LobbyApi>).operationsTicket;
    const socketMethod = (this.api as Partial<LobbyApi>).openOperationsSocket;
    if (typeof ticketMethod !== "function" || typeof socketMethod !== "function") return;
    try {
      const { matchId, adminToken } = this.credentials();
      const ticket = await ticketMethod.call(this.api, matchId, adminToken);
      if (this.disposed || this.matchId !== matchId || this.adminToken !== adminToken) return;
      const socket = socketMethod.call(this.api, matchId, ticket.websocket_ticket);
      this.liveSocket = socket;
      socket.addEventListener("open", () => {
        if (this.liveSocket === socket) this.reconnectAttempt = 0;
      });
      socket.addEventListener("message", (event) => this.handleLiveMessage(event));
      socket.addEventListener("error", () => this.socketFailed(socket, true));
      socket.addEventListener("close", () => this.socketFailed(socket, false));
    } catch (error) {
      this.options.onError?.(error);
      this.scheduleReconnect();
    }
  }

  private socketFailed(socket: WebSocket, closeSocket: boolean): void {
    if (this.liveSocket !== socket) return;
    this.liveSocket = null;
    if (closeSocket) socket.close();
    this.scheduleReconnect();
  }

  private scheduleReconnect(): void {
    const maximumAttempts = 5;
    if (
      this.disposed ||
      !this.matchId ||
      !this.adminToken ||
      this.reconnectTimer !== null ||
      this.reconnectAttempt >= maximumAttempts
    ) return;
    const delay = Math.min(1_000 * (2 ** this.reconnectAttempt), 16_000);
    this.reconnectAttempt += 1;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      void this.connectLive();
    }, delay);
  }

  private handleLiveMessage(event: MessageEvent): void {
    let message: AdminWebSocketMessage;
    try {
      message = JSON.parse(String(event.data)) as AdminWebSocketMessage;
    } catch {
      return;
    }
    if (message.schema_version !== "1.1") return;
    if (message.type === "lobby.snapshot") {
      this.snapshot = message.payload;
      this.render();
      return;
    }
    void this.refresh().catch((error) => this.options.onError?.(error));
  }

  private closeLive(): void {
    if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    const socket = this.liveSocket;
    this.liveSocket = null;
    socket?.close();
  }

  private policyError(): Error {
    const error = new Error(translate("lobby.policyOneHuman"));
    this.errorMessage = error.message;
    if (this.snapshot) {
      this.render();
    } else {
      const alert = element("p", error.message);
      alert.setAttribute("role", "alert");
      this.root.replaceChildren(alert);
    }
    return error;
  }

  private control<T extends HTMLSelectElement>(attribute: "controllerSelect" | "baselineSelect", colonyId: string): T | null {
    return [...this.root.querySelectorAll<T>(`[data-${attribute.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}]`)]
      .find((candidate) => candidate.dataset[attribute] === colonyId) ?? null;
  }

  private handleClick(event: Event): void {
    const button = (event.target as Element | null)?.closest<HTMLButtonElement>("button[data-action], button[data-copy]");
    if (!button || !this.root.contains(button)) return;
    const colonyId = button.dataset.colonyId;
    let operation: Promise<void> | undefined;
    if (button.dataset.action === "start") operation = this.start();
    else if (button.dataset.action === "refresh") operation = this.refresh();
    else if (button.dataset.action === "configure" && colonyId) {
      const controller = this.control<HTMLSelectElement>("controllerSelect", colonyId);
      const baseline = this.control<HTMLSelectElement>("baselineSelect", colonyId);
      operation = this.configure(
        colonyId,
        (controller?.value ?? "external") as ControllerType,
        baseline?.value as BaselineKind | undefined,
      );
    } else if (button.dataset.action === "pair" && colonyId) operation = this.pair(colonyId);
    else if (button.dataset.action?.startsWith("replace-") && colonyId) {
      const replacement = button.dataset.action.slice("replace-".length) as ControllerType;
      const baseline = this.control<HTMLSelectElement>("baselineSelect", colonyId)?.value as BaselineKind | undefined;
      operation = this.replace(colonyId, replacement, baseline);
    } else if (button.dataset.copy && colonyId) {
      operation = this.copy(colonyId, button.dataset.copy);
    }
    if (operation) void operation.catch((error) => this.options.onError?.(error));
  }

  private handleChange(event: Event): void {
    const select = event.target as HTMLSelectElement | null;
    if (!select || !this.root.contains(select)) return;
    const controllerColony = select.dataset.controllerSelect;
    if (controllerColony) {
      const baseline = this.control<HTMLSelectElement>("baselineSelect", controllerColony);
      if (baseline) baseline.hidden = select.value !== "baseline";
      return;
    }
    const providerColony = select.dataset.providerColony;
    if (providerColony) {
      this.providers.set(providerColony, select.value as PairingProvider);
      this.render();
    }
  }

  private async copy(colonyId: string, target: string): Promise<void> {
    const grant = this.grants.get(colonyId);
    if (!grant || grant.expires_at <= this.now()) throw new Error(translate("lobby.expired"));
    const provider = this.providers.get(colonyId) ?? "codex";
    const text = target === "code"
      ? grant.pairing_code
      : target === "endpoint"
        ? this.endpoint
        : pairingInstructions(grant, provider, this.endpoint);
    if (!navigator.clipboard?.writeText) throw new Error(translate("lobby.clipboardUnavailable"));
    await navigator.clipboard.writeText(text);
  }
}
