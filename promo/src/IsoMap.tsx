import React from "react";
import { Img, interpolate, spring, useVideoConfig } from "remotion";

import { TILE_HEIGHT, TILE_WIDTH, colonyColour, theme } from "./theme";
import { effectSprite, replay, structureSprite, type Frame } from "./replay";

const BIOME_GROUND: Record<string, string> = {
  grassland: "#2f5d3a",
  desert: "#8a7038",
  snow: "#5d6b7a",
};

// The diamond runs from x-y = -(height-1) on the left to x-y = width-1 on the right, so
// the whole thing has to be pushed right by half a map before it sits inside its box.
const ORIGIN_LEFT = ((replay.height - 1) * TILE_WIDTH) / 2;
const DIAMOND_WIDTH = (replay.width + replay.height) * (TILE_WIDTH / 2);
const DIAMOND_HEIGHT = (replay.width + replay.height) * (TILE_HEIGHT / 2);

function project(x: number, y: number) {
  return {
    left: (x - y) * (TILE_WIDTH / 2) + ORIGIN_LEFT,
    top: (x + y) * (TILE_HEIGHT / 2),
  };
}

function Tile({ x, y, water, resource }: { x: number; y: number; water: boolean; resource: string }) {
  const { left, top } = project(x, y);
  const ground = water ? "#1e4d6b" : BIOME_GROUND[replay.biome] ?? "#2f5d3a";
  return (
    <div
      style={{
        position: "absolute",
        left,
        top,
        width: TILE_WIDTH,
        height: TILE_HEIGHT,
        background: ground,
        clipPath: "polygon(50% 0, 100% 50%, 50% 100%, 0 50%)",
        boxShadow: "inset 0 0 0 1px rgba(0,0,0,0.18)",
      }}
    >
      {resource && !water ? (
        <div
          style={{
            position: "absolute",
            left: TILE_WIDTH / 2 - 3,
            top: TILE_HEIGHT / 2 - 3,
            width: 6,
            height: 6,
            borderRadius: 3,
            background: resource === "food" ? "#8fd14f" : resource === "wood" ? "#a06b3c" : "#c9cfd6",
            opacity: 0.85,
          }}
        />
      ) : null}
    </div>
  );
}

/**
 * One structure, popped in with a spring on the frame it first appears.
 *
 * The pop is the only liberty the film takes with the simulation: buildings arrive over
 * three turns of construction, and a cut every second turn would otherwise make them
 * blink into existence with no sense of who built what.
 */
function Structure({
  structure,
  bornAtVideoFrame,
  videoFrame,
}: {
  structure: Frame["structures"][number];
  bornAtVideoFrame: number;
  videoFrame: number;
}) {
  const { fps } = useVideoConfig();
  const sprite = structureSprite(structure.k, structure.s);
  const { left, top } = project(structure.x, structure.y);
  const age = videoFrame - bornAtVideoFrame;
  const scale = spring({ frame: age, fps, config: { damping: 14, mass: 0.4 } });
  if (!sprite) return null;
  const burning = structure.s === "burning";
  const damaged = structure.s === "damaged";
  const ruined = structure.s === "ruined";
  return (
    <div
      style={{
        position: "absolute",
        left: left + TILE_WIDTH / 2 - 28,
        top: top + TILE_HEIGHT / 2 - 44,
        width: 56,
        height: 56,
        transform: `scale(${scale})`,
        transformOrigin: "50% 90%",
      }}
    >
      <div
        style={{
          position: "absolute",
          left: 17,
          top: 39,
          width: 22,
          height: 11,
          borderRadius: "50%",
          background: colonyColour[structure.c] ?? theme.textMuted,
          opacity: ruined ? 0.12 : 0.45,
          filter: "blur(2px)",
        }}
      />
      <Img
        src={sprite}
        style={{
          width: 56,
          height: 56,
          imageRendering: "pixelated",
          opacity: ruined ? 0.55 : 1,
          filter: damaged ? "saturate(0.6) brightness(0.8)" : undefined,
        }}
      />
      {burning ? <Fire /> : null}
    </div>
  );
}

function Fire() {
  const sprite = effectSprite("effect.fire.base");
  if (!sprite) return null;
  return (
    <Img
      src={sprite}
      style={{
        position: "absolute",
        left: 16,
        top: 4,
        width: 32,
        height: 32,
        imageRendering: "pixelated",
      }}
    />
  );
}

export function IsoMap({
  frame,
  videoFrame,
  framesPerStep,
  stepStartFrame,
  bornAt,
  scale = 1,
  fade = 1,
}: {
  frame: Frame;
  videoFrame: number;
  framesPerStep: number;
  stepStartFrame: number;
  bornAt: Map<string, number>;
  scale?: number;
  fade?: number;
}) {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        opacity: fade,
      }}
    >
      <div
        style={{
          position: "relative",
          width: DIAMOND_WIDTH,
          height: DIAMOND_HEIGHT,
          transform: `scale(${scale})`,
          transformOrigin: "50% 50%",
        }}
      >
        <div style={{ position: "absolute", inset: 0 }}>
          {replay.cells.map((cell) => (
            <Tile
              key={`${cell.x}:${cell.y}`}
              x={cell.x}
              y={cell.y}
              water={cell.w === 1}
              resource={cell.r}
            />
          ))}
          {frame.structures.map((structure) => (
            <Structure
              key={structure.id}
              structure={structure}
              bornAtVideoFrame={
                stepStartFrame + (bornAt.get(structure.id) ?? 0) * framesPerStep
              }
              videoFrame={videoFrame}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

/** The frame index at which each structure was first seen, so the pop only plays once. */
export function birthIndex(frames: Frame[]): Map<string, number> {
  const born = new Map<string, number>();
  frames.forEach((frame, index) => {
    for (const structure of frame.structures) {
      if (!born.has(structure.id)) born.set(structure.id, index);
    }
  });
  return born;
}

export function fadeIn(frame: number, start: number, length = 12) {
  return interpolate(frame, [start, start + length], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
}
