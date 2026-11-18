// EagleEye load test (k6). Each virtual user signs in with its load-test token, opens a chat and
// asks questions from the shared pool every 60-90 seconds, reading each answer's stream to the
// end, like the web app does. Mix per question: 90% documents, 3% database, 3% charts, 3% attacks,
// 1% notebooks (notebooks only from users seeded with a data file: every 20th user).
//
//   k6 run -e API=https://<cloudfront> -e PROFILE=run chat.js
//
// tokens.json (from scripts/loadtest_seed.py users) and loadtest_questions.json sit next to this
// script in the private k6 image (evals/load/Dockerfile); both are shared between users in memory.
//
// PROFILE=rehearsal runs 100 users for 10 minutes; PROFILE=run is the recorded 1 → 50 → 500 →
// 1,000 → 2,000 test in steps (so the response-time rise and the autoscaling drop are visible).
import http from "k6/http";
import { check, sleep } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";
import { SharedArray } from "k6/data";
import exec from "k6/execution";

const API = __ENV.API;
const POOL = JSON.parse(open("./loadtest_questions.json"));
const TOKENS = new SharedArray("tokens", () => JSON.parse(open("./tokens.json")).users.map((u) => u.token));
const byKind = (k) => POOL.questions.filter((q) => q.kind === k);
const KINDS = { docs: byKind("docs"), sql: byKind("sql"), chart: byKind("chart"), attack: byKind("attack"), notebook: byKind("notebook") };
const QUESTIONS_PER_CHAT = 5;
const ANALYSIS_EVERY = 20; // as scripts/loadtest_seed.py: user n has a data file when n % 20 == 0

const PROFILES = {
  rehearsal: [
    { duration: "1m", target: 20 },
    { duration: "1m", target: 100 },
    { duration: "7m", target: 100 },
    { duration: "1m", target: 0 },
  ],
  run: [
    { duration: "20s", target: 1 }, // smoke: one user
    { duration: "100s", target: 1 },
    { duration: "40s", target: 50 },
    { duration: "160s", target: 50 },
    { duration: "60s", target: 500 }, // step: response time rises, then workers are added
    { duration: "180s", target: 500 },
    { duration: "60s", target: 1000 },
    { duration: "180s", target: 1000 },
    { duration: "120s", target: 2000 },
    { duration: "300s", target: 2000 },
    { duration: "180s", target: 0 }, // ramp down: the cluster scales in
  ],
};

export const options = {
  scenarios: {
    users: { executor: "ramping-vus", startVUs: 0, stages: PROFILES[__ENV.PROFILE || "rehearsal"], gracefulRampDown: "90s" },
  },
  thresholds: { errors: ["rate<0.02"] },
  summaryTrendStats: ["avg", "med", "p(90)", "p(95)", "max"],
};

const answerSeconds = new Trend("answer_seconds", false);
const errors = new Rate("errors");
const asked = new Counter("questions");
const perKind = Object.fromEntries(Object.keys(KINDS).map((k) => [k, new Counter(`questions_${k}`)]));

function pickKind(hasData) {
  if (hasData && Math.random() < 0.2) return "notebook"; // 5% of users × 20% ≈ 1% of questions
  const r = Math.random() * (POOL.weights.docs + POOL.weights.sql + POOL.weights.chart + POOL.weights.attack);
  if (r < POOL.weights.docs) return "docs";
  if (r < POOL.weights.docs + POOL.weights.sql) return "sql";
  if (r < POOL.weights.docs + POOL.weights.sql + POOL.weights.chart) return "chart";
  return "attack";
}

const state = { chat: null, count: 0 };

export default function () {
  const n = exec.vu.idInTest; // 1..2000, matches the seeded user number
  const token = TOKENS[(n - 1) % TOKENS.length];
  const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  if (exec.vu.iterationInScenario === 0) sleep(Math.random() * 20); // spread sign-ins

  if (!state.chat || state.count >= QUESTIONS_PER_CHAT) {
    const res = http.post(`${API}/v1/chats`, null, { headers, tags: { name: "create_chat" } });
    if (!check(res, { "chat created": (r) => r.status === 200 || r.status === 201 })) {
      errors.add(1);
      sleep(10);
      return;
    }
    state.chat = res.json("data.id");
    state.count = 0;
  }

  const kind = pickKind(n % ANALYSIS_EVERY === 0);
  const list = KINDS[kind];
  const q = list[Math.floor(Math.random() * list.length)];
  const started = Date.now();
  const send = http.post(
    `${API}/v1/chats/${state.chat}/messages`,
    JSON.stringify({ text: q.text, idempotency_key: `${n}-${exec.vu.iterationInScenario}-${started}`, doc_ids: [] }),
    { headers, tags: { name: "send", kind } },
  );
  state.count += 1;
  asked.add(1);
  perKind[kind].add(1);
  if (!check(send, { "question accepted": (r) => r.status === 200 || r.status === 202 })) {
    errors.add(1);
    sleep(15);
    return;
  }
  const runId = send.json("data.run_id");
  // read the answer's event stream to the end (the server closes it when the answer is done)
  const stream = http.get(`${API}/v1/runs/${runId}/stream`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream" },
    timeout: "180s",
    tags: { name: "stream", kind },
  });
  // a finished answer ends with run.done; run.error counts as a failure
  const body = stream.body || "";
  const ok = check(stream, { "answer completed": (r) => r.status === 200 && body.includes("event: run.done") && !body.includes("event: run.error") });
  errors.add(!ok);
  const seconds = (Date.now() - started) / 1000;
  answerSeconds.add(seconds, { kind });
  // one line per answer (finish time, kind, seconds, ok): export.py turns these into response
  // time per minute for the before/after-scaling graph
  console.log(`ANS ${Date.now()} ${kind} ${seconds.toFixed(2)} ${ok ? 1 : 0}`);

  sleep(60 + Math.random() * 30); // read the answer, think, ask again
}

export function handleSummary(summary) {
  // printed to the task log; export.py reads it from CloudWatch Logs
  return { stdout: `K6_SUMMARY ${JSON.stringify({ metrics: summary.metrics, state: summary.state })}\n` };
}
