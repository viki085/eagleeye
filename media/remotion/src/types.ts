export interface Segment {
  startMs: number; // position in the scene clip
  endMs: number;
  speed: number; // 1 = real time; >1 sped up (a badge shows it)
  from: number; // frame in the video
  frames: number;
}

export type Item =
  | { kind: "title"; from: number; frames: number; title: string }
  | { kind: "typed"; from: number; frames: number; line1: string; line2: string }
  | { kind: "clip"; scene: number; src: string; from: number; frames: number; segments: Segment[] }
  | { kind: "card"; card: "builtwith"; from: number; frames: number }
  | { kind: "outro"; from: number; frames: number }
  | { kind: "caption"; from: number; frames: number; text: string };

export interface Line {
  id: string;
  src: string;
  character: "narrator" | "expert";
  text: string;
  from: number;
  frames: number;
}

export interface Timeline {
  fps: number;
  durationInFrames: number;
  items: Item[];
  lines: Line[];
}
