// The architecture map: nodes (positions on a 1920x1080 canvas), connectors, traffic colours.
import * as si from "simple-icons";

export type IconKey = keyof typeof si;

export interface ArchNode {
  x: number;
  y: number;
  label: string;
  sub?: string;
  icon?: IconKey;
  letters?: string;
  person?: boolean;
  layer: string;
  scaleOnly?: boolean; // appears only in the scaling scene
}

export const NODES: Record<string, ArchNode> = {
  employee: { x: 130, y: 430, label: "Employee", sub: "browser", person: true, layer: "People" },
  admin: { x: 130, y: 650, label: "Admin", sub: "browser", person: true, layer: "People" },
  vercel: { x: 370, y: 430, label: "Web app", sub: "Next.js on Vercel", icon: "siVercel", layer: "Front end" },
  clerk: { x: 370, y: 650, label: "Clerk", sub: "sign-in, tokens", icon: "siClerk", layer: "Front end" },
  cloudfront: { x: 600, y: 540, label: "CloudFront", sub: "HTTPS edge", letters: "CF", layer: "Edge" },
  alb: { x: 715, y: 330, label: "Load balancer", sub: "scale mode", icon: "siAwselasticloadbalancing", layer: "Edge", scaleOnly: true },
  api: { x: 830, y: 540, label: "EagleEye API", sub: "FastAPI", icon: "siFastapi", layer: "Application" },
  redis: { x: 1050, y: 540, label: "Redis", sub: "queue, cache", icon: "siRedis", layer: "Application" },
  agent: { x: 1270, y: 400, label: "Agent worker", sub: "Celery", icon: "siCelery", layer: "Application" },
  ingest: { x: 1270, y: 690, label: "Ingest worker", sub: "Celery · Docling", icon: "siCelery", layer: "Application" },
  gateway: { x: 1500, y: 220, label: "Data gateway", sub: "read-only SQL", letters: "DG", layer: "Data" },
  opsdb: { x: 1730, y: 220, label: "Operations DB", sub: "PostgreSQL", icon: "siPostgresql", layer: "Data" },
  qdrant: { x: 1500, y: 470, label: "Qdrant", sub: "document vectors", letters: "Qd", layer: "Data" },
  s3: { x: 1500, y: 720, label: "Amazon S3", sub: "files", icon: "siAmazons3", layer: "Data" },
  postgres: { x: 1050, y: 860, label: "Supabase Postgres", sub: "accounts, chats, usage", icon: "siSupabase", layer: "Data" },
  openai: { x: 1730, y: 470, label: "OpenAI", sub: "models", icon: "siOpenai", layer: "AI & compute" },
  lambda: { x: 1730, y: 720, label: "Lambda sandbox", sub: "Python, no network", icon: "siAwslambda", layer: "AI & compute" },
  cloudwatch: { x: 1730, y: 930, label: "CloudWatch", sub: "logs, scaling metric", icon: "siAmazoncloudwatch", layer: "Operations" },
};

// [from, to, curvature]: curvature bends the connector (0 = straight)
export const EDGES: [string, string, number][] = [
  ["employee", "vercel", 0],
  ["admin", "vercel", 0.15],
  ["employee", "clerk", 0.12],
  ["employee", "cloudfront", -0.1],
  ["cloudfront", "api", 0],
  ["clerk", "api", 0.18],
  ["api", "redis", 0],
  ["api", "postgres", 0.1],
  ["api", "s3", -0.22],
  ["api", "cloudwatch", 0.12],
  ["redis", "agent", 0.08],
  ["redis", "ingest", -0.08],
  ["agent", "openai", -0.08],
  ["agent", "qdrant", 0.05],
  ["agent", "gateway", 0.08],
  ["gateway", "opsdb", 0],
  ["agent", "lambda", -0.18],
  ["lambda", "s3", 0],
  ["agent", "postgres", 0.2],
  ["ingest", "s3", 0],
  ["ingest", "openai", 0.12],
  ["ingest", "qdrant", -0.08],
  ["ingest", "postgres", -0.1],
  ["cloudfront", "alb", 0],
  ["alb", "api", 0],
];

export const COLORS = {
  auth: "#a78bfa", // sign-in and tokens
  request: "#4f9dff", // user request and streamed answer
  file: "#f5b041", // documents and files
  data: "#3ddc84", // database and SQL
  model: "#f4f4f5", // model calls
  blocked: "#ff4d4f", // blocked by a guardrail
} as const;
export type Traffic = keyof typeof COLORS;

export const LEGEND: [Traffic, string][] = [
  ["auth", "Sign-in and tokens"],
  ["request", "Requests and answers"],
  ["file", "Documents and files"],
  ["data", "Database and SQL"],
  ["model", "Model calls"],
  ["blocked", "Blocked by a guardrail"],
];

export const LAYERS: [string, number][] = [
  ["People", 130],
  ["Front end", 370],
  ["Edge", 600],
  ["Application (AWS)", 1050],
  ["Data", 1500],
  ["AI & compute", 1730],
];

/** Connector geometry: a quadratic curve from a to b (node centres). */
export function curve(a: string, b: string, bend: number) {
  const p0 = NODES[a];
  const p1 = NODES[b];
  const mx = (p0.x + p1.x) / 2;
  const my = (p0.y + p1.y) / 2;
  const dx = p1.x - p0.x;
  const dy = p1.y - p0.y;
  const c = { x: mx - dy * bend, y: my + dx * bend };
  return {
    d: `M ${p0.x} ${p0.y} Q ${c.x} ${c.y} ${p1.x} ${p1.y}`,
    at: (s: number) => ({
      x: (1 - s) * (1 - s) * p0.x + 2 * (1 - s) * s * c.x + s * s * p1.x,
      y: (1 - s) * (1 - s) * p0.y + 2 * (1 - s) * s * c.y + s * s * p1.y,
    }),
  };
}

/** The connector for a hop, in either direction. */
export function hopPath(from: string, to: string) {
  const e = EDGES.find(([a, b]) => (a === from && b === to) || (a === to && b === from));
  if (!e) throw new Error(`no connector ${from} → ${to}`);
  const g = curve(e[0], e[1], e[2]);
  const reverse = e[0] !== from;
  return { d: g.d, at: (s: number) => g.at(reverse ? 1 - s : s) };
}
