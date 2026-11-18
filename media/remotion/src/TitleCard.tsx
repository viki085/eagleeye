import React from "react";
import { AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";

const GOLD = "#C5A368";
const FONT = "Inter, 'Segoe UI', system-ui, sans-serif";

/** Cold open: the logo settles in, the name, then the subtitle is typed. */
export const TitleCard: React.FC<{ title: string; subtitle: string }> = ({ title, subtitle }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({ frame, fps, config: { damping: 18, mass: 0.8 } });
  const nameIn = interpolate(frame, [12, 30], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const typed = subtitle.slice(0, Math.max(0, Math.floor((frame - 34) / 1.6)));
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 40%, #1a1712 0%, #0a0a0a 65%)", justifyContent: "center", alignItems: "center", fontFamily: FONT }}>
      <Img src={staticFile("brand/eagleeye-icon.png")} style={{ width: 168, height: 168, borderRadius: 34, transform: `scale(${0.6 + 0.4 * pop})`, opacity: pop, boxShadow: `0 0 80px ${GOLD}33` }} />
      <div style={{ marginTop: 34, color: "#f4f1ea", fontSize: 84, fontWeight: 700, letterSpacing: 1, opacity: nameIn }}>{title}</div>
      <div style={{ marginTop: 18, height: 40, color: GOLD, fontSize: 32, fontWeight: 500, letterSpacing: 1.5 }}>
        {typed}
        {typed.length < subtitle.length && frame > 34 && <span style={{ opacity: frame % 20 < 10 ? 1 : 0 }}>▍</span>}
      </div>
    </AbsoluteFill>
  );
};
