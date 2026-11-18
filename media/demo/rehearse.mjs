// V2 rehearsal: ask candidate questions on the live app as the video's employees and keep the
// results (answer text, time, cost, a full-length screenshot) for choosing the final script.
//
//   node demo/rehearse.mjs <site url> [question ids...]      (run from media/)
//
// Each question runs in a new chat. Spend is checked through the account's own usage figure
// and logged in costs.jsonl; the run stops before the answers' share of the budget is passed.
// Sign-in uses a one-time ticket (no typing, no email). Results go to raw/rehearsal/.
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { openRecordingBrowser } from "../tools/browser.mjs";
import { signInWithTicket } from "../tools/clerk-ticket.mjs";

const API = "https://d16snbdnl2nrgm.cloudfront.net";
const ANSWERS_BUDGET_USD = 3.0;
const ANSWER_TIMEOUT_MS = 8 * 60 * 1000;
const LEDGER = "costs.jsonl";
const OUT = "raw/rehearsal";

const [site, ...only] = process.argv.slice(2);
const questions = JSON.parse(readFileSync("demo/questions.json", "utf8")).filter((q) => !only.length || only.includes(q.id));
mkdirSync(OUT, { recursive: true });

const answersSpent = () =>
  existsSync(LEDGER)
    ? readFileSync(LEDGER, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse).filter((r) => r.kind === "answers").reduce((s, r) => s + r.usd, 0)
    : 0;

async function api(page, path, init) {
  return page.evaluate(
    async ({ base, path, init }) => {
      const token = await window.Clerk.session.getToken();
      const res = await fetch(base + path, { ...init, headers: { ...(init?.headers ?? {}), Authorization: `Bearer ${token}` } });
      return res.json();
    },
    { base: API, path, init },
  );
}
const usage = async (page) => (await api(page, "/v1/me/usage")).data.cost_usd;

async function waitForApp(page) {
  // the demo server may be asleep: the app shows "Starting EagleEye" until it answers
  await page.getByLabel("Message").waitFor({ timeout: 6 * 60 * 1000 });
}

async function waitForAnswer(page) {
  await page.getByLabel("Stop answering").waitFor({ timeout: 60_000 });
  await page.getByLabel("Stop answering").waitFor({ state: "detached", timeout: ANSWER_TIMEOUT_MS });
  await page.waitForTimeout(2500); // final render (charts, pictures)
}

async function fullScreenshot(page, path) {
  // let the chat column grow to its full height for one screenshot, then restore it
  await page.evaluate(() => {
    const shell = document.querySelector("div.h-dvh");
    const scroller = document.querySelector("main .overflow-y-auto");
    shell?.setAttribute("data-h", shell.className);
    shell?.classList.remove("h-dvh", "overflow-hidden");
    scroller?.classList.remove("overflow-y-auto", "flex-1");
  });
  await page.screenshot({ path, fullPage: true, scale: "css" });
  await page.evaluate(() => {
    const shell = document.querySelector("div[data-h]");
    if (shell) shell.className = shell.getAttribute("data-h");
    document.querySelector("main > div:not([class*=overflow])")?.classList.add("overflow-y-auto", "flex-1");
  });
}

let current = null; // { email, browser, page }
async function as(email) {
  if (current?.email === email) return current.page;
  if (current) await current.browser.close();
  const { browser, page } = await openRecordingBrowser();
  await page.goto(`${site}/sign-in`, { waitUntil: "load" });
  await page.waitForFunction(() => window.Clerk?.loaded, null, { timeout: 30_000 });
  await signInWithTicket(page, email);
  await page.goto(site, { waitUntil: "load" });
  await waitForApp(page);
  current = { email, browser, page };
  return page;
}

const results = [];
try {
  for (const q of questions) {
    if (answersSpent() >= ANSWERS_BUDGET_USD - 0.3) {
      console.log(`stopping: answers budget nearly used ($${answersSpent().toFixed(3)} of $${ANSWERS_BUDGET_USD})`);
      break;
    }
    const page = await as(q.who);
    await page.getByRole("button", { name: /New chat/ }).first().click();
    await page.waitForTimeout(800);
    if (q.upload) {
      await page.locator('input[type="file"]').first().setInputFiles(resolve("..", q.upload));
      await page.getByText(/Ready/).first().waitFor({ timeout: 3 * 60 * 1000 });
      await page.waitForTimeout(3000);
    }
    const before = await usage(page);
    const started = Date.now();
    await page.getByLabel("Message").fill(q.text);
    await page.keyboard.press("Enter");
    await waitForAnswer(page);
    const seconds = Math.round((Date.now() - started) / 1000);
    const after = await usage(page);
    const usd = Math.max(0, after - before);
    appendFileSync(LEDGER, JSON.stringify({ t: new Date().toISOString().slice(0, 19), kind: "answers", usd: Number(usd.toFixed(5)), detail: `rehearsal ${q.id} ${seconds}s` }) + "\n");
    const text = await page.locator("main").innerText();
    writeFileSync(`${OUT}/${q.id}.txt`, text);
    await fullScreenshot(page, `${OUT}/${q.id}.png`);
    results.push({ id: q.id, seconds, usd: Number(usd.toFixed(4)) });
    console.log(`${q.id}: ${seconds}s, $${usd.toFixed(4)} (answers total $${answersSpent().toFixed(3)})`);
  }
} finally {
  if (current) await current.browser.close();
  writeFileSync(`${OUT}/summary.json`, JSON.stringify(results, null, 2));
}
