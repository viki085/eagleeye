import React from "react";
import { AbsoluteFill, Audio, Img, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import * as si from "simple-icons";
import { COLORS, EDGES, LAYERS, LEGEND, NODES, curve, hopPath, type ArchNode, type Traffic } from "./graph";
import { SCALE, SCENES, type Ev } from "./scenes";

const GOLD = "#C5A368";
const FONT = "Inter, 'Segoe UI', system-ui, sans-serif";
const TILE = 112;

export interface ArchLine { id: string; src: string; from: number; frames: number }
export interface ArchTimeline {
  fps: number;
  durationInFrames: number;
  scenes: { n: number; start: number; length: number }[]; // seconds
  lines: ArchLine[];
}

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
const fade = (t: number, start: number, dur: number, edge = 0.35) =>
  clamp01(Math.min((t - start) / edge, (start + dur - t) / edge));

/** Step value from [time, value] pairs (the last reached pair wins). */
function stepAt(points: [number, number][], t: number): number {
  let v = points[0][1];
  for (const [at, val] of points) if (t >= at) v = val;
  return v;
}
/** Smooth value between [time, value] pairs. */
function rampAt(points: [number, number][], t: number): number {
  if (t <= points[0][0]) return points[0][1];
  for (let i = 1; i < points.length; i++) {
    const [t0, v0] = points[i - 1];
    const [t1, v1] = points[i];
    if (t <= t1) return v0 + (v1 - v0) * ((t - t0) / (t1 - t0));
  }
  return points[points.length - 1][1];
}

function visible(hex: string): string {
  const n = parseInt(hex, 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b < 70 ? "#f2f2f2" : `#${hex}`;
}

const Person: React.FC = () => (
  <svg viewBox="0 0 24 24" width={50} height={50} fill="none" stroke="#e8e4da" strokeWidth={1.6} strokeLinecap="round">
    <circle cx="12" cy="8" r="4" />
    <path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" />
  </svg>
);

const Tile: React.FC<{ node: ArchNode; opacity: number; glow: Traffic | null; replicas: number }> = ({ node, opacity, glow, replicas }) => {
  const icon = node.icon ? (si[node.icon] as { path: string; hex: string } | undefined) : undefined;
  const color = glow ? COLORS[glow] : null;
  return (
    <div style={{ position: "absolute", left: node.x - TILE / 2, top: node.y - TILE / 2, width: TILE, opacity, transition: "none" }}>
      {/* stacked copies behind the tile when the service has several running tasks */}
      {Array.from({ length: Math.min(replicas - 1, 10) }).map((_, k) => (
        <div
          key={k}
          style={{
            position: "absolute", left: 7 * (k + 1), top: -7 * (k + 1), width: TILE, height: TILE, borderRadius: 24,
            background: "#141416", border: `1px solid ${GOLD}55`, opacity: 0.9 - k * 0.07,
          }}
        />
      ))}
      <div
        style={{
          position: "relative", width: TILE, height: TILE, borderRadius: 24, background: "#141416",
          border: `2px solid ${color ?? "#2c2c31"}`, display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: color ? `0 0 38px ${color}aa, inset 0 0 18px ${color}33` : "0 6px 20px rgba(0,0,0,0.5)",
          transform: color ? "scale(1.06)" : "none",
        }}
      >
        {node.person ? (
          <Person />
        ) : icon ? (
          <svg viewBox="0 0 24 24" width={52} height={52}>
            <path d={icon.path} fill={visible(icon.hex)} />
          </svg>
        ) : (
          <span style={{ color: GOLD, fontSize: 32, fontWeight: 800, fontFamily: FONT }}>{node.letters}</span>
        )}
        {replicas > 1 && (
          <div style={{ position: "absolute", right: -14, bottom: -12, padding: "2px 9px", borderRadius: 999, background: GOLD, color: "#111", fontSize: 18, fontWeight: 800, fontFamily: FONT }}>
            ×{replicas}
          </div>
        )}
      </div>
      <div style={{ marginTop: 10, width: 220, marginLeft: -54, textAlign: "center", fontFamily: FONT }}>
        <div style={{ color: "#f1ede4", fontSize: 21, fontWeight: 700 }}>{node.label}</div>
        {node.sub && <div style={{ color: "#8e8a82", fontSize: 15, marginTop: 2 }}>{node.sub}</div>}
      </div>
    </div>
  );
};

const Badge: React.FC<{ node: ArchNode; text: string; traffic: Traffic; opacity: number }> = ({ node, text, traffic, opacity }) => (
  <div
    style={{
      position: "absolute", left: node.x, top: node.y - TILE / 2 - 50, transform: `translate(-50%, ${(1 - opacity) * 8}px)`,
      opacity, padding: "7px 14px", borderRadius: 10, whiteSpace: "nowrap", fontFamily: FONT, fontSize: 18, fontWeight: 700,
      color: "#0d0d0d", background: COLORS[traffic], boxShadow: `0 0 24px ${COLORS[traffic]}88`,
    }}
  >
    {text}
  </div>
);

const Title: React.FC<{ t: number }> = ({ t }) => {
  const logo = clamp01((t - 0.2) / 2.2);
  const typedText = "How it works, and how it scales";
  const typed = typedText.slice(0, Math.max(0, Math.floor((t - 1.8) * 22)));
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 42%, #1a1712 0%, #0a0a0a 65%)", justifyContent: "center", alignItems: "center", fontFamily: FONT }}>
      <Img src={staticFile("brand/eagleeye-icon.png")} style={{ width: 160, height: 160, borderRadius: 34, opacity: logo, boxShadow: `0 0 ${80 * logo}px ${GOLD}33` }} />
      <div style={{ marginTop: 30, color: "#f4f1ea", fontSize: 76, fontWeight: 700, opacity: logo }}>EagleEye</div>
      <div style={{ marginTop: 16, height: 46, color: GOLD, fontSize: 38, fontWeight: 500, letterSpacing: 1 }}>
        {typed}
        {typed.length < typedText.length && t > 1.8 && <span style={{ opacity: Math.floor(t * 3) % 2 ? 1 : 0 }}>▍</span>}
      </div>
    </AbsoluteFill>
  );
};

function Diagram({ n, t }: { n: number; t: number }) {
  const scene = SCENES[n];
  const isScale = n === 6;
  const events = scene.events;
  const active = (ev: Ev) => ("dur" in ev ? t >= ev.t && t <= ev.t + ev.dur : false);

  // which nodes are visible (scene 1 builds them up layer by layer)
  const layerOrder = ["People", "Front end", "Edge", "Application", "Data", "AI & compute", "Operations"];
  const shown = (node: ArchNode) => {
    if (node.scaleOnly) return isScale ? clamp01((t - 1.0) / 0.6) : 0;
    if (n !== 1) return 1;
    return clamp01((t - 0.3 - layerOrder.indexOf(node.layer) * 0.75) / 0.5);
  };
  const focused = (id: string) => scene.focus === "all" || scene.focus.includes(id);
  // in "the big picture", the second line points at Vercel and Clerk, then at AWS
  const bigPictureHighlight = (id: string): Traffic | null => {
    if (n !== 1) return null;
    if (t > 11 && t < 15.5 && (id === "vercel" || id === "clerk")) return "request";
    if (t > 15.5 && t < 20 && ["api", "redis", "agent", "ingest", "gateway", "s3", "lambda", "cloudwatch", "cloudfront"].includes(id)) return "file";
    return null;
  };
  const glowOf = (id: string): Traffic | null => {
    const g = [...events].reverse().find((e) => e.kind === "glow" && e.node === id && active(e)) as Extract<Ev, { kind: "glow" }> | undefined;
    return g?.traffic ?? bigPictureHighlight(id);
  };
  const replicas = (id: string) => {
    if (!isScale) return 1;
    const pts = (SCALE.tasks as Record<string, [number, number][]>)[id];
    return pts ? stepAt(pts, t) : 1;
  };

  const hops = events.filter((e) => e.kind === "hop" && t >= e.t && t <= e.t + e.dur + 0.25) as Extract<Ev, { kind: "hop" }>[];
  const caption = [...events].reverse().find((e) => e.kind === "caption" && active(e)) as Extract<Ev, { kind: "caption" }> | undefined;
  const legendIn = n === 1 ? clamp01((t - 5.6) / 0.6) : 1;
  const users = isScale ? Math.round(rampAt(SCALE.usersAt, t)) : 0;

  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 55% 45%, #15130f 0%, #09090a 72%)", fontFamily: FONT }}>
      {/* layer headers */}
      {LAYERS.map(([label, x]) => (
        <div key={label} style={{ position: "absolute", left: x - 140, width: 280, top: 92, textAlign: "center", color: "#6e6a62", fontSize: 15, fontWeight: 700, letterSpacing: 3, textTransform: "uppercase", opacity: isScale ? 0 : n === 1 ? clamp01(t / 1) : 0.9 }}>
          {label}
        </div>
      ))}
      {/* AWS region frame */}
      <div style={{ position: "absolute", left: 525, top: 150, width: 1325, height: 870, borderRadius: 28, border: `1.5px dashed ${isScale ? "#ff9900aa" : "#ffffff1a"}`, opacity: n === 1 ? clamp01((t - 2.2) / 0.8) : 1 }}>
        <div style={{ position: "absolute", left: 20, top: -13, padding: "0 10px", background: "#0d0c0b", color: isScale ? "#ff9900" : "#77736b", fontSize: 15, fontWeight: 700, letterSpacing: 2 }}>
          {isScale ? "AWS · ECS FARGATE CLUSTER (AUTOSCALING)" : "AWS"}
        </div>
      </div>

      {/* connectors and pulses */}
      <svg viewBox="0 0 1920 1080" style={{ position: "absolute", inset: 0 }}>
        <defs>
          <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="5" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        {EDGES.map(([a, b, bend]) => {
          const scaleEdge = NODES[a].scaleOnly || NODES[b].scaleOnly;
          const op = Math.min(shown(NODES[a]), shown(NODES[b])) * (scaleEdge && !isScale ? 0 : 1);
          const busy = hops.find((h) => (h.from === a && h.to === b) || (h.from === b && h.to === a));
          const dim = focused(a) && focused(b) ? 1 : 0.35;
          return (
            <path key={`${a}-${b}`} d={curve(a, b, bend).d} fill="none" stroke={busy ? COLORS[busy.traffic] : "#ffffff"} strokeOpacity={(busy ? 0.55 : 0.1) * op * dim} strokeWidth={busy ? 2.4 : 1.6} />
          );
        })}
        {hops.map((h, i) => {
          const p = hopPath(h.from, h.to);
          const s = clamp01((t - h.t) / h.dur);
          const tail = Array.from({ length: 6 }, (_, k) => clamp01(s - k * 0.035));
          const color = COLORS[h.traffic];
          const life = t > h.t + h.dur ? 1 - (t - h.t - h.dur) / 0.25 : 1;
          return (
            <g key={i} opacity={life} filter="url(#glow)">
              {tail.map((ts, k) => {
                const q = p.at(ts);
                return <circle key={k} cx={q.x} cy={q.y} r={9 - k * 1.3} fill={color} opacity={1 - k * 0.15} />;
              })}
            </g>
          );
        })}
      </svg>

      {/* nodes */}
      {Object.entries(NODES).map(([id, node]) => {
        const op = shown(node) * (focused(id) ? 1 : 0.3);
        if (op <= 0) return null;
        return <Tile key={id} node={node} opacity={op} glow={glowOf(id)} replicas={replicas(id)} />;
      })}
      {events.filter((e) => e.kind === "badge" && active(e)).map((e, i) => {
        const b = e as Extract<Ev, { kind: "badge" }>;
        return <Badge key={i} node={NODES[b.node]} text={b.text} traffic={b.traffic} opacity={fade(t, b.t, b.dur)} />;
      })}

      {/* scene title */}
      <div style={{ position: "absolute", left: 60, top: 36, color: "#f1ede4", fontSize: 30, fontWeight: 800 }}>
        <span style={{ color: GOLD, marginRight: 14 }}>{n}</span>
        {scene.title}
      </div>

      {/* legend */}
      <div style={{ position: "absolute", left: 60, bottom: 40, display: "flex", flexDirection: "column", gap: 8, opacity: legendIn * 0.95 }}>
        {LEGEND.map(([k, label]) => (
          <div key={k} style={{ display: "flex", alignItems: "center", gap: 10, color: "#a9a59c", fontSize: 15, fontWeight: 600 }}>
            <span style={{ width: 13, height: 13, borderRadius: 999, background: COLORS[k], boxShadow: `0 0 10px ${COLORS[k]}` }} />
            {label}
          </div>
        ))}
      </div>

      {/* caption */}
      {caption && (
        <div style={{ position: "absolute", left: 360, right: 360, bottom: 34, textAlign: "center", opacity: fade(t, caption.t, caption.dur) }}>
          <span style={{ display: "inline-block", padding: "10px 22px", borderRadius: 12, background: "rgba(12,12,12,0.85)", border: "1px solid #2b2b2f", color: "#ece8de", fontSize: 22, fontWeight: 600 }}>
            {caption.text}
          </span>
        </div>
      )}

      {/* scaling: users online and the queue metric */}
      {isScale && (
        <>
          <div style={{ position: "absolute", right: 70, top: 30, textAlign: "right" }}>
            <div style={{ color: "#8e8a82", fontSize: 16, fontWeight: 700, letterSpacing: 3 }}>USERS ONLINE</div>
            <div style={{ color: "#f4f1ea", fontSize: 64, fontWeight: 800, fontVariantNumeric: "tabular-nums" }}>{users.toLocaleString("en-US")}</div>
          </div>
          <div style={{ position: "absolute", left: NODES.cloudwatch.x - 330, top: NODES.cloudwatch.y - 34, width: 230 }}>
            <div style={{ color: "#a9a59c", fontSize: 14, fontWeight: 700, letterSpacing: 1 }}>QUEUED ANSWERS PER WORKER</div>
            <div style={{ marginTop: 6, height: 10, borderRadius: 6, background: "#ffffff14", overflow: "hidden" }}>
              <div style={{ width: `${Math.min(100, (users / 2000) * 100 * (0.5 + 0.5 * Math.sin(t * 1.3) ** 2))}%`, height: "100%", background: "#ff9900" }} />
            </div>
          </div>
          {SCALE.preliminary && (
            <div style={{ position: "absolute", right: 70, top: 128, color: "#77736b", fontSize: 14 }}>Preliminary task counts · replaced by the real counts from the load test</div>
          )}
        </>
      )}
    </AbsoluteFill>
  );
}

export const Architecture: React.FC<{ timeline: ArchTimeline }> = ({ timeline }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const T = frame / fps;
  const current = [...timeline.scenes].reverse().find((s) => T >= s.start) ?? timeline.scenes[0];
  const t = T - current.start;
  const sceneFade = interpolate(t, [0, 0.5], [0, 1], { extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ background: "#09090a" }}>
      <AbsoluteFill style={{ opacity: current.n === 1 ? 1 : sceneFade }}>
        {current.n === 0 ? <Title t={t} /> : <Diagram n={current.n} t={t} />}
      </AbsoluteFill>
      {timeline.lines.map((l) => (
        <Sequence key={l.id} from={l.from} durationInFrames={l.frames}>
          <Audio src={staticFile(l.src)} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
