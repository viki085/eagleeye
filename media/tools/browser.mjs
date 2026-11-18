// The recording browser: Google Chrome in kiosk mode (full screen; no tabs, address bar,
// bookmarks or taskbar), a fresh temporary profile (none of your own accounts, history or
// extensions), and no "controlled by automated software" banner.
//
// The display is 3840x2160 at 150% Windows scaling. Chrome renders at scale 2, so the app lays
// out as a standard 1920x1080 screen with 4K-sharp text; the capture is scaled to 1920x1080.
import { chromium } from "playwright";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const CURSOR = fileURLToPath(new URL("./cursor.js", import.meta.url));
const PAGE_TITLE = "EagleEye recording";
// Chrome names its window "<page title> - Google Chrome"; ffmpeg needs the exact window name
export const WINDOW_TITLE = `${PAGE_TITLE} - Google Chrome`;

export async function openRecordingBrowser() {
  // one persistent window (kiosk applies to it) on a fresh, throwaway profile
  const profile = mkdtempSync(join(tmpdir(), "ee-recording-"));
  const context = await chromium.launchPersistentContext(profile, {
    headless: false,
    channel: "chrome",
    viewport: null,
    ignoreDefaultArgs: ["--enable-automation"],
    args: [
      "--kiosk",
      "--start-fullscreen",
      "--window-position=0,0",
      "--force-device-scale-factor=2",
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-infobars",
      "--hide-crash-restore-bubble",
      "--disable-features=Translate,PasswordManagerOnboarding",
      "--password-store=basic",
    ],
  });
  await context.addInitScript({ path: CURSOR });
  // keep a fixed window title so the capture finds this window and nothing else
  await context.addInitScript((title) => {
    const pin = () => {
      if (document.title !== title) document.title = title;
    };
    document.addEventListener("DOMContentLoaded", () => {
      pin();
      new MutationObserver(pin).observe(document.head, { subtree: true, childList: true, characterData: true });
    });
  }, PAGE_TITLE);
  const page = context.pages()[0] ?? (await context.newPage());
  const browser = {
    close: async () => {
      await context.close();
      rmSync(profile, { recursive: true, force: true }); // nothing from the session is kept
    },
  };
  return { browser, context, page };
}
