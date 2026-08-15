import type {
  AdminWebSocketMessage,
  OperationsSnapshot,
  OperationalEvent,
  RunReport,
} from "./api";
import { metricName, structureName, translate, type TranslationKey } from "./i18n";

export type AgentRosterState =
  | "unassigned"
  | "ready"
  | "pairing"
  | "connected"
  | "thinking"
  | "submitted"
  | "timed-out"
  | "disconnected"
  | "taken-over";

export type StatusShape = "dash" | "bar" | "circle" | "diamond" | "square" | "triangle" | "ring" | "split";

export interface AgentRosterRow {
  readonly colonyId: string;
  readonly displayName: string;
  readonly controllerType: string;
  readonly provider: string;
  readonly model: string;
  readonly state: AgentRosterState;
  readonly statusText: string;
  readonly statusShape: StatusShape;
  readonly generation: number;
  readonly takenOver: boolean;
  readonly latencyMs: number | null;
  readonly latencyText: string;
}

const STATE_PRESENTATION: Readonly<Record<AgentRosterState, readonly [TranslationKey, StatusShape]>> = {
  unassigned: ["state.unassigned", "dash"],
  ready: ["state.ready", "bar"],
  pairing: ["state.pairing", "bar"],
  connected: ["state.connected", "circle"],
  thinking: ["state.thinking", "diamond"],
  submitted: ["state.submitted", "square"],
  "timed-out": ["state.timedOut", "triangle"],
  disconnected: ["state.disconnected", "ring"],
  "taken-over": ["state.takenOver", "split"],
};

function rosterState(value: string): AgentRosterState {
  const normalized = value.replaceAll("_", "-");
  return normalized in STATE_PRESENTATION ? normalized as AgentRosterState : "unassigned";
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function record(value: unknown): Readonly<Record<string, unknown>> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Readonly<Record<string, unknown>>
    : {};
}

function latestLatency(report: RunReport | null, colonyId: string, generation: number): number | null {
  if (!report) return null;
  const metrics = record(report.metrics);
  const tenures = record(metrics.tenure_metrics)[colonyId];
  if (Array.isArray(tenures)) {
    const matching = tenures.findLast((candidate) => finiteNumber(record(candidate).generation) === generation);
    const segmented = finiteNumber(record(record(matching).adapter_reported_model_usage).latency_ms);
    if (segmented !== null) return segmented;
  }
  return finiteNumber(record(record(metrics.adapter_reported_model_usage)[colonyId]).latency_ms);
}

export function agentRosterRows(snapshot: OperationsSnapshot, report: RunReport | null = null): readonly AgentRosterRow[] {
  return [...snapshot.slots]
    .sort((left, right) => left.colony_id.localeCompare(right.colony_id, undefined, { numeric: true }))
    .map((slot) => {
      const state = rosterState(slot.presence);
      const [statusKey, statusShape] = STATE_PRESENTATION[state];
      const latencyMs = latestLatency(report, slot.colony_id, slot.generation);
      const fallbackName = slot.controller_type === "baseline"
        ? slot.baseline_kind ?? translate("roster.baseline")
        : slot.controller_type === "human" ? translate("roster.human") : translate("roster.external");
      return {
        colonyId: slot.colony_id,
        displayName: slot.identity?.display_name ?? fallbackName,
        controllerType: slot.controller_type,
        provider: slot.identity?.provider ?? "—",
        model: slot.identity?.model ?? "—",
        state,
        statusText: translate(statusKey),
        statusShape,
        generation: slot.generation,
        takenOver: state === "taken-over" || (snapshot.tenures[slot.colony_id]?.length ?? 0) > 1,
        latencyMs,
        latencyText: latencyMs === null ? "—" : `${new Intl.NumberFormat("en-US").format(latencyMs)} ms`,
      };
    });
}

export interface TimelineItem {
  readonly sequence: number;
  readonly turn: number;
  readonly kind: string;
  readonly colonyId: string | null;
  readonly label: string;
  readonly detail: string;
  readonly segmentId: string;
  readonly boundary: boolean;
  readonly tone: "neutral" | "attention" | "danger" | "success";
}

const EVENT_LABELS: Readonly<Record<string, TranslationKey>> = {
  turn_opened: "event.turnOpened",
  controller_submitted: "event.controllerSubmitted",
  turn_resolved: "event.turnResolved",
  metric_updated: "event.metricUpdated",
  controller_presence_changed: "event.presenceChanged",
  controller_connected: "event.controllerConnected",
  controller_disconnected: "event.controllerDisconnected",
  controller_ready: "event.controllerReady",
  controller_timed_out: "event.controllerTimedOut",
  controller_replaced: "event.controllerReplaced",
  controller_claimed: "event.controllerClaimed",
  heartbeat_rejected: "event.heartbeatRejected",
  pairing_rejected: "event.pairingRejected",
  match_completed: "event.matchCompleted",
};

const SAFE_EVENT_FIELDS = [
  "previous",
  "current",
  "replacement_type",
  "reason",
  "reconnect",
  "deadline_at",
] as const;

