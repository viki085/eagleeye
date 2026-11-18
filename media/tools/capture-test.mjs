// V1 check: a 10-second capture of the live sign-in page in the recording browser.
//   node tools/capture-test.mjs <site url>      (run from media/)
import { openRecordingBrowser } from "./browser.mjs";
import { startCapture } from "./capture.mjs";
import { clickOn, moveTo, sleep, typeLikeAPerson } from "./human.mjs";

const url = process.argv[2];
if (!url) throw new Error("usage: node tools/capture-test.mjs <site url>");

const { browser, page } = await openRecordingBrowser();
try {
  await page.goto(url, { waitUntil: "load" });
  await page.waitForTimeout(2500); // sign-in widget settles
  const stop = await startCapture(page, { out: "raw/capture-test.mp4" });
  await moveTo(page, 400, 300);
  await sleep(400);
  const email = page.getByPlaceholder(/yourcompany/i);
  await clickOn(page, email);
  await typeLikeAPerson(page, "ava.chen+clerk_test@example.com");
  await sleep(800);
  await moveTo(page, 1300, 700);
  await sleep(600);
  await moveTo(page, 960, 540);
  await sleep(2000);
  console.log(await stop());
} finally {
  await browser.close();
}
