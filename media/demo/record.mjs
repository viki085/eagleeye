// Records the product video's scenes on the live site (see demo/script.md).
//
//   node demo/record.mjs <site url> [scene numbers...]      (run from media/)
//
// Each scene is its own clip: raw/scenes/s<N>.mp4, with raw/scenes/s<N>.json holding markers
// (milliseconds from the clip's start): typing, the answer's start and end (so the edit can
// speed up the wait), and every reading stop with its screen rectangle.
//
// Before scene 1 the employees' chats, uploaded documents and data files are cleared, so the
// video starts from a clean account. Sign-in is typed on camera; at the cut a one-time ticket
// finishes it (no email, no code check).
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { openRecordingBrowser } from "../tools/browser.mjs";
import { startCapture } from "../tools/capture.mjs";
import { signInWithTicket } from "../tools/clerk-ticket.mjs";
import { clickOn, moveTo, sleep, smoothScroll, typeLikeAPerson } from "../tools/human.mjs";

const API = "https://d16snbdnl2nrgm.cloudfront.net";
const VIKRAM = "vikram.k@grandlineshipping.com";
const SAM = "sam.rivera@grandlineshipping.com";
const NOTES = resolve("..", "Trial/data/documents/account-review-notes-hunt-williams-francis.docx");
const VOYAGES = resolve("..", "Trial/data/data-files/vessel_fuel_and_emissions.csv");
const OUT = "raw/scenes";
const ANSWER_TIMEOUT_MS = 8 * 60 * 1000;
const STOP_MS = 1500; // a reading stop on a key insight

const Q = Object.fromEntries(JSON.parse(readFileSync("demo/questions.json", "utf8")).map((q) => [q.id, q.text]));
Q.brent = "The customer will ask about fuel surcharges. " + Q.chart;
const passwords = JSON.parse(readFileSync(".secrets/employees.json", "utf8"));

const [site, ...wanted] = process.argv.slice(2);
mkdirSync(OUT, { recursive: true });

// ---------- helpers ----------

async function api(page, path, init) {
  await page.waitForFunction(() => window.Clerk?.session, null, { timeout: 60_000 }); // Clerk ready
  return page.evaluate(
    async ({ base, path, init }) => {
      const token = await window.Clerk.session.getToken();
      const res = await fetch(base + path, { ...init, headers: { Authorization: `Bearer ${token}` } });
      return res.status === 204 ? null : res.json();
    },
    { base: API, path, init },
  );
}

/** Clean account: no chats, no personal documents, no data files. */
async function resetAccount(page) {
  for (const c of (await api(page, "/v1/chats")).data ?? []) await api(page, `/v1/chats/${c.id}`, { method: "DELETE" });
  for (const d of (await api(page, "/v1/documents")).data ?? [])
    if (d.scope === "personal") await api(page, `/v1/documents/${d.id}`, { method: "DELETE" });
  for (const d of (await api(page, "/v1/datasets")).data ?? []) await api(page, `/v1/datasets/${d.id}`, { method: "DELETE" }).catch(() => {});
}

async function openAs(email, { typed = false } = {}) {
  const { browser, page } = await openRecordingBrowser();
  await page.goto(`${site}/sign-in`, { waitUntil: "load" });
  await page.waitForFunction(() => window.Clerk?.loaded, null, { timeout: 30_000 });
  if (!typed) {
    await signInWithTicket(page, email);
    await page.goto(site, { waitUntil: "load" });
    await page.getByLabel("Message").waitFor({ timeout: 6 * 60 * 1000 });
  }
  return { browser, page };
}

let currentScene = null;

class Scene {
  constructor(n, page) {
    this.n = n;
    this.page = page;
    this.markers = [];
    currentScene = this;
  }
  async discard() {
    if (this.stop) await this.stop().catch(() => {});
  }
  async start() {
    this.stop = await startCapture(this.page, { out: `${OUT}/s${this.n}.mp4` });
    this.t0 = this.stop.startedAt;
    this.mark("start");
  }
  mark(type, extra = {}) {
    this.markers.push({ t: Date.now() - this.t0, type, ...extra });
  }
  async end() {
    this.mark("end");
    const result = await this.stop();
    writeFileSync(`${OUT}/s${this.n}.json`, JSON.stringify({ scene: this.n, ...result, markers: this.markers }, null, 2));
    console.log(`scene ${this.n}: ${result.seconds.toFixed(1)}s`);
  }
}