function eventDetail(data: Readonly<Record<string, unknown>>): string {
  const parts: string[] = [];
  for (const field of SAFE_EVENT_FIELDS) {
    const value = data[field];
    if (value === null || value === undefined || typeof value === "object") continue;
    parts.push(`${field.replaceAll("_", " ")}: ${String(value)}`);
  }
  return parts.join(" · ");
}

function eventTone(kind: string): TimelineItem["tone"] {
  if (kind.includes("timed_out")) return "danger";
  if (kind.includes("disconnected") || kind.includes("replaced")) return "attention";
  if (kind.includes("submitted") || kind.includes("resolved") || kind.includes("completed")) return "success";
  return "neutral";
}

export function timelineItems(events: readonly OperationalEvent[]): readonly TimelineItem[] {
  const unique = new Map<number, OperationalEvent>();
  for (const candidate of events) unique.set(candidate.sequence, candidate);
  const generations = new Map<string, number>();
  return [...unique.values()].sort((left, right) => left.sequence - right.sequence).map((candidate) => {
      const colony = candidate.colony_id ?? "match";
      const explicitGeneration = finiteNumber(candidate.data.generation);
      if (candidate.colony_id && explicitGeneration !== null) generations.set(candidate.colony_id, explicitGeneration);
      const generation = explicitGeneration ?? generations.get(colony) ?? 0;
      const current = String(candidate.data.current ?? "");
      const labelKey = EVENT_LABELS[candidate.kind];
      return {
        sequence: candidate.sequence,
        turn: candidate.turn,
        kind: candidate.kind,
        colonyId: candidate.colony_id,
        label: labelKey ? translate(labelKey) : candidate.kind.replaceAll("_", " "),
        detail: eventDetail(candidate.data),
        segmentId: `${colony}:${generation}`,
        boundary: candidate.kind === "controller_replaced" || current === "taken_over",
        tone: eventTone(candidate.kind),
      };
    });
}

export interface DecisionFeedItem {
  readonly sequence: number;
  readonly turn: number;
  readonly colonyId: string;
  readonly displayName: string;
  readonly actions: readonly string[];
  readonly results: readonly { readonly status: "accepted" | "rejected"; readonly detail: string }[];
}

function colonyDisplayName(snapshot: OperationsSnapshot, colonyId: string): string {
  const slot = snapshot.slots.find((candidate) => candidate.colony_id === colonyId);
  return slot?.identity?.display_name ?? colonyId;
}

function describeAction(action: Readonly<Record<string, unknown>>): string {
  const kind = String(action.kind ?? "unknown");
  switch (kind) {
    case "wait": return translate("action.wait");
    case "gather": return translate("action.gather", { x: String(action.x), y: String(action.y) });
    case "build": return translate("action.build", { structure: structureName(String(action.structure)), x: String(action.x), y: String(action.y) });
    case "diplomacy": {
      const op = String(action.operation ?? "contact");
      if (op === "alliance") return translate("action.diplomacy.alliance", { target: String(action.target_colony_id) });
      if (op === "peace") return translate("action.diplomacy.peace", { target: String(action.target_colony_id) });
      return translate("action.diplomacy", { op: translate("action.contact"), target: String(action.target_colony_id) });
    }
    case "trade_offer": return translate("action.tradeOffer", { target: String(action.target_colony_id) });
    case "trade_respond": return action.accept
      ? translate("action.tradeRespond.accept")
      : `${translate("action.tradeRespond.decline")} ${translate("action.tradeRespond.offer", { id: String(action.offer_id) })}`;
    case "raid": return translate("action.raid", { target: String(action.target_colony_id) });
    case "set_policy": return translate("action.setPolicy", { policy: String(action.policy), value: String(action.value) });
    case "scout": return translate("action.scout", { x: String(action.x), y: String(action.y) });
    case "repair": return translate("action.repair", { structure_id: String(action.structure_id) });
    case "extinguish": return translate("action.extinguish", { structure_id: String(action.structure_id) });
    case "demolish": return translate("action.demolish", { structure_id: String(action.structure_id) });
    case "message": return translate("action.message", { target: String(action.target_colony_id) });
    case "diplomacy_respond": return action.accept ? translate("proposals.accept") : translate("proposals.decline");
    default: return kind;
  }
}

export function decisionFeedItems(snapshot: OperationsSnapshot): readonly DecisionFeedItem[] {
  const items: DecisionFeedItem[] = [];
  for (const event of snapshot.events) {
    if (event.kind !== "turn_resolved") continue;
    const decisions = event.data.decisions;
    if (!Array.isArray(decisions)) continue;
    for (const raw of decisions) {
      const decision = record(raw);
      const colonyId = String(decision.colony_id ?? "?");
      const rawActions = Array.isArray(decision.actions) ? decision.actions : [];
      const rawResults = Array.isArray(decision.results) ? decision.results : [];
      items.push({
        sequence: event.sequence,
        turn: event.turn,
        colonyId,
        displayName: colonyDisplayName(snapshot, colonyId),
        actions: rawActions.map(describeAction),
        results: rawResults.map((entry) => {
          const result = record(entry);
          const status = result.status === "accepted" ? "accepted" : "rejected";
          return { status, detail: String(result.code ?? result.status ?? "ok") };
        }),
      });
    }
  }
  return items;
}

