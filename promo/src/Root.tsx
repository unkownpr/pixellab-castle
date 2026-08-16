import React from "react";
import { Composition } from "remotion";

import { Promo, PROMO_DURATION } from "./Promo";
import { Loop, LOOP_DURATION } from "./Loop";

export function RemotionRoot() {
  return (
    <>
      <Composition
        id="promo-en"
        component={Promo}
        durationInFrames={PROMO_DURATION}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{ lang: "en" as const }}
      />
      <Composition
        id="promo-tr"
        component={Promo}
        durationInFrames={PROMO_DURATION}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{ lang: "tr" as const }}
      />
      <Composition
        id="loop-en"
        component={Loop}
        durationInFrames={LOOP_DURATION}
        fps={30}
        width={960}
        height={540}
        defaultProps={{ lang: "en" as const }}
      />
      <Composition
        id="loop-tr"
        component={Loop}
        durationInFrames={LOOP_DURATION}
        fps={30}
        width={960}
        height={540}
        defaultProps={{ lang: "tr" as const }}
      />
    </>
  );
}
