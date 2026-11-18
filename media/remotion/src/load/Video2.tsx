import React from "react";
import { AbsoluteFill, Sequence } from "remotion";
import { Architecture, type ArchTimeline } from "../arch/Architecture";
import archTimeline from "../../../public/arch-timeline.json";
import { LoadTest } from "./LoadTest";

export const ARCH = archTimeline as ArchTimeline;

/** Video 2: Part 1 (the animated architecture) then Part 2 (the load test). */
export const Video2: React.FC = () => (
  <AbsoluteFill style={{ background: "#000" }}>
    <Sequence durationInFrames={ARCH.durationInFrames}>
      <Architecture timeline={ARCH} />
    </Sequence>
    <Sequence from={ARCH.durationInFrames}>
      <LoadTest />
    </Sequence>
  </AbsoluteFill>
);