export type MetricAxis =
  | "survival"
  | "growth"
  | "prosperity"
  | "diplomacy"
  | "resilience"
  | "action-validity"
  | "presence"
  | "server-mcp"
  | "adapter-usage";

export type MetricProvenance = "simulation-raw" | "server-measured" | "adapter-reported" | "unavailable";

export interface MetricValue {
  readonly colonyId: string;
  readonly segmentId?: string;
  readonly provider?: string;
  readonly model?: string;
  readonly metric: string;
  readonly value: number;
}

export interface MetricSeries {
  readonly axis: MetricAxis;
  readonly label: string;
  readonly provenance: MetricProvenance;
  readonly values: readonly MetricValue[];
}

function sortedEntries(value: unknown): readonly [string, unknown][] {
  return Object.entries(record(value)).sort(([left], [right]) => left.localeCompare(right, undefined, { numeric: true }));
}

function valuesFromNested(axis: unknown, metrics: readonly string[]): MetricValue[] {
  const values: MetricValue[] = [];
  for (const [colonyId, rawRow] of sortedEntries(axis)) {
    const row = record(rawRow);
    for (const metric of metrics) {
      const value = finiteNumber(row[metric]);
      if (value !== null) values.push({ colonyId, metric, value });
    }
  }
  return values;
}

function valuesFromScalars(axis: unknown, metric: string): MetricValue[] {
  return sortedEntries(axis).flatMap(([colonyId, rawValue]) => {
    const value = finiteNumber(rawValue);
    return value === null ? [] : [{ colonyId, metric, value }];
  });
}

function resourceValues(axis: unknown): MetricValue[] {
  const values: MetricValue[] = [];
  for (const [colonyId, rawRow] of sortedEntries(axis)) {
    for (const [metric, rawValue] of sortedEntries(record(rawRow).resources)) {
      const value = finiteNumber(rawValue);
      if (value !== null) values.push({ colonyId, metric, value });
    }
  }
  return values;
}

function provenanceValues(
  axis: unknown,
  metrics: readonly string[],
): MetricValue[] {
  return valuesFromNested(axis, metrics);
}

interface TenureUsage {
  readonly server: readonly MetricValue[];
  readonly adapter: readonly MetricValue[];
  readonly presence: readonly MetricValue[];
}

function tenureUsage(value: unknown): TenureUsage {
  const server: MetricValue[] = [];
  const adapter: MetricValue[] = [];
  const presence: MetricValue[] = [];
  for (const [colonyId, rawTenures] of sortedEntries(value)) {
    if (!Array.isArray(rawTenures)) continue;
    for (const rawTenure of rawTenures) {
      const tenure = record(rawTenure);
      const generation = finiteNumber(tenure.generation);
      if (generation === null) continue;
      const identity = record(tenure.identity);
      const attribution = {
        colonyId,
        segmentId: `${colonyId}:${generation}`,
        provider: typeof identity.provider === "string" ? identity.provider : "—",
        model: typeof identity.model === "string" ? identity.model : "—",
      };
      const serverMeasured = record(tenure.server_measured);
      const adapterReported = record(tenure.adapter_reported_model_usage);
      for (const metric of ["mcp_calls"] as const) {
        const metricValue = finiteNumber(serverMeasured[metric]);
        if (metricValue !== null) server.push({ ...attribution, metric, value: metricValue });
      }
      for (const metric of ["timeouts", "reconnects"] as const) {
        const metricValue = finiteNumber(serverMeasured[metric]);
        if (metricValue !== null) presence.push({ ...attribution, metric, value: metricValue });
      }
      for (const metric of ["input_tokens", "output_tokens", "latency_ms"] as const) {
        const metricValue = finiteNumber(adapterReported[metric]);
        if (metricValue !== null) adapter.push({ ...attribution, metric, value: metricValue });
      }
    }
  }
  return { server, adapter, presence };
}

export function metricSeries(report: RunReport): readonly MetricSeries[] {
  const metrics = record(report.metrics);
  const presence = record(metrics.presence);
  const serverMeasured = record(metrics.server_measured);
  const adapterReported = metrics.adapter_reported_model_usage;
  const diplomacy = [
    ...valuesFromScalars(metrics.trade, "trade"),
    ...valuesFromScalars(metrics.aggression, "aggression"),
  ];
  const presenceValues = [
    ...valuesFromScalars(presence.timeouts, "timeouts"),
    ...valuesFromScalars(presence.reconnects, "reconnects"),
  ];
  const segmented = tenureUsage(metrics.tenure_metrics);

  return [
    {
      axis: "survival",
      label: translate("metrics.survival"),
      provenance: "simulation-raw",
      values: valuesFromNested(metrics.survival, ["turns", "population"]),
    },
    {
      axis: "growth",
      label: translate("metrics.growth"),
      provenance: "simulation-raw",
      values: valuesFromNested(metrics.growth, ["initial_population", "peak_population", "housing"]),
    },
    {
      axis: "prosperity",
      label: translate("metrics.prosperity"),
      provenance: "simulation-raw",
      values: resourceValues(metrics.prosperity),
    },
    {
      axis: "diplomacy",
      label: translate("metrics.diplomacy"),
      provenance: "simulation-raw",
      values: diplomacy,
    },
    {
      axis: "resilience",
      label: translate("metrics.resilience"),
      provenance: "unavailable",
      values: [],
    },
    {
      axis: "action-validity",
      label: translate("metrics.actionValidity"),
      provenance: "simulation-raw",
      values: valuesFromNested(metrics.decision_quality, ["invalid_actions"]),
    },
    {
      axis: "presence",
      label: translate("metrics.timeouts"),
      provenance: "server-measured",
      values: segmented.presence.length ? segmented.presence : presenceValues,
    },
    {
      axis: "server-mcp",
      label: translate("metrics.mcpCalls"),
      provenance: "server-measured",
      values: segmented.server.length ? segmented.server : valuesFromScalars(serverMeasured.mcp_calls, "mcp_calls"),
    },
    {
      axis: "adapter-usage",
      label: translate("metrics.tokens"),
      provenance: "adapter-reported",
      values: segmented.adapter.length
        ? segmented.adapter
        : provenanceValues(adapterReported, ["input_tokens", "output_tokens", "latency_ms"]),
    },
  ];
}

