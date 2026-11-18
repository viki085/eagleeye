import React from "react";
import { AbsoluteFill, Freeze, OffthreadVideo, staticFile, useCurrentFrame } from "remotion";
import { FONT, GOLD, INK, clamp01 } from "./data";

export interface AdminPart {
  type: "admin";
  src: string;
  at: number;
  from: number;
  to: number;
  end: number;
  holdUntil: number;
  spot: { t: number; label: string }[];
  note?: string;
}

/**
 * A stretch of an admin console recording (clip time from → to), shown from scene time `at`;
 * after `to` the last frame holds while the narration finishes. The metric being explained is
 * named in a small chip (the recording already carries the gold outline).
 */
export const AdminSegment: React.FC<{ part: AdminPart; t: number; fps: number }> = ({ part, t, fps }) => {
  const frame = useCurrentFrame();
  const local = t - part.at;
  const playing = t <= part.end;
  const video = (
    <OffthreadVideo src={staticFile(part.src)} startFrom={Math.round(part.from * fps)} muted style={{ width: "100%", height: "100%" }} />
  );
  const current = [...part.spot].reverse().find((s) => t >= s.t);
  const chipIn = current ? clamp01((t - current.t) / 0.3) : 0;
  const fadeIn = clamp01(local / 0.35);
  return (
    <AbsoluteFill style={{ opacity: fadeIn, background: "#000" }}>
      {playing ? video : <Freeze frame={frame - Math.round((t - part.end) * fps) - 1}>{video}</Freeze>}
      {current && (
        <div style={{ position: "absolute", left: 64, bottom: 56, opacity: chipIn, transform: `translateY(${(1 - chipIn) * 12}px)`, background: "rgba(10,10,10,0.88)", border: `1px solid ${GOLD}`, borderRadius: 12, padding: "12px 22px", fontFamily: FONT, fontSize: 30, fontWeight: 600, color: INK, boxShadow: "0 8px 30px rgba(0,0,0,0.5)" }}>
          {current.label}
        </div>
      )}
      {part.note && (
        <div style={{ position: "absolute", right: 64, bottom: 56, maxWidth: 760, background: "rgba(10,10,10,0.88)", border: `1px solid ${GOLD}88`, borderRadius: 12, padding: "12px 20px", fontFamily: FONT, fontSize: 22, color: INK, opacity: clamp01((local - 0.5) / 0.4) }}>
          {part.note}
        </div>
      )}
    </AbsoluteFill>
  );
};
