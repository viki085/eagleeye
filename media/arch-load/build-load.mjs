// Builds public/load-timeline.json for Part 2 (the load test): each scene's visuals (window wall
// stages, admin console segments, the response-time graph, cards), the voice lines placed on
// their anchors (copied at 1.25x speed), and scene lengths that fit them.
//   node arch-load/build-load.mjs      (run from media/, after prep-load.py)
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import ffmpeg from "ffmpeg-static";

const FPS = 30;
const TEMPO = 1.25;
const GAP = 0.35;
const durations = JSON.parse(readFileSync("audio/durations.json", "utf8"));
const lines = JSON.parse(readFileSync("arch-load/lines-part2.json", "utf8"));
const data = JSON.parse(readFileSync("public/load-data.json", "utf8"));
mkdirSync("public/load-lines", { recursive: true });
const sec = (id) => durations[id].seconds / TEMPO;
const mark = (clip, label) => data.admin[clip].marks.find((m) => m.label === label).t;

// An admin segment: clip time [from, to] shown from scene time `at`; `lines` anchor voice lines
// to the clip's marks (scene time = at + mark - from).
const admin = (src, at, from, to, anchored) => ({
  type: "admin", src: `load/${src}.mp4`, at, from, to,
  anchors: Object.fromEntries(anchored.map(([id, label]) => [id, at + mark(src, label) - from])),
  spot: data.admin[src].marks.filter((m) => m.t >= from && m.t <= to).map((m) => ({ t: at + m.t - from, label: m.label })),
});

// run-time windows (seconds into the load test) each wall stage covers: the user counter and the
// k6 log follow the real run
const SCENES = [
  { n: 7, min: 15, anchors: { "b7-01": 1.2 }, parts: [{ type: "briefing", at: 0 }] },
  {
    n: 8, min: 10.5, anchors: { "b8-01": 0.8 },
    parts: [{ type: "wall", at: 0, stages: [[0, 1], [2.5, 2], [5, 4], [7.5, 8]], run: [0, 250] }],
  },
  {
    n: 9, min: 51,
    parts: [
      { type: "wall", at: 0, stages: [[0, 16], [2.5, 64]], run: [250, 420], until: 5.2 },
      admin("admin-500", 5.5, 2.2, 33.0, [["b9-01", "Online now"], ["b9-02", "Answers in progress"], ["b9-03", "Request volume and outcomes"]]),
      { type: "chart", after: "admin", upTo: 10.5, callout: { minutes: [6, 9], label: "500 users" } , line: "b9-04" },
    ],
  },
  {
    n: 10, min: 33,
    parts: [
      { type: "wall", at: 0, stages: [[0, 64], [1.6, 256]], run: [420, 650], until: 3.8 },
      admin("admin-1000", 4.0, 2.2, 19.5, [["b10-01", "Avg response time"], ["b10-02", "Slowest pipeline steps"]]),
      { type: "chart", after: "admin", upTo: 14.5, callout: { minutes: [10, 13], label: "1,000 users" }, line: "b10-03" },
    ],
  },
  {
    n: 11, min: 66,
    parts: [
      { type: "wall", at: 0, stages: [[0, 256]], run: [650, 930], until: 3.3, glitch: true },
      admin("admin-2000", 3.5, 16.4, 44.0, [["b11-01", "Safety events by category"], ["b11-02", "Request routing distribution"]]),
      { ...admin("admin-cost", 0, 2.2, 21.0, [["b11-03", "LLM cost"]]), after: "admin", note: "Model simulated · cost estimated at gpt-6-luna rates from the recorded token counts" },
      { type: "chart", after: "admin", upTo: 21.5, callout: { minutes: [15, 18], label: "2,000 users" }, line: "b11-04" },
    ],
  },
  { n: 12, min: 12, anchors: { "b12-01": 1.0 }, parts: [{ type: "results", at: 0, run: [1220, 1420] }] },
  { n: 13, min: 20, anchors: { "b13-01": 1.6 }, parts: [{ type: "summary", at: 0 }] },
  { n: 14, min: 7, anchors: { "b14-01": 0.8 }, parts: [{ type: "logo", at: 0 }] },
];

const scenes = [];
const placed = [];
let start = 0;
for (const s of SCENES) {
  const anchors = { ...(s.anchors ?? {}) };
  const parts = [];
  let cursor = 0; // end of the previous segment (scene time), for parts placed "after"
  let lineEnd = 0;
  const place = (id, at) => {
    const t = Math.max(at, lineEnd ? lineEnd + GAP : 0);
    execFileSync(ffmpeg, ["-hide_banner", "-loglevel", "error", "-y", "-i", `audio/lines/${id}.wav`, "-filter:a", `atempo=${TEMPO}`, `public/load-lines/${id}.wav`]);
    placed.push({ id, src: `load-lines/${id}.wav`, from: Math.round((start + t) * FPS), frames: Math.round(sec(id) * FPS) });
    lineEnd = t + sec(id);
    return t;
  };
  for (const p of s.parts) {
    if (p.type === "admin") {
      const shift = p.after ? Math.max(cursor, lineEnd) + 0.4 - p.at : 0;
      const seg = { ...p, at: p.at + shift, spot: p.spot.map((x) => ({ ...x, t: x.t + shift })) };
      for (const [id, t] of Object.entries(p.anchors)) place(id, t + shift);
      seg.end = seg.at + (seg.to - seg.from);
      seg.holdUntil = Math.max(seg.end, lineEnd + 0.3); // freeze the last frame while a line ends
      cursor = seg.holdUntil;
      delete seg.anchors;
      parts.push(seg);
    } else if (p.type === "chart") {
      const at = Math.max(cursor, lineEnd) + 0.4;
      const t = place(p.line, at + 0.5);
      parts.push({ ...p, at, end: Math.max(at + 8, t + sec(p.line) + 0.6) });
      cursor = parts.at(-1).end;
    } else {
      parts.push(p);
      cursor = Math.max(cursor, p.until ?? 0);
    }
  }
  for (const [id, at] of Object.entries(anchors)) place(id, at);
  const length = Math.max(s.min, lineEnd + 0.8, cursor + 0.3);
  scenes.push({ n: s.n, start: +start.toFixed(2), length: +length.toFixed(2), parts });
  start += length;
}

const timeline = { fps: FPS, durationInFrames: Math.round(start * FPS), scenes, lines: placed };
writeFileSync("public/load-timeline.json", JSON.stringify(timeline, null, 2));
console.log(`Part 2: ${Math.floor(start / 60)}:${String(Math.round(start % 60)).padStart(2, "0")}`);
for (const s of scenes) console.log(`  scene ${s.n}: ${s.start.toFixed(1)}s +${s.length.toFixed(1)}s`);
