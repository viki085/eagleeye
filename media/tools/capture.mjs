// Records ONLY the web page: frames come from Chrome's own screencast (DevTools protocol), so
// nothing else on the computer can ever be in the video: not other windows, notifications,
// the taskbar or the desktop. The drawn cursor (cursor.js) is part of the page, so it is
// included; the real mouse pointer is not.
//
// Chrome sends a frame whenever the page changes. A steady clock feeds the latest frame to ffmpeg
// 30 times a second, giving a constant-rate 3840x2160 (4K) H.264 file.
//
//   const stop = await startCapture(page, { out: "raw/scene2.mp4" });
//   ... drive the page ...
//   await stop();
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import ffmpegPath from "ffmpeg-static";

const FPS = 30;

export async function startCapture(page, { out }) {
  mkdirSync(dirname(out), { recursive: true });
  const ffmpeg = spawn(
    ffmpegPath,
    [
      "-y", "-hide_banner", "-loglevel", "error",
      "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "mjpeg", "-i", "-",
      // 4K: the page renders at 3840x2160 device pixels; the GPU encoder (NVENC) keeps up in real time
      "-vf", "scale=3840:2160:flags=lanczos,format=yuv420p",
      "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "17", "-b:v", "0", "-r", String(FPS),
      out,
    ],
    { stdio: ["pipe", "inherit", "inherit"] },
  );

  const cdp = await page.context().newCDPSession(page);
  let latest = null;
  cdp.on("Page.screencastFrame", async ({ data, sessionId }) => {
    latest = Buffer.from(data, "base64");
    try {
      await cdp.send("Page.screencastFrameAck", { sessionId });
    } catch {
      // the session ended while a frame was in flight
    }
  });
  await cdp.send("Page.startScreencast", { format: "jpeg", quality: 95, maxWidth: 3840, maxHeight: 2160 });

  // wait for the first frame, then write frames on a wall-clock schedule (no drift)
  for (let i = 0; i < 100 && !latest; i++) await new Promise((r) => setTimeout(r, 30));
  if (!latest) throw new Error("no frames from the page screencast");
  const started = Date.now();
  let written = 0;
  const timer = setInterval(() => {
    const due = Math.floor(((Date.now() - started) / 1000) * FPS);
    for (; written < due; written++) ffmpeg.stdin.write(latest);
  }, 1000 / FPS / 2);

  const stop = async () => {
    clearInterval(timer);
    await cdp.send("Page.stopScreencast").catch(() => {});
    await cdp.detach().catch(() => {});
    await new Promise((resolve, reject) => {
      ffmpeg.once("exit", (code) => (code === 0 ? resolve() : reject(new Error(`ffmpeg exited ${code}`))));
      ffmpeg.stdin.end();
    });
    return { out, seconds: written / FPS };
  };
  stop.startedAt = started; // video time 0, for scene markers
  return stop;
}