/** While the agent works, keep its steps panel open (it redraws as steps arrive, which can
 * close it again). Calls onTick with the panel's text every half second. */
async function keepStepsOpen(scene, onTick) {
  const { page } = scene;
  let marked = false;
  while (await page.getByLabel("Stop answering").count()) {
    const live = page.locator("main button[aria-expanded]").filter({ hasText: /Working/ }).last();
    if ((await live.count()) && (await live.getAttribute("aria-expanded").catch(() => null)) === "false") {
      await clickOn(page, live).catch(() => {});
      if (!marked) {
        scene.mark("steps_open");
        marked = true;
      }
    }
    if (onTick) await onTick(await page.locator("main").innerText().catch(() => ""));
    await sleep(500);
  }
  if (!marked) scene.mark("steps_open");
}

async function ask(scene, text, { expandSteps = false } = {}) {
  const { page } = scene;
  await clickOn(page, page.getByLabel("Message"));
  scene.mark("typing");
  await typeLikeAPerson(page, text);
  await sleep(400);
  await clickOn(page, page.getByRole("button", { name: "Send", exact: true }));
  scene.mark("answer_start");
  await page.getByLabel("Stop answering").waitFor({ timeout: 60_000 });
  if (expandSteps) await keepStepsOpen(scene);
  await page.getByLabel("Stop answering").waitFor({ state: "detached", timeout: ANSWER_TIMEOUT_MS });
  await sleep(1500); // charts and pictures finish drawing
  scene.mark("answer_end");
  // the steps panel is left as the app leaves it (it closes itself when the answer completes)
}

/**
 * Back to the start of the latest answer, then a stop (gold outline) at each key insight only.
 * targets: [{ sel, text }] — the first element in the answer matching the CSS selector whose
 * text matches the pattern; charts and pictures are found in the whole answer bubble.
 */
async function readAnswer(scene, targets) {
  const { page } = scene;
  const found = await page.evaluate((targets) => {
    document.querySelectorAll("[data-ee-stop]").forEach((e) => e.removeAttribute("data-ee-stop"));
    const prose = [...document.querySelectorAll("main .prose")].pop();
    if (!prose) return 0;
    const bubble = prose.parentElement;
    let n = 0;
    for (const t of targets) {
      const scope = /figure|img/.test(t.sel) ? bubble : prose;
      const re = new RegExp(t.text ?? ".", "i");
      const el = [...scope.querySelectorAll(t.sel)].find((e) => !e.hasAttribute("data-ee-stop") && re.test(e.textContent || e.getAttribute("alt") || ""));
      if (el) {
        el.setAttribute("data-ee-stop", String(n++));
        el.setAttribute("data-ee-target", String(targets.indexOf(t)));
      }
    }
    if (n === 0 && prose.querySelector("p")) prose.querySelector("p").setAttribute("data-ee-stop", String(n++));
    return n;
  }, targets);

  await page.locator("main .prose").last().evaluate((el) => el.scrollIntoView({ block: "start", behavior: "smooth" }));
  await sleep(1100);
  for (let i = 0; i < found; i++) {
    const el = page.locator(`[data-ee-stop="${i}"]`);
    await el.evaluate((e) => e.scrollIntoView({ block: "center", behavior: "smooth" }));
    await sleep(650);
    const box = await el.boundingBox();
    if (!box) continue;
    const rect = { x: box.x, y: box.y, width: box.width, height: Math.min(box.height, 300) };
    await page.evaluate((r) => window.__eeSpotlight(r), rect);
    scene.mark("read", { rect, label: (await el.innerText()).slice(0, 80) });
    const ti = Number(await el.getAttribute("data-ee-target"));
    await sleep(targets[ti]?.ms ?? STOP_MS);
    await page.evaluate(() => window.__eeSpotlight(null));
    await sleep(200);
  }
}

class Retake extends Error {}

/** A showcase answer must be clean: no work-limit note, no figure-check warning. */
async function requireCleanAnswer(page) {
  const text = await page.locator("main .prose").last().locator("xpath=..").innerText();
  if (/work limit|couldn.t be matched|could not be generated|may be incomplete/i.test(text)) throw new Retake(text.slice(0, 80));
}

async function deleteNewestChat(page) {
  const chats = (await api(page, "/v1/chats")).data ?? [];
  if (chats[0]) await api(page, `/v1/chats/${chats[0].id}`, { method: "DELETE" });
}

