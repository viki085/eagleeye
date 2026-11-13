#!/usr/bin/env bash
# Start the whole EagleEye stack (macOS/Linux). Options: --skip-infra --onboard
cd "$(dirname "$0")/.." && exec uv run --no-project --with psutil==6.1.1 python scripts/eagleeye.py start "$@"