export type InspectorTab = "decision" | "resources" | "diplomacy" | "cost";
const INSPECTOR_TABS: readonly InspectorTab[] = ["decision", "resources", "diplomacy", "cost"];

export interface OperationsState {
  readonly selectedAgentId: string | null;
  readonly selectedTurn: number | null;
  readonly selectedSequence: number | null;
  readonly selectedTab: InspectorTab;
  readonly announcement: string;
}

export interface OperationsControllerOptions {
  readonly onChange?: (controller: OperationsController) => void;
  readonly onResync?: (gap: { readonly expected: number; readonly received: number }) => void;
}

export type ApplyMessageResult = "applied" | "ignored" | "resync";

export function currentSourceMessageHandler<TSource, TMessage>(
  source: TSource,
  current: () => TSource | null,
  receive: (message: TMessage) => void,
): (message: TMessage) => void {
  return (message) => {
    if (current() === source) receive(message);
  };
}

export interface WorldView {
  readonly scale: number;
  readonly x: number;
  readonly y: number;
}

export type WorldViewAction =
  | { readonly kind: "zoom"; readonly delta: number }
  | { readonly kind: "pan"; readonly x: number; readonly y: number }
  | { readonly kind: "reset" };

export function nextWorldView(view: WorldView, action: WorldViewAction): WorldView {
  if (action.kind === "reset") return { scale: 1, x: 0, y: 0 };
  if (action.kind === "pan") return { ...view, x: view.x + action.x, y: view.y + action.y };
  return { ...view, scale: Math.min(1.6, Math.max(0.65, view.scale + action.delta)) };
}

export class OperationsController {
  private snapshot: OperationsSnapshot | null = null;
  private report: RunReport | null = null;
  private lastSequence = 0;
  private currentState: OperationsState = {
    selectedAgentId: null,
    selectedTurn: null,
    selectedSequence: null,
    selectedTab: "decision",
    announcement: translate("ops.announcement.waiting"),
  };

  constructor(private readonly options: OperationsControllerOptions = {}) {}

  get state(): OperationsState {
    return this.currentState;
  }

  get roster(): readonly AgentRosterRow[] {
    return this.snapshot ? agentRosterRows(this.snapshot, this.report) : [];
  }

  get timeline(): readonly TimelineItem[] {
    return this.snapshot ? timelineItems(this.snapshot.events) : [];
  }

  get decisions(): readonly DecisionFeedItem[] {
    return this.snapshot ? decisionFeedItems(this.snapshot) : [];
  }

  get metrics(): readonly MetricSeries[] {
    return this.report ? metricSeries(this.report) : [];
  }

  get currentSnapshot(): OperationsSnapshot | null {
    return this.snapshot;
  }

  reset(announcement = translate("ops.announcement.waiting")): void {
    this.snapshot = null;
    this.report = null;
    this.lastSequence = 0;
    this.currentState = {
      selectedAgentId: null,
      selectedTurn: null,
      selectedSequence: null,
      selectedTab: "decision",
      announcement,
    };
    this.changed();
  }

  announce(announcement: string): void {
    this.currentState = { ...this.currentState, announcement };
    this.changed();
  }

  applySnapshot(next: OperationsSnapshot): void {
    const currentSnapshot = this.snapshot;
    const sameMatch = currentSnapshot?.match_id === next.match_id;
    if (currentSnapshot && !sameMatch) this.report = null;
    if (sameMatch && currentSnapshot) {
      const currentLast = currentSnapshot.events.at(-1)?.sequence ?? 0;
      const nextLast = [...next.events].sort((left, right) => left.sequence - right.sequence).at(-1)?.sequence ?? 0;
      if (nextLast < currentLast) return;
      const mergedEvents = new Map(currentSnapshot.events.map((event) => [event.sequence, event]));
      for (const event of next.events) mergedEvents.set(event.sequence, event);
      next = { ...next, events: [...mergedEvents.values()].sort((left, right) => left.sequence - right.sequence) };
    }
    const roster = agentRosterRows(next, this.report);
    const selectedEvent = next.events.find(({ sequence }) => sequence === this.currentState.selectedSequence);
    const selectedAgentId = roster.some(({ colonyId }) => colonyId === this.currentState.selectedAgentId)
      ? this.currentState.selectedAgentId
      : roster[0]?.colonyId ?? null;
    this.snapshot = {
      ...next,
      events: [...next.events].sort((left, right) => left.sequence - right.sequence),
    };
    this.lastSequence = this.snapshot.events.at(-1)?.sequence ?? 0;
    this.currentState = {
      ...this.currentState,
      selectedAgentId,
      selectedSequence: selectedEvent?.sequence ?? null,
      selectedTurn: selectedEvent?.turn ?? next.turn,
      announcement: translate("ops.announcement.turn", { turn: next.turn, count: roster.length }),
    };
    this.changed();
  }

