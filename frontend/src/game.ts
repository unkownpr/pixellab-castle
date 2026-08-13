import {
  AnimatedSprite,
  Application,
  Assets,
  Container,
  Graphics,
  Sprite,
  Text,
} from "pixi.js";

import type {
  Observation,
  StructureKind,
  StructureStatus,
  VisibleCell,
  VisibleStructure,
} from "./api";
import { nextWorldView, type WorldView } from "./operations";

export const TILE_WIDTH = 48;
export const TILE_HEIGHT = 24;

export function shouldAnimateWorld(reducedMotion: boolean): boolean {
  return !reducedMotion;
}

export interface GridPosition {
  readonly x: number;
  readonly y: number;
}

export interface ScreenPosition {
  readonly x: number;
  readonly y: number;
}

export type ControllerAction = Readonly<Record<string, unknown>> & { readonly kind: string };

export interface ControllerBatch {
  readonly version: "1";
  readonly turn: number;
  readonly colony_id: string;
  readonly actions: readonly ControllerAction[];
}

export type EventAnimation =
  | "construction"
  | "completion"
  | "impact"
  | "fire"
  | "weather"
  | "none";

export function isoToScreen(
  position: GridPosition,
  origin: ScreenPosition,
): ScreenPosition {
  return {
    x: origin.x + (position.x - position.y) * (TILE_WIDTH / 2),
    y: origin.y + (position.x + position.y) * (TILE_HEIGHT / 2),
  };
}

export function compareIsoDepth(a: GridPosition, b: GridPosition): number {
  const diagonal = a.x + a.y - (b.x + b.y);
  return diagonal === 0 ? a.x - b.x : diagonal;
}

export function actionBatch(
  turn: number,
  colonyId: string,
  actions: readonly ControllerAction[],
): ControllerBatch {
  return { version: "1", turn, colony_id: colonyId, actions };
}

export function animationForEvent(event: { readonly kind: string }): EventAnimation {
  switch (event.kind) {
    case "construction_started":
    case "construction_progress":
      return "construction";
    case "construction_completed":
      return "completion";
    case "combat_damage":
    case "raid_resolved":
      return "impact";
    case "fire_started":
    case "fire_spread":
      return "fire";
    case "weather":
    case "hazard":
    case "weather_hazard":
      return "weather";
    case "surprise_raid":
    case "raid":
      return "impact";
    default:
      return "none";
  }
}

export interface ReplaySnapshot {
  readonly scenario_id: string;
  readonly turn: number;
  readonly world: { readonly cells: readonly Readonly<Record<string, unknown>>[] };
  readonly colonies: Readonly<Record<string, Readonly<Record<string, unknown>>>>;
  readonly structures: Readonly<Record<string, Readonly<Record<string, unknown>>>>;
  readonly offers: Readonly<Record<string, Readonly<Record<string, unknown>>>>;
}

export function snapshotToObservation(snapshot: ReplaySnapshot, colonyId: string): Observation {
  const colony = snapshot.colonies[colonyId];
  if (!colony) throw new Error(`Replay kolonisi bulunamadı: ${colonyId}`);
  const health = {
    healthy: Number(colony.healthy ?? 0),
    injured: Number(colony.injured ?? 0),
    sick: Number(colony.sick ?? 0),
    hungry: Number(colony.hungry ?? 0),
  };
  const visibleCells = snapshot.world.cells.map((cell) => ({
    x: Number(cell.x),
    y: Number(cell.y),
    biome: String(cell.biome) as VisibleCell["biome"],
    water: Boolean(cell.water),
    buildable: Boolean(cell.buildable),
    movement_cost: Number(cell.movement_cost),
    resource: cell.resource === null || cell.resource === undefined ? null : String(cell.resource),
    resource_amount: Number(cell.resource_amount ?? 0),
  }));
  const visibleStructures = Object.values(snapshot.structures).map((structure) => {
    const position = structure.position as Readonly<Record<string, unknown>>;
    return {
      id: String(structure.id),
      colony_id: String(structure.colony_id),
      kind: String(structure.kind) as StructureKind,
      status: String(structure.status) as StructureStatus,
      progress: Number(structure.progress),
      required_progress: Number(structure.required_progress),
      condition: Number(structure.condition),
      x: Number(position.x),
      y: Number(position.y),
    };
  });
  const relations = colony.relations as Readonly<Record<string, string>>;
  return {
    schema_version: "1.0",
    scenario_id: snapshot.scenario_id,
    turn: snapshot.turn,
    colony_id: colonyId,
    colony: {
      id: colonyId,
      population: Number(colony.population),
      housing: Number(colony.housing),
      health,
      resources: colony.resources as Readonly<Record<string, number>>,
      policies: colony.policies as Readonly<Record<string, string>>,
    },
    visible_cells: visibleCells,
    visible_structures: visibleStructures,
    known_colonies: Object.fromEntries(
      Object.entries(relations).map(([id, relation]) => [id, { id, relation, contacted: relation !== "unknown" }]),
    ),
    active_offers: Object.values(snapshot.offers),
    valid_action_kinds: [],
  };
}

