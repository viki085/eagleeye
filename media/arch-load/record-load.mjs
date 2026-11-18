// Records Part 2 during the load test: starts the k6 task, then follows a schedule measured from
// the load's start. Window-wall clips (a video account signs in, asks a pool question, the answer
// streams) fill the gaps; the admin console is recorded at 500, 1,000 and 2,000 users, each
// checkpoint covering different metrics. Every clip saves its absolute start time, so
// export.py can place it against the user count and response-time series.
//
//   node arch-load/record-load.mjs --profile rehearsal|run --api https://<scale cloudfront>
//        [--site http://localhost:3000] [--no-k6]   (from media/)
//
// Same page-only 4K capture as the product video (kiosk Chrome, throwaway profile, CDP screencast).
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { openRecordingBrowser } from "../tools/browser.mjs";
import { startCapture } from "../tools/capture.mjs";
import { signInWithTicket } from "../tools/clerk-ticket.mjs";
import { clickOn, sleep, smoothScroll, typeLikeAPerson } from "../tools/human.mjs";

const { values: args } = parseArgs({
  options: {
    profile: { type: "string", default: "rehearsal" },
    api: { type: "string" },
    site: { type: "string", default: "http://localhost:3000" },
    "no-k6": { type: "boolean", default: false },
  },
});
if (!args.api?.startsWith("https://")) throw new Error("--api https://<scale cloudfront> is required");
const OUT = new URL(`./raw/${args.profile}/`, import.meta.url).pathname.replace(/^\/(\w:)/, "$1");
mkdirSync(OUT, { recursive: true });

const ADMIN = "vikram.k@grandlineshipping.com";
const MEMBER = "sam.rivera@grandlineshipping.com";
const POOL = JSON.parse(readFileSync(new URL("../../packages/llm/eagleeye_llm/loadtest_questions.json", import.meta.url)));

// questions for the wall: mostly documents, like the mix, plus database, chart and an attack
function wallQuestions() {
  const of = (k) => POOL.questions.filter((q) => q.kind === k);
  const docs = of("docs");
  const pick = (list, i) => list[(i * 7) % list.length];
  return [
    pick(docs, 0), pick(of("sql"), 1), pick(docs, 1), pick(docs, 2), pick(of("chart"), 0), pick(docs, 3),
    pick(of("attack"), 0), pick(docs, 4), pick(docs, 5), pick(of("sql"), 4), pick(docs, 6), pick(of("chart"), 3),
    pick(docs, 7), pick(docs, 8), pick(docs, 9), pick(docs, 10),
  ];
}

// --- the k6 task -----------------------------------------------------------------------------

function tf(name) {
  return execFileSync("terraform", ["-chdir=../infra/terraform/scale", "output", "-raw", name], { encoding: "utf8" }).trim();
}

function aws(argv) {
  return JSON.parse(execFileSync("aws", [...argv, "--profile", "eagleeye", "--region", "us-east-1", "--output", "json"], { encoding: "utf8", env: { ...process.env, MSYS_NO_PATHCONV: "1" } }));
}

async function startK6(profile) {
  const cluster = tf("cluster");
  const cmd = tf("k6_run_task");
  const net = cmd.match(/'awsvpcConfiguration=\{(.*)\}'/)[1];
  const family = cmd.match(/--task-definition (\S+)/)[1];
  const res = aws([
    "ecs", "run-task", "--cluster", cluster, "--launch-type", "FARGATE", "--task-definition", family,
    "--network-configuration", `awsvpcConfiguration={${net}}`,
    "--overrides", JSON.stringify({ containerOverrides: [{ name: "k6", environment: [{ name: "PROFILE", value: profile }] }] }),
  ]);
  const arn = res.tasks[0].taskArn;
  for (;;) {
    const t = aws(["ecs", "describe-tasks", "--cluster", cluster, "--tasks", arn]).tasks[0];
    if (t.lastStatus === "RUNNING") return { arn, t0: Date.now() };
    if (t.lastStatus === "STOPPED") throw new Error(`k6 stopped: ${t.stoppedReason}`);
    await sleep(3000);
  }
}

// --- helpers ---------------------------------------------------------------------------------

async function api(page, path, init = {}) {
  return page.evaluate(
    async ({ base, path, init }) => {
      const token = await window.Clerk.session.getToken();
      const res = await fetch(base + path, { ...init, headers: { Authorization: `Bearer ${token}` } });
      return res.status === 204 ? null : res.json();
    },
    { base: args.api, path, init },
  );
}

