import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";

import { IsoMap, birthIndex, fadeIn } from "./IsoMap";
import { colonyColour, font, theme } from "./theme";
import { copy, type Lang } from "./copy";
import { replay } from "./replay";

/**
 * The README's GIF: forty turns of a real match in eight seconds, no cards, no claims.
 *
 * A loop has to earn its place in a page that people scroll past, so it shows the one
 * thing a screenshot cannot — a colony spreading across ground it had to reach.
 */
const FRAMES_PER_STEP = 6;
export const LOOP_STEPS = 40;
export const LOOP_DURATION = FRAMES_PER_STEP * LOOP_STEPS;

export function Loop({ lang }: { lang: Lang }) {
  const frame = useCurrentFrame();
  const bornAt = React.useMemo(() => birthIndex(replay.frames), []);
  const step = Math.min(replay.frames.length - 1, Math.floor(frame / FRAMES_PER_STEP));
  const frameData = replay.frames[step];
  const words = copy[lang];
  return (
    <AbsoluteFill style={{ background: theme.ink }}>
      <IsoMap
        frame={frameData}
        videoFrame={frame}
        framesPerStep={FRAMES_PER_STEP}
        stepStartFrame={0}
        bornAt={bornAt}
        scale={0.95}
        fade={fadeIn(frame, 0, 8)}
      />
      <AbsoluteFill style={{ padding: 22, justifyContent: "space-between" }}>
        <div style={{ fontFamily: font, fontSize: 15, color: theme.textMuted }}>
          {words.title}
          <span style={{ color: theme.line }}> · </span>
          {replay.scenario} · seed {replay.seed}
        </div>
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between" }}>
          <div style={{ display: "flex", gap: 14 }}>
            {Object.entries(frameData.colonies).map(([colonyId, colony]) => (
              <div key={colonyId} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 4,
                    background: colonyColour[colonyId] ?? theme.textMuted,
                  }}
                />
                <span style={{ fontFamily: font, fontSize: 14, color: theme.textMuted }}>
                  {colony.pop}
                </span>
              </div>
            ))}
          </div>
          <div style={{ fontFamily: font, fontSize: 14, color: theme.textMuted }}>
            {words.turn} <span style={{ color: theme.accent }}>{frameData.turn}</span>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
}
