// Builds the edit (public/timeline.json) from the recorded scenes' markers and the voice lines'
// lengths, and copies the media Remotion needs into public/.
//   node demo/build-timeline.mjs      (run from media/)
//
// Waits are sped up (typing, uploads, the model working) with a visible badge; everything the
// viewer should read plays in real time. Voice lines are placed at anchors in their scene and
// never overlap; if a scene ends before its last line, its final frame is held.
import { execFileSync } from "node:child_process";
import { copyFileSync, cpSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import ffmpeg from "ffmpeg-static";

const FPS = 30;
const PUBLIC = "public";
const durations = JSON.parse(readFileSync("audio/durations.json", "utf8"));
const lines = JSON.parse(readFileSync("demo/lines.json", "utf8"));
const GAP_MS = 350; // silence between consecutive lines
const TEMPO = 1.25; // narration played 25% faster (pitch kept: ffmpeg atempo)

mkdirSync(`${PUBLIC}/scenes`, { recursive: true });
mkdirSync(`${PUBLIC}/lines`, { recursive: true });
cpSync("../apps/web/public/brand", `${PUBLIC}/brand`, { recursive: true });
for (const l of lines) {
  execFileSync(ffmpeg, ["-hide_banner", "-loglevel", "error", "-y", "-i", `audio/lines/${l.id}.wav`, "-filter:a", `atempo=${TEMPO}`, `${PUBLIC}/lines/${l.id}.wav`]);
}

const f = (ms) => Math.round((ms / 1000) * FPS);
const lineMs = (id) => (durations[id].seconds * 1000) / TEMPO;

// speed-up zones per scene: [fromMarker, toMarker, target seconds on screen]
const ZONES = [
  ["typing", "answer_start", null, 3.5], // fixed speed 3.5x for typing
  ["profile", "typing", 5.0],
  ["notebook", "figure_enlarged", 12.0],
  ["upload", "ready", 2.0],
  ["answer_start", "answer_end", 5.0],
];

// where each line starts: [scene, line id, anchor marker, offset ms]
const ANCHORS = [
  [1, "s1-01", "start", 400],
  [2, "s2-01", "start", 600],
  [2, "s2-02", "preview", 300],
  [2, "s2-03", "enterprise", 200],
  [2, "s2-04", "viewer_open", 800],
  [3, "s3-01", "typing", 600], // over the typed request
  [3, "s3-02", "answer_end", 1600], // "built around his notes", over a freeze at the top of the brief
  [3, "s3-03", "read~claim", 200], // each source line plays on the highlight it describes
  [3, "s3-04", "read~alarm|SOP", 200],
  [3, "s3-05", "read~reliab|2026|measure", 200],
  [3, "s3-06", "source_open", 0],
  [4, "s4-01", "read", 0],
  [5, "s5-01", "read", 0],
  [6, "s6-01", "start", 500],
  [6, "s6-02", "answer_start", 600],
  [6, "s6-03", "step_write", 0], // each step line starts when its stage appears in the panel
  [6, "s6-04", "step_run", 0],
  [6, "s6-05", "step_answer", 0],
  [6, "s6-06", "download_hover", -1500],
  [7, "s7-01", "start", 300],
  [7, "s7-02", "read", 300],
];

// freeze frames: [marker, ms after it, how long to hold] — keeps a view on screen while its line plays
const HOLDS = { 2: [["preview", 2600, 7600]], 3: [["answer_end", 1500, 3900]] };

// per-scene zones, checked before the general ones: the EDA wait plays near real time so the
// step-by-step narration fits
const SCENE_ZONES = { 2: [["upload", "ready", null, 1.0]], 6: [["answer_start", "answer_end", null, 1.0]] };

function segmentsFor(markers, endMs, n) {
  const at = (type) => markers.find((m) => m.type === type)?.t;
  const zones = [];
  for (const [a, b, target, fixed] of [...(SCENE_ZONES[n] ?? []), ...ZONES]) {
    const s = at(a), e = at(b);
    if (s === undefined || e === undefined || e <= s) continue;
    if (zones.some((z) => s < z.e && e > z.s)) continue; // first matching zone wins
    const speed = fixed ?? Math.min(16, Math.max(1, (e - s) / (target * 1000)));
    zones.push({ s, e, speed }); // a real-time zone (speed 1) still blocks the general rules
  }
  zones.sort((x, y) => x.s - y.s);
  const segs = [];
  let cursor = 0;
  for (const z of zones) {
    if (z.s > cursor) segs.push({ startMs: cursor, endMs: z.s, speed: 1 });
    segs.push({ startMs: z.s, endMs: z.e, speed: z.speed > 1.05 ? Number(z.speed.toFixed(2)) : 1 });
    cursor = z.e;
  }
  if (cursor < endMs) segs.push({ startMs: cursor, endMs, speed: 1 });
  // insert freeze frames by splitting the segment that contains each hold point
  for (const [marker, after, ms] of HOLDS[n] ?? []) {
    const t = at(marker);
    if (t === undefined) continue;
    const point = t + after;
    const i = segs.findIndex((g) => point > g.startMs && point < g.endMs && !g.holdMs);
    if (i < 0) continue;
    const g = segs[i];
    segs.splice(i, 1, { ...g, endMs: point }, { startMs: point, endMs: point, speed: 1, holdMs: ms }, { ...g, startMs: point });
  }
  return segs;
}

/** clip time (ms) -> output time (ms from the scene's start) */
function mapTime(segs, ms) {
  let out = 0;
  for (const s of segs) {
    if (s.holdMs) {
      if (ms > s.startMs) out += s.holdMs;
      continue;
    }
    if (ms <= s.endMs) return out + (Math.max(ms, s.startMs) - s.startMs) / s.speed;
    out += (s.endMs - s.startMs) / s.speed;
  }
  return out;
}

const items = [];
const placed = [];
let cursorMs = 0; // output timeline
let lastLineEnd = 0;

function placeLine(id, wantMs) {
  const start = Math.max(wantMs, lastLineEnd + GAP_MS);
  const l = lines.find((x) => x.id === id);
  placed.push({ id, src: `lines/${id}.wav`, character: l.character, text: l.text, from: f(start), frames: f(lineMs(id)) });
  lastLineEnd = start + lineMs(id);
  return lastLineEnd;
}

// 0 · cold open
items.push({ kind: "title", from: 0, frames: f(11000), title: "EagleEye", subtitle: "Grand Line Shipping · Monday, 08:57" });
placeLine("s0-01", 900);
cursorMs = 11000;

for (const n of [1, 2, 3, 4, 5, 6, 7]) {
  const file = `raw/scenes/s${n}.json`;
  if (!existsSync(file)) { console.warn(`missing scene ${n}`); continue; }
  const rec = JSON.parse(readFileSync(file, "utf8"));
  copyFileSync(`raw/scenes/s${n}.mp4`, `${PUBLIC}/scenes/s${n}.mp4`);
  const endMs = rec.seconds * 1000;
  const segs = segmentsFor(rec.markers, endMs, n);
  if (n === 7) {
    items.push({ kind: "caption", from: f(cursorMs), frames: f(1800), text: "Meanwhile…" });
    cursorMs += 1800;
  }
  const sceneStart = cursorMs;
  let sceneLen = mapTime(segs, endMs);
  for (const [scene, id, anchor, offset] of ANCHORS.filter((a) => a[0] === n)) {
    // "read#2" = the second read marker; "read~claim" = the read marker whose text matches
    const [type, rest] = anchor.split(/[#~]/);
    const ofType = rec.markers.filter((x) => x.type === type);
    const m = anchor.includes("~")
      ? ofType.find((x) => new RegExp(rest, "i").test(x.label ?? ""))
      : ofType[Number(rest ?? 1) - 1];
    if (!m) {
      console.warn(`scene ${n}: no marker for ${anchor}; ${id} follows the previous line`);
    }
    const end = placeLine(id, m ? sceneStart + mapTime(segs, m.t) + offset : 0);
    sceneLen = Math.max(sceneLen, end - sceneStart + 400);
  }
  const holdMs = sceneLen - mapTime(segs, endMs);
  if (holdMs > 30) segs.push({ startMs: endMs, endMs, speed: 1, holdMs });
  let fr = f(sceneStart);
  const segments = segs.map((s) => {
    const frames = s.holdMs ? f(s.holdMs) : Math.max(1, f((s.endMs - s.startMs) / s.speed));
    // a hold shows one frame for its whole length (Remotion: a tiny playback rate)
    const seg = { startMs: s.holdMs ? Math.max(0, s.startMs - 40) : s.startMs, endMs: s.endMs, speed: s.holdMs ? 0.001 : s.speed, from: fr, frames };
    fr += frames;
    return seg;
  });
  items.push({ kind: "clip", scene: n, src: `scenes/s${n}.mp4`, from: f(sceneStart), frames: fr - f(sceneStart), segments });
  cursorMs = (fr / FPS) * 1000;
}

// 8 · built with (groups appear, then the whole card holds 5 s)
const cardMs = 10000;
items.push({ kind: "card", card: "builtwith", from: f(cursorMs), frames: f(cardMs) });
placeLine("s8-01", cursorMs + 1000);
cursorMs += cardMs;

const timeline = { fps: FPS, durationInFrames: f(cursorMs), items, lines: placed };
writeFileSync(`${PUBLIC}/timeline.json`, JSON.stringify(timeline, null, 2));
const totalS = Math.round(cursorMs / 1000);
const mm = Math.floor(totalS / 60), ss = totalS % 60;
console.log(`timeline: ${mm}:${String(ss).padStart(2, "0")} (${items.length} items, ${placed.length} lines)`);
for (const it of items) console.log(`  ${it.kind}${it.scene ? " " + it.scene : ""}: ${(it.from / FPS).toFixed(1)}s +${(it.frames / FPS).toFixed(1)}s`);
