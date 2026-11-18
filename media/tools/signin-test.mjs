// V1 check: the on-camera sign-in for a video employee. Types the company email and password
// like a person, then (where the video cuts) signs in with a one-time ticket instead of pressing
// Sign in, so Clerk's new-device code check never runs and no email is sent.
//   node tools/signin-test.mjs <site url> <email>      (run from media/)
import { readFileSync } from "node:fs";
import { openRecordingBrowser } from "./browser.mjs";
import { signInWithTicket } from "./clerk-ticket.mjs";
import { clickOn, moveTo, sleep, typeLikeAPerson } from "./human.mjs";

const [url, email] = process.argv.slice(2);
const { password } = JSON.parse(readFileSync(new URL("../.secrets/employees.json", import.meta.url)))[email];

const { browser, page } = await openRecordingBrowser();
try {
  await page.goto(`${url}/sign-in`, { waitUntil: "load" });
  await clickOn(page, page.getByPlaceholder(/yourcompany/i));
  await typeLikeAPerson(page, email);
  await clickOn(page, page.getByRole("button", { name: "Continue", exact: true }));
  const pw = page.locator('input[type="password"]');
  await pw.waitFor({ timeout: 15000 });
  await clickOn(page, pw);
  await page.keyboard.type(password, { delay: 45 });
  const signInButton = page.getByRole("button", { name: "Sign in", exact: true });
  const box = await signInButton.boundingBox();
  await moveTo(page, box.x + box.width / 2, box.y + box.height / 2);
  await sleep(300);
  // --- the video cuts here ---
  await signInWithTicket(page, email);
  await page.goto(url, { waitUntil: "load" });
  await sleep(10000); // the app may show "Starting EagleEye" while the server wakes
  await page.screenshot({ path: "raw/signin-test.png", scale: "css" });
  console.log("signed in, now at", new URL(page.url()).pathname);
} catch (e) {
  await page.screenshot({ path: "raw/signin-fail.png", scale: "css" });
  console.log("failed:", e.message.split(/\r?\n/)[0]);
} finally {
  await browser.close();
}
