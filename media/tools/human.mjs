// Person-like input for recordings: quick eased mouse moves, clicks on elements, and typing at
// a natural pace. Kept brisk on purpose: a move takes about 0.25–0.5 s, like a confident user.

let cursor = { x: 960, y: 540 };

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

/** Move the mouse to (x, y) along an eased path; duration grows a little with distance. */
export async function moveTo(page, x, y) {
  const from = { ...cursor };
  const distance = Math.hypot(x - from.x, y - from.y);
  const duration = Math.min(500, 220 + distance * 0.25); // ms
  const frames = Math.max(8, Math.round(duration / 16));
  for (let i = 1; i <= frames; i++) {
    const t = easeInOut(i / frames);
    await page.mouse.move(from.x + (x - from.x) * t, from.y + (y - from.y) * t);
    await sleep(duration / frames);
  }
  cursor = { x, y };
}

/** Move to the centre of an element (scrolled into view) and click it. */
export async function clickOn(page, locator, { pause = 120 } = {}) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (!box) throw new Error("element is not visible");
  await moveTo(page, box.x + box.width / 2, box.y + box.height / 2);
  await sleep(pause);
  await page.mouse.down();
  await sleep(60);
  await page.mouse.up();
}

/** Type like a person: 35–90 ms per key, a little longer after spaces and punctuation. */
export async function typeLikeAPerson(page, text) {
  for (const ch of text) {
    await page.keyboard.type(ch);
    const base = 35 + Math.random() * 55;
    await sleep(/[ ,.?!]/.test(ch) ? base + 40 : base);
  }
}

/** Smooth scroll of the element under (x, y) by dy pixels over `ms`. */
export async function smoothScroll(page, dy, ms = 700) {
  const steps = Math.max(10, Math.round(ms / 16));
  for (let i = 0; i < steps; i++) {
    await page.mouse.wheel(0, dy / steps);
    await sleep(ms / steps);
  }
}

export { sleep };
