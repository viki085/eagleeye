#!/usr/bin/env bash
# Shut EagleEye down safely (macOS/Linux). Options: --infra --force --drain-timeout N
cd "$(dirname "$0")/.." && exec uv run --no-project --with psutil==6.1.1 python scripts/eagleeye.py stop "$@"