  setReport(report: RunReport): void {
    this.report = report;
    this.currentState = { ...this.currentState, announcement: translate("ops.announcement.metricsUpdated") };
    this.changed();
  }

  applyMessage(message: AdminWebSocketMessage): ApplyMessageResult {
    if (message.schema_version !== "1.1") return "ignored";
    if (message.type === "lobby.snapshot") {
      this.applySnapshot(message.payload);
      return "applied";
    }
    const nextEvent = message.type === "metric.updated" ? message.payload.event : message.payload;
    if (nextEvent.sequence <= this.lastSequence) return "ignored";
    if (this.lastSequence > 0 && nextEvent.sequence !== this.lastSequence + 1) {
      this.options.onResync?.({ expected: this.lastSequence + 1, received: nextEvent.sequence });
      return "resync";
    }
    if (!this.snapshot) {
      this.options.onResync?.({ expected: 1, received: nextEvent.sequence });
      return "resync";
    }
    this.snapshot = this.snapshotWithEvent(this.snapshot, nextEvent);
    this.lastSequence = nextEvent.sequence;
    if (message.type === "metric.updated") {
      this.report = {
        schema_version: "1.1",
        status: this.report?.status ?? {},
        latest_events: this.report?.latest_events ?? [],
        metrics: message.payload.metrics,
      };
    }
    this.currentState = {
      ...this.currentState,
      selectedTurn: nextEvent.turn,
      announcement: `${EVENT_LABELS[nextEvent.kind] ? translate(EVENT_LABELS[nextEvent.kind]!) : nextEvent.kind.replaceAll("_", " ")} · ${translate("timeline.turn", { turn: nextEvent.turn })}`,
    };
    this.changed();
    return "applied";
  }

  selectAgent(colonyId: string): void {
    if (!this.roster.some((row) => row.colonyId === colonyId)) return;
    this.currentState = { ...this.currentState, selectedAgentId: colonyId };
    this.changed();
  }

  moveRosterSelection(delta: number): void {
    const roster = this.roster;
    if (!roster.length) return;
    const current = Math.max(0, roster.findIndex(({ colonyId }) => colonyId === this.currentState.selectedAgentId));
    const next = (current + delta + roster.length) % roster.length;
    this.selectAgent(roster[next]!.colonyId);
  }

  selectTimeline(sequence: number): void {
    const item = this.timeline.find((candidate) => candidate.sequence === sequence);
    if (!item) return;
    this.currentState = {
      ...this.currentState,
      selectedSequence: sequence,
      selectedTurn: item.turn,
      selectedAgentId: item.colonyId ?? this.currentState.selectedAgentId,
    };
    this.changed();
  }

  selectTab(tab: InspectorTab): void {
    if (!INSPECTOR_TABS.includes(tab)) return;
    this.currentState = { ...this.currentState, selectedTab: tab };
    this.changed();
  }

  moveTab(delta: number): void {
    const current = INSPECTOR_TABS.indexOf(this.currentState.selectedTab);
    this.selectTab(INSPECTOR_TABS[(current + delta + INSPECTOR_TABS.length) % INSPECTOR_TABS.length]!);
  }

  private snapshotWithEvent(snapshot: OperationsSnapshot, nextEvent: OperationalEvent): OperationsSnapshot {
    const currentPresence = String(nextEvent.data.current ?? "");
    const slots = currentPresence
      ? snapshot.slots.map((slot) => slot.colony_id === nextEvent.colony_id
        ? { ...slot, presence: currentPresence, generation: finiteNumber(nextEvent.data.generation) ?? slot.generation }
        : slot)
      : snapshot.slots;
    const pending = nextEvent.kind === "turn_opened"
      ? snapshot.slots.map(({ colony_id }) => colony_id).sort((left, right) => left.localeCompare(right, undefined, { numeric: true }))
      : nextEvent.kind === "controller_submitted" && nextEvent.colony_id
        ? snapshot.pending_colonies.filter((colonyId) => colonyId !== nextEvent.colony_id)
        : snapshot.pending_colonies;
    return {
      ...snapshot,
      status: nextEvent.kind === "match_completed" ? "completed" : snapshot.status,
      turn: nextEvent.kind === "turn_opened" ? nextEvent.turn : snapshot.turn,
      deadline_at: nextEvent.kind === "turn_opened"
        ? finiteNumber(nextEvent.data.deadline_at)
        : snapshot.deadline_at,
      pending_colonies: pending,
      slots,
      events: [...snapshot.events, nextEvent],
    };
  }

  private changed(): void {
    this.options.onChange?.(this);
  }
}

