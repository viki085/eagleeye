#!/usr/bin/env bash
# Show which EagleEye services are running (macOS/Linux).
cd "$(dirname "$0")/.." && exec uv run --no-project --with psutil==6.1.1 python scripts/eagleeye.py status "$@"
