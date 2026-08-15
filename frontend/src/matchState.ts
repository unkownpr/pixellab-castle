import { translate, type TranslationKey } from "./i18n";

export type MatchPhase = "idle" | "waiting" | "running" | "finished";

const PHASE_SHAPE: Readonly<Record<MatchPhase, string>> = {
  idle: "dash",
  waiting: "bar",
  running: "circle",
  finished: "square",
};

const PHASE_LABEL: Readonly<Record<MatchPhase, TranslationKey>> = {
  idle: "matchState.idle",
  waiting: "matchState.waiting",
  running: "matchState.running",
  finished: "matchState.finished",
};

export interface MatchStatePresentation {
  readonly shape: string;
  readonly label: string;
}

export function matchStatePresentation(phase: MatchPhase): MatchStatePresentation {
  return { shape: PHASE_SHAPE[phase], label: translate(PHASE_LABEL[phase]) };
}

export function updateMatchStateIndicator(root: ParentNode, phase: MatchPhase): void {
  const host = root.querySelector<HTMLElement>("#match-state");
  if (!host) return;
  const presentation = matchStatePresentation(phase);
  host.dataset.phase = phase;
  const shape = host.querySelector<HTMLElement>("[data-status-shape]");
  if (shape) shape.dataset.statusShape = presentation.shape;
  const label = host.querySelector<HTMLElement>("#match-state-label");
  if (label) label.textContent = presentation.label;
}
