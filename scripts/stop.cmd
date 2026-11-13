@echo off
rem Shut EagleEye down safely (Windows). Options: --infra --force --drain-timeout N
cd /d "%~dp0.."
uv run --no-project --with psutil==6.1.1 python scripts\eagleeye.py stop %*
