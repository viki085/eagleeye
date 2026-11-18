import React from "react";
import { AbsoluteFill, Audio, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame } from "remotion";
import { BuiltWith } from "./BuiltWith";
import { TitleCard } from "./TitleCard";
import type { Item, Line, Segment, Timeline } from "./types";

const GOLD = "#C5A368";
const FONT = "Inter, 'Segoe UI', system-ui, sans-serif";

/** One scene clip, cut into segments that each play at their own speed. */
const Clip: React.FC<{ item: Extract<Item, { kind: "clip" }>; fps: number }> = ({ item, fps }) => (
  <>
    {item.segments.map((s, i) => (
      <Sequence key={i} from={s.from - item.from} durationInFrames={s.frames} layout="none">
        <AbsoluteFill>
          <OffthreadVideo src={staticFile(item.src)} startFrom={Math.round((s.startMs / 1000) * fps)} playbackRate={s.speed} muted />
          {s.speed > 1.05 && <SpeedBadge speed={s.speed} />}
        </AbsoluteFill>
      </Sequence>
    ))}
  </>
);

const SpeedBadge: React.FC<{ speed: number }> = ({ speed }) => (
  <div
    style={{
      position: "absolute", top: 28, right: 32, padding: "8px 16px", borderRadius: 999,
      background: "rgba(10,10,10,0.72)", border: `1px solid ${GOLD}66`, color: GOLD,
      fontFamily: FONT, fontSize: 24, fontWeight: 600, letterSpacing: 0.5,
    }}
  >
    ⏩ {speed >= 10 ? Math.round(speed) : speed.toFixed(speed % 1 ? 1 : 0)}×
  </div>
);

/** Burned-in subtitle with the speaker's name tag. */
const Subtitle: React.FC<{ line: Line }> = ({ line }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 6, line.frames - 6, line.frames], [0, 1, 1, 0], { extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: 54, opacity }}>
      <div style={{ maxWidth: 1380, textAlign: "center", fontFamily: FONT }}>
        <div style={{ display: "inline-block", marginBottom: 10, padding: "4px 12px", borderRadius: 6, background: "rgba(10,10,10,0.78)", color: GOLD, fontSize: 18, fontWeight: 700, letterSpacing: 2, textTransform: "uppercase" }}>
          {line.character === "narrator" ? "Narrator" : "Expert"}
        </div>
        <div style={{ padding: "12px 22px", borderRadius: 10, background: "rgba(10,10,10,0.78)", color: "#f2f2f2", fontSize: 32, lineHeight: 1.35, fontWeight: 500 }}>
          {line.text}
        </div>
      </div>
    </AbsoluteFill>
  );
};

const Caption: React.FC<{ text: string; frames: number }> = ({ text, frames }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 8, frames - 8, frames], [0, 1, 1, 0], { extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", background: "rgba(0,0,0,0.55)", opacity }}>
      <div style={{ fontFamily: FONT, color: "#f2f2f2", fontSize: 64, fontWeight: 600, letterSpacing: 1 }}>{text}</div>
    </AbsoluteFill>
  );
};

export const Demo: React.FC<{ timeline: Timeline }> = ({ timeline }) => (
  <AbsoluteFill style={{ background: "#0a0a0a" }}>
    {timeline.items.map((item, i) => (
      <Sequence key={i} from={item.from} durationInFrames={item.frames}>
        {item.kind === "title" && <TitleCard title={item.title} subtitle={item.subtitle} />}
        {item.kind === "clip" && <Clip item={item} fps={timeline.fps} />}
        {item.kind === "card" && <BuiltWith />}
        {item.kind === "caption" && <Caption text={item.text} frames={item.frames} />}
      </Sequence>
    ))}
    {timeline.lines.map((line) => (
      <Sequence key={line.id} from={line.from} durationInFrames={line.frames}>
        <Audio src={staticFile(line.src)} />
        <Subtitle line={line} />
      </Sequence>
    ))}
  </AbsoluteFill>
);
