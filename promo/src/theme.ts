/** The film borrows the client's palette so the promo and the product look like one thing. */
export const theme = {
  ink: "#0d1117",
  inkSoft: "#151b24",
  line: "#233043",
  text: "#e6edf3",
  textMuted: "#8b98a9",
  accent: "#f0b429",
  danger: "#e5484d",
  good: "#3fb950",
} as const;

/** One colour per colony, matching the operations room's colony tinting. */
export const colonyColour: Record<string, string> = {
  c1: "#f0b429",
  c2: "#4c9df0",
  c3: "#3fb950",
  c4: "#e5484d",
};

export const TILE_WIDTH = 48;
export const TILE_HEIGHT = 24;

export const font =
  '"SF Mono", "JetBrains Mono", "Fira Code", ui-monospace, monospace';
