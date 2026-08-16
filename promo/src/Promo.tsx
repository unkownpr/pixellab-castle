import React from "react";
import {
  AbsoluteFill,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

import { IsoMap, birthIndex, fadeIn } from "./IsoMap";
import { colonyColour, font, theme } from "./theme";
import { copy, model, type Lang } from "./copy";
import { replay } from "./replay";

const REPLAY_START = 240;
const REPLAY_FRAMES_PER_STEP = 9;
const REPLAY_STEPS = 34;
const RESULT_START = REPLAY_START + REPLAY_FRAMES_PER_STEP * REPLAY_STEPS;
const OUTRO_START = RESULT_START + 210;
export const PROMO_DURATION = OUTRO_START + 150;

function Backdrop() {
  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(circle at 50% 35%, ${theme.inkSoft} 0%, ${theme.ink} 70%)`,
      }}
    />
  );
}

function Title({ lang }: { lang: Lang }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const rise = spring({ frame, fps, config: { damping: 18 } });
  const words = copy[lang];
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
      <div style={{ transform: `translateY(${(1 - rise) * 24}px)`, opacity: rise, textAlign: "center" }}>
        <Img
          src={staticFile("sprites/structure_headquarters_operational.png")}
          style={{ width: 128, height: 128, imageRendering: "pixelated", marginBottom: 8 }}
        />
        <div style={{ fontFamily: font, fontSize: 84, color: theme.text, letterSpacing: -2 }}>
          {words.title}
        </div>
        <div
          style={{
            fontFamily: font,
            fontSize: 26,
            color: theme.textMuted,
            marginTop: 16,
            maxWidth: 1100,
            lineHeight: 1.5,
          }}
        >
          {words.subtitle}
        </div>
      </div>
    </AbsoluteFill>
  );
}

function Measures({ lang }: { lang: Lang }) {
  const frame = useCurrentFrame();
  const words = copy[lang];
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
      <div style={{ width: 1320 }}>
        <div
          style={{
            fontFamily: font,
            fontSize: 20,
            letterSpacing: 4,
            color: theme.accent,
            opacity: fadeIn(frame, 0),
            marginBottom: 28,
          }}
        >
          {words.measuresTitle.toUpperCase()}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
          {words.measures.map(([name, detail], index) => (
            <div
              key={name}
              style={{
                opacity: fadeIn(frame, 10 + index * 9),
                transform: `translateY(${(1 - fadeIn(frame, 10 + index * 9)) * 10}px)`,
                border: `1px solid ${theme.line}`,
                borderLeft: `3px solid ${theme.accent}`,
                borderRadius: 6,
                padding: "18px 22px",
                background: "rgba(255,255,255,0.02)",
              }}
            >
              <div style={{ fontFamily: font, fontSize: 26, color: theme.text }}>{name}</div>
              <div style={{ fontFamily: font, fontSize: 19, color: theme.textMuted, marginTop: 6 }}>
                {detail}
              </div>
            </div>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
}

function ColonyStrip({ frameData }: { frameData: (typeof replay.frames)[number] }) {
  return (
    <div style={{ display: "flex", gap: 26 }}>
      {Object.entries(frameData.colonies).map(([colonyId, colony]) => (
        <div key={colonyId} style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            style={{
              width: 12,
              height: 12,
              borderRadius: 6,
              background: colonyColour[colonyId] ?? theme.textMuted,
            }}
          />
          <span style={{ fontFamily: font, fontSize: 22, color: theme.text }}>{colonyId}</span>
          <span style={{ fontFamily: font, fontSize: 22, color: theme.textMuted }}>
            {colony.pop}
          </span>
        </div>
      ))}
    </div>
  );
}

function Replay({ lang }: { lang: Lang }) {
  const frame = useCurrentFrame();
  const words = copy[lang];
  const bornAt = React.useMemo(() => birthIndex(replay.frames), []);
  const step = Math.min(
    replay.frames.length - 1,
    Math.floor(frame / REPLAY_FRAMES_PER_STEP),
  );
  const frameData = replay.frames[step];
  const zoom = interpolate(frame, [0, REPLAY_FRAMES_PER_STEP * REPLAY_STEPS], [1.45, 1.72], {
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill>
      <IsoMap
        frame={frameData}
        videoFrame={frame}
        framesPerStep={REPLAY_FRAMES_PER_STEP}
        stepStartFrame={0}
        bornAt={bornAt}
        scale={zoom}
        fade={fadeIn(frame, 0, 20)}
      />
      <AbsoluteFill style={{ padding: 64, justifyContent: "space-between" }}>
        <div style={{ opacity: fadeIn(frame, 6) }}>
          <div style={{ fontFamily: font, fontSize: 30, color: theme.text }}>{words.replayTitle}</div>
          <div style={{ fontFamily: font, fontSize: 19, color: theme.textMuted, marginTop: 8 }}>
            {words.replayNote}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between" }}>
          <ColonyStrip frameData={frameData} />
          <div style={{ fontFamily: font, fontSize: 22, color: theme.textMuted }}>
            {words.turn}{" "}
            <span style={{ color: theme.accent, fontSize: 40 }}>
              {String(frameData.turn).padStart(2, "0")}
            </span>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
}

function Result({ lang }: { lang: Lang }) {
  const frame = useCurrentFrame();
  const words = copy[lang];
  const top = model.composites[0].score;
  const suite = replay.suite;
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
      <div style={{ width: 1240 }}>
        <div style={{ opacity: fadeIn(frame, 0) }}>
          <div style={{ fontFamily: font, fontSize: 44, color: theme.text }}>{words.resultTitle}</div>
          <div style={{ fontFamily: font, fontSize: 21, color: theme.textMuted, marginTop: 10 }}>
            {words.resultLine}
          </div>
        </div>
        <div style={{ marginTop: 40 }}>
          {model.composites.map((entry, index) => {
            const appear = fadeIn(frame, 18 + index * 8, 14);
            const width = (entry.score / top) * 900 * appear;
            return (
              <div key={entry.colony} style={{ display: "flex", alignItems: "center", gap: 18, marginBottom: 14 }}>
                <div
                  style={{
                    width: 190,
                    textAlign: "right",
                    fontFamily: font,
                    fontSize: 21,
                    color: index === 0 ? theme.text : theme.textMuted,
                  }}
                >
                  {entry.label[lang]}
                </div>
                <div
                  style={{
                    height: 30,
                    width,
                    background: colonyColour[entry.colony],
                    opacity: index === 0 ? 1 : 0.55,
                    borderRadius: 3,
                  }}
                />
                <div style={{ fontFamily: font, fontSize: 24, color: theme.text, opacity: appear }}>
                  {entry.score}
                </div>
              </div>
            );
          })}
          <div style={{ fontFamily: font, fontSize: 17, color: theme.textMuted, marginLeft: 208 }}>
            {words.resultScores}
          </div>
        </div>
        {suite ? (
          <div style={{ marginTop: 44, opacity: fadeIn(frame, 96), display: "flex", gap: 40 }}>
            <div style={{ fontFamily: font, fontSize: 17, color: theme.accent, letterSpacing: 2 }}>
              {words.suiteTitle.toUpperCase()}
            </div>
            {Object.entries(suite.controllers)
              .sort((a, b) => b[1].composite - a[1].composite)
              .map(([kind, stats]) => (
                <div key={kind} style={{ fontFamily: font, fontSize: 17, color: theme.textMuted }}>
                  {kind} <span style={{ color: theme.text }}>{stats.composite.toFixed(1)}</span>
                </div>
              ))}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
}

function Outro({ lang }: { lang: Lang }) {
  const frame = useCurrentFrame();
  const words = copy[lang];
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
      <div style={{ width: 1100, opacity: fadeIn(frame, 0) }}>
        <div style={{ fontFamily: font, fontSize: 20, letterSpacing: 4, color: theme.accent }}>
          {words.outroTitle.toUpperCase()}
        </div>
        <div
          style={{
            marginTop: 22,
            border: `1px solid ${theme.line}`,
            borderRadius: 8,
            padding: "26px 30px",
            background: "rgba(255,255,255,0.02)",
          }}
        >
          {words.outroLines.map((line, index) => (
            <div
              key={line}
              style={{
                fontFamily: font,
                fontSize: 23,
                color: theme.text,
                opacity: fadeIn(frame, 10 + index * 8),
                marginBottom: index === words.outroLines.length - 1 ? 0 : 12,
              }}
            >
              <span style={{ color: theme.good }}>$ </span>
              {line}
            </div>
          ))}
        </div>
        <div style={{ fontFamily: font, fontSize: 19, color: theme.textMuted, marginTop: 24 }}>
          {words.outroNote}
        </div>
        <div style={{ fontFamily: font, fontSize: 22, color: theme.accent, marginTop: 34 }}>
          github.com/unkownpr/pixellab-castle
        </div>
      </div>
    </AbsoluteFill>
  );
}

export function Promo({ lang }: { lang: Lang }) {
  return (
    <AbsoluteFill>
      <Backdrop />
      <Sequence durationInFrames={110}>
        <Title lang={lang} />
      </Sequence>
      <Sequence from={110} durationInFrames={REPLAY_START - 110}>
        <Measures lang={lang} />
      </Sequence>
      <Sequence from={REPLAY_START} durationInFrames={RESULT_START - REPLAY_START}>
        <Replay lang={lang} />
      </Sequence>
      <Sequence from={RESULT_START} durationInFrames={OUTRO_START - RESULT_START}>
        <Result lang={lang} />
      </Sequence>
      <Sequence from={OUTRO_START}>
        <Outro lang={lang} />
      </Sequence>
    </AbsoluteFill>
  );
}
