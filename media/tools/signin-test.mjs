// V1 check: sign in on the live site as a video employee (company email + password).
//   node tools/signin-test.mjs <site url> <email>      (run from media/)
import { readFileSync } from "node:fs";
import { openRecordingBrowser } from "./browser.mjs";
import { clickOn, sleep, typeLikeAPerson } from "./human.mjs";

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
  await page.keyboard.type(password, { delay: 40 });
  await clickOn(page, page.getByRole("button", { name: "Sign in", exact: true }));
  await page.waitForURL((u) => !u.pathname.startsWith("/sign-in"), { timeout: 30000 });
  await sleep(8000); // the app may show "Starting EagleEye" while the server wakes
  await page.screenshot({ path: "raw/signin-test.png" });
  console.log("signed in, now at", new URL(page.url()).pathname);
} catch (e) {
  await page.screenshot({ path: "raw/signin-fail.png" });
  console.log("failed:", e.message.split(/\r?\n/)[0]);
} finally {
  await browser.close();
}