interface AssetEntry {
  readonly path: string;
  readonly anchor: readonly [number, number];
  readonly size: readonly [number, number];
}

interface AssetManifest {
  readonly assets: Readonly<Record<string, AssetEntry>>;
}

const STRUCTURE_KEYS: Readonly<Record<string, readonly string[]>> = {
  headquarters: ["structure.headquarters.operational"],
  house: ["structure.house.grass.operational"],
  market: ["structure.market.operational"],
  watchtower: ["structure.watchtower.operational"],
};

interface RendererVisualTokens {
  readonly ink: number;
  readonly accent: number;
  readonly surfaceMap: number;
  readonly focus: number;
  readonly damaged: number;
  readonly burning: number;
  readonly colonies: readonly number[];
  readonly fontBody: string;
  readonly labelSize: number;
  readonly labelTracking: number;
}

function cssToken(name: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  if (!value) throw new Error(`Eksik renderer tasarım tokenı: ${name}`);
  return value;
}

function canvasColor(value: string): number {
  const canvas = document.createElement("canvas");
  canvas.width = 1;
  canvas.height = 1;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("Renderer renk dönüşümü için Canvas 2D gerekli");
  context.clearRect(0, 0, 1, 1);
  context.fillStyle = value;
  context.fillRect(0, 0, 1, 1);
  const pixels = context.getImageData(0, 0, 1, 1).data;
  const red = pixels[0] ?? 0;
  const green = pixels[1] ?? 0;
  const blue = pixels[2] ?? 0;
  return (red << 16) | (green << 8) | blue;
}

function rendererVisualTokens(): RendererVisualTokens {
  return {
    ink: canvasColor(cssToken("--color-ink")),
    accent: canvasColor(cssToken("--color-accent")),
    surfaceMap: canvasColor(cssToken("--color-surface-map")),
    focus: canvasColor(cssToken("--color-focus")),
    damaged: canvasColor(cssToken("--color-structure-damaged")),
    burning: canvasColor(cssToken("--color-structure-burning")),
    colonies: Array.from(
      { length: 6 },
      (_, index) => canvasColor(cssToken(`--color-colony-${index + 1}`)),
    ),
    fontBody: cssToken("--font-body"),
    labelSize: Number.parseFloat(cssToken("--text-pixi-label")),
    labelTracking: Number.parseFloat(cssToken("--tracking-pixi-label")),
  };
}

export class CastleRenderer {
  private readonly app = new Application();
  private readonly world = new Container();
  private manifest: AssetManifest | null = null;
  private visualTokens: RendererVisualTokens | null = null;
  private renderVersion = 0;
  private selectHandler: ((cell: VisibleCell) => void) | null = null;
  private currentObservation: Observation | null = null;
  private focusedColonyId: string | null = null;
  private view: WorldView = { scale: 1, x: 0, y: 0 };

  async init(host: HTMLElement, manifestUrl = "/manifest.json"): Promise<void> {
    await this.app.init({
      resizeTo: host,
      antialias: false,
      backgroundAlpha: 0,
      resolution: Math.min(window.devicePixelRatio || 1, 2),
      autoDensity: true,
    });
    this.app.canvas.className = "world-canvas";
    this.app.canvas.setAttribute("aria-label", "İzometrik koloni haritası");
    host.replaceChildren(this.app.canvas);
    this.app.stage.addChild(this.world);
    this.visualTokens = rendererVisualTokens();
    const response = await fetch(manifestUrl);
    if (!response.ok) throw new Error(`Asset manifest yüklenemedi (${response.status})`);
    this.manifest = await response.json() as AssetManifest;
  }

  onCellSelected(handler: (cell: VisibleCell) => void): void {
    this.selectHandler = handler;
  }