type OperationsHostName = "live" | "roster" | "tabs" | "inspector" | "timeline" | "decisions" | "metrics";

const TAB_LABELS: Readonly<Record<InspectorTab, TranslationKey>> = {
  decision: "tab.decision",
  resources: "tab.resources",
  diplomacy: "tab.diplomacy",
  cost: "tab.cost",
};

function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function operationsHost(root: HTMLElement, name: OperationsHostName): HTMLElement | null {
  return root.matches(`[data-operations-${name}]`)
    ? root
    : root.querySelector<HTMLElement>(`[data-operations-${name}]`);
}

function ensureOperationsHosts(root: HTMLElement): void {
  if (operationsHost(root, "roster")) return;
  const fixture = element("div", "operations-fixture");
  for (const [name, tag] of [
    ["live", "p"],
    ["roster", "section"],
    ["tabs", "div"],
    ["inspector", "section"],
    ["timeline", "section"],
    ["decisions", "section"],
    ["metrics", "section"],
  ] as const) {
    const host = element(tag);
    host.setAttribute(`data-operations-${name}`, "");
    fixture.append(host);
  }
  root.replaceChildren(fixture);
}

function renderRoster(host: HTMLElement, controller: OperationsController): void {
  const title = element("h2", "section-title", translate("roster.title"));
  const list = element("div", "agent-roster");
  list.setAttribute("role", "listbox");
  list.setAttribute("aria-label", translate("roster.title"));

  for (const row of controller.roster) {
    const selected = row.colonyId === controller.state.selectedAgentId;
    const option = element("button", "agent-row");
    option.type = "button";
    option.dataset.agentId = row.colonyId;
    option.dataset.state = row.state;
    if (row.takenOver) option.dataset.tenureBoundary = "";
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", String(selected));
    option.tabIndex = selected ? 0 : -1;

    const shape = element("span", "status-shape");
    shape.dataset.statusShape = row.statusShape;
    shape.setAttribute("aria-hidden", "true");
    const identity = element("span", "agent-identity");
    identity.append(
      element("strong", "agent-name", row.displayName),
      element("span", "agent-model", `${row.provider} · ${row.model}`),
    );
    const state = element("span", "agent-state", row.statusText);
    const latency = element("span", "agent-latency", row.latencyText);
    latency.setAttribute("aria-label", translate("roster.latencyAria", { value: row.latencyText }));
    option.append(shape, identity, state, latency);
    list.append(option);
  }
  host.replaceChildren(title, list);
  if (!controller.roster.length) {
    host.append(element("p", "operations-empty", translate("roster.empty")));
  }
}

function renderTabs(host: HTMLElement, controller: OperationsController): void {
  host.className = "inspector-tabs";
  host.setAttribute("role", "tablist");
  host.setAttribute("aria-label", translate("intel.title"));
  const tabs = INSPECTOR_TABS.map((tab) => {
    const selected = controller.state.selectedTab === tab;
    const button = element("button", "inspector-tab", translate(TAB_LABELS[tab]));
    button.type = "button";
    button.id = `operations-tab-${tab}`;
    button.dataset.tab = tab;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", String(selected));
    button.setAttribute("aria-controls", "operations-inspector-panel");
    button.tabIndex = selected ? 0 : -1;
    return button;
  });
  host.replaceChildren(...tabs);
}

function renderInspector(host: HTMLElement, controller: OperationsController): void {
  const selected = controller.roster.find(({ colonyId }) => colonyId === controller.state.selectedAgentId);
  host.id = "operations-inspector-panel";
  host.className = "inspector-panel";
  host.setAttribute("role", "tabpanel");
  host.setAttribute("aria-labelledby", `operations-tab-${controller.state.selectedTab}`);

  const heading = element("h3", "inspector-title", selected?.displayName ?? translate("inspector.none"));
  const body = element("dl", "inspector-spec");
  const rows: readonly [string, string][] = controller.state.selectedTab === "decision"
    ? [
      [translate("inspector.turn"), controller.state.selectedTurn === null ? "—" : String(controller.state.selectedTurn)],
      [translate("inspector.state"), selected?.statusText ?? "—"],
      [translate("inspector.controller"), selected?.controllerType ?? "—"],
    ]
    : controller.state.selectedTab === "resources"
      ? [
        [translate("inspector.source"), translate("inspector.sourceValue")],
        [translate("inspector.detail"), translate("inspector.detailValue")],
      ]
      : controller.state.selectedTab === "diplomacy"
        ? [
          [translate("inspector.rawAxes"), translate("inspector.rawAxesValue")],
          [translate("inspector.composite"), translate("inspector.compositeValue")],
        ]
        : [
          [translate("inspector.provider"), selected?.provider ?? "—"],
          [translate("inspector.model"), selected?.model ?? "—"],
          [translate("inspector.latency"), selected?.latencyText ?? "—"],
          [translate("inspector.attribution"), translate("inspector.attributionValue")],
        ];
  for (const [term, description] of rows) {
    body.append(element("dt", undefined, term), element("dd", undefined, description));
  }
  host.replaceChildren(heading, body);
}