/** Before a recording: both video accounts start with no chats (off camera). */
async function clearAccounts() {
  for (const email of [MEMBER, ADMIN]) {
    const { browser, page } = await openSignedIn(email);
    try {
      await signInWithTicket(page, email);
      await page.goto(args.site, { waitUntil: "load" });
      await page.getByLabel("Message").waitFor({ timeout: 60_000 });
      await page.waitForFunction(() => window.Clerk?.session, null, { timeout: 30_000 });
      const chats = (await api(page, "/v1/chats")).data ?? [];
      for (const c of chats) await api(page, `/v1/chats/${c.id}`, { method: "DELETE" });
      console.log(`${email}: ${chats.length} chats cleared`);
    } finally {
      await browser.close();
    }
  }
}

async function openSignedIn(email) {
  const { browser, page } = await openRecordingBrowser();
  page.setDefaultTimeout(15_000); // no step may hang a recording
  await page.goto(`${args.site}/sign-in`, { waitUntil: "load" });
  await page.waitForFunction(() => window.Clerk?.loaded, null, { timeout: 60_000 });
  return { browser, page };
}

function save(name, meta) {
  writeFileSync(`${OUT}/${name}.json`, JSON.stringify(meta, null, 2));
  console.log(`${name}: ${meta.seconds?.toFixed?.(1) ?? "?"}s ${meta.note ?? ""}`);
}

// --- a wall clip: sign in, ask, the answer streams ------------------------------------------

async function wallClip(n, question, email) {
  const { browser, page } = await openSignedIn(email);
  const marks = [];
  try {
    const stop = await startCapture(page, { out: `${OUT}/wall-${String(n).padStart(2, "0")}.mp4` });
    const mark = (type) => marks.push({ t: Date.now() - stop.startedAt, type });
    await sleep(1200);
    await signInWithTicket(page, email);
    await page.goto(args.site, { waitUntil: "load" });
    await page.getByLabel("Message").waitFor({ timeout: 120_000 });
    mark("ready");
    // continue the account's latest chat: a first question can be replayed from the answer
    // cache in 0 s, a follow-up is always worked out, so its time shows the real load
    const latest = page.locator("aside button[title]:not([aria-label])").first(); // chat entries
    // the list loads after the page (showing "No chats yet" meanwhile): wait for an entry
    await latest.waitFor({ timeout: 6_000 }).catch(() => {});
    if (await latest.count()) {
      await clickOn(page, latest);
      await sleep(1800);
      mark("continued");
    }
    await clickOn(page, page.getByLabel("Message"));
    await typeLikeAPerson(page, question.text);
    // an answer is done when its "Worked for ..." summary appears (also for a cache replay)
    const done = page.locator("main button[aria-expanded]").filter({ hasText: /Worked for/ });
    const before = await done.count();
    await page.keyboard.press("Enter");
    mark("asked");
    await page.waitForFunction(
      (n) => [...document.querySelectorAll("main button[aria-expanded]")].filter((b) => /Worked for/.test(b.textContent)).length > n,
      before,
      { timeout: 240_000, polling: 200 },
    );
    mark("answered");
    await sleep(2500);
    const result = await stop();
    const asked = marks.find((m) => m.type === "asked").t;
    const answered = marks.find((m) => m.type === "answered").t;
    const text = await page.locator("main").innerText().catch(() => "");
    save(`wall-${String(n).padStart(2, "0")}`, {
      ...result, startedAtEpoch: stop.startedAt, kind: question.kind, question: question.text, email,
      answerSeconds: (answered - asked) / 1000, marks,
      note: /something went wrong|error/i.test(text.slice(-400)) ? "CHECK: error text on screen" : `${question.kind} ${((answered - asked) / 1000).toFixed(1)}s`,
    });
    // chats are kept: deleting one would also delete its answer from the admin metrics
  } finally {
    await browser.close();
  }
}

// --- admin console checkpoints ---------------------------------------------------------------

const CHECKPOINTS = {
  500: [
    ["Overview", "Online now"], ["System & controls", "Answers in progress"], ["System & controls", "Services"],
    ["Overview", "Request volume and outcomes"],
  ],
  1000: [
    ["Overview", "Avg response time"], ["Overview", "Success rate"], ["Overview", "Slowest pipeline steps"],
    ["Overview", "Caching: Hit rate"],
  ],
  // after the run: the simulated calls priced at the real model's rates (load-test DB only),
  // shown over 24 hours; the edit labels it an estimate
  cost: [["Overview", "LLM cost"], ["Overview", "November spend"], ["Overview", "LLM cost by model"]],
  2000: [
    ["Quality & safety", "Safety events by category"], ["Quality & safety", "SQL refused or failed"],
    ["Quality & safety", "Sandbox runs"], ["Overview", "Request routing distribution"], ["Overview", "LLM cost"],
  ],
};

