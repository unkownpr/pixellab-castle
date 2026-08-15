import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  currentLanguage,
  initLanguage,
  messages,
  setLanguage,
  translate,
  translateStatic,
  type TranslationKey,
} from "../src/i18n";
import { matchStatePresentation, updateMatchStateIndicator } from "../src/matchState";
import { OperationsController, renderOperationsRoom } from "../src/operations";

function installLocalStorage(): void {
  const store = new Map<string, string>();
  const storage: Storage = {
    get length() { return store.size; },
    clear: () => store.clear(),
    getItem: (key) => store.get(key) ?? null,
    key: (index) => [...store.keys()][index] ?? null,
    removeItem: (key) => { store.delete(key); },
    setItem: (key, value) => { store.set(key, String(value)); },
  };
  Object.defineProperty(window, "localStorage", { value: storage, configurable: true });
}

beforeEach(() => {
  installLocalStorage();
});

afterEach(() => {
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

describe("translation dictionary", () => {
  it("has a non-empty value for every key in both languages", () => {
    const keys = Object.keys(messages.en) as TranslationKey[];

    for (const key of keys) {
      expect(messages.en[key], `missing English value for ${key}`).toBeTruthy();
      expect(messages.tr[key], `missing Turkish value for ${key}`).toBeTruthy();
    }
    expect(Object.keys(messages.tr).sort()).toEqual(Object.keys(messages.en).sort());
  });

  it("translates rather than transliterates key operator labels", () => {
    expect(translate("timeline.title")).toBe("Servis günlüğü");
    setLanguage("en");
    expect(translate("timeline.title")).toBe("Service log");
  });
});

describe("language switching", () => {
  it("changes rendered strings when the language changes", () => {
    const root = document.createElement("section");
    const controller = new OperationsController();

    setLanguage("tr");
    renderOperationsRoom(root, controller);
    expect(root.textContent).toContain("Ajan kadrosu");
    expect(root.textContent).toContain("Servis günlüğü");

    setLanguage("en");
    renderOperationsRoom(root, controller);
    expect(root.textContent).toContain("Agent roster");
    expect(root.textContent).toContain("Service log");
  });

  it("replaces static data-i18n text and aria-labels", () => {
    document.body.innerHTML =
      '<span data-i18n="setup.title">x</span><button data-i18n-aria-label="map.reset" aria-label="x"></button>';

    setLanguage("tr");
    translateStatic(document);
    expect(document.querySelector("span")?.textContent).toBe("Operasyonu kur");
    expect(document.querySelector("button")?.getAttribute("aria-label")).toBe("Harita görünümünü sıfırla");

    setLanguage("en");
    translateStatic(document);
    expect(document.querySelector("span")?.textContent).toBe("Set up the operation");
    expect(document.querySelector("button")?.getAttribute("aria-label")).toBe("Reset map view");
  });

  it("persists the chosen language across a reload", async () => {
    setLanguage("en");
    expect(currentLanguage()).toBe("en");
    expect(document.documentElement.lang).toBe("en");

    vi.resetModules();
    const fresh = await import("../src/i18n");
    fresh.initLanguage();

    expect(fresh.currentLanguage()).toBe("en");
    expect(document.documentElement.lang).toBe("en");
  });
});

describe("metrics legibility", () => {
  it("never shows raw provenance slugs to the operator", () => {
    const controller = new OperationsController();
    controller.setReport({
      schema_version: "1.1",
      status: {},
      latest_events: [],
      metrics: {
        survival: { c1: { turns: 12, population: 6 } },
        presence: { timeouts: { c1: 2 }, reconnects: { c1: 1 } },
        server_measured: { mcp_calls: { c1: 7 } },
        adapter_reported_model_usage: { c1: { input_tokens: 120, output_tokens: 35, latency_ms: 480 } },
      },
    });
    const root = document.createElement("section");

    setLanguage("tr");
    renderOperationsRoom(root, controller);

    const text = root.textContent ?? "";
    expect(text).not.toMatch(/simulation-raw|server-measured|adapter-reported/);
    expect(text).not.toContain("unavailable as a raw axis");
    expect(text).toContain("Dayanıklılık");
    expect(text).toContain("Sunucu ölçtü.");
    expect(text).toContain("özbildirim");
  });
});

describe("match-state indicator", () => {
  function mountIndicator(): void {
    document.body.innerHTML = `
      <div id="match-state" role="status" data-phase="idle">
        <span class="status-shape" data-status-shape="dash" aria-hidden="true"></span>
        <span id="match-state-label"></span>
      </div>`;
  }

  it("reflects waiting, running and finished", () => {
    mountIndicator();
    setLanguage("en");

    updateMatchStateIndicator(document, "waiting");
    expect(document.querySelector("#match-state-label")?.textContent).toContain("Waiting for agents");
    expect(document.querySelector("#match-state")?.getAttribute("data-phase")).toBe("waiting");
    expect(matchStatePresentation("waiting").shape).toBe("bar");

    updateMatchStateIndicator(document, "running");
    expect(document.querySelector("#match-state-label")?.textContent).toContain("Running");
    expect(matchStatePresentation("running").shape).toBe("circle");

    updateMatchStateIndicator(document, "finished");
    expect(document.querySelector("#match-state-label")?.textContent).toContain("Finished");
    expect(matchStatePresentation("finished").shape).toBe("square");
  });

  it("follows the active language", () => {
    mountIndicator();
    setLanguage("tr");
    updateMatchStateIndicator(document, "finished");
    expect(document.querySelector("#match-state-label")?.textContent).toContain("Bitti");
  });
});
