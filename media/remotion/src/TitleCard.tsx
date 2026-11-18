import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";

const GOLD = "#C5A368";
const FONT = "Inter, 'Segoe UI', system-ui, sans-serif";

/** Cold open: the logo and the name fade in slowly. */
export const TitleCard: React.FC<{ title: string }> = ({ title }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const logo = interpolate(frame, [0.3 * fps, 3.2 * fps], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const name = interpolate(frame, [1.8 * fps, 4.2 * fps], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 42%, #1a1712 0%, #0a0a0a 65%)", justifyContent: "center", alignItems: "center", fontFamily: FONT }}>
      <Img src={staticFile("brand/eagleeye-icon.png")} style={{ width: 176, height: 176, borderRadius: 36, opacity: logo, transform: `scale(${0.94 + 0.06 * logo})`, boxShadow: `0 0 ${90 * logo}px ${GOLD}33` }} />
      <div style={{ marginTop: 36, color: "#f4f1ea", fontSize: 84, fontWeight: 700, letterSpacing: 1, opacity: name }}>{title}</div>
    </AbsoluteFill>
  );
};

/** A dark card where the first line types out and the second appears beneath it. */
export const TypedCard: React.FC<{ line1: string; line2: string }> = ({ line1, line2 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const typed = line1.slice(0, Math.max(0, Math.floor((frame - 0.3 * fps) / 2.2)));
  const doneAt = 0.3 * fps + line1.length * 2.2;
  const second = interpolate(frame, [doneAt + 6, doneAt + 22], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ background: "#0a0a0a", justifyContent: "center", alignItems: "center", fontFamily: FONT }}>
      <div style={{ color: "#f4f1ea", fontSize: 76, fontWeight: 700, letterSpacing: 1, height: 96 }}>
        {typed}
        {typed.length < line1.length && <span style={{ color: GOLD, opacity: frame % 20 < 10 ? 1 : 0 }}>▍</span>}
      </div>
      <div style={{ marginTop: 20, color: GOLD, fontSize: 38, fontWeight: 500, letterSpacing: 2, opacity: second }}>{line2}</div>
    </AbsoluteFill>
  );
};
