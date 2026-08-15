import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AdminWebSocketMessage,
  ControllerTenure,
  LobbySlot,
  OperationsSnapshot,
  OperationalEvent,
  RunReport,
} from "../src/api";
import {
  OperationsController,
  agentRosterRows,
  bindOperationsRoom,
  currentSourceMessageHandler,
  decisionFeedItems,
  metricSeries,
  nextWorldView,
  renderOperationsRoom,
  timelineItems,
} from "../src/operations";
import { setLanguage } from "../src/i18n";

const identity = {
  display_name: "Codex North",
  provider: "openai",
  model: "gpt-5",
};

function slot(
  colonyId: string,
  presence: string,
  overrides: Partial<LobbySlot> = {},
): LobbySlot {
  return {
    colony_id: colonyId,
    controller_type: "external",
    controller_id: `controller-${colonyId}`,
    identity,
    presence,
    baseline_kind: null,
    generation: 1,
    pairing_active: false,
    pairing_expires_at: null,
    pairing_consumed: true,
    pairing_attempts: 0,
    last_heartbeat_at: 1_000,
    last_heartbeat_turn: 3,
    ...overrides,
  };
}

function event(
  sequence: number,
  kind: string,
  colonyId: string | null = null,
  data: Readonly<Record<string, unknown>> = {},
): OperationalEvent {
  return { sequence, turn: 3, kind, colony_id: colonyId, data };
}

function tenure(
  colonyId: string,
  generation: number,
  overrides: Partial<ControllerTenure> = {},
): ControllerTenure {
  return {
    colony_id: colonyId,
    controller_id: `controller-${generation}`,
    controller_type: "external",
    identity: { ...identity, display_name: `Codex ${generation}` },
    generation,
    started_at: 900 + generation,
    ended_at: null,
    ...overrides,
  };
}

function snapshot(
  slots: readonly LobbySlot[],
  events: readonly OperationalEvent[] = [],
  tenures: OperationsSnapshot["tenures"] = {},
): OperationsSnapshot {
  return {
    schema_version: "1.1",
    match_id: "match-1",
    scenario_id: "basic-survival-v1",
    seed: 17,
    colony_count: slots.length,
    deadline_seconds: 30,
    status: "running",
    slots,
    turn: 3,
    deadline_at: 1_030,
    pending_colonies: [],
    events,
    tenures,
  };
}

