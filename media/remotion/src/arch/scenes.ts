// The flows, scene by scene. Times are seconds from the start of their scene; build-arch.mjs
// sets each scene's start and length from its narration.
import type { Traffic } from "./graph";

export type Ev =
  | { kind: "hop"; t: number; from: string; to: string; traffic: Traffic; dur: number }
  | { kind: "glow"; t: number; node: string; dur: number; traffic: Traffic }
  | { kind: "caption"; t: number; dur: number; text: string }
  | { kind: "badge"; t: number; dur: number; node: string; text: string; traffic: Traffic };

export interface SceneDef {
  title: string;
  focus: string[] | "all"; // nodes shown at full strength; the rest dim
  events: Ev[];
}

const HOP = 0.8;
const hop = (t: number, from: string, to: string, traffic: Traffic, dur = HOP): Ev => ({ kind: "hop", t, from, to, traffic, dur });
/** A request travelling node to node: one hop after another. */
function route(t: number, nodes: string[], traffic: Traffic, dur = HOP): Ev[] {
  return nodes.slice(1).map((n, i) => hop(t + i * dur, nodes[i], n, traffic, dur));
}
const glow = (t: number, node: string, dur: number, traffic: Traffic): Ev => ({ kind: "glow", t, node, dur, traffic });
const cap = (t: number, dur: number, text: string): Ev => ({ kind: "caption", t, dur, text });
const badge = (t: number, dur: number, node: string, text: string, traffic: Traffic): Ev => ({ kind: "badge", t, dur, node, text, traffic });
/** Words of a streamed answer: small pulses back along the path to the browser. */
function stream(t: number, nodes: string[], count: number, every = 0.35): Ev[] {
  const out: Ev[] = [];
  for (let k = 0; k < count; k++) out.push(...route(t + k * every, nodes, "request", 0.45));
  return out;
}

