import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DiplomacyProposal, Message } from "../src/api";
import { renderInboxInto, renderProposalsInto, terminationReason } from "../src/intel";
import { setLanguage } from "../src/i18n";

const message = (overrides: Partial<Message> = {}): Message => ({
  turn: 4,
  from_colony_id: "c2",
  channel: "direct",
  text: "Grain for stone?",
  ...overrides,
});

const proposal = (overrides: Partial<DiplomacyProposal> = {}): DiplomacyProposal => ({
  id: "p1",
  source_colony_id: "c2",
  target_colony_id: "c1",
  operation: "alliance",
  message: "",
  expires_turn: 9,
  ...overrides,
});

describe("inbox", () => {
  beforeEach(() => {
    setLanguage("en");
    document.body.innerHTML = "<div id='host'></div>";
  });

  it("says so plainly when nothing has arrived", () => {
    const host = document.querySelector("#host")!;

    renderInboxInto(host, []);

    expect(host.textContent).toBe("No messages.");
  });

  it("shows who wrote a message, on which turn, over which channel", () => {
    const host = document.querySelector("#host")!;

    renderInboxInto(host, [message()]);

    expect(host.querySelectorAll("li")).toHaveLength(1);
    expect(host.textContent).toContain("T4");
    expect(host.textContent).toContain("c2");
    expect(host.textContent).toContain("Grain for stone?");
  });

  it("renders a message as text, so a colony cannot inject markup into the room", () => {
    const host = document.querySelector("#host")!;

    renderInboxInto(host, [message({ text: "<img src=x onerror=alert(1)>" })]);

    expect(host.querySelector("img")).toBeNull();
    expect(host.textContent).toContain("<img src=x onerror=alert(1)>");
  });

  it("translates its empty state", () => {
    setLanguage("tr");
    const host = document.querySelector("#host")!;

    renderInboxInto(host, []);

    expect(host.textContent).toBe("Mesaj yok.");
  });
});

describe("proposals", () => {
  beforeEach(() => {
    setLanguage("en");
    document.body.innerHTML = "<div id='host'></div>";
  });

  it("offers accept and decline to the colony that was asked", () => {
    const host = document.querySelector("#host")!;
    const onRespond = vi.fn();

    renderProposalsInto(host, [proposal()], "c1", onRespond);
    host.querySelector<HTMLButtonElement>("[data-proposal-response='accept']")!.click();

    expect(onRespond).toHaveBeenCalledWith("p1", true);
  });

  it("gives the proposer no controls over its own offer", () => {
    const host = document.querySelector("#host")!;

    renderProposalsInto(host, [proposal()], "c2", vi.fn());

    expect(host.querySelectorAll("button")).toHaveLength(0);
    expect(host.textContent).toContain("c2");
  });

  it("declines through the same callback", () => {
    const host = document.querySelector("#host")!;
    const onRespond = vi.fn();

    renderProposalsInto(host, [proposal({ operation: "peace" })], "c1", onRespond);
    host.querySelector<HTMLButtonElement>("[data-proposal-response='decline']")!.click();

    expect(onRespond).toHaveBeenCalledWith("p1", false);
  });
});

describe("termination reasons", () => {
  it("names every ending the service can report, in both languages", () => {
    setLanguage("en");
    expect(terminationReason("monument_victory")).toBe("monument victory");
    expect(terminationReason("domination_victory")).toBe("domination victory");
    expect(terminationReason("turn_limit")).toBe("turn limit");

    setLanguage("tr");
    expect(terminationReason("monument_victory")).toBe("anıt zaferi");
    expect(terminationReason("extinction")).toBe("tükeniş");
  });

  it("passes an unknown reason through rather than hiding it", () => {
    setLanguage("en");
    expect(terminationReason("something_new")).toBe("something_new");
  });
});