function renderTimeline(host: HTMLElement, controller: OperationsController): void {
  const title = element("h2", "section-title", translate("timeline.title"));
  const list = element("ol", "operations-timeline");
  list.setAttribute("aria-label", translate("timeline.aria"));
  for (const [index, item] of controller.timeline.entries()) {
    const selected = item.sequence === controller.state.selectedSequence;
    const row = element("li", "timeline-item");
    row.dataset.segmentId = item.segmentId;
    row.dataset.tone = item.tone;
    if (item.boundary) row.dataset.tenureBoundary = "";
    row.setAttribute("aria-current", selected ? "true" : "false");
    const action = element("button", "timeline-action");
    action.type = "button";
    action.dataset.sequence = String(item.sequence);
    action.tabIndex = selected || (controller.state.selectedSequence === null && index === 0) ? 0 : -1;

    const marker = element("span", "timeline-marker", item.boundary ? translate("timeline.tenure") : `#${item.sequence}`);
    const description = element("span", "timeline-description");
    description.append(
      element("strong", undefined, item.label),
      element("span", undefined, `${translate("timeline.turn", { turn: item.turn })}${item.colonyId ? ` · ${item.colonyId}` : ""}`),
    );
    if (item.detail) description.append(element("small", undefined, item.detail));
    action.append(marker, description);
    row.append(action);
    list.append(row);
  }
  if (!controller.timeline.length) {
    list.append(element("li", "operations-empty", translate("timeline.empty")));
  }
  host.replaceChildren(title, list);
}

function renderDecisionFeed(host: HTMLElement, controller: OperationsController): void {
  const title = element("h2", "section-title", translate("decisions.title"));
  const list = element("ol", "decision-feed");
  list.setAttribute("aria-label", translate("decisions.aria"));
  for (const item of controller.decisions) {
    const row = element("li", "decision-item");
    row.dataset.colonyId = item.colonyId;
    const header = element("span", "decision-header");
    header.append(
      element("strong", undefined, item.displayName),
      element("span", undefined, translate("timeline.turn", { turn: item.turn })),
    );
    const body = element("span", "decision-body", item.actions.join(" · ") || "—");
    const outcomes = element("span", "decision-outcomes");
    for (const result of item.results) {
      outcomes.append(
        element(
          "span",
          `decision-result decision-${result.status}`,
          result.status === "accepted" ? translate("decisions.accepted") : translate("decisions.rejected", { detail: result.detail }),
        ),
      );
    }
    row.append(header, body, outcomes);
    list.append(row);
  }
  if (!controller.decisions.length) {
    list.append(element("li", "operations-empty", translate("decisions.empty")));
  }
  host.replaceChildren(title, list);
}

function metricValueLabel(value: MetricValue, controller: OperationsController): string {
  const agent = controller.roster.find(({ colonyId }) => colonyId === value.colonyId);
  const provider = value.provider ?? agent?.provider;
  const model = value.model ?? agent?.model;
  const generation = value.segmentId?.split(":").at(-1);
  const segment = generation ? ` · ${translate("metrics.generation", { n: generation })}` : "";
  const attribution = provider && provider !== "—" ? ` · ${provider}/${model ?? "—"}` : "";
  return `${value.colonyId}${segment}${attribution} · ${metricName(value.metric)}`;
}

const PROVENANCE_KEYS: Readonly<Record<MetricProvenance, TranslationKey>> = {
  "simulation-raw": "metrics.provenance.simulationRaw",
  "server-measured": "metrics.provenance.serverMeasured",
  "adapter-reported": "metrics.provenance.adapterReported",
  unavailable: "metrics.provenance.unavailable",
};

function renderMetrics(host: HTMLElement, controller: OperationsController): void {
  const previousValues = new Map(
    [...host.querySelectorAll<HTMLElement>("[data-metric-key]")]
      .map((node) => [node.dataset.metricKey ?? "", node.textContent ?? ""] as const),
  );
  host.className = "metric-dock";
  host.setAttribute("aria-label", translate("metrics.aria"));
  const title = element("h2", "section-title", translate("metrics.title"));
  if (!controller.metrics.length) {
    host.replaceChildren(title, element("p", "operations-empty", translate("metrics.empty2")));
    return;
  }
  const sections = controller.metrics.map((series) => {
    const section = element("section", "metric-series");
    section.dataset.axis = series.axis;
    const heading = element("h3", undefined, series.label);
    const provenance = element("p", "metric-provenance", translate(PROVENANCE_KEYS[series.provenance]));
    const values = element("ul", "metric-values");
    const maximum = Math.max(1, ...series.values.map(({ value }) => value));
    for (const value of series.values) {
      const item = element("li");
      const valueLabel = metricValueLabel(value, controller);
      const label = element("span", undefined, valueLabel);
      const meter = element("meter");
      meter.min = 0;
      meter.max = maximum;
      meter.value = value.value;
      meter.textContent = String(value.value);
      meter.setAttribute("aria-label", `${valueLabel} ${value.value}`);
      const formattedValue = new Intl.NumberFormat("en-US").format(value.value);
      const output = element("strong", undefined, formattedValue);
      const metricKey = `${series.axis}:${value.segmentId ?? value.colonyId}:${value.metric}`;
      output.dataset.metricKey = metricKey;
      if (previousValues.get(metricKey) !== formattedValue) output.dataset.liveNumber = "";
      item.append(label, meter, output);
      values.append(item);
    }
    if (!series.values.length) values.append(element("li", "metric-unavailable", "—"));
    section.append(heading, provenance, values);
    return section;
  });
  host.replaceChildren(title, ...sections);
}

