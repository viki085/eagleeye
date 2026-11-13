@echo off
rem Start the whole EagleEye stack (Windows). Options: --skip-infra --onboard
cd /d "%~dp0.."
uv run --no-project --with psutil==6.1.1 python scripts\eagleeye.py start %*
