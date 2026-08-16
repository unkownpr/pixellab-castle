import { staticFile } from "remotion";

export type Cell = { x: number; y: number; w: 0 | 1; r: string };

export type StructureFrame = {
  id: string;
  c: string;
  k: string;
  s: string;
  x: number;
  y: number;
};

export type Frame = {
  turn: number;
  structures: StructureFrame[];
  colonies: Record<string, { pop: number; food: number; water: number; known: number }>;
};

export type Replay = {
  scenario: string;
  seed: number;
  width: number;
  height: number;
  biome: string;
  cells: Cell[];
  frames: Frame[];
  sprites: Record<string, { file: string; size: [number, number] }>;
  suite?: {
    seeds: number[];
    rotations: number;
    controllers: Record<string, { composite: number; n: number }>;
  };
};

import replayJson from "../public/replay.json";

export const replay = replayJson as unknown as Replay;

/** The sprite bound to a structure, falling back the way the client does. */
export function structureSprite(kind: string, status: string): string | null {
  const ruined = replay.sprites["structure.generic.ruined"];
  if (status === "ruined" && ruined) return staticFile(`sprites/${ruined.file}`);
  const exact =
    replay.sprites[`structure.${kind}.operational`] ??
    replay.sprites[`structure.${kind}.grass.operational`];
  return exact ? staticFile(`sprites/${exact.file}`) : null;
}

export function effectSprite(key: string): string | null {
  const entry = replay.sprites[key];
  return entry ? staticFile(`sprites/${entry.file}`) : null;
}