  zoomBy(delta: number): void {
    this.view = nextWorldView(this.view, { kind: "zoom", delta });
    this.applyViewTransform();
  }

  panBy(x: number, y: number): void {
    this.view = nextWorldView(this.view, { kind: "pan", x, y });
    this.applyViewTransform();
  }

  resetView(): void {
    this.view = nextWorldView(this.view, { kind: "reset" });
    this.applyViewTransform();
  }

  focusColony(colonyId: string | null): void {
    if (this.focusedColonyId === colonyId) return;
    this.focusedColonyId = colonyId;
    if (this.currentObservation) void this.render(this.currentObservation);
  }

  async render(observation: Observation): Promise<void> {
    if (!this.manifest) throw new Error("Renderer henüz hazır değil");
    const visualTokens = this.requireVisualTokens();
    this.currentObservation = observation;
    const version = ++this.renderVersion;
    this.world.removeChildren().forEach((child) => child.destroy({ children: true }));

    const cells = [...observation.visible_cells].sort(compareIsoDepth);
    const structures = [...observation.visible_structures].sort(compareIsoDepth);
    const origin = this.worldOrigin(cells);
    const cellLayer = new Container();
    const markerLayer = new Container();
    const structureLayer = new Container();
    cellLayer.sortableChildren = true;
    structureLayer.sortableChildren = true;
    this.world.addChild(cellLayer, markerLayer, structureLayer);

    await Promise.all(cells.map(async (cell) => {
      const position = isoToScreen(cell, origin);
      const key = this.terrainKey(cell);
      const sprite = await this.spriteFor(key, position);
      if (version !== this.renderVersion) {
        sprite?.destroy();
        return;
      }
      if (sprite) {
        sprite.zIndex = (cell.x + cell.y) * 1000 + cell.x;
        cellLayer.addChild(sprite);
      }

      const hit = new Graphics()
        .poly([
          position.x, position.y - TILE_HEIGHT / 2,
          position.x + TILE_WIDTH / 2, position.y,
          position.x, position.y + TILE_HEIGHT / 2,
          position.x - TILE_WIDTH / 2, position.y,
        ])
        .fill({ color: visualTokens.ink, alpha: 0.001 });
      hit.eventMode = "static";
      hit.cursor = "pointer";
      hit.on("pointertap", () => this.selectHandler?.(cell));
      markerLayer.addChild(hit);

      if (cell.resource && cell.resource_amount > 0) {
        const resource = new Graphics()
          .circle(position.x, position.y - 7, 2.5)
          .fill({ color: visualTokens.accent, alpha: 0.9 });
        markerLayer.addChild(resource);
      }
    }));

    await Promise.all(structures.map(async (structure) => {
      const position = isoToScreen(structure, origin);
      const sprite = await this.structureSprite(structure, position);
      if (version !== this.renderVersion || !sprite) {
        sprite?.destroy();
        return;
      }
      const depth = (structure.x + structure.y) * 1000 + structure.x;
      sprite.zIndex = depth;
      structureLayer.addChild(sprite);
      const ownerIndex = Math.max(0, Number(structure.colony_id.replace(/\D/g, "")) - 1);
      const flag = new Graphics()
        .rect(position.x - 14, position.y - 35, 5, 12)
        .fill({
          color: visualTokens.colonies[ownerIndex % visualTokens.colonies.length]
            ?? visualTokens.colonies[0],
        });
      flag.zIndex = depth + 0.1;
      structureLayer.addChild(flag);

      if (["foundation", "building", "repairing"].includes(structure.status)) {
        const ratio = Math.min(1, structure.progress / Math.max(1, structure.required_progress));
        const progress = new Graphics()
          .rect(position.x - 14, position.y + 3, 28, 3)
          .fill({ color: visualTokens.surfaceMap, alpha: 0.8 })
          .rect(position.x - 14, position.y + 3, 28 * ratio, 3)
          .fill({ color: visualTokens.accent });
        progress.zIndex = depth + 0.2;
        structureLayer.addChild(progress);
        const scaffold = await this.spriteFor("effect.construction", position);
        if (version !== this.renderVersion) {
          scaffold?.destroy();
          return;
        }
        if (scaffold) {
          scaffold.alpha = 0.72;
          scaffold.zIndex = depth + 0.3;
          structureLayer.addChild(scaffold);
        }
      }

      if (structure.status === "burning") {
        const fire = await this.fireSprite(position);
        if (version !== this.renderVersion) {
          fire?.destroy();
          return;
        }
        if (fire) {
          fire.zIndex = depth + 0.4;
          structureLayer.addChild(fire);
        }
      }

      if (structure.colony_id === this.focusedColonyId) {
        const focus = new Graphics()
          .circle(position.x, position.y - 8, 22)
          .stroke({ color: visualTokens.focus, width: 2, alpha: 0.95 });
        focus.zIndex = depth + 0.5;
        structureLayer.addChild(focus);
      }
    }));

    if (version !== this.renderVersion) return;

    const turnLabel = new Text({
      text: `TUR ${String(observation.turn).padStart(2, "0")} · ${observation.colony_id.toUpperCase()}`,
      style: {
        fill: visualTokens.ink,
        fontFamily: visualTokens.fontBody,
        fontSize: visualTokens.labelSize,
        letterSpacing: visualTokens.labelTracking,
      },
    });
    turnLabel.position.set(14, 12);
    this.world.addChild(turnLabel);
    this.applyViewTransform();
  }

