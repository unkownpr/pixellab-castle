import { afterEach, describe, expect, it, vi } from "vitest";

import { BenchmarkApi, type LobbySnapshot, type PairingGrant } from "../src/api";
import {
  LobbyController,
  lobbyRows,
  pairingInstructions,
  renderLobby,
  renderPairingGrant,
  setHumanActionControlsEnabled,
  type LobbyApi,
} from "../src/lobby";

const externalSlot = {
  colony_id: "c1",
  controller_type: "external" as const,
  controller_id: null,
  identity: null,
  presence: "unassigned",
  baseline_kind: null,
  generation: 0,
  pairing_active: false,
  pairing_expires_at: null,
  pairing_consumed: false,
  pairing_attempts: 0,
  last_heartbeat_at: null,
  last_heartbeat_turn: null,
};

function snapshot(slots: LobbySnapshot["slots"], status = "draft"): LobbySnapshot {
  return {
    schema_version: "1.1",
    match_id: "match-1",
    scenario_id: "basic-survival-v1",
    seed: 17,
    colony_count: slots.length,
    deadline_seconds: 30,
    status,
    slots,
  };
}

afterEach(() => {
  document.body.replaceChildren();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("lobby projections", () => {
  it("keeps lobby controls independent from human in-match action availability", () => {
    const actionGrid = document.createElement("div");
    actionGrid.id = "action-grid";
    const action = document.createElement("button");
    action.dataset.action = "wait";
    actionGrid.append(action);
    const lobby = document.createElement("section");
    lobby.id = "lobby-root";
    const configure = document.createElement("button");
    configure.dataset.action = "configure";
    lobby.append(configure);
    document.body.append(actionGrid, lobby);

    setHumanActionControlsEnabled(false);

    expect(action.disabled).toBe(true);
    expect(configure.disabled).toBe(false);
  });

  it("distinguishes ready human/baseline slots from external pairing states", () => {
    const rows = lobbyRows(snapshot([
      { ...externalSlot, colony_id: "c1", controller_type: "human", presence: "ready" },
      { ...externalSlot, colony_id: "c2", controller_type: "baseline", presence: "ready", baseline_kind: "survivalist" },
      { ...externalSlot, colony_id: "c3", pairing_active: true, pairing_expires_at: 1_100 },
      {
        ...externalSlot,
        colony_id: "c4",
        controller_id: "controller-4",
        presence: "connected",
        last_heartbeat_at: 1_050,
        last_heartbeat_turn: 0,
      },
    ]), 1_060);

    expect(rows.map(({ state, ready }) => [state, ready])).toEqual([
      ["ready", true],
      ["ready", true],
      ["pairing", false],
      ["ready", true],
    ]);
  });

  it("marks expired and disconnected external slots as requiring attention", () => {
    const rows = lobbyRows(snapshot([
      { ...externalSlot, colony_id: "c1", pairing_expires_at: 999 },
      {
        ...externalSlot,
        colony_id: "c2",
        controller_id: "controller-2",
        presence: "disconnected",
        last_heartbeat_at: 990,
      },
    ]), 1_000);

    expect(rows.map(({ state, statusText }) => [state, statusText])).toEqual([
      ["expired", "Pairing expired"],
      ["attention", "Disconnected — choose a fallback or pair again"],
    ]);
  });

  it("enables explicit start only when every slot is ready", () => {
    const waiting = renderLobby(snapshot([
      { ...externalSlot, colony_id: "c1", controller_type: "human", presence: "ready" },
      { ...externalSlot, colony_id: "c2" },
    ]));
    const ready = renderLobby(snapshot([
      { ...externalSlot, colony_id: "c1", controller_type: "human", presence: "ready" },
      { ...externalSlot, colony_id: "c2", controller_type: "baseline", presence: "ready", baseline_kind: "random_valid" },
    ]));

    expect(waiting.querySelector<HTMLButtonElement>("[data-action='start']")?.disabled).toBe(true);
    expect(waiting.querySelector("[data-readiness]")?.textContent).toContain("1 slot waiting");
    expect(ready.querySelector<HTMLButtonElement>("[data-action='start']")?.disabled).toBe(false);
    expect(ready.querySelector("[data-readiness]")?.textContent).toBe("All slots ready — start explicitly when prepared");
  });

  it("renders hostile controller identity as inert text", () => {
    const hostile = `<img src=x onerror="globalThis.pwned=true">`;
    const view = renderLobby(snapshot([{
      ...externalSlot,
      controller_id: "controller-1",
      identity: { display_name: hostile, provider: "test", model: "model" },
      presence: "connected",
      last_heartbeat_at: 1,
    }]));

    expect(view.querySelector("img")).toBeNull();
    expect(view.textContent).toContain(hostile);
    expect((globalThis as typeof globalThis & { pwned?: boolean }).pwned).not.toBe(true);
  });
});

describe("pairing grant", () => {
  const grant: PairingGrant = {
    schema_version: "1.1",
    match_id: "match-1",
    colony_id: "c2",
    pairing_code: "PAIR-ONLY-SECRET",
    expires_at: 1_600,
  };

  it.each(["codex", "claude", "opencode", "generic"] as const)(
    "builds secure %s provider instructions",
    (provider) => {
      const instructions = pairingInstructions(grant, provider, "https://castle.example/mcp");

      expect(instructions).toContain("benchmark.claim_slot");
      expect(instructions).toContain("benchmark.heartbeat");
      expect(instructions).toContain("PAIR-ONLY-SECRET");
      expect(instructions).toContain("https://castle.example/mcp");
      expect(instructions).not.toMatch(/admin_token|controller_token|orchestrator_token|digest/i);
    },
  );

  it("shows the one-time code only in its explicit grant panel with absolute expiry", () => {
    const view = renderPairingGrant(grant, "codex", "https://castle.example/mcp", 1_540);

    expect(view.textContent).toContain("PAIR-ONLY-SECRET");
    expect(view.querySelector("[data-pairing-countdown]")?.textContent).toBe("Expires in 01:00");
    expect(view.querySelector("[data-pairing-countdown]")?.getAttribute("data-expires-at")).toBe("1600");
    expect(view.querySelectorAll("button[data-copy]")).toHaveLength(3);
  });

  it("does not leak the grant code into the sanitized lobby roster", () => {
    const view = renderLobby(snapshot([{
      ...externalSlot,
      pairing_active: true,
      pairing_expires_at: grant.expires_at,
    }]));

    expect(view.textContent).not.toContain(grant.pairing_code);
  });
});

describe("typed session client", () => {
  it("uses bearer headers for lobby operations and never puts capabilities in URLs", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        schema_version: "1.1",
        match_id: "match-1",
        scenario_id: "basic-survival-v1",
        status: "draft",
        admin_token: "admin-secret",
      }), { status: 201, headers: { "content-type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify(snapshot([])), {
        status: 200,
        headers: { "content-type": "application/json" },
      }));
    vi.stubGlobal("fetch", fetchMock);
    const api = new BenchmarkApi("https://castle.example");

    await api.createSession({
      scenario_id: "basic-survival-v1",
      seed: 17,
      colony_count: 2,
      deadline_seconds: 30,
      slots: [],
    }, "orchestrator-secret");
    await api.lobby("match-1", "admin-secret");

    expect(fetchMock.mock.calls[0]?.[0]).toBe("https://castle.example/api/sessions");
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(expect.objectContaining({
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer orchestrator-secret",
      },
    }));
    expect(fetchMock.mock.calls[1]?.[0]).toBe("https://castle.example/api/sessions/match-1/lobby");
    expect(JSON.stringify(fetchMock.mock.calls.map(([url]) => url))).not.toContain("secret");
  });

  it("passes the single-use operations ticket as a websocket subprotocol, not a URL value", () => {
    const socket = {} as WebSocket;
    const socketConstructor = vi.fn((_url: string, _protocols?: string | string[]) => socket);
    const api = new BenchmarkApi("https://castle.example");

    expect(api.openOperationsSocket("match/1", "ticket-secret", socketConstructor)).toBe(socket);
    expect(socketConstructor).toHaveBeenCalledWith(
      "wss://castle.example/api/matches/match%2F1/operations/ws",
      ["castle.operations", "ticket-secret"],
    );
    expect(String(socketConstructor.mock.calls[0]?.[0])).not.toContain("ticket-secret");
  });
});

