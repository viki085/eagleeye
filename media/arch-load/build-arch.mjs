// Builds public/arch-timeline.json for Part 1 (the animated architecture): scene starts and
// lengths from the narration, and the voice lines (copied at 1.25x speed).
//   node arch-load/build-arch.mjs      (run from media/)
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import ffmpeg from "ffmpeg-static";

const FPS = 30;
const TEMPO = 1.25;
const GAP = 0.35;
const durations = JSON.parse(readFileSync("audio/durations.json", "utf8"));
const lines = JSON.parse(readFileSync("arch-load/lines.json", "utf8"));
mkdirSync("public/arch-lines", { recursive: true });

// each line's wanted start, in seconds from its scene's start (the flows in scenes.ts match these)
const ANCHOR = {
  "a0-01": 0.8,
  "a1-01": 0.5, "a1-02": 10.6,
  "a2-01": 0.4,
  "a3-01": 0.4, "a3-02": 7.0,
  "a4-01": 0.4, "a4-02": 7.2, "a4-03": 17.7, "a4-04": 28.7,
  "a5-01": 0.4,
  "a6-01": 0.4, "a6-02": 0,
};
// the flows' own length per scene (seconds); a scene lasts at least this long
const MIN_LENGTH = { 0: 9, 1: 21, 2: 12.4, 3: 19.8, 4: 37.4, 5: 11.6, 6: 17.4 };

const sec = (id) => durations[id].seconds / TEMPO;
const scenes = [];
const placed = [];
let start = 0;
for (const n of [0, 1, 2, 3, 4, 5, 6]) {
  let end = 0;
  for (const l of lines.filter((x) => x.id.startsWith(`a${n}-`))) {
    const at = Math.max(ANCHOR[l.id] ?? 0, end + (end ? GAP : 0));
    execFileSync(ffmpeg, ["-hide_banner", "-loglevel", "error", "-y", "-i", `audio/lines/${l.id}.wav`, "-filter:a", `atempo=${TEMPO}`, `public/arch-lines/${l.id}.wav`]);
    placed.push({ id: l.id, src: `arch-lines/${l.id}.wav`, from: Math.round((start + at) * FPS), frames: Math.round(sec(l.id) * FPS) });
    end = at + sec(l.id);
  }
  const length = Math.max(MIN_LENGTH[n], end + 0.8);
  scenes.push({ n, start: Number(start.toFixed(3)), length: Number(length.toFixed(3)) });
  start += length;
}
const timeline = { fps: FPS, durationInFrames: Math.round(start * FPS), scenes, lines: placed };
writeFileSync("public/arch-timeline.json", JSON.stringify(timeline, null, 2));
console.log(`part 1: ${Math.floor(start / 60)}:${String(Math.round(start % 60)).padStart(2, "0")}`);
for (const s of scenes) console.log(`  scene ${s.n}: ${s.start.toFixed(1)}s +${s.length.toFixed(1)}s`);