async function adminCheckpoint(users) {
  const { browser, page } = await openSignedIn(ADMIN);
  try {
    await signInWithTicket(page, ADMIN);
    await page.goto(`${args.site}/admin`, { waitUntil: "load" });
    const period = users === "cost" ? "Last 24 hours" : "Last hour, by the minute";
    await page.getByRole("radio", { name: period }).click({ timeout: 60_000 });
    await page.getByRole("button", { name: "Live" }).click();
    await sleep(4000); // first live refresh lands
    const stop = await startCapture(page, { out: `${OUT}/admin-${users}.mp4` });
    const marks = [];
    let section = "Overview";
    await sleep(2500);
    for (const [where, label] of CHECKPOINTS[users]) {
      try {
      if (where !== section) {
        await clickOn(page, page.getByRole("tab", { name: where }).first());
        section = where;
        await sleep(1800);
      }
      const target = page.getByText(label, { exact: true }).first();
      await target.scrollIntoViewIfNeeded().catch(() => {});
      await target.evaluate((el) => {
        const card = el.closest("section, article, [class*='rounded']") ?? el;
        card.scrollIntoView({ behavior: "smooth", block: "center" });
      });
      await sleep(1100); // measure only once the smooth scroll has settled
      const box = await target.evaluate((el) => {
        const r = (el.closest("section, article, [class*='rounded']") ?? el).getBoundingClientRect();
        return { x: r.x, y: r.y, width: r.width, height: r.height };
      });
      marks.push({ t: Date.now() - stop.startedAt, type: "metric", label, box });
      await page.evaluate((b) => window.__eeSpotlight?.(b), box).catch(() => {});
      await sleep(4500); // live numbers tick while the metric is held
      } catch (e) {
        console.error(`admin-${users}: "${label}" not shown (${e.message.split(String.fromCharCode(10))[0]})`);
        marks.push({ t: Date.now() - stop.startedAt, type: "missing", label });
      }
    }
    await smoothScroll(page, -2000, 900);
    await sleep(1500);
    const result = await stop();
    save(`admin-${users}`, { ...result, startedAtEpoch: stop.startedAt, users, marks });
  } finally {
    await browser.close();
  }
}

// --- schedules (seconds from the load's start; a step is skipped if it can't start in time) ---

const W = (at, until) => ({ type: "wall", at, until });
const A = (at, until, users) => ({ type: "admin", at, until, users });
const SCHEDULES = {
  smoke: [W(0, 9999), A(0, 9999, 500)],
  cost: [A(0, 9999, "cost")], // with --no-k6, after the run // with --no-k6: one clip of each kind, to check the setup
  rehearsal: [W(25, 60), W(130, 200), A(250, 330, 500), W(400, 480)],
  run: [
    W(5, 40), W(60, 95), // 1 user
    W(170, 210), W(240, 280), // 50 users
    W(325, 360), // rising to 500
    A(410, 470, 500), W(510, 540), // 500 users
    A(670, 720, 1000), W(760, 790), // 1,000 users
    W(830, 860), W(880, 910), // rising to 2,000
    A(980, 1040, 2000), W(1100, 1130), W(1150, 1180), // 2,000 users
    W(1240, 1290), // ramp down
  ],
};

async function main() {
  const questions = wallQuestions();
  if (args.profile !== "cost") await clearAccounts();
  const { t0, arn } = args["no-k6"] ? { t0: Date.now(), arn: null } : await startK6(args.profile);
  writeFileSync(`${OUT}/k6.json`, JSON.stringify({ profile: args.profile, t0, arn }, null, 2));
  console.log(`k6 running (${args.profile}); schedule starts`);
  let clip = 0;
  for (const step of SCHEDULES[args.profile]) {
    const now = (Date.now() - t0) / 1000;
    if (now > step.until) {
      console.log(`skipped ${step.type} at ${step.at}s (now ${now.toFixed(0)}s)`);
      continue;
    }
    if (now < step.at) await sleep((step.at - now) * 1000);
    try {
      if (step.type === "wall") {
        clip += 1;
        await wallClip(clip, questions[(clip - 1) % questions.length], clip % 2 ? MEMBER : ADMIN);
      } else {
        await adminCheckpoint(step.users);
      }
    } catch (e) {
      console.error(`${step.type} at ${step.at}s failed: ${e.message}`);
    }
  }
  console.log("schedule done");
}

await main();
