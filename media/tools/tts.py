"""Voice lines for the EagleEye videos (OpenAI gpt-4o-mini-tts), with a hard spending cap.

    uv run python media/tools/tts.py audition            one sample per candidate voice
    uv run python media/tools/tts.py lines <lines.json>  every line of a script

lines.json: [{"id": "s2-01", "character": "narrator", "text": "..."}, ...]
Audio goes to media/audio/ (git-ignored); durations to media/audio/durations.json.

Every call is logged in media/costs.jsonl. Before a call, its cost is estimated from the text
(with a margin); if that would take the voice spend past BUDGET_USD the script stops. The key is
read from the repo's .env and never printed.
"""

import argparse
import json
import os
import sys
import time
import wave
from pathlib import Path

MEDIA = Path(__file__).resolve().parent.parent
REPO = MEDIA.parent
AUDIO = MEDIA / "audio"
LEDGER = MEDIA / "costs.jsonl"
CHARACTERS = MEDIA / "characters.json"

MODEL = "gpt-4o-mini-tts"
BUDGET_USD = 0.30  # voices' share of the video's $4.50 OpenAI cap
USD_PER_MINUTE = 0.015  # list price estimate for gpt-4o-mini-tts audio
CHARS_PER_SECOND = 13.0  # conservative speaking rate for the pre-call estimate
ESTIMATE_MARGIN = 1.5


def load_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENAI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"')
    if not key:
        sys.exit("OPENAI_API_KEY not found in the environment or .env")
    return key


def spent(kind: str) -> float:
    if not LEDGER.exists():
        return 0.0
    total = 0.0
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["kind"] == kind:
            total += row["usd"]
    return total


def log_cost(kind: str, usd: float, detail: str) -> None:
    with LEDGER.open("a", encoding="utf-8") as f:
        row = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, "usd": round(usd, 5), "detail": detail}
        f.write(json.dumps(row) + "\n")


def estimate_usd(text: str) -> float:
    seconds = len(text) / CHARS_PER_SECOND
    return seconds / 60 * USD_PER_MINUTE * ESTIMATE_MARGIN


def wav_seconds(path: Path) -> float:
    """Length from the data size: streamed WAVs carry a placeholder frame count in the header."""
    with wave.open(str(path), "rb") as w:
        bytes_per_second = w.getframerate() * w.getnchannels() * w.getsampwidth()
    header = 44
    return max(path.stat().st_size - header, 0) / bytes_per_second


def speak(client, voice: str, instructions: str, text: str, out: Path) -> float:
    """One clip; returns its length in seconds. Refuses if it could pass the budget."""
    so_far = spent("tts")
    if so_far + estimate_usd(text) > BUDGET_USD:
        sys.exit(f"stopping: voice budget ${BUDGET_USD:.2f} would be exceeded (spent ${so_far:.3f})")
    out.parent.mkdir(parents=True, exist_ok=True)
    with client.audio.speech.with_streaming_response.create(
        model=MODEL, voice=voice, input=text, instructions=instructions, response_format="wav"
    ) as response:
        response.stream_to_file(out)
    seconds = wav_seconds(out)
    log_cost("tts", seconds / 60 * USD_PER_MINUTE, f"{out.name} {seconds:.1f}s")
    return seconds


def audition(client, characters: dict) -> None:
    for key, c in characters.items():
        if key.startswith("_"):
            continue
        for voice in c["candidates"]:
            out = AUDIO / "audition" / f"{key}-{voice}.wav"
            if out.exists():
                print(f"skip (exists) {out.name}")
                continue
            print(f"{out.name}: {speak(client, voice, c['instructions'], c['audition'], out):.1f}s")


def lines(client, characters: dict, path: Path) -> None:
    durations_file = AUDIO / "durations.json"
    durations = json.loads(durations_file.read_text(encoding="utf-8")) if durations_file.exists() else {}
    for line in json.loads(path.read_text(encoding="utf-8")):
        c = characters[line["character"]]
        if not c["voice"]:
            sys.exit(f"pick a voice for {line['character']} in characters.json first")
        out = AUDIO / "lines" / f"{line['id']}.wav"
        if out.exists() and durations.get(line["id"], {}).get("text") == line["text"]:
            continue  # unchanged line: no new call
        seconds = speak(client, c["voice"], line.get("instructions", c["instructions"]), line["text"], out)
        durations[line["id"]] = {"seconds": round(seconds, 2), "character": line["character"], "text": line["text"]}
        print(f"{line['id']}: {seconds:.1f}s")
    durations_file.write_text(json.dumps(durations, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("audition")
    p_lines = sub.add_parser("lines")
    p_lines.add_argument("file", type=Path)
    args = parser.parse_args()

    from openai import OpenAI

    client = OpenAI(api_key=load_key())
    characters = json.loads(CHARACTERS.read_text(encoding="utf-8"))
    if args.cmd == "audition":
        audition(client, characters)
    else:
        lines(client, characters, args.file)
    print(f"voice spend so far: ${spent('tts'):.3f} of ${BUDGET_USD:.2f}")


if __name__ == "__main__":
    main()