async function waitForRow(page, text, timeout = 4 * 60 * 1000) {
  await page.waitForFunction(
    (s) =>
      [...document.querySelectorAll("aside li, aside div")].some((el) => {
        const t = el.textContent.toLowerCase().replace(/[-_]+/g, " ");
        return el.children.length < 12 && t.includes(s) && /ready/.test(t);
      }),
    text,
    { timeout, polling: 1000 },
  );
}

async function upload(page, file) {
  const chooser = page.waitForEvent("filechooser");
  await clickOn(page, page.getByText(/Upload document or data/).first());
  await (await chooser).setFiles(file);
}

// ---------- scenes ----------

const scenes = {
  // 1 · sign in (typed); the clip ends at the cut
  async 1() {
    // clean account first (also wakes the server), signed in off camera with a ticket
    {
      const pre = await openAs(VIKRAM);
      await resetAccount(pre.page);
      await pre.browser.close();
    }
    const { browser, page } = await openAs(VIKRAM, { typed: true });
    const s = new Scene(1, page);
    await sleep(1500);
    await s.start();
    await sleep(800);
    await clickOn(page, page.getByPlaceholder(/yourcompany/i));
    await typeLikeAPerson(page, VIKRAM);
    await sleep(300);
    await clickOn(page, page.getByRole("button", { name: "Continue", exact: true }));
    const pw = page.locator('input[type="password"]');
    await pw.waitFor({ timeout: 15000 });
    await clickOn(page, pw);
    await page.keyboard.type(passwords[VIKRAM].password, { delay: 55 });
    const button = await page.getByRole("button", { name: "Sign in", exact: true }).boundingBox();
    await moveTo(page, button.x + button.width / 2, button.y + button.height / 2);
    await sleep(500);
    s.mark("cut");
    await s.end();
    await signInWithTicket(page, VIKRAM);
    await page.goto(site, { waitUntil: "load" });
    await page.getByLabel("Message").waitFor({ timeout: 6 * 60 * 1000 });
    return { browser, page };
  },

  // 2 · tour: upload notes, open the review in the PDF viewer, search the data sources
  async 2(page) {
    const s = new Scene(2, page);
    await sleep(1500);
    await s.start();
    await sleep(1200);
    await clickOn(page, page.getByRole("tab", { name: /personal/i }));
    await upload(page, NOTES);
    s.mark("upload");
    await waitForRow(page, "account review notes");
    s.mark("ready");
    await sleep(900);
    await clickOn(page, page.locator("aside").getByText(/account-review-notes/).first());
    s.mark("preview");
    await sleep(3200);
    await clickOn(page, page.locator("dialog").getByLabel("Close"));
    await sleep(700);
    await clickOn(page, page.getByRole("tab", { name: /enterprise/i }));
    s.mark("enterprise");
    await sleep(900);
    const search = page.getByLabel("Search company documents and data sources");
    await clickOn(page, search);
    await typeLikeAPerson(page, "fleet and market");
    await sleep(900);
    await clickOn(page, page.getByText("Fleet and Market Review 2025").first());
    s.mark("viewer_open");
    await sleep(2500); // the PDF renders
    const frame = await page.locator("dialog iframe").boundingBox();
    if (frame) {
      await moveTo(page, frame.x + frame.width / 2, frame.y + frame.height / 2);
      await smoothScroll(page, 1800, 1300); // one quick scroll to the chart page
      s.mark("charts_page");
      await sleep(2000);
    }
    await clickOn(page, page.locator("dialog").getByLabel("Close"));
    await sleep(700);
    await clickOn(page, search);
    await page.keyboard.press("Control+A");
    await typeLikeAPerson(page, "reliability");
    s.mark("data_sources");
    await sleep(1500);
    const sources = page.getByText("Data sources").first();
    const box = await sources.boundingBox();
    if (box) await moveTo(page, box.x + 60, box.y + 60);
    await sleep(2500);
    await clickOn(page, search);
    await page.keyboard.press("Control+A");
    await page.keyboard.press("Backspace");
    await clickOn(page, page.getByRole("tab", { name: /personal/i }));
    await sleep(800);
    await s.end();
  },

  // 3 · the meeting brief: notes + policies + database; reading stops; Show on page
  async 3(page) {
    const s = new Scene(3, page);
    await s.start();
    await sleep(800);
    await clickOn(page, page.getByRole("button", { name: /New chat/ }).first());
    await sleep(600);
    await ask(s, Q.brief, { expandSteps: true });
    await requireCleanAnswer(page);
    // each stop is held while the Expert names where that part came from
    await readAnswer(s, [
      { sel: "h1, h2, h3, h4, p", text: "brief|meeting", ms: 4800 },
      { sel: "p, li, table", text: "claims", ms: 6300 },
      { sel: "p, li", text: "temperature alarm|30 minutes", ms: 7700 },
      { sel: "p, li, table", text: "2026", ms: 7200 },
    ]);
    const chip = page.locator('[aria-label="Sources"] button').filter({ hasText: /Reefer/ }).first();
    await chip.evaluate((e) => e.scrollIntoView({ block: "center", behavior: "smooth" }));
    await sleep(700);
    await clickOn(page, chip);
    s.mark("source_open");
    await sleep(1800);
    await clickOn(page, page.getByRole("button", { name: /Show on page/ }));
    await sleep(3500);
    s.mark("page_highlight");
    await sleep(2500);
    await clickOn(page, page.getByLabel("Close source"));
    await sleep(800);
    await s.end();
  },

  // 4 · a chart inside a PDF (same chat)
  async 4(page) {
    const s = new Scene(4, page);
    await s.start();
    await sleep(600);
    await ask(s, Q.brent, { expandSteps: true });
    await readAnswer(s, [
      { sel: "p", text: "Brent|\\$" },
      { sel: "figure, img", text: "." },
    ]);
    await sleep(800);
    await s.end();
  },

  // 5 · the SQL in plain sight (same chat)
  async 5(page) {
    const s = new Scene(5, page);
    await s.start();
    await sleep(600);
    await ask(s, Q.database, { expandSteps: true });
    await readAnswer(s, [
      { sel: "p", text: "worst|Asia" },
      { sel: "figure", text: "." },
    ]);
    const card = page.locator("main details summary").filter({ hasText: /table & SQL/ }).last();
    await card.evaluate((e) => e.scrollIntoView({ block: "center", behavior: "smooth" }));
    await sleep(600);
    await clickOn(page, card);
    await sleep(900);
    const sql = page.locator("main details[open] details summary").filter({ hasText: /SQL/ }).last();
    await clickOn(page, sql);
    s.mark("sql_open");
    await sleep(700);
    await page.locator("main details[open] pre").last().evaluate((e) => e.scrollIntoView({ block: "center", behavior: "smooth" }));
    await sleep(2800);
    await clickOn(page, page.locator("main button[aria-expanded]").filter({ hasText: /Worked for/ }).last());
    s.mark("steps_open");
    await sleep(2500);
    await s.end();
  },

  // 6 · upload, profile, drag the file into the message, the EDA notebook
  async 6(page) {
    const s = new Scene(6, page);
    await s.start();
    await sleep(800);
    await clickOn(page, page.getByRole("button", { name: /New chat/ }).first());
    if (!(await page.locator("aside li").filter({ hasText: /vessel fuel and emissions/i }).count())) {
      await upload(page, VOYAGES);
      s.mark("upload");
      await waitForRow(page, "vessel fuel and emissions");
      s.mark("ready");
    }
    await sleep(1000);
    const row = page.locator("aside li").filter({ hasText: /vessel fuel and emissions/i }).first();
    await clickOn(page, row.getByRole("button", { name: "Profile" }));
    s.mark("profile");
    await sleep(2500);
    const dialog = page.locator("section[role=dialog]");
    const dbox = await dialog.boundingBox();
    if (dbox) {
      await moveTo(page, dbox.x + dbox.width / 2, dbox.y + dbox.height / 2);
      await smoothScroll(page, 600, 1400);
      await sleep(1800);
    }
    await clickOn(page, dialog.getByLabel("Close"));
    await sleep(700);
    // type the start, drag the file in, type the rest
    const [before, after] = Q.eda.split("my vessel_fuel_and_emissions data");
    await clickOn(page, page.getByLabel("Message"));
    s.mark("typing");
    await typeLikeAPerson(page, before);
    const source = await row.boundingBox();
    const target = await page.getByLabel("Message").boundingBox();
    await moveTo(page, source.x + 60, source.y + source.height / 2);
    await page.mouse.down();
    await moveTo(page, target.x + target.width * 0.6, target.y + target.height / 2);
    await sleep(250);
    await page.mouse.up();
    s.mark("dropped");
    await sleep(600);
    await page.keyboard.press("End");
    await typeLikeAPerson(page, after.trimStart().startsWith(":") ? after : ` ${after.trimStart()}`);
    await sleep(500);
    await clickOn(page, page.getByRole("button", { name: "Send", exact: true }));
    s.mark("answer_start");
    await page.getByLabel("Stop answering").waitFor({ timeout: 60_000 });
    const stages = [["step_write", /write notebook/i], ["step_run", /run notebook/i], ["step_answer", /plan & answer[\s\S]*plan & answer/i]];
    await keepStepsOpen(s, (text) => {
      while (stages.length && stages[0][1].test(text)) s.mark(stages.shift()[0]);
    });
    for (const [name] of stages) s.mark(name);
    await sleep(2500);
    s.mark("answer_end");

    await requireCleanAnswer(page);
    await readAnswer(s, [
      { sel: "p, li", text: "speed" },
      { sel: "p, li", text: "vessel class|Post-Panamax" },
      { sel: "p, li", text: "Data quality|duplicate|missing" },
    ]);
    // the notebook: open it, scroll the cells, enlarge a figure, hover the download
    const nb = page.locator("main section[aria-label^='Notebook']").last();
    await nb.evaluate((e) => e.scrollIntoView({ block: "start", behavior: "smooth" }));
    await sleep(1200);
    const head = nb.locator("header button").first();
    if ((await head.getAttribute("aria-expanded")) === "false") await clickOn(page, head);
    s.mark("notebook");
    await sleep(1200);
    const nbox = await nb.boundingBox();
    await moveTo(page, nbox.x + nbox.width / 2, Math.min(nbox.y + 300, 900));
    for (let i = 0; i < 6; i++) {
      await smoothScroll(page, 650, 1300);
      await sleep(1500);
    }
    const fig = nb.locator("img").nth(2);
    if (await fig.count()) {
      await fig.evaluate((e) => e.scrollIntoView({ block: "center", behavior: "smooth" }));
      await sleep(800);
      await clickOn(page, fig);
      s.mark("figure_enlarged");
      await sleep(3000);
      await page.keyboard.press("Escape").catch(() => {});
      await page.mouse.click(30, 30);
      await sleep(800);
    }
    const dl = nb.getByRole("button", { name: /Download \.ipynb/ });
    await dl.evaluate((e) => e.scrollIntoView({ block: "center", behavior: "smooth" }));
    await sleep(700);
    const dlbox = await dl.boundingBox();
    await moveTo(page, dlbox.x + dlbox.width / 2, dlbox.y + dlbox.height / 2);
    s.mark("download_hover");
    await sleep(2200);
    await s.end();
  },

  // 7 · Sam tries the guardrails
  async 7() {
    const pre = await openAs(SAM);
    await resetAccount(pre.page);
    await pre.page.reload({ waitUntil: "load" });
    await pre.page.getByLabel("Message").waitFor({ timeout: 6 * 60 * 1000 });
    const page = pre.page;
    const s = new Scene(7, page);
    await sleep(1200);
    await s.start();
    await sleep(800);
    const showSteps = async (label) => {
      await sleep(900);
      const done = page.locator("main button[aria-expanded]").filter({ hasText: /Worked for/ }).last();
      if ((await done.getAttribute("aria-expanded")) === "false") await clickOn(page, done);
      s.mark("read", { label });
      await sleep(3200);
    };
    await ask(s, Q.guard_injection);
    await showSteps("declined");
    await ask(s, Q.guard_salary);
    await showSteps("not available");
    await s.end();
    await pre.browser.close();
  },
};

// ---------- run ----------

const order = (wanted.length ? wanted : ["1", "2", "3", "4", "5", "6", "7"]).map(String);
let session = null;
try {
  for (const n of order) {
    if (n === "7") {
      await scenes[7]();
      continue;
    }
    if (!session) {
      session = n === "1" ? await scenes[1]() : await openAs(VIKRAM);
      if (n === "1") continue;
    }
    for (let attempt = 1; ; attempt++) {
      try {
        await scenes[n](session.page);
        break;
      } catch (e) {
        if (!(e instanceof Retake) || attempt >= 5 || !["3", "6"].includes(n)) throw e;
        console.log(`scene ${n}: retake ${attempt} (${e.message})`);
        await currentScene?.discard();
        await deleteNewestChat(session.page);
        await session.page.goto(site, { waitUntil: "load" });
        await session.page.getByLabel("Message").waitFor({ timeout: 120_000 });
      }
    }
  }
} finally {
  if (session) await session.browser.close();
}