export const SCENES: Record<number, SceneDef> = {
  1: {
    title: "The big picture",
    focus: "all",
    events: [cap(0.8, 9, "Web app in front · services on AWS in the middle · company data underneath")],
  },
  2: {
    title: "Signing in",
    focus: ["employee", "clerk", "cloudfront", "api", "postgres"],
    events: [
      cap(0.4, 11.5, "Clerk signs the person in and issues a short-lived token; the API checks it on every request"),
      ...route(0.8, ["employee", "clerk"], "auth"),
      glow(1.6, "clerk", 1.2, "auth"),
      hop(2.8, "clerk", "employee", "auth"),
      badge(3.6, 2.4, "employee", "token", "auth"),
      ...route(4.4, ["employee", "cloudfront", "api"], "auth"),
      hop(6.2, "api", "clerk", "auth"),
      hop(7.0, "clerk", "api", "auth"),
      hop(7.9, "api", "postgres", "auth"),
      hop(8.7, "postgres", "api", "auth"),
      glow(9.5, "api", 2.0, "auth"),
      badge(9.5, 2.4, "api", "✓ signed in · role checked", "auth"),
    ],
  },
  3: {
    title: "A document arrives",
    focus: ["employee", "cloudfront", "api", "s3", "redis", "ingest", "openai", "qdrant", "postgres"],
    events: [
      cap(0.4, 6.2, "Upload: the file is stored and a job joins the queue, so the upload returns at once"),
      ...route(0.6, ["employee", "cloudfront", "api"], "file"),
      hop(2.3, "api", "s3", "file"),
      glow(3.1, "s3", 1.2, "file"),
      hop(3.4, "api", "redis", "file"),
      hop(4.4, "redis", "ingest", "file"),
      cap(6.8, 11.6, "Ingest worker: Docling reads text, tables and charts; a vision model describes each chart; passages become vectors"),
      hop(7.0, "ingest", "s3", "file"),
      hop(7.8, "s3", "ingest", "file"),
      glow(8.6, "ingest", 3.0, "file"),
      badge(8.6, 3.2, "ingest", "Docling: text · tables · charts", "file"),
      hop(11.0, "ingest", "openai", "model"),
      badge(11.8, 2.2, "openai", "vision: describe chart", "model"),
      hop(12.6, "openai", "ingest", "model"),
      hop(13.5, "ingest", "openai", "model"),
      badge(14.3, 2.0, "openai", "embeddings", "model"),
      hop(15.0, "openai", "ingest", "model"),
      hop(15.9, "ingest", "qdrant", "file"),
      glow(16.7, "qdrant", 1.4, "file"),
      hop(16.9, "ingest", "postgres", "file"),
      ...route(17.4, ["api", "cloudfront", "employee"], "file", 0.6),
      badge(18.6, 1.8, "employee", "✓ Ready", "file"),
    ],
  },
  4: {
    title: "A question",
    focus: ["employee", "cloudfront", "api", "redis", "agent", "openai", "qdrant", "gateway", "opsdb", "lambda", "s3", "postgres", "cloudwatch"],
    events: [
      cap(0.4, 6.4, "The API puts the question on the queue; an agent worker picks it up"),
      ...route(0.6, ["employee", "cloudfront", "api", "redis", "agent"], "request"),
      glow(3.8, "agent", 2.4, "request"),
      // safety check, then the planner
      cap(7.2, 9.8, "Safety check → planner → tools, in parallel"),
      hop(7.6, "agent", "openai", "model"),
      badge(8.4, 1.8, "openai", "safety check", "model"),
      hop(9.2, "openai", "agent", "model"),
      hop(10.2, "agent", "openai", "model"),
      badge(11.0, 1.8, "openai", "planner", "model"),
      hop(11.8, "openai", "agent", "model"),
      // the tools fan out at once
      hop(13.0, "agent", "qdrant", "data"),
      hop(13.0, "agent", "gateway", "data"),
      hop(13.0, "agent", "lambda", "data"),
      badge(13.8, 3.0, "qdrant", "document search", "data"),
      glow(13.8, "qdrant", 2.0, "data"),
      // the gateway: read-only, limited to the person's role
      cap(17.7, 10.6, "Database questions go through a read-only gateway; analysis code runs in a sandbox with no internet"),
      hop(18.0, "gateway", "opsdb", "data"),
      badge(18.4, 4.0, "gateway", "read-only · role-limited", "data"),
      glow(18.8, "opsdb", 1.6, "data"),
      hop(20.4, "opsdb", "gateway", "data"),
      hop(21.2, "gateway", "agent", "data"),
      // the sandbox: data in from S3, no network
      hop(22.6, "s3", "lambda", "file"),
      glow(23.4, "lambda", 2.6, "data"),
      badge(23.4, 4.0, "lambda", "isolated · no network", "data"),
      hop(26.2, "lambda", "agent", "data"),
      hop(26.4, "qdrant", "agent", "data"),
      // the writer, the checks, the streamed answer
      cap(28.7, 8.4, "The answer is written from the results, every figure checked, and streamed back with citations"),
      hop(29.0, "agent", "openai", "model"),
      badge(29.8, 1.8, "openai", "writer", "model"),
      hop(30.6, "openai", "agent", "model"),
      glow(31.4, "agent", 1.6, "request"),
      badge(31.4, 2.0, "agent", "citations · figure checks", "request"),
      ...stream(33.0, ["agent", "redis", "api", "cloudfront", "employee"], 6),
      hop(33.4, "agent", "postgres", "data"),
      hop(34.0, "api", "cloudwatch", "data"),
    ],
  },
  5: {
    title: "Guardrails",
    focus: ["employee", "cloudfront", "api", "redis", "agent", "openai", "gateway", "opsdb", "postgres"],
    events: [
      cap(0.4, 10.8, "A malicious request stops at the safety check · restricted data stops at the gateway · both are recorded"),
      ...route(0.6, ["employee", "cloudfront", "api", "redis", "agent"], "blocked", 0.6),
      hop(3.2, "agent", "openai", "blocked"),
      hop(4.0, "openai", "agent", "blocked"),
      glow(4.8, "agent", 1.8, "blocked"),
      badge(4.8, 2.4, "agent", "🛡 blocked: prompt injection", "blocked"),
      ...route(6.0, ["agent", "gateway"], "blocked"),
      glow(6.8, "gateway", 1.8, "blocked"),
      badge(6.8, 2.6, "gateway", "🔒 HR data: not for this role", "blocked"),
      hop(8.4, "agent", "postgres", "blocked"),
      badge(9.2, 2.0, "postgres", "security events recorded", "blocked"),
    ],
  },
  6: {
    title: "Scaling",
    focus: ["cloudfront", "alb", "api", "redis", "agent", "ingest", "gateway", "cloudwatch"],
    events: [cap(0.4, 16.4, "More questions waiting → more workers: the cluster scales on the queue")],
  },
};

/** Scaling scene: users and task counts over the scene (seconds → values). */
export const SCALE = {
  usersAt: [[1.5, 1], [4, 50], [8, 1000], [12.5, 2000]] as [number, number][],
  tasks: {
    // preliminary: replaced by the real ECS task counts from the load test
    api: [[1.5, 1], [6, 2], [10, 3], [12.5, 4]] as [number, number][],
    agent: [[1.5, 1], [5, 3], [8, 6], [10.5, 9], [12.5, 11]] as [number, number][],
    ingest: [[1.5, 1], [9, 2]] as [number, number][],
    gateway: [[1.5, 1], [10, 2]] as [number, number][],
  },
  preliminary: true,
};
