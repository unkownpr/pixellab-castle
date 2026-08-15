import type { DiplomacyProposal, Message } from "./api";
import { translate } from "./i18n";

/** Terminal reasons the service can report, mapped to their translated labels. */
const TERMINAL_REASON_KEYS = {
  monument_victory: "terminal.monumentVictory",
  domination_victory: "terminal.dominationVictory",
  turn_limit: "terminal.turnLimit",
  extinction: "terminal.extinction",
} as const;

export function terminationReason(reason: unknown): string {
  const key = TERMINAL_REASON_KEYS[String(reason) as keyof typeof TERMINAL_REASON_KEYS];
  return key ? translate(key) : String(reason ?? "terminal");
}

export function renderInboxInto(host: Element, messages: readonly Message[]): void {
  if (!messages.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = translate("inbox.empty");
    host.replaceChildren(empty);
    return;
  }
  const list = document.createElement("ol");
  list.className = "inbox-list";
  for (const message of messages) {
    const item = document.createElement("li");
    const meta = document.createElement("span");
    meta.className = "inbox-meta";
    meta.textContent = [
      `T${message.turn}`,
      translate("inbox.messageFrom", { colony: message.from_colony_id }),
      translate("inbox.channel", { channel: message.channel }),
    ].join(" · ");
    // The body is text another colony wrote. It goes in as text, never as markup, and
    // it is quoted so the operator reads it as someone's claim rather than as something
    // the simulation is asserting.
    const body = document.createElement("q");
    body.className = "inbox-text";
    body.textContent = message.text;
    item.append(meta, body);
    list.append(item);
  }
  host.replaceChildren(list);
}

export function renderProposalsInto(
  host: Element,
  proposals: readonly DiplomacyProposal[],
  viewerColonyId: string,
  onRespond: (proposalId: string, accept: boolean) => void,
): void {
  if (!proposals.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = translate("proposals.empty");
    host.replaceChildren(empty);
    return;
  }
  const list = document.createElement("ul");
  list.className = "proposal-list";
  for (const proposal of proposals) {
    const item = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = [
      translate(proposal.operation === "alliance" ? "proposals.alliance" : "proposals.peace", {
        source: proposal.source_colony_id,
      }),
      translate("proposals.expires", { turn: proposal.expires_turn }),
    ].join(" · ");
    item.append(label);
    // Only the side that was asked can answer; the proposer sees the same row without
    // controls, which is what tells them the offer is still outstanding.
    if (proposal.target_colony_id === viewerColonyId) {
      for (const [accept, key] of [[true, "proposals.accept"], [false, "proposals.decline"]] as const) {
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.proposalResponse = accept ? "accept" : "decline";
        button.textContent = translate(key);
        button.addEventListener("click", () => onRespond(proposal.id, accept));
        item.append(button);
      }
    }
    list.append(item);
  }
  host.replaceChildren(list);
}
