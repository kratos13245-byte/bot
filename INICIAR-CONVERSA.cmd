@echo off
cd /d "%~dp0"
set ENABLE_MINECRAFT=0
set ENABLE_TWITCH=0
set VISION_AUTO_START=1
".venv\Scripts\python.exe" main.py
pause
