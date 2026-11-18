import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";

const GOLD = "#C5A368";
const FONT = "Inter, 'Segoe UI', system-ui, sans-serif";

/** The zoom-out chain, innermost first. Each image is composed so the previous subject could sit
 * at its centre; a feathered round mask blends the hand-off. */
export const LAYERS = [
  "finale/01-ruins.png",
  "finale/02-pyramids.png",
  "finale/03-skyline.png",
  "finale/04-earth.png",
  "finale/05-solar-system.png",
  "finale/06-galaxy.png",
  "finale/07-universe.png",
  "finale/08-eye.png",
];
// how far each layer shrinks as the next takes over; the universe must end up inside the small pupil
const KS = [3.2, 3.2, 3.2, 3.2, 3.2, 3.2, 7.5];
const ZOOM_S = 8.6; // the chain; the logo reveal takes the rest of the 10 s

const ease = (t: number) => t * t * (3 - 2 * t);

const Layer: React.FC<{ src: string; scale: number; feather: boolean; opacity?: number }> = ({ src, scale, feather, opacity = 1 }) => (
  <AbsoluteFill style={{ transform: `scale(${scale})`, opacity }}>
    <Img
      src={staticFile(src)}
      style={{
        width: "100%",
        height: "100%",
        objectFit: "cover",
        // inner layers fade out at the edge so they melt into the layer around them
        WebkitMaskImage: feather ? "radial-gradient(ellipse 50% 50% at 50% 50%, #000 62%, transparent 100%)" : undefined,
        maskImage: feather ? "radial-gradient(ellipse 50% 50% at 50% 50%, #000 62%, transparent 100%)" : undefined,
      }}
    />
  </AbsoluteFill>
);

/** 10 seconds: ruins → pyramids → skyline → Earth → solar system → galaxy → universe, which turns
 * out to sit inside the pupil of an eye; the eye pulls back and becomes the EagleEye logo. */
export const CosmicZoom: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const zoomFrames = ZOOM_S * fps;
  const beat = zoomFrames / (LAYERS.length - 1); // hand-offs between consecutive layers
  const pos = Math.min(frame / beat, LAYERS.length - 1 - 1e-6);
  const i = Math.floor(pos);
  const p = ease(pos - i);
  const outer = LAYERS[i + 1];
  const inner = LAYERS[i];

  // logo reveal: the eye pulls back and fades as the logo and the name come in
  const reveal = interpolate(frame, [zoomFrames - 6, 10 * fps - 12], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const eyeFade = 1 - ease(Math.min(1, reveal * 1.4));
  const logoIn = ease(Math.min(1, Math.max(0, reveal * 1.3 - 0.15)));
  const nameIn = ease(Math.min(1, Math.max(0, reveal * 1.6 - 0.7)));

  return (
    <AbsoluteFill style={{ background: "#050505", overflow: "hidden" }}>
      <AbsoluteFill style={{ opacity: eyeFade, transform: `scale(${1 - 0.35 * reveal})` }}>
        <Layer src={outer} scale={Math.pow(KS[i], 1 - p)} feather={false} />
        <Layer src={inner} scale={Math.pow(KS[i], -p)} feather opacity={1 - Math.max(0, p - 0.85) / 0.15} />
      </AbsoluteFill>
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", fontFamily: FONT }}>
        <Img
          src={staticFile("brand/eagleeye-icon.png")}
          style={{ width: 200, height: 200, borderRadius: 42, opacity: logoIn, transform: `scale(${0.75 + 0.25 * logoIn})`, boxShadow: `0 0 ${120 * logoIn}px ${GOLD}55` }}
        />
        <div style={{ marginTop: 34, color: "#f4f1ea", fontSize: 88, fontWeight: 700, letterSpacing: 1, opacity: nameIn }}>EagleEye</div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
