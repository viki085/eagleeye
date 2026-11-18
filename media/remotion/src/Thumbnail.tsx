import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";

const GOLD = "#C5A368";
const FONT = "Inter, 'Segoe UI', system-ui, sans-serif";

/** YouTube / link-preview thumbnail (1280x720): the product promise on the left, a real frame
 * from the video (the meeting brief with a highlighted, cited answer) on the right. */
export const Thumbnail: React.FC = () => (
  <AbsoluteFill style={{ background: "radial-gradient(ellipse at 30% 45%, #1c1912 0%, #0a0a0a 70%)", fontFamily: FONT, overflow: "hidden" }}>
    {/* product shot: the answer column of the chat, tilted slightly, gold edge */}
    <div
      style={{
        position: "absolute", right: -40, top: 70, width: 760, height: 560, borderRadius: 18, overflow: "hidden",
        border: `2px solid ${GOLD}aa`, boxShadow: `0 0 60px ${GOLD}40, 0 30px 80px rgba(0,0,0,0.6)`,
        transform: "perspective(1400px) rotateY(-14deg) rotateZ(1.5deg)",
      }}
    >
      <Img src={staticFile("thumb-shot.png")} style={{ position: "absolute", width: 2280, left: -560, top: -40 }} />
      <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg, rgba(10,10,10,0.35), rgba(10,10,10,0) 30%)" }} />
    </div>

    {/* the promise */}
    <div style={{ position: "absolute", left: 70, top: 92, width: 560 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
        <Img src={staticFile("brand/eagleeye-icon.png")} style={{ width: 76, height: 76, borderRadius: 16, boxShadow: `0 0 40px ${GOLD}40` }} />
        <div style={{ color: "#f4f1ea", fontSize: 54, fontWeight: 800, letterSpacing: 0.5 }}>EagleEye</div>
      </div>
      <div style={{ marginTop: 44, color: "#ffffff", fontSize: 64, fontWeight: 800, lineHeight: 1.06 }}>
        Ask your company
        <br />
        <span style={{ color: GOLD }}>anything.</span>
      </div>
      <div style={{ marginTop: 26, color: "#cfcac0", fontSize: 27, fontWeight: 500, lineHeight: 1.4 }}>
        Documents, databases and data files,
        <br />
        answered with evidence.
      </div>
      <div style={{ marginTop: 34, display: "flex", gap: 10 }}>
        {["Cited answers", "Text-to-SQL", "EDA notebooks"].map((t) => (
          <div key={t} style={{ padding: "8px 14px", borderRadius: 999, border: `1px solid ${GOLD}77`, color: GOLD, fontSize: 19, fontWeight: 600 }}>
            {t}
          </div>
        ))}
      </div>
    </div>

    {/* corner badge */}
    <div style={{ position: "absolute", left: 70, bottom: 52, color: "#8f8a80", fontSize: 20, fontWeight: 600, letterSpacing: 3, textTransform: "uppercase" }}>
      Product demo · 5 min
    </div>
  </AbsoluteFill>
);
