# ruff: noqa: E501  (long image prompts)
"""Images for the cosmic-zoom finale (OpenAI gpt-image-2, medium quality), with a spending cap.

    uv run python media/tools/finale_images.py            all missing images
    uv run python media/tools/finale_images.py 08-eye     one image again (a retry)

Images go to media/public/finale/ (git-ignored). Each call is logged in media/costs.jsonl; the
script stops before the images' share of the budget would be passed. The key is read from .env.
"""

import base64
import json
import sys
import time
from pathlib import Path

MEDIA = Path(__file__).resolve().parent.parent
OUT = MEDIA / "public" / "finale"
LEDGER = MEDIA / "costs.jsonl"
MODEL = "gpt-image-2"
SIZE = "1536x1024"
QUALITY = "medium"
USD_PER_IMAGE = 0.063  # conservative: list price for gpt-image-2 medium 1536x1024 is about $0.041
BUDGET_USD = 1.20

STYLE = (
    "Cinematic, photorealistic, ultra detailed, dramatic natural light, rich but natural colour, "
    "the main subject centred and filling the middle third of the frame, wide 3:2 composition, "
    "no text, no letters, no logos, no watermark, no people in close-up."
)

PROMPTS = {
    "01-ruins": "Ancient Greek temple ruins with weathered marble columns at golden hour, seen from a low drone height, warm sunlight.",
    "02-pyramids": "The pyramids of Giza at dusk seen from high above the desert, long shadows, the ancient complex small in the centre of a vast landscape.",
    "03-skyline": "A modern city skyline at night seen from very high altitude, glowing towers and lit streets in the centre, surrounded by the dark landscape and a coastline.",
    "04-earth": "The whole planet Earth seen from space, centred, clouds and city lights on the night side, thin blue atmosphere, deep black space around it.",
    "05-solar-system": "The solar system seen from far above: the Sun glowing at the centre with the planets on faint elliptical orbits, deep space background, scientifically inspired.",
    "06-galaxy": "A majestic spiral galaxy seen face-on, glowing golden core at the centre, blue spiral arms, deep black space with distant stars.",
    "07-universe": "The deep-field universe: countless distant galaxies of many colours scattered across black space, a faint glowing cluster at the centre.",
    "08-eye": "An extreme close-up of a golden eagle's eye, the iris amber and gold, and inside the round black pupil a tiny universe of galaxies and stars, the eye centred, dark feathers around it.",
}


def load_key() -> str:
    for line in (MEDIA.parent / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].split(" #", 1)[0].strip().strip('"')
    sys.exit("OPENAI_API_KEY not found in .env")


def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    rows = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines() if line]
    return sum(r["usd"] for r in rows if r["kind"] == "images")


def main() -> None:
    from openai import OpenAI

    client = OpenAI(api_key=load_key())
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = sys.argv[1:] or [k for k in PROMPTS if not (OUT / f"{k}.png").exists()]
    for key in wanted:
        if spent() + USD_PER_IMAGE > BUDGET_USD:
            sys.exit(
                f"stopping: image budget ${BUDGET_USD:.2f} would be exceeded (spent ${spent():.2f})"
            )
        prompt = f"{PROMPTS[key]} {STYLE}"
        result = client.images.generate(model=MODEL, prompt=prompt, size=SIZE, quality=QUALITY, n=1)
        (OUT / f"{key}.png").write_bytes(base64.b64decode(result.data[0].b64_json))
        with LEDGER.open("a", encoding="utf-8") as f:
            row = {
                "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "kind": "images",
                "usd": USD_PER_IMAGE,
                "detail": key,
            }
            f.write(json.dumps(row) + "\n")
        print(f"{key}: done (images ${spent():.2f} of ${BUDGET_USD:.2f})")


if __name__ == "__main__":
    main()
