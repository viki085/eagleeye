import React from "react";
import { Composition } from "remotion";
import { Demo } from "./Demo";
import { BuiltWith } from "./BuiltWith";
import timeline from "../../public/timeline.json";
import type { Timeline } from "./types";

const t = timeline as Timeline;

export const Root: React.FC = () => (
  <>
    <Composition id="Demo" component={Demo} durationInFrames={t.durationInFrames} fps={t.fps} width={1920} height={1080} defaultProps={{ timeline: t }} />
    <Composition id="BuiltWith" component={BuiltWith} durationInFrames={t.fps * 12} fps={t.fps} width={1920} height={1080} />
  </>
);
