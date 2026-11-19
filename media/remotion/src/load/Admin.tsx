import React from "react";
import { AbsoluteFill, OffthreadVideo, Sequence, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { FONT, GOLD, INK, clamp01 } from "./data";

/** A rectangle in the recording's CSS pixels (a 1600 x 900 viewport). */
export interface Box { x: number; y: number; width: number; height: number }
export interface Highlight { t0: number; t1: number; box: Box; label: string }
export interface Beat {
  src: string;
  at: number; // scene time the beat starts (it fades in over FADE)
  seconds: number; // footage length; the last frame holds after it
  end: number; // scene time the next beat has fully covered this one
  highlights: Highlight[];
  note?: string | null;
}
export interface BeatsPart { type: "beats"; at: number; end: number; beats: Beat[] }

export const FADE = 0.5;
const VIEW_W = 1600; // recording viewport width (CSS px)
const PAD = 10;
const HL_IN = 0.35;
const HL_OUT = 0.35;

const ease = (v: number) => v * v * (3 - 2 * v);

/**
 * The gold spotlight, drawn by the edit so it can appear on a metric, hold while the line about it
 * plays, and disappear before the screen moves on (the recording's own spotlight was removed).
 */
const Spotlight: React.FC<{ h: Highlight; t: number }> = ({ h, t }) => {
  const { width } = useVideoConfig();
  const k = width / VIEW_W;
  const o = ease(clamp01((t - h.t0) / HL_IN) * clamp01((h.t1 - t) / HL_OUT));
  if (o <= 0) return null;
  const grow = 1 + (1 - o) * 0.02;
  const w = (h.box.width + PAD * 2) * k;
  const hh = (h.box.height + PAD * 2) * k;
  return (
    <div
      style={{
        position: "absolute",
        left: (h.box.x - PAD) * k,
        top: (h.box.y - PAD) * k,
        width: w,
        height: hh,
        borderRadius: 10 * k,
        border: `${2 * k}px solid rgba(197,163,104,${0.95 * o})`,
        background: `rgba(197,163,104,${0.07 * o})`,
        boxShadow: `0 0 0 9999px rgba(0,0,0,${0.38 * o}), 0 0 ${28 * k}px rgba(197,163,104,${0.35 * o})`,
        transform: `scale(${grow})`,
        boxSizing: "border-box",
      }}
    />
  );
};

const Chip: React.FC<{ h: Highlight; t: number }> = ({ h, t }) => {
  const o = clamp01((t - h.t0) / 0.3) * clamp01((h.t1 - t) / HL_OUT);
  if (o <= 0) return null;
  return (
    <div style={{ position: "absolute", left: 64, bottom: 56, opacity: o, transform: `translateY(${(1 - o) * 12}px)`, background: "rgba(10,10,10,0.88)", border: `1px solid ${GOLD}`, borderRadius: 12, padding: "12px 22px", fontFamily: FONT, fontSize: 30, fontWeight: 600, color: INK, boxShadow: "0 8px 30px rgba(0,0,0,0.5)" }}>
      {h.label}
    </div>
  );
};

/** One beat, inside a Sequence that starts at beat.at: footage, then its last frame held. */
const BeatView: React.FC<{ beat: Beat }> = ({ beat }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const local = frame / fps;
  const t = beat.at + local; // scene time
  const last = Math.round(beat.seconds * fps) - 1;
  const video = <OffthreadVideo src={staticFile(beat.src)} muted style={{ width: "100%", height: "100%" }} />;
  return (
    <AbsoluteFill style={{ opacity: ease(clamp01(local / FADE)), background: "#000" }}>
      {/* after the footage, shift the clip so it keeps showing its last frame */}
      <Sequence from={Math.max(0, frame - last)} layout="none">{video}</Sequence>
      {beat.highlights.map((h, i) => <Spotlight key={i} h={h} t={t} />)}
      {beat.highlights.map((h, i) => <Chip key={i} h={h} t={t} />)}
      {beat.note && (
        <div style={{ position: "absolute", right: 64, bottom: 56, maxWidth: 760, background: "rgba(10,10,10,0.88)", border: `1px solid ${GOLD}88`, borderRadius: 12, padding: "12px 20px", fontFamily: FONT, fontSize: 22, color: INK, opacity: clamp01((local - 0.8) / 0.4) }}>
          {beat.note}
        </div>
      )}
    </AbsoluteFill>
  );
};

/** An admin console checkpoint: its beats in turn, each cross-fading over the one before. */
export const AdminBeats: React.FC<{ part: BeatsPart }> = ({ part }) => {
  const { fps } = useVideoConfig();
  return (
    <>
      {part.beats.map((b, i) => {
        const from = Math.round(b.at * fps);
        return (
          <Sequence key={i} from={from} durationInFrames={Math.round(b.end * fps) - from + 1} layout="none">
            <BeatView beat={b} />
          </Sequence>
        );
      })}
    </>
  );
};
