import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";

const GOLD = "#C5A368";
const FONT = "Inter, 'Segoe UI', system-ui, sans-serif";
export const CROSSFADE_S = 1.0; // overlaps the end of the "Built with" card

/** Closing frame: cross-fades in over the "Built with" card, the logo and name hold, then black. */
export const LogoOutro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const fadeIn = interpolate(frame, [0, CROSSFADE_S * fps], [0, 1], { extrapolateRight: "clamp" });
  const nameIn = interpolate(frame, [0.5 * fps, 1.4 * fps], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const toBlack = interpolate(frame, [durationInFrames - 0.8 * fps, durationInFrames - 1], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ opacity: fadeIn }}>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 42%, #1a1712 0%, #0a0a0a 65%)", justifyContent: "center", alignItems: "center", fontFamily: FONT }}>
        <Img src={staticFile("brand/eagleeye-icon.png")} style={{ width: 176, height: 176, borderRadius: 36, boxShadow: `0 0 90px ${GOLD}33` }} />
        <div style={{ marginTop: 36, color: "#f4f1ea", fontSize: 84, fontWeight: 700, letterSpacing: 1, opacity: nameIn }}>EagleEye</div>
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "#000", opacity: toBlack }} />
    </AbsoluteFill>
  );
};