export function renderOperationsRoom(root: HTMLElement, controller: OperationsController): void {
  const restoreSelector = focusedOperationsSelector(document.activeElement);
  ensureOperationsHosts(root);
  const live = operationsHost(root, "live");
  if (live) {
    live.className = "operations-live";
    live.setAttribute("aria-live", "polite");
    live.setAttribute("aria-atomic", "true");
    live.textContent = controller.state.announcement;
  }
  const roster = operationsHost(root, "roster");
  const tabs = operationsHost(root, "tabs");
  const inspector = operationsHost(root, "inspector");
  const timeline = operationsHost(root, "timeline");
  const decisions = operationsHost(root, "decisions");
  const metrics = operationsHost(root, "metrics");
  if (roster) renderRoster(roster, controller);
  if (tabs) renderTabs(tabs, controller);
  if (inspector) renderInspector(inspector, controller);
  if (timeline) renderTimeline(timeline, controller);
  if (decisions) renderDecisionFeed(decisions, controller);
  if (metrics) renderMetrics(metrics, controller);
  if (restoreSelector) {
    root.querySelector<HTMLElement>(restoreSelector)?.focus({ preventScroll: true });
  }
}

function focusedOperationsSelector(active: Element | null): string | null {
  if (!active) return null;
  const agent = active.closest<HTMLElement>("[data-agent-id]");
  if (agent?.dataset.agentId) return `[data-agent-id='${agent.dataset.agentId}']`;
  const tab = active.closest<HTMLElement>("[data-tab]");
  if (tab?.dataset.tab) return `[data-tab='${tab.dataset.tab}']`;
  const timeline = active.closest<HTMLElement>("[data-sequence]");
  if (timeline?.dataset.sequence) return `[data-sequence='${timeline.dataset.sequence}']`;
  return null;
}

function focusSelected(root: HTMLElement, selector: string): void {
  queueMicrotask(() => root.querySelector<HTMLElement>(selector)?.focus({ preventScroll: true }));
}

export function bindOperationsRoom(root: HTMLElement, controller: OperationsController): void {
  if (root.dataset.operationsBound === "true") return;
  root.dataset.operationsBound = "true";
  root.addEventListener("click", (event) => {
    const target = event.target as Element | null;
    const agent = target?.closest<HTMLElement>("[data-agent-id]");
    const tab = target?.closest<HTMLElement>("[data-tab]");
    const timeline = target?.closest<HTMLElement>("[data-sequence]");
    if (agent?.dataset.agentId) {
      controller.selectAgent(agent.dataset.agentId);
      focusSelected(root, "[role='option'][aria-selected='true']");
    } else if (tab?.dataset.tab) {
      controller.selectTab(tab.dataset.tab as InspectorTab);
      focusSelected(root, "[role='tab'][aria-selected='true']");
    } else if (timeline?.dataset.sequence) {
      controller.selectTimeline(Number(timeline.dataset.sequence));
      focusSelected(root, `[data-sequence='${timeline.dataset.sequence}']`);
    }
  });
  root.addEventListener("keydown", (event) => {
    const target = event.target as Element | null;
    const agent = target?.closest<HTMLElement>("[data-agent-id]");
    const tab = target?.closest<HTMLElement>("[data-tab]");
    const timeline = target?.closest<HTMLElement>("[data-sequence]");
    if (agent && ["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      if (event.key === "Home") controller.selectAgent(controller.roster[0]?.colonyId ?? "");
      else if (event.key === "End") controller.selectAgent(controller.roster.at(-1)?.colonyId ?? "");
      else controller.moveRosterSelection(["ArrowDown", "ArrowRight"].includes(event.key) ? 1 : -1);
      focusSelected(root, "[role='option'][aria-selected='true']");
    } else if (tab && ["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      if (event.key === "Home") controller.selectTab(INSPECTOR_TABS[0]!);
      else if (event.key === "End") controller.selectTab(INSPECTOR_TABS.at(-1)!);
      else controller.moveTab(event.key === "ArrowRight" ? 1 : -1);
      focusSelected(root, "[role='tab'][aria-selected='true']");
    } else if (timeline && ["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const items = controller.timeline;
      const current = Math.max(0, items.findIndex(({ sequence }) => sequence === Number(timeline.dataset.sequence)));
      const next = event.key === "Home"
        ? items[0]
        : event.key === "End"
          ? items.at(-1)
          : items[(current + (["ArrowDown", "ArrowRight"].includes(event.key) ? 1 : -1) + items.length) % items.length];
      if (next) {
        controller.selectTimeline(next.sequence);
        focusSelected(root, `[data-sequence='${next.sequence}']`);
      }
    } else if (timeline && ["Enter", " "].includes(event.key)) {
      event.preventDefault();
      controller.selectTimeline(Number(timeline.dataset.sequence));
      focusSelected(root, `[data-sequence='${timeline.dataset.sequence}']`);
    }
  });
}
