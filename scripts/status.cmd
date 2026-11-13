@echo off
rem Show which EagleEye services are running (Windows).
cd /d "%~dp0.."
uv run --no-project --with psutil==6.1.1 python scripts\eagleeye.py status %*
