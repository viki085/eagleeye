import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";

const GOLD = "#C5A368";
const GREEN = "#3ddc84";
const FONT = "Inter, 'Segoe UI', system-ui, sans-serif";
const MONO = "'JetBrains Mono', 'Cascadia Mono', Consolas, monospace";

// the diagonal: left (architecture, gold) and right (load test, green)
const SPLIT = "polygon(56% 0, 100% 0, 100% 100%, 44% 100%)";

/** Video 2 thumbnail (1280x720): the architecture's scaling scene on the left, the 2,000-user
 * window wall on the right, split on a diagonal; real frames from the video. Same badge and
 * logo placement as the product video's thumbnail, so the two read as a series. */
export const Thumbnail2: React.FC = () => (
  <AbsoluteFill style={{ background: "#0a0a0a", fontFamily: FONT, overflow: "hidden" }}>
    {/* left: the cluster core of the architecture (API, Redis, agent workers x9) */}
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 35% 50%, #1c1912 0%, #0a0a0a 72%)" }}>
      <Img src={staticFile("thumb2-arch.png")} style={{ position: "absolute", width: 1560, left: -520, top: -105, opacity: 0.95 }} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse 520px 220px at 0% 0%, rgba(10,10,10,0.95) 40%, rgba(10,10,10,0) 100%), linear-gradient(0deg, rgba(10,10,10,1) 0%, rgba(10,10,10,0.92) 14%, rgba(10,10,10,0) 34%), linear-gradient(180deg, rgba(10,10,10,1) 0%, rgba(10,10,10,0) 8%)" }} />
      <AbsoluteFill style={{ background: "linear-gradient(90deg, rgba(10,10,10,0.15), rgba(10,10,10,0) 40%, rgba(10,10,10,0.5) 60%)" }} />
    </AbsoluteFill>

    {/* right: the window wall, darkened, green */}
    <AbsoluteFill style={{ clipPath: SPLIT }}>
      <Img src={staticFile("thumb2-wall.png")} style={{ position: "absolute", width: 1280, height: 720, objectFit: "cover", filter: "brightness(0.85)" }} />
      <AbsoluteFill style={{ background: "rgba(0,40,14,0.5)" }} />
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 80% 50%, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0) 60%)" }} />
    </AbsoluteFill>
    {/* the seam */}
    <svg width={1280} height={720} style={{ position: "absolute", inset: 0 }}>
      <line x1={1280 * 0.56} y1={0} x2={1280 * 0.44} y2={720} stroke={GREEN} strokeWidth={4} opacity={0.9} />
      <line x1={1280 * 0.56 - 7} y1={0} x2={1280 * 0.44 - 7} y2={720} stroke={GOLD} strokeWidth={3} opacity={0.8} />
    </svg>

    {/* logo (as on the first thumbnail) */}
    <div style={{ position: "absolute", left: 56, top: 48, display: "flex", alignItems: "center", gap: 16 }}>
      <Img src={staticFile("brand/eagleeye-icon.png")} style={{ width: 64, height: 64, borderRadius: 14, boxShadow: `0 0 36px ${GOLD}55` }} />
      <div style={{ color: "#f4f1ea", fontSize: 44, fontWeight: 800, textShadow: "0 2px 12px rgba(0,0,0,0.8)" }}>EagleEye</div>
    </div>

    {/* the hook */}
    <div style={{ position: "absolute", right: 56, top: 200, textAlign: "right", fontFamily: MONO }}>
      <div style={{ color: GREEN, fontSize: 104, fontWeight: 800, lineHeight: 1, textShadow: `0 0 30px ${GREEN}99, 0 4px 16px rgba(0,0,0,0.9)` }}>2,000</div>
      <div style={{ color: GREEN, fontSize: 56, fontWeight: 800, letterSpacing: 6, textShadow: `0 0 24px ${GREEN}88, 0 4px 14px rgba(0,0,0,0.9)` }}>USERS</div>
      <div style={{ marginTop: 34, display: "inline-block", background: "rgba(0,0,0,0.72)", border: `2px solid ${GREEN}aa`, borderRadius: 12, padding: "10px 20px", color: "#ffffff", fontSize: 46, fontWeight: 800 }}>
        27 s <span style={{ color: GREEN }}>→</span> 8 s
      </div>
      <div style={{ marginTop: 10, color: "#cfe9d6", fontSize: 20, fontFamily: FONT, fontWeight: 600, textShadow: "0 2px 8px rgba(0,0,0,0.9)" }}>
        response time, as the cluster scales
      </div>
    </div>

    {/* corner badge (as on the first thumbnail) */}
    <div style={{ position: "absolute", left: 56, bottom: 46, color: "#cfcac0", fontSize: 20, fontWeight: 700, letterSpacing: 3, textTransform: "uppercase", textShadow: "0 2px 10px rgba(0,0,0,0.9)" }}>
      How it works &amp; scales · 6 min
    </div>
  </AbsoluteFill>
);
