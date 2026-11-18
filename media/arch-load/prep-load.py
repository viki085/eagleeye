"""Prepare Part 2 (the load test) for the Remotion edit, from the recorded run.

  public/load/wall-NN.mp4       the 12 wall clips (4K originals, for the 1-4 big windows)
  public/load/wall-NN-960.mp4   960x540 proxies (the 8-window wall)
  public/load/mosaic.mp4        a 4x4 mosaic of the clips, 3840x2160, 24 s (16 windows; tiled 2x2
                                and 4x4 in the edit for 64 and 256, so only 4 / 16 videos decode)
  public/load/admin-*.mp4       the admin checkpoints and the cost clip
  public/load-data.json         per-minute timeline, per-answer lines (for the k6 log and graphs),
                                clip marks

    uv run python arch-load/prep-load.py        (from media/)
"""

import json
import shutil
import subprocess
from pathlib import Path

MEDIA = Path(__file__).resolve().parent.parent
RAW = MEDIA / "arch-load" / "raw"
OUT = MEDIA / "public" / "load"
FFMPEG = subprocess.run(
    ["node", "-e", "console.log(require('ffmpeg-static'))"],
    cwd=MEDIA, capture_output=True, text=True, check=True,
).stdout.strip()
MOSAIC_S = 24


def ff(*args: str) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def walls() -> list[dict]:
    metas = []
    for i in range(1, 13):
        name = f"wall-{i:02d}"
        meta = json.loads((RAW / "run" / f"{name}.json").read_text())
        shutil.copyfile(RAW / "run" / f"{name}.mp4", OUT / f"{name}.mp4")
        ff("-i", str(RAW / "run" / f"{name}.mp4"), "-vf", "scale=960:540:flags=lanczos",
           "-an", "-c:v", "h264_nvenc", "-preset", "p5", "-cq", "24", str(OUT / f"{name}-960.mp4"))
        marks = {m["type"]: m["t"] / 1000 for m in meta["marks"]}
        metas.append({
            "name": name, "seconds": meta["seconds"], "kind": meta["kind"],
            "ready": marks.get("ready", 4), "asked": marks.get("asked", 8),
            "answered": marks.get("answered", 20), "answer_s": meta["answerSeconds"],
            "offset_s": round((meta["startedAtEpoch"] - RUN_T0) / 1000, 1),
        })
    return metas


def mosaic(metas: list[dict]) -> None:
    """16 tiles: the 12 clips from just before the question is typed, then 4 repeats later on."""
    inputs, layout = [], []
    for k in range(16):
        m = metas[k % 12]
        start = max(0.0, m["ready"] - 1 + (6 if k >= 12 else 0))
        inputs += ["-stream_loop", "-1", "-ss", f"{start:.2f}", "-i", str(OUT / f"{m['name']}-960.mp4")]
        layout.append(f"{(k % 4) * 960}_{(k // 4) * 540}")
    chains = "".join(f"[{k}:v]setpts=PTS-STARTPTS,fps=30[v{k}];" for k in range(16))
    stack = "".join(f"[v{k}]" for k in range(16))
    ff(*inputs, "-filter_complex", f"{chains}{stack}xstack=inputs=16:layout={'|'.join(layout)}[out]",
       "-map", "[out]", "-t", str(MOSAIC_S), "-an", "-c:v", "h264_nvenc", "-preset", "p5",
       "-cq", "23", "-pix_fmt", "yuv420p", str(OUT / "mosaic.mp4"))


def admin() -> dict:
    marks = {}
    for src, name in [("run/admin-500", "admin-500"), ("run/admin-1000", "admin-1000"),
                      ("run/admin-2000", "admin-2000"), ("cost/admin-cost", "admin-cost")]:
        shutil.copyfile(RAW / f"{src}.mp4", OUT / f"{name}.mp4")
        meta = json.loads((RAW / f"{src}.json").read_text())
        marks[name] = {
            "seconds": meta["seconds"],
            "marks": [{"label": m["label"], "t": m["t"] / 1000, "box": m.get("box")}
                      for m in meta["marks"] if m["type"] == "metric"],
        }
    return marks


def answers() -> list[list]:
    """[seconds into the run, kind, answer seconds, ok] for every answer, in time order."""
    rows = []
    for line in (RAW / "run" / "answers.jsonl").read_text().splitlines():
        a = json.loads(line)
        rows.append([round((a["t"] - RUN_T0) / 1000, 2), a["kind"], a["s"], int(a["ok"])])
    return sorted(rows)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    timeline = json.loads((RAW / "run" / "timeline.json").read_text())
    RUN_T0 = timeline["t0"]
    metas = walls()
    mosaic(metas)
    data = {
        "totals": timeline["totals"],
        "minutes": timeline["minutes"],
        "walls": metas,
        "admin": admin(),
        "answers": answers(),
        "mosaicSeconds": MOSAIC_S,
    }
    (MEDIA / "public" / "load-data.json").write_text(json.dumps(data, separators=(",", ":")))
    print(f"prepared {len(metas)} wall clips, mosaic, 4 admin clips, {len(data['answers'])} answers")