afterEach(() => {
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

beforeEach(() => {
  setLanguage("en");
});

describe("operations projections", () => {
  it("preserves every server-owned controller state as text and shape", () => {
    const rows = agentRosterRows(snapshot([
      slot("c1", "connected"),
      slot("c2", "thinking"),
      slot("c3", "submitted"),
      slot("c4", "timed_out"),
      slot("c5", "disconnected"),
      slot("c6", "taken_over", { controller_type: "baseline", identity: null }),
    ]));

    expect(rows.map(({ state, statusText, statusShape }) => [state, statusText, statusShape])).toEqual([
      ["connected", "Connected", "circle"],
      ["thinking", "Thinking", "diamond"],
      ["submitted", "Submitted", "square"],
      ["timed-out", "Timed out", "triangle"],
      ["disconnected", "Disconnected", "ring"],
      ["taken-over", "Taken over", "split"],
    ]);
  });

  it("keeps a fixed latency slot before and after adapter usage arrives", () => {
    const before = agentRosterRows(snapshot([slot("c1", "thinking")]));
    const after = agentRosterRows(snapshot([slot("c1", "submitted")]), {
      schema_version: "1.1",
      status: {},
      latest_events: [],
      metrics: {
        adapter_reported_model_usage: { c1: { latency_ms: 999 } },
        tenure_metrics: {
          c1: [{
            ...tenure("c1", 1),
            adapter_reported_model_usage: { latency_ms: 480 },
          }],
        },
      },
    });

    expect(before[0]).toMatchObject({ latencyMs: null, latencyText: "—" });
    expect(after[0]).toMatchObject({ latencyMs: 480, latencyText: "480 ms" });
  });

  it("sorts and deduplicates events while exposing takeover tenure boundaries", () => {
    const items = timelineItems([
      event(12, "controller_submitted", "c2", { controller_id: "controller-2" }),
      event(10, "controller_replaced", "c2", { generation: 2, replacement_type: "baseline" }),
      event(9, "controller_timed_out", "c2", { generation: 1 }),
      event(12, "controller_submitted", "c2", { controller_id: "controller-2" }),
    ]);

    expect(items.map(({ sequence, segmentId, boundary }) => [sequence, segmentId, boundary])).toEqual([
      [9, "c2:1", false],
      [10, "c2:2", true],
      [12, "c2:2", false],
    ]);
  });

  it("marks a presence-derived takeover as a tenure boundary", () => {
    const items = timelineItems([
      event(1, "controller_presence_changed", "c2", { current: "taken_over", generation: 2 }),
    ]);

    expect(items[0]).toMatchObject({ boundary: true, segmentId: "c2:2" });
  });

  it("surfaces the raw growth axis present in the report", () => {
    const report: RunReport = {
      schema_version: "1.1",
      status: {},
      latest_events: [],
      metrics: {
        growth: { c1: { initial_population: 3, peak_population: 8, housing: 5 } },
      },
    };

    const series = metricSeries(report);

    expect(series.find(({ axis }) => axis === "growth")?.values).toEqual([
      { colonyId: "c1", metric: "initial_population", value: 3 },
      { colonyId: "c1", metric: "peak_population", value: 8 },
      { colonyId: "c1", metric: "housing", value: 5 },
    ]);
  });

  it("returns raw axes with explicit provenance and marks absent metrics unavailable", () => {
    const report: RunReport = {
      schema_version: "1.1",
      status: { terminal: true },
      latest_events: [],
      metrics: {
        survival: { c1: { turns: 12, population: 6 } },
        prosperity: { c1: { resources: { food: 8, wood: 3 } } },
        trade: { c1: 2 },
        aggression: { c1: 1 },
        decision_quality: { c1: { invalid_actions: 1 } },
        presence: { timeouts: { c1: 2 }, reconnects: { c1: 1 } },
        server_measured: { mcp_calls: { c1: 7 } },
        adapter_reported_model_usage: {
          c1: { input_tokens: 120, output_tokens: 35, latency_ms: 480 },
        },
      },
    };

    const series = metricSeries(report);

    expect(series.find(({ axis }) => axis === "diplomacy")?.values).toEqual([
      { colonyId: "c1", metric: "trade", value: 2 },
      { colonyId: "c1", metric: "aggression", value: 1 },
    ]);
    expect(series.find(({ axis }) => axis === "resilience")).toMatchObject({
      provenance: "unavailable",
      values: [],
    });
    expect(series.find(({ axis }) => axis === "action-validity")?.values).toEqual([
      { colonyId: "c1", metric: "invalid_actions", value: 1 },
    ]);
    expect(series.find(({ axis }) => axis === "server-mcp")).toMatchObject({
      provenance: "server-measured",
      values: [{ colonyId: "c1", metric: "mcp_calls", value: 7 }],
    });
    expect(series.find(({ axis }) => axis === "adapter-usage")).toMatchObject({
      provenance: "adapter-reported",
      values: [
        { colonyId: "c1", metric: "input_tokens", value: 120 },
        { colonyId: "c1", metric: "output_tokens", value: 35 },
        { colonyId: "c1", metric: "latency_ms", value: 480 },
      ],
    });
  });

  it("segments server and adapter usage by real controller tenure", () => {
    const report: RunReport = {
      schema_version: "1.1",
      status: {},
      latest_events: [],
      metrics: {
        tenure_metrics: {
          c1: [
            {
              ...tenure("c1", 1, { identity: { ...identity, display_name: "Alpha", provider: "openai", model: "gpt-5" } }),
              server_measured: { mcp_calls: 4, timeouts: 1, reconnects: 0 },
              adapter_reported_model_usage: { input_tokens: 100, output_tokens: 20, latency_ms: 300 },
            },
            {
              ...tenure("c1", 2, { identity: { ...identity, display_name: "Beta", provider: "anthropic", model: "claude" } }),
              server_measured: { mcp_calls: 2, timeouts: 0, reconnects: 1 },
              adapter_reported_model_usage: { input_tokens: 80, output_tokens: 10, latency_ms: 200 },
            },
          ],
        },
      },
    };

    const series = metricSeries(report);

    expect(series.find(({ axis }) => axis === "server-mcp")?.values).toEqual([
      { colonyId: "c1", segmentId: "c1:1", provider: "openai", model: "gpt-5", metric: "mcp_calls", value: 4 },
      { colonyId: "c1", segmentId: "c1:2", provider: "anthropic", model: "claude", metric: "mcp_calls", value: 2 },
    ]);
    expect(series.find(({ axis }) => axis === "adapter-usage")?.values.filter(({ metric }) => metric === "latency_ms")).toEqual([
      { colonyId: "c1", segmentId: "c1:1", provider: "openai", model: "gpt-5", metric: "latency_ms", value: 300 },
      { colonyId: "c1", segmentId: "c1:2", provider: "anthropic", model: "claude", metric: "latency_ms", value: 200 },
    ]);
  });
});

describe("OperationsController", () => {
  it("preserves operator selection across live metric updates", () => {
    const controller = new OperationsController();
    controller.applySnapshot(snapshot([slot("c1", "connected"), slot("c2", "thinking")]));
    controller.selectAgent("c2");
    controller.selectTab("cost");

    controller.applySnapshot(snapshot(
      [slot("c1", "connected"), slot("c2", "submitted")],
      [event(1, "metric_updated")],
    ));
    controller.setReport({
      schema_version: "1.1",
      status: {},
      latest_events: [],
      metrics: { adapter_reported_model_usage: { c2: { latency_ms: 25 } } },
    });

    expect(controller.state).toMatchObject({ selectedAgentId: "c2", selectedTab: "cost" });
    expect(controller.roster.find(({ colonyId }) => colonyId === "c2")?.latencyText).toBe("25 ms");
  });

  it("requests a resync instead of applying a sequence gap", () => {
    const onResync = vi.fn();
    const controller = new OperationsController({ onResync });
    controller.applySnapshot(snapshot([slot("c1", "connected")], [event(4, "turn_opened")]));
    const message: AdminWebSocketMessage = {
      schema_version: "1.1",
      type: "turn.resolved",
      payload: event(6, "turn_resolved"),
    };

    expect(controller.applyMessage(message)).toBe("resync");
    expect(onResync).toHaveBeenCalledWith({ expected: 5, received: 6 });
    expect(controller.timeline.map(({ sequence }) => sequence)).toEqual([4]);
  });

  it("merges truncated same-match snapshots and ignores stale sequence rollback", () => {
    const controller = new OperationsController();
    controller.applySnapshot(snapshot(
      [slot("c1", "connected")],
      [event(100, "turn_opened"), event(101, "controller_submitted", "c1")],
    ));
    controller.applySnapshot(snapshot(
      [slot("c1", "submitted")],
      [event(101, "controller_submitted", "c1"), event(102, "turn_resolved")],
    ));
    controller.applySnapshot(snapshot(
      [slot("c1", "connected")],
      [event(101, "controller_submitted", "c1")],
    ));

    expect(controller.timeline.map(({ sequence }) => sequence)).toEqual([100, 101, 102]);
    expect(controller.roster[0]?.state).toBe("submitted");
    expect(controller.applyMessage({
      schema_version: "1.1",
      type: "turn.opened",
      payload: event(103, "turn_opened"),
    })).toBe("applied");
  });

  it("opens each new turn with every colony pending until real submissions arrive", () => {
    const controller = new OperationsController();
    controller.applySnapshot({
      ...snapshot([slot("c1", "connected"), slot("c2", "connected")], [event(8, "turn_resolved")]),
      pending_colonies: [],
    });

    expect(controller.applyMessage({
      schema_version: "1.1",
      type: "turn.opened",
      payload: event(9, "turn_opened", null, { deadline_at: 1_060 }),
    })).toBe("applied");

    expect(controller.currentSnapshot?.pending_colonies).toEqual(["c1", "c2"]);
    expect(controller.currentSnapshot?.deadline_at).toBe(1_060);
  });

  it("synchronizes timeline focus to turn and agent and supports roster arrow movement", () => {
    const controller = new OperationsController();
    controller.applySnapshot(snapshot(
      [slot("c1", "connected"), slot("c2", "submitted")],
      [event(1, "turn_opened"), event(2, "controller_submitted", "c2")],
    ));

    controller.moveRosterSelection(1);
    expect(controller.state.selectedAgentId).toBe("c2");
    controller.selectTimeline(2);

    expect(controller.state).toMatchObject({ selectedAgentId: "c2", selectedTurn: 3, selectedSequence: 2 });
  });

  it("clears stale live selection when imported replay takes over the shell", () => {
    const controller = new OperationsController();
    controller.applySnapshot(snapshot([slot("c1", "connected")]));

    controller.reset("Replay mode uses imported authoritative frames.");

    expect(controller.roster).toEqual([]);
    expect(controller.timeline).toEqual([]);
    expect(controller.metrics).toEqual([]);
    expect(controller.state).toEqual({
      selectedAgentId: null,
      selectedTurn: null,
      selectedSequence: null,
      selectedTab: "decision",
      announcement: "Replay mode uses imported authoritative frames.",
    });
  });

  it("clears stale live selection when legacy development quick play takes over the shell", () => {
    const controller = new OperationsController();
    controller.applySnapshot(snapshot([slot("c1", "connected")], [event(1, "turn_opened")]));

    controller.reset("Development quick play does not expose the session operations stream.");

    expect(controller.roster).toEqual([]);
    expect(controller.timeline).toEqual([]);
    expect(controller.state.announcement).toBe("Development quick play does not expose the session operations stream.");
  });

  it("announces degraded live transport without clearing retained operations data", () => {
    const controller = new OperationsController();
    controller.applySnapshot(snapshot([slot("c1", "connected")], [event(1, "turn_opened")]));

    controller.announce("Operations live feed disconnected; retained data remains visible.");

    expect(controller.timeline).toHaveLength(1);
    expect(controller.roster).toHaveLength(1);
    expect(controller.state.announcement).toBe("Operations live feed disconnected; retained data remains visible.");
  });

  it("applies metric.updated messages to both the timeline and the report metrics", () => {
    const controller = new OperationsController();
    controller.applySnapshot(snapshot([slot("c1", "connected")], [event(1, "turn_opened")]));
    const message: AdminWebSocketMessage = {
      schema_version: "1.1",
      type: "metric.updated",
      payload: {
        event: event(2, "metric_updated"),
        metrics: { server_measured: { mcp_calls: { c1: 9 } } },
      },
    };

    expect(controller.applyMessage(message)).toBe("applied");
    expect(controller.timeline.map(({ sequence, kind }) => [sequence, kind])).toEqual([
      [1, "turn_opened"],
      [2, "metric_updated"],
    ]);
    expect(controller.metrics.find(({ axis }) => axis === "server-mcp")?.values).toEqual([
      { colonyId: "c1", metric: "mcp_calls", value: 9 },
    ]);
  });
});

describe("operations DOM", () => {
  it("renders hostile identity and event data as inert text without capabilities", () => {
    const hostile = `<img src=x onerror="globalThis.pwned=true">`;
    const root = document.createElement("section");
    const controller = new OperationsController();
    controller.applySnapshot(snapshot([
      slot("c1", "connected", {
        identity: { display_name: hostile, provider: "test", model: "model" },
      }),
    ], [event(1, "controller_connected", "c1", {
      note: "private reasoning",
      controller_token: "controller-token",
      admin_token: "admin-secret",
      digest: "digest",
    })]));

    renderOperationsRoom(root, controller);

    expect(root.querySelector("img")).toBeNull();
    expect(root.textContent).toContain(hostile);
    expect(root.textContent).not.toMatch(/private reasoning|controller-token|admin-secret|digest/i);
    expect((globalThis as typeof globalThis & { pwned?: boolean }).pwned).not.toBe(true);
  });

  it("exposes roving roster options, tabs, an ordered timeline and polite updates", () => {
    const root = document.createElement("section");
    const controller = new OperationsController();
    controller.applySnapshot(snapshot(
      [slot("c1", "connected"), slot("c2", "thinking")],
      [event(1, "turn_opened"), event(2, "controller_submitted", "c2")],
    ));
    controller.selectAgent("c2");

    renderOperationsRoom(root, controller);

    expect(root.querySelector("[aria-live='polite']")).not.toBeNull();
    expect(root.querySelectorAll("[role='option']")).toHaveLength(2);
    expect(root.querySelector("[role='option'][aria-selected='true']")?.getAttribute("tabindex")).toBe("0");
    expect(root.querySelectorAll("[role='tab']")).toHaveLength(4);
    expect(root.querySelector("[role='tabpanel']")?.getAttribute("aria-labelledby")).toBe("operations-tab-decision");
    expect([...root.querySelectorAll("[data-sequence]")].map((item) => item.getAttribute("data-sequence"))).toEqual(["1", "2"]);
    expect(root.querySelector("[data-sequence='1']")?.getAttribute("tabindex")).toBe("0");
    expect(root.querySelector("[data-sequence='1']")?.tagName).toBe("BUTTON");
  });

  it("marks real metric outputs as the single live-number motion primitive", () => {
    const root = document.createElement("section");
    const controller = new OperationsController();
    controller.setReport({
      schema_version: "1.1",
      status: {},
      latest_events: [],
      metrics: { server_measured: { mcp_calls: { c1: 3 } } },
    });

    renderOperationsRoom(root, controller);

    expect(root.querySelector("[data-live-number]")?.textContent).toBe("3");
  });

  it("keeps keyboard focus on the roster across live metric re-renders", () => {
    const root = document.createElement("section");
    document.body.append(root);
    let controller!: OperationsController;
    controller = new OperationsController({ onChange: () => renderOperationsRoom(root, controller) });
    controller.applySnapshot(snapshot([slot("c1", "connected"), slot("c2", "thinking")]));
    controller.selectAgent("c2");
    renderOperationsRoom(root, controller);
    bindOperationsRoom(root, controller);

    root.querySelector<HTMLElement>("[data-agent-id='c2']")!.focus();
    expect(document.activeElement?.getAttribute("data-agent-id")).toBe("c2");

    controller.setReport({
      schema_version: "1.1",
      status: {},
      latest_events: [],
      metrics: { adapter_reported_model_usage: { c2: { latency_ms: 25 } } },
    });

    expect(document.activeElement?.getAttribute("data-agent-id")).toBe("c2");
  });

  it("surfaces tenure takeover boundaries on roster rows", () => {
    const root = document.createElement("section");
    const controller = new OperationsController();
    controller.applySnapshot(snapshot(
      [slot("c1", "connected", { generation: 2 })],
      [],
      { c1: [tenure("c1", 1), tenure("c1", 2)] },
    ));

    renderOperationsRoom(root, controller);

    expect(root.querySelector("[data-agent-id='c1']")?.hasAttribute("data-tenure-boundary")).toBe(true);
  });

  it("keeps empty-state messages outside the listbox", () => {
    const root = document.createElement("section");
    const controller = new OperationsController();

    renderOperationsRoom(root, controller);

    const listbox = root.querySelector("[role='listbox']");
    expect(listbox).not.toBeNull();
    expect(listbox?.querySelector("p")).toBeNull();
    expect(root.textContent).toContain("No sanitized controller snapshot yet.");
  });

  it("moves roster and tab focus with arrow keys", async () => {
    const root = document.createElement("section");
    document.body.append(root);
    let controller!: OperationsController;
    controller = new OperationsController({ onChange: () => renderOperationsRoom(root, controller) });
    controller.applySnapshot(snapshot([slot("c1", "connected"), slot("c2", "thinking")]));
    renderOperationsRoom(root, controller);
    bindOperationsRoom(root, controller);

    const first = root.querySelector<HTMLElement>("[data-agent-id='c1']")!;
    first.focus();
    first.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    await Promise.resolve();
    expect(controller.state.selectedAgentId).toBe("c2");
    expect(document.activeElement?.getAttribute("data-agent-id")).toBe("c2");

    const decision = root.querySelector<HTMLElement>("[data-tab='decision']")!;
    decision.focus();
    decision.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    await Promise.resolve();
    expect(controller.state.selectedTab).toBe("resources");
    expect(document.activeElement?.getAttribute("data-tab")).toBe("resources");

    root.querySelector<HTMLElement>("[data-tab='cost']")!.click();
    await Promise.resolve();
    expect(document.activeElement?.getAttribute("data-tab")).toBe("cost");

    const timelineRoot = document.createElement("section");
    document.body.append(timelineRoot);
    const timelineController = new OperationsController({ onChange: () => renderOperationsRoom(timelineRoot, timelineController) });
    timelineController.applySnapshot(snapshot(
      [slot("c1", "connected")],
      [event(1, "turn_opened"), event(2, "controller_submitted", "c1")],
    ));
    bindOperationsRoom(timelineRoot, timelineController);
    const timeline = timelineRoot.querySelector<HTMLElement>("[data-sequence='1']")!;
    timeline.focus();
    timeline.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    await Promise.resolve();
    expect(timelineController.state.selectedSequence).toBe(2);
    expect(document.activeElement?.getAttribute("data-sequence")).toBe("2");
  });
});

describe("live source guard", () => {
  it("drops queued messages from a superseded operations socket", () => {
    const first = new EventTarget() as WebSocket;
    const second = new EventTarget() as WebSocket;
    let current: WebSocket | null = first;
    const receive = vi.fn();
    const handler = currentSourceMessageHandler(first, () => current, receive);
    const message = new MessageEvent("message", { data: "{}" });

    handler(message);
    current = second;
    handler(message);

    expect(receive).toHaveBeenCalledTimes(1);
  });
});

describe("world view projection", () => {
  it("clamps touch zoom and keeps pan offsets until reset", () => {
    expect(nextWorldView({ scale: 1, x: 0, y: 0 }, { kind: "zoom", delta: 2 })).toEqual({
      scale: 1.6,
      x: 0,
      y: 0,
    });
    expect(nextWorldView({ scale: 1, x: 0, y: 0 }, { kind: "pan", x: 24, y: -24 })).toEqual({
      scale: 1,
      x: 24,
      y: -24,
    });
    expect(nextWorldView({ scale: 1.4, x: 24, y: -24 }, { kind: "reset" })).toEqual({
      scale: 1,
      x: 0,
      y: 0,
    });
  });
});

describe("decision feed", () => {
  const decisions = [
    { colony_id: "c1", actions: [{ kind: "wait" }], results: [{ kind: "wait", status: "accepted", code: "ok" }] },
    { colony_id: "c2", actions: [{ kind: "gather", x: 0, y: 0 }], results: [{ kind: "gather", status: "rejected", code: "cell_not_visible" }] },
  ];

  it("reports each colony's actions in order with rejection reasons", () => {
    const items = decisionFeedItems(snapshot(
      [
        slot("c1", "connected", { identity: { ...identity, display_name: "Claude" } }),
        slot("c2", "connected", { identity: { ...identity, display_name: "codex-agent" } }),
      ],
      [event(9, "turn_resolved", null, { decisions })],
    ));

    expect(items.map(({ colonyId, displayName, actions }) => [colonyId, displayName, actions])).toEqual([
      ["c1", "Claude", ["wait"]],
      ["c2", "codex-agent", ["gather (0, 0)"]],
    ]);
    expect(items[0]!.results).toEqual([{ status: "accepted", detail: "ok" }]);
    expect(items[1]!.results).toEqual([{ status: "rejected", detail: "cell_not_visible" }]);
  });

  it("falls back to the colony id when no display name is known", () => {
    const items = decisionFeedItems(snapshot(
      [slot("c1", "connected", { identity: null })],
      [event(1, "turn_resolved", null, { decisions: [decisions[0]] })],
    ));

    expect(items[0]!.displayName).toBe("c1");
  });

  it("renders the feed as inert text without leaking capability-shaped keys", () => {
    const root = document.createElement("section");
    const controller = new OperationsController();
    controller.applySnapshot(snapshot(
      [slot("c1", "connected", { identity: { ...identity, display_name: "Claude" } })],
      [event(1, "turn_resolved", null, {
        decisions: [{
          ...decisions[0],
          actions: [{ kind: "gather", x: 0, y: 0, controller_token: "secret", admin_token: "secret" }],
        }],
      })],
    ));

    renderOperationsRoom(root, controller);

    expect(root.querySelector(".decision-feed")).not.toBeNull();
    expect(root.textContent).toContain("Claude");
    expect(root.textContent).toContain("accepted");
    expect(root.textContent).not.toContain("secret");
  });

  it("describes repair, extinguish, and demolish actions with structure ids", () => {
    const actions = [
      { kind: "repair", structure_id: "s123" },
      { kind: "extinguish", structure_id: "s456" },
      { kind: "demolish", structure_id: "s789" },
    ];
    const items = decisionFeedItems(snapshot(
      [slot("c1", "connected", { identity: { ...identity, display_name: "Claude" } })],
      [event(1, "turn_resolved", null, {
        decisions: [{
          colony_id: "c1",
          actions,
          results: actions.map((a) => ({ status: "accepted", code: "ok" })),
        }],
      })],
    ));

    expect(items[0]!.actions).toEqual(["repair s123", "extinguish s456", "demolish s789"]);
  });

  it("translates structure action descriptions in both languages", () => {
    const root = document.createElement("section");
    const controller = new OperationsController();
    const actions = [{ kind: "repair", structure_id: "s1" }];
    controller.applySnapshot(snapshot(
      [slot("c1", "connected", { identity: { ...identity, display_name: "Test" } })],
      [event(1, "turn_resolved", null, {
        decisions: [{
          colony_id: "c1",
          actions,
          results: [{ status: "accepted", code: "ok" }],
        }],
      })],
    ));

    setLanguage("en");
    renderOperationsRoom(root, controller);
    expect(root.textContent).toContain("repair s1");

    setLanguage("tr");
    renderOperationsRoom(root, controller);
    expect(root.textContent).toContain("s1 onarımı");
  });
});
