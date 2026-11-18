import React from "react";
import { Composition } from "remotion";
import { Demo } from "./Demo";
import { BuiltWith } from "./BuiltWith";
import { Thumbnail } from "./Thumbnail";
import { Architecture, type ArchTimeline } from "./arch/Architecture";
import archTimeline from "../../public/arch-timeline.json";
import timeline from "../../public/timeline.json";
import { LoadTest } from "./load/LoadTest";
import { ARCH, Video2 } from "./load/Video2";
import { TIMELINE as LOAD } from "./load/data";
import type { Timeline } from "./types";

const t = timeline as Timeline;

export const Root: React.FC = () => (
  <>
    <Composition id="Demo" component={Demo} durationInFrames={t.durationInFrames} fps={t.fps} width={1920} height={1080} defaultProps={{ timeline: t }} />
    <Composition id="Architecture" component={Architecture} durationInFrames={(archTimeline as ArchTimeline).durationInFrames} fps={30} width={1920} height={1080} defaultProps={{ timeline: archTimeline as ArchTimeline }} />
    <Composition id="LoadTest" component={LoadTest} durationInFrames={LOAD.durationInFrames} fps={30} width={1920} height={1080} />
    <Composition id="Video2" component={Video2} durationInFrames={ARCH.durationInFrames + LOAD.durationInFrames} fps={30} width={1920} height={1080} />
    <Composition id="Thumbnail" component={Thumbnail} durationInFrames={1} fps={t.fps} width={1280} height={720} />
    <Composition id="BuiltWith" component={BuiltWith} durationInFrames={t.fps * 12} fps={t.fps} width={1920} height={1080} />
  </>
);
