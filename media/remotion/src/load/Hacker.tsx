import React from "react";
import { AbsoluteFill, random } from "remotion";
import { AMBER, GREEN, MONO, MUTED, answersUpTo, clamp01, fmt } from "./data";

/** Faint scanlines and a vignette over the hacker-movie scenes. */
export const Scanlines: React.FC = () => (
  <AbsoluteFill
    style={{
      pointerEvents: "none",
      background:
        "repeating-linear-gradient(0deg, rgba(0,0,0,0.18) 0px, rgba(0,0,0,0.18) 1px, transparent 2px, transparent 4px), radial-gradient(ellipse at 50% 50%, transparent 55%, rgba(0,0,0,0.55) 100%)",
    }}
  />
);

/** Typed terminal lines (characters appear over time from `t`). */
export const Typed: React.FC<{ lines: string[]; t: number; cps?: number; size?: number }> = ({ lines, t, cps = 38, size = 34 }) => {
  let budget = Math.max(0, t) * cps;
  return (
    <div style={{ fontFamily: MONO, fontSize: size, color: GREEN, lineHeight: 1.7, whiteSpace: "pre" }}>
      {lines.map((line, i) => {
        const shown = line.slice(0, Math.max(0, Math.floor(budget)));
        budget -= line.length + 6; // a short pause between lines
        const typing = shown.length < line.length && shown.length > 0;
        return (
          <div key={i} style={{ minHeight: size * 1.7 }}>
            {shown}
            {(typing || (i === lines.length - 1 && shown.length === line.length)) && (
              <span style={{ opacity: Math.floor(t * 2.4) % 2 ? 1 : 0.15 }}>▌</span>
            )}
          </div>
        );
      })}
    </div>
  );
};

const KIND: Record<string, string> = { docs: "docs ", sql: "sql  ", chart: "chart", attack: "BLOCK", notebook: "nbook" };

/** The k6 log: the real answers as they finished, by run time. */
export const K6Log: React.FC<{ runT: number; rows?: number; width?: number }> = ({ runT, rows = 16, width = 470 }) => {
  const lines = answersUpTo(runT, rows);
  return (
    <div style={{ width, fontFamily: MONO, fontSize: 19, lineHeight: 1.55, color: GREEN, background: "rgba(0,10,4,0.82)", border: `1px solid ${GREEN}44`, borderRadius: 10, padding: "14px 18px", boxShadow: `0 0 40px ${GREEN}22` }}>
      <div style={{ color: MUTED, marginBottom: 6 }}>k6 · answers as they finish</div>
      {lines.map(([t, kind, s, ok], i) => {
        const m = Math.floor(t / 60);
        const sec = Math.floor(t % 60);
        return (
          <div key={`${t}-${i}`} style={{ opacity: 0.45 + (0.55 * (i + 1)) / lines.length, color: kind === "attack" ? AMBER : ok ? GREEN : "#ff5f56", whiteSpace: "pre" }}>
            {`+${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}  ${ok ? "✓" : "✗"} ${KIND[kind] ?? kind}  ${s.toFixed(1).padStart(5)} s`}
          </div>
        );
      })}
    </div>
  );
};

/** Big user counter (top right). */
export const UserCounter: React.FC<{ users: number; label?: string }> = ({ users, label = "USERS ONLINE" }) => (
  <div style={{ position: "absolute", top: 46, right: 64, textAlign: "right", fontFamily: MONO, color: GREEN, textShadow: `0 0 24px ${GREEN}88` }}>
    <div style={{ fontSize: 22, letterSpacing: 6, color: `${GREEN}cc` }}>{label}</div>
    <div style={{ fontSize: 104, fontWeight: 700, lineHeight: 1 }}>{fmt(users)}</div>
  </div>
);

/** RGB-split jitter for a few frames at a time (the 2,000-user glitch). */
export function glitch(frame: number, on: boolean): React.CSSProperties {
  if (!on) return {};
  const burst = random(`g${Math.floor(frame / 9)}`) > 0.55;
  if (!burst) return {};
  const dx = (random(`x${frame}`) - 0.5) * 26;
  return { transform: `translateX(${dx}px)`, filter: `drop-shadow(${dx / 2}px 0 0 rgba(255,0,60,0.55)) drop-shadow(${-dx / 2}px 0 0 rgba(0,220,255,0.55))` };
}

/** Fade helper shared by scenes. */
export const appear = (t: number, at: number, dur = 0.4) => clamp01((t - at) / dur);