  destroy(): void {
    this.app.destroy(true, { children: true, texture: false });
  }

  private worldOrigin(cells: readonly VisibleCell[]): ScreenPosition {
    if (!cells.length) return { x: this.app.screen.width / 2, y: this.app.screen.height / 2 };
    const maxDiagonal = Math.max(...cells.map((cell) => cell.x + cell.y));
    return {
      x: this.app.screen.width / 2,
      y: Math.max(72, (this.app.screen.height - maxDiagonal * TILE_HEIGHT / 2) / 2),
    };
  }

  private requireVisualTokens(): RendererVisualTokens {
    if (!this.visualTokens) throw new Error("Renderer tasarım tokenları henüz hazır değil");
    return this.visualTokens;
  }

  private applyViewTransform(): void {
    this.world.scale.set(this.view.scale);
    this.world.position.set(
      this.view.x + this.app.screen.width * (1 - this.view.scale) / 2,
      this.view.y + this.app.screen.height * (1 - this.view.scale) / 2,
    );
  }

  private terrainKey(cell: VisibleCell): string {
    const terrainFamily = cell.biome === "grassland" ? "grass" : cell.biome === "desert" ? "sand" : "snow";
    if (cell.water) return `terrain.${terrainFamily}.wang.15`;
    if (cell.biome === "desert") return "terrain.sand.base";
    if (cell.biome === "snow") return "terrain.snow.wang.0";
    return "terrain.grass.base";
  }

  private async structureSprite(
    structure: VisibleStructure,
    position: ScreenPosition,
  ): Promise<Sprite | null> {
    const generated = structure.status === "ruined"
      ? "structure.generic.ruined"
      : `structure.${structure.kind}.operational`;
    const candidates = [generated, ...(STRUCTURE_KEYS[structure.kind] ?? []), "structure.house.grass.operational"];
    const key = candidates.find((candidate) => this.manifest?.assets[candidate]);
    if (!key) return null;
    const sprite = await this.spriteFor(key, position);
    if (!sprite) return null;
    if (["foundation", "building", "repairing"].includes(structure.status)) sprite.alpha = 0.62;
    if (structure.status === "damaged") sprite.tint = this.requireVisualTokens().damaged;
    if (structure.status === "burning") sprite.tint = this.requireVisualTokens().burning;
    return sprite;
  }

  private async spriteFor(key: string, position: ScreenPosition): Promise<Sprite | null> {
    const entry = this.manifest?.assets[key];
    if (!entry) return null;
    const texture = await Assets.load(`/${entry.path}`);
    const sprite = new Sprite(texture);
    sprite.position.set(position.x - entry.anchor[0], position.y - entry.anchor[1]);
    return sprite;
  }

  private async fireSprite(position: ScreenPosition): Promise<AnimatedSprite | null> {
    const entries = Array.from(
      { length: 9 },
      (_, index) => this.manifest?.assets[`effect.fire.loop.${index}`],
    );
    if (entries.some((entry) => !entry)) return null;
    const textures = await Promise.all(entries.map((entry) => Assets.load(`/${entry!.path}`)));
    const sprite = new AnimatedSprite(textures);
    const anchor = entries[0]!.anchor;
    sprite.position.set(position.x - anchor[0], position.y - anchor[1]);
    sprite.animationSpeed = 0.14;
    sprite.loop = true;
    if (shouldAnimateWorld(window.matchMedia("(prefers-reduced-motion: reduce)").matches)) sprite.play();
    return sprite;
  }
}