describe("LobbyController", () => {
  it("removes a one-time pairing code after the external slot consumes it", async () => {
    const root = document.createElement("div");
    const lobby = vi.fn()
      .mockResolvedValueOnce(snapshot([{ ...externalSlot }]))
      .mockResolvedValueOnce(snapshot([{
        ...externalSlot,
        controller_id: "controller-1",
        pairing_consumed: true,
        presence: "connected",
        last_heartbeat_at: 1,
      }]));
    const api = {
      createSession: vi.fn().mockResolvedValue({
        schema_version: "1.1",
        match_id: "match-1",
        scenario_id: "basic-survival-v1",
        status: "draft",
        admin_token: "admin-secret",
      }),
      lobby,
      createPairing: vi.fn().mockResolvedValue({
        schema_version: "1.1",
        match_id: "match-1",
        colony_id: "c1",
        pairing_code: "PAIR-ONCE",
        expires_at: Date.now() / 1_000 + 600,
      }),
    } as unknown as LobbyApi;
    const controller = new LobbyController(root, api);

    await controller.create({
      scenario_id: "basic-survival-v1",
      seed: 17,
      colony_count: 1,
      deadline_seconds: 30,
      slots: [],
    });
    await controller.pair("c1");
    expect(root.textContent).toContain("PAIR-ONCE");

    await controller.refresh();

    expect(root.textContent).not.toContain("PAIR-ONCE");
    controller.dispose();
  });

  it("hands off a newly requested human takeover without retaining it in DOM", async () => {
    const root = document.createElement("div");
    const running = snapshot([{ ...externalSlot }], "running");
    const humanRunning = snapshot([{
      ...externalSlot,
      controller_type: "human",
      presence: "taken_over",
    }], "running");
    const api = {
      createSession: vi.fn().mockResolvedValue({
        schema_version: "1.1",
        match_id: "match-1",
        scenario_id: "basic-survival-v1",
        status: "draft",
        admin_token: "admin-secret",
      }),
      lobby: vi.fn().mockResolvedValueOnce(running).mockResolvedValueOnce(humanRunning),
      replaceSlot: vi.fn().mockResolvedValue({
        schema_version: "1.1",
        match_id: "match-1",
        colony_id: "c1",
        status: "taken_over",
      }),
      humanCapability: vi.fn().mockResolvedValue({
        schema_version: "1.1",
        match_id: "match-1",
        colony_id: "c1",
        controller_token: "takeover-secret",
      }),
    } as unknown as LobbyApi;
    const started = vi.fn();
    const controller = new LobbyController(root, api, { onStarted: started });
    await controller.create({
      scenario_id: "basic-survival-v1",
      seed: 17,
      colony_count: 1,
      deadline_seconds: 30,
      slots: [],
    });

    await controller.replace("c1", "human");

    expect(api.replaceSlot).toHaveBeenCalledWith("match-1", "c1", "admin-secret", {
      replacement: "human",
      baseline_kind: null,
    });
    expect(started).toHaveBeenCalledWith({
      matchId: "match-1",
      colonyId: "c1",
      controllerToken: "takeover-secret",
    });
    expect(root.textContent).not.toContain("takeover-secret");
    controller.dispose();
  });

  it("opens the sanitized operations stream with a fresh single-use ticket", async () => {
    const root = document.createElement("div");
    const socket = { addEventListener: vi.fn(), close: vi.fn() } as unknown as WebSocket;
    const api = {
      createSession: vi.fn().mockResolvedValue({
        schema_version: "1.1",
        match_id: "match-1",
        scenario_id: "basic-survival-v1",
        status: "draft",
        admin_token: "admin-secret",
      }),
      lobby: vi.fn().mockResolvedValue(snapshot([{ ...externalSlot }])),
      operationsTicket: vi.fn().mockResolvedValue({
        schema_version: "1.1",
        match_id: "match-1",
        websocket_ticket: "ticket-secret",
        expires_at: 1_030,
      }),
      openOperationsSocket: vi.fn().mockReturnValue(socket),
    } as unknown as LobbyApi;
    const controller = new LobbyController(root, api);

    await controller.create({
      scenario_id: "basic-survival-v1",
      seed: 17,
      colony_count: 1,
      deadline_seconds: 30,
      slots: [],
    }, "orchestrator-secret");

    expect(api.operationsTicket).toHaveBeenCalledWith("match-1", "admin-secret");
    expect(api.openOperationsSocket).toHaveBeenCalledWith("match-1", "ticket-secret");
    expect(root.textContent).not.toContain("ticket-secret");
    controller.dispose();
  });

  it("keeps admin and human capabilities in memory and out of rendered DOM", async () => {
    const root = document.createElement("div");
    document.body.append(root);
    const readySnapshot = snapshot([{
      ...externalSlot,
      controller_type: "human",
      presence: "ready",
    }]);
    const api = {
      createSession: vi.fn().mockResolvedValue({
        schema_version: "1.1",
        match_id: "match-1",
        scenario_id: "basic-survival-v1",
        status: "draft",
        admin_token: "admin-secret",
      }),
      lobby: vi.fn().mockResolvedValue(readySnapshot),
      startSession: vi.fn().mockResolvedValue({ schema_version: "1.1", match_id: "match-1", status: "running" }),
      humanCapability: vi.fn().mockResolvedValue({
        schema_version: "1.1",
        match_id: "match-1",
        colony_id: "c1",
        controller_token: "human-secret",
      }),
    } as unknown as LobbyApi;
    const started = vi.fn();
    const controller = new LobbyController(root, api, { onStarted: started });

    await controller.create({
      scenario_id: "basic-survival-v1",
      seed: 17,
      colony_count: 1,
      deadline_seconds: 30,
      slots: [],
    }, "orchestrator-secret");
    await controller.start();

    expect(started).toHaveBeenCalledWith({ matchId: "match-1", colonyId: "c1", controllerToken: "human-secret" });
    expect(root.textContent).not.toMatch(/admin-secret|human-secret|orchestrator-secret/);
    expect(JSON.stringify(root.dataset)).not.toMatch(/admin-secret|human-secret|orchestrator-secret/);
  });
});
