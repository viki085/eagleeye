"""Cut the admin console recordings into one clean clip per narrated metric (a "beat").

Each beat clip is the recording while that metric was held, with the burned-in spotlight removed
(unspot.py), optionally preceded by the clean lead-in before the first spotlight appeared. The
edit then draws its own highlight, timed to the voice line. Writes:
  public/load/beat-<clip>-<n>.mp4   the clips
  public/load-beats.json            per beat: src, lead-in seconds, total seconds, boxes

  python arch-load/prep-beats.py    (run from media/, after prep-load.py)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from unspot import Unspot  # noqa: E402

MEDIA = Path(__file__).resolve().parents[1]
PUB = MEDIA / "public"
FFMPEG = subprocess.run(["node", "-e", "console.log(require('ffmpeg-static'))"], capture_output=True,
                        text=True, cwd=MEDIA, check=True).stdout.strip()
W, H, FPS = 3840, 2160, 30
SETTLE = 0.45  # the spotlight's 380 ms move/fade has finished
HOLD_END = 4.4  # the recorder held each metric 4.5 s before moving on


def frames(src: Path, start: float, seconds: float):
    """Yield BGR frames of src from start for seconds."""
    p = subprocess.Popen([FFMPEG, "-v", "error", "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{seconds:.3f}",
                          "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    size = W * H * 3
    while chunk := p.stdout.read(size):
        if len(chunk) < size:
            break
        yield np.frombuffer(chunk, np.uint8).reshape(H, W, 3)
    p.wait()


def build(clip: str, n: int, beat: dict, marks: list[dict]) -> dict:
    mark = next(m for m in marks if m["label"] == beat["label"])
    out = PUB / "load" / f"beat-{clip}-{n}.mp4"
    enc = subprocess.Popen([FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "h264_nvenc", "-preset", "p5", "-cq", "19",
                            "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
    count = 0
    lead = 0.0
    if "pre" in beat:  # before the first spotlight: the page is clean as recorded
        for f in frames(PUB / "load" / f"{clip}.mp4", beat["pre"], mark["t"] - 0.05 - beat["pre"]):
            enc.stdin.write(f.tobytes())
            count += 1
        lead = count / FPS
    clean = Unspot(mark["box"], (H, W))
    for f in frames(PUB / "load" / f"{clip}.mp4", mark["t"] + SETTLE, HOLD_END - SETTLE):
        enc.stdin.write(clean(f).tobytes())
        count += 1
    enc.stdin.close()
    enc.wait()
    extra = beat.get("extra")
    if extra and "box" not in extra:
        extra = {**extra, "box": next(m for m in marks if m["label"] == extra["label"])["box"]}
    print(f"  {out.name}: {count / FPS:.2f} s (lead-in {lead:.2f} s)")
    return {"src": f"load/{out.name}", "label": beat["label"], "line": beat["line"], "box": mark["box"],
            "lead": round(lead, 3), "seconds": round(count / FPS, 3), "extra": extra, "note": beat.get("note")}


if __name__ == "__main__":
    spec = json.loads((MEDIA / "arch-load" / "beats.json").read_text(encoding="utf-8"))
    data = json.loads((PUB / "load-data.json").read_text())
    only = sys.argv[1:]
    path = PUB / "load-beats.json"
    result = json.loads(path.read_text()) if path.exists() else {}
    for clip, beats in spec.items():
        if clip.startswith("_") or (only and clip not in only):
            continue
        marks = data["admin"][clip]["marks"]
        result[clip] = [build(clip, i, b, marks) for i, b in enumerate(beats)]
    path.write_text(json.dumps(result, indent=1))
